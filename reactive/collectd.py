import os.path
from charmhelpers import fetch
from charmhelpers.core import host, hookenv
from charmhelpers.core.templating import render
from charms.reactive import when, set_state, hook


@hook('config-changed', 'install')
def setup_collectd():
    hookenv.status_set('maintenance', 'Configuring collectd')
    if not get_plugins():
        return
    config = hookenv.config()
    settings = {'config': config,
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
    install_packages()
    if 'plugins' not in config:
        hookenv.status_set('waiting', 'Please set "plugins" option')
        return
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
