import os
import glob
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
    settings = {'config': hookenv.config(),
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
    required = set(('graphite_host', 'graphite_port', 'graphite_protocol',
                    'interval', 'plugins', 'prefix'))
    config = hookenv.config()
    missing = required.difference(config.viewkeys())
    if missing:
        hookenv.status_set('waiting', 'Missing configuration options: {}'.format(missing))
        return False
    if config['graphite_protocol'].upper() not in ('TCP', 'UDP'):
        hookenv.status_set('waiting', 'Bad value for "graphite_protocol" option')
        return False
    if config['graphite_port'] < 1 or config['graphite_port'] > 65535:
        hookenv.status_set('waiting', '"graphite_port" outside of allowed range')
        return False
    return True


def install_packages():
    packages = ['collectd-core']
    fetch.apt_update()
    fetch.apt_install(packages)


def get_plugins():
    default_plugins = [
        'write_graphite', 'syslog', 'battery',
        'cpu', 'df', 'disk', 'entropy', 'interface',
        'irq', 'load', 'memory', 'processes', 'rrdtool',
        'swap', 'users',
        ]
    config = hookenv.config()
    if config['plugins'] == 'default':
        plugins = default_plugins
    else:
        plugins = [p.strip() for p in config['plugins'].split(',')]
    for p in plugins:
        if not os.path.isfile(os.path.join('/usr/lib/collectd', p + '.so')):
            hookenv.status_set('waiting', 'Invalid plugin {}'.format(p))
            return
    return plugins


@when('collectd.start')
def start_collectd():
    if not host.service_running('collectd'):
        host.service_start('collectd')
