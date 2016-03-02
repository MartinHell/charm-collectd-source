import os
import re
import glob
import six
from charmhelpers import fetch
from charmhelpers.core import host, hookenv
from charmhelpers.core.templating import render
from charms.reactive import when, when_not, set_state, remove_state
from charms.reactive.helpers import any_file_changed, data_changed

if six.PY2:
    import urlparse
else:
    import urllib.parse as urlparse


# When prometheus_export=True
DEFAULT_PROMETHEUS_EXPORT = 'http://127.0.0.1:9103/metrics'


@when_not('collectd.started')
def setup_collectd():
    hookenv.status_set('maintenance', 'Configuring collectd')
    install_packages()
    if not validate_settings():
        return
    config = resolve_config()
    install_conf_d(get_plugins())
    settings = {'config': config,
                'plugins': get_plugins(),
                }
    render(source='collectd.conf.j2',
           target='/etc/collectd/collectd.conf',
           context=settings,
           )

    if get_prometheus_export() and config['http_endpoint'].startswith('127.0.0.1'):
        render(source='collectd-exporter-prometheus.j2',
               target='/etc/default/collectd-exporter-prometheus',
               context=settings,
               )
        set_state('prometheus-exporter.start')

    set_state('collectd.start')
    hookenv.status_set('active', 'Ready')


@when('collectd.started')
def check_config():
    if data_changed('collectd.config', hookenv.config()):
        if validate_settings():
            setup_collectd()  # reconfigure and restart


@when('nrpe-external-master.available')
def setup_nrpe_checks(nagios):
    config = hookenv.config()
    options = {'check_name': 'check_collectd',
               'description': 'Verify that collectd process is running',
               'servicegroups': config['nagios_servicegroups'],
               'command': '/usr/lib/nagios/plugins/check_procs -C collectd -c 1:1'
               }
    options['hostname'] = '{}-{}'.format(config['nagios_context'],
                                         hookenv.local_unit()).replace('/', '-')

    render(source='nagios-export.jinja2',
           target='/var/lib/nagios/export/service__{}_collectd.cfg'.format(options['hostname']),
           context=options
           )
    render(source='nrpe-config.jinja2',
           target='/etc/nagios/nrpe.d/check_collectd.cfg',
           context=options
           )
    if any_file_changed(['/etc/nagios/nrpe.d/check_collectd.cfg']):
        host.service_reload('nagios-nrpe-server')


@when_not('nrpe-external-master.available')
def wipe_nrpe_checks():
    checks = ['/etc/nagios/nrpe.d/check_collectd.cfg',
              '/var/lib/nagios/export/service__*_collectd.cfg']
    for check in checks:
        for f in glob.glob(check):
            if os.path.isfile(f):
                os.unlink(f)


def validate_settings():
    required = set(('interval', 'plugins'))
    config = resolve_config()
    missing = required.difference(config.keys())
    if missing:
        hookenv.status_set('waiting', 'Missing configuration options: {}'.format(missing))
        return False
    if 'graphite_protocol' in config and config['graphite_protocol'].upper() not in ('TCP', 'UDP'):
        hookenv.status_set('waiting', 'Bad value for "graphite_protocol" option')
        return False
    if 'graphite_port' in config and (config['graphite_port'] < 1 or config['graphite_port'] > 65535):
        hookenv.status_set('waiting', '"graphite_port" outside of allowed range')
        return False
    if 'network_port' in config and (config['network_port'] < 1 or config['network_port'] > 65535):
        hookenv.status_set('waiting', '"network_port" outside of allowed range')
        return False
    return True


def install_packages():
    packages = ['collectd-core']
    config = resolve_config()
    if get_prometheus_export() and config['http_endpoint'].startswith('127.0.0.1'):
        # XXX comes from aluria's PPA, check if there is upstream package available
        hookenv.log('prometheus_export set to localhost, installing exporter locally')
        packages.append('canonical-bootstack-collectd-exporter')
    fetch.configure_sources()
    fetch.apt_update()
    fetch.apt_install(packages)


