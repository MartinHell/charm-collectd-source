import os
import glob
import urlparse
from charmhelpers import fetch
from charmhelpers.core import host, hookenv
from charmhelpers.core.templating import render
from charms.reactive import when, when_not, set_state, hook
from charms.reactive.helpers import any_file_changed


@hook('config-changed', 'install')
def setup_collectd():
    hookenv.status_set('maintenance', 'Configuring collectd')
    install_packages()
    if not validate_settings():
        return
    install_conf_d(get_plugins())
    settings = {'config': resolve_config(),
                'plugins': get_plugins(),
                }
    render(source='collectd.conf.j2',
           target='/etc/collectd/collectd.conf',
           owner='root',
           group='root',
           perms=0o644,
           context=settings,
           )

    set_state('collectd.start')
    hookenv.status_set('active', 'Ready')


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
           perms=0o644,
           context=options
           )
    render(source='nrpe-config.jinja2',
           target='/etc/nagios/nrpe.d/check_collectd.cfg',
           perms=0o644,
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
    missing = required.difference(config.viewkeys())
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
    if config.get('prometheus_export', False):
        # XXX comes from aluria's PPA, check if there is upstream package available
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

    if 'graphite_host' in config:
        plugins.append('write_graphite')
    if 'network_host' in config:
        plugins.append('network')
    if 'http_endpoint' in config:
        plugins.append('write_http')

    for p in plugins:
        if not os.path.isfile(os.path.join('/usr/lib/collectd', p + '.so')):
            hookenv.status_set('waiting', 'Invalid plugin {}'.format(p))
            return
    return plugins


def install_conf_d(plugins):
    if not os.path.isdir('/etc/collectd/collectd.conf.d'):
        os.mkdir('/etc/collectd/collectd.conf.d')
    for plugin in plugins:
        template = 'collectd.conf.d/{}.conf.j2'.format(plugin)
        if os.path.isfile(os.path.join('templates', template)):
            hookenv.log('Installing configuration file for "{}" plugin'.format(plugin))

            render(source=template,
                   target='/etc/collectd/collectd.conf.d/{}.conf'.format(plugin),
                   owner='root',
                   group='root',
                   perms=0o644,
                   context={'config': resolve_config()}
                   )


def resolve_config():
    config = hookenv.config()
    if config.get('graphite_endpoint', False):
        config['graphite_host'], config['graphite_port'] = config['graphite_endpoint'].split(':')
        config['graphite_port'] = int(config['graphite_port'])
    if config.get('prometheus_export', False):
        prometheus_export = urlparse.urlparse(config['prometheus_export'])
        config['http_endpoint'] = prometheus_export.netloc
        config['http_path'] = '/collectd-post'
        config['http_format'] = 'JSON'
        config['http_rates'] = 'true'
        config['prometheus_path'] = prometheus_export.path
    if config.get('network_target', False):
        config['network_host'], config['network_port'] = config['network_target'].split(':')
        config['network_port'] = int(config['network_port'])
    return config


@when('collectd.start')
def start_collectd():
    if not host.service_running('collectd'):
        host.service_start('collectd')
