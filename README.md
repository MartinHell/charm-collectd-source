# Overview

This subordinate charm will deploy a collectd daemon. By default, metrics are
not forwarded or exposed in any way until configuration options are set.

This charm can optionally expose metrics for prometheus scraping.
This requires the `canonical-bootstack-collectd-exporter` package to
be available for installation.


## Deployment

The charm relates with any principal charm using the `juju-info` interface.
Assuming you have deployed a principal service called `ubuntu` and you have a
copy of this collectd subordinate in `./charms/$distrocodename/collectd`,
you would execute the following:

    juju deploy --repository=charms local:trusty/collectd collectd
    juju add-relation ubuntu collectd


## Usage

To send metrics to the graphite server listening on 192.168.99.10 port 2003:

    juju set collectd graphite_endpoint=192.168.99.10:2003

To expose metrics for prometheus on port 9103 under "/metrics" URL:

    juju set collectd prometheus_export=http://127.0.0.1:9103/metrics

See config.yaml for more details about configuration options


## Development

This charm was written using the
[layered charm](https://jujucharms.com/docs/devel/developer-getting-started)
approach. Source for this charm is available in
[Launchpad](https://code.launchpad.net/~jacekn/canonical-is-charms/collectd-composer).
To extend or customize this charm, branch the code:

    bzr branch lp:~jacekn/canonical-is-charms/collectd-composer \
        $JUJU_REPOSITORY/layers/collectd

    cd $JUJU_REPOSITORY/layers/collectd

Make desired modifications, and assemble the charm:

    charm build


## Contact

- <jacek.nykis@canonical.com>