def get_plugins():
    default_plugins = [
        'syslog', 'battery', 'cpu', 'df', 'disk', 'entropy', 'interface',
        'irq', 'load', 'memory', 'processes', 'rrdtool', 'swap', 'users'
        ]
    config = resolve_config()
    if config['plugins'] == 'default':
        plugins = default_plugins
    else:
        plugins = [p.strip() for p in config['plugins'].split(',')]

    if config.get('graphite_endpoint', False):
        plugins.append('write_graphite')
    if config.get('network_target', False):
        plugins.append('network')
    if config.get('prometheus_export', False):
        plugins.append('write_http')
    if 'df' in config['plugins']:
        plugins.append('df')

    for p in plugins:
        if not os.path.isfile(os.path.join('/usr/lib/collectd', p + '.so')):
            hookenv.status_set('waiting', 'Invalid plugin {}'.format(p))
            return
    hookenv.log('Plugins to enable: {}'.format(plugins))
    return plugins


def install_conf_d(plugins):
    if not os.path.isdir('/etc/collectd/collectd.conf.d'):
        os.mkdir('/etc/collectd/collectd.conf.d')
    for plugin in plugins:
        template = 'collectd.conf.d/{}.conf.j2'.format(plugin)
        if os.path.isfile(os.path.join('templates', template)):
            hookenv.log('Installing configuration file for "{}" plugin'.format(plugin))

            render(source=template,
                   target='/etc/collectd/collectd.conf.d/juju_{}.conf'.format(plugin),
                   context={'config': resolve_config()}
                   )
    for config in glob.glob('/etc/collectd/collectd.conf.d/juju_*.conf'):
        config_regex = '/etc/collectd/collectd.conf.d/juju_(.+).conf'
        if re.match(config_regex, config).group(1) not in plugins:
            hookenv.log('Clearing unused configuration file: {}'.format(config))
            os.unlink(config)


def get_prometheus_export():
    config = hookenv.config()
    prometheus_export = config.get('prometheus_export', False)
    if prometheus_export is True or prometheus_export in ("True", "true"):
        prometheus_export = DEFAULT_PROMETHEUS_EXPORT
    return prometheus_export


def resolve_config():
    config = hookenv.config()
    if config.get('graphite_endpoint', False):
        config['graphite_host'], config['graphite_port'] = config['graphite_endpoint'].split(':')
        config['graphite_port'] = int(config['graphite_port'])
    if get_prometheus_export():
        prometheus_export = urlparse.urlparse(get_prometheus_export())
        config['http_endpoint'] = prometheus_export.netloc
        config['http_format'] = 'JSON'
        config['http_rates'] = 'true'
        if config['http_endpoint'].startswith('127.0.0.1') or config['http_endpoint'].startswith('localhost'):
            config['http_path'] = '/collectd-post'
            config['prometheus_export_path'] = prometheus_export.path
            config['prometheus_export_port'] = int(config['http_endpoint'].split(':')[1])
        else:
            config['http_path'] = prometheus_export.path
    if config.get('network_target', False):
        config['network_host'], config['network_port'] = config['network_target'].split(':')
        config['network_port'] = int(config['network_port'])
    return config


@when('collectd.start')
def start_collectd():
    if not host.service_running('collectd'):
        hookenv.log('Starting collectd...')
        host.service_start('collectd')
        set_state('collectd.started')
    if any_file_changed(['/etc/collectd/collectd.conf']):
        hookenv.log('Restarting collectd, config file changed...')
        host.service_restart('collectd')
    remove_state('collectd.start')


@when('prometheus-exporter.start')
def start_prometheus_exporter():
    if not host.service_running('collectd-exporter-prometheus'):
        hookenv.log('Starting collectd-exporter-prometheus...')
        host.service_start('collectd-exporter-prometheus')
        set_state('prometheus-exporter.started')
    if any_file_changed(['/etc/default/collectd-exporter-prometheus']):
        # Restart, reload breaks it
        hookenv.log('Restarting collectd-exporter-prometheus, config file changed...')
        host.service_restart('collectd-exporter-prometheus')
    remove_state('prometheus-exporter.start')


@when('target.available')
def configure_prometheus_relation(target):
    if get_prometheus_export():
        prometheus_export = urlparse.urlparse(get_prometheus_export())
        port = prometheus_export.netloc.split(':')[1]
        target.configure(port)
