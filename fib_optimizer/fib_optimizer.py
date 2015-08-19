#!/usr/bin/env python


from pySIR.pySIR import pySIR

import sys
import json

import shlex
import subprocess
import os
import time
import datetime

import logging
logger = logging.getLogger('fib_optimizer')

log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_format)

'''
def _split_tables(s):
    lem = list()
    lpm = list()

    for p in s:
        if p.split('/')[1] == '24':
            lem.append(p)
        else:
            lpm.append(p)
    return lem, lpm


def get_bgp_prefix_lists():
    bgp_p = sir.get_bgp_prefixes(date=end_time).result
    p = list()

    for router, prefix_list in bgp_p.iteritems():
        for prefix in prefix_list:
                p.append(prefix)

    return _split_tables(p)


def inc_exc_prefixes():
    i_lem, i_lpm = _split_tables(conf['include_prefixes'])
    e_lem, e_lpm = _split_tables(conf['exclude_prefixes'])

    return i_lem, i_lpm, e_lem, e_lpm


def complete_prefix_list():
    def _complete_pl(pl, bgp_pl, num):
        if len(pl) < num:
            num = num - len(pl)

            for prefix in bgp_pl:
                if prefix not in pl:
                    pl.append(prefix)
                    num -= 1

                    if num == 0:
                        break

            return pl
        else:
            return pl

    lem_pl = _complete_pl(lem_prefixes, bgp_lem, conf['max_lem_prefixes'])
    lpm_pl = _complete_pl(lpm_prefixes, bgp_lpm, conf['max_lpm_prefixes'])
    return lem_pl, lpm_pl

'''


def get_variables():
    logger.debug('Getting variables from SIR')
    v = sir.get_variables_by_category_and_name('apps', 'fib_optimizer').result[0]
    logger.debug('Configuration: {}'.format(json.loads(v['content'])))
    return json.loads(v['content'])


def get_date_range():
    # These are dates for which we have flows. We want to "calculate" the range we want to use
    # to calculate the topN prefixes

    logger.debug('Getting available dates')
    dates = sir.get_available_dates().result

    if len(dates) < conf['age']:
        sd = dates[0]
    else:
        sd = dates[-conf['age']]
    ed = dates[-1]

    logger.debug("Date range: {} - {}".format(sd, ed))

    time_delta = datetime.datetime.now() - datetime.datetime.strptime(ed, '%Y-%m-%dT%H:%M:%S')

    if time_delta.days > 2:
        msg = 'Data is more than 48 hours old: {}'.format(ed)
        logger.error(msg)
        raise Exception(msg)

    return sd, ed


def get_top_prefixes():
    logger.debug('Getting top prefixes')
    # limit_lem = int(conf['max_lem_prefixes']) - len(inc_lem) + len(exc_lem)
    limit_lem = int(conf['max_lem_prefixes'])
    lem = [p['key'] for p in sir.get_top_prefixes(
            start_time=start_time,
            end_time=end_time,
            limit_prefixes=limit_lem,
            net_masks=conf['lem_prefixes'],
            filter_proto=4,
        ).result]

    # limit_lpm = int(conf['max_lpm_prefixes']) - len(inc_lpm) + len(exc_lpm)
    limit_lpm = int(conf['max_lpm_prefixes'])
    lpm = [p['key'] for p in sir.get_top_prefixes(
            start_time=start_time,
            end_time=end_time,
            limit_prefixes=limit_lpm,
            net_masks=conf['lem_prefixes'],
            filter_proto=4,
            exclude_net_masks=1,
        ).result]
    return lem, lpm


def build_prefix_lists():
    logger.debug('Storing prefix lists in disk')

    def _build_pl(name, prefixes):
        pl = ''
        for s, p in prefixes.iteritems():
            pl += '{} permit {}\n'.format(s, p)

        with open('{}/{}'.format(conf['path'], name), "w") as f:
            f.write(pl)

    _build_pl('fib_optimizer_lpm_v4', lpm_prefixes)
    _build_pl('fib_optimizer_lem_v4', lem_prefixes)


def install_prefix_lists():
    logger.debug('Installing the prefix-lists in the system')

    cli_lpm = shlex.split('printf "conf t\n ip prefix-list fib_optimizer_lpm_v4 file:{}/fib_optimizer_lpm_v4"'.format(
                                                                                                        conf['path']))
    cli_lem = shlex.split('printf "conf t\n ip prefix-list fib_optimizer_lem_v4 file:{}/fib_optimizer_lem_v4"'.format(
                                                                                                        conf['path']))
    cli = shlex.split('sudo ip netns exec default FastCli -p 15 -A')

    p_lpm = subprocess.Popen(cli_lpm, stdout=subprocess.PIPE)
    p_cli = subprocess.Popen(cli, stdin=p_lpm.stdout, stdout=subprocess.PIPE)

    time.sleep(30)

    p_lem = subprocess.Popen(cli_lem, stdout=subprocess.PIPE)
    p_cli = subprocess.Popen(cli, stdin=p_lem.stdout, stdout=subprocess.PIPE)


def merge_pl():
    logger.debug('Merging new prefix-list with existing ones')

    def _merge_pl(pl, pl_file, max_p):
        if os.path.isfile(pl_file):
            logger.debug('Prefix list {} already exists. Merging'.format(pl_file))
            with open(pl_file, 'r') as f:
                original_pl = dict()
                for line in f.readlines():
                    seq, permit, prefix = line.split(' ')
                    original_pl[prefix.rstrip()] = int(seq)

            if len(original_pl)*0.75 > len(pl):
                msg = 'New prefix list ({}) is more than 25\% smaller than the new one ({})'.format(
                                                                                            len(original_pl), len(pl))
                logger.error(msg)
                raise Exception(msg)

            new_prefixes = set(pl) - set(original_pl.keys())
            existing_prefixes = set(pl) & set(original_pl.keys())

            new_pl = dict()
            for p in existing_prefixes:
                new_pl[original_pl[p]] = p

            empty_pos = sorted(list(set(xrange(1, int(max_p)+1)) - set(original_pl.values())))
            for p in new_prefixes:
                new_pl[empty_pos.pop(0)] = p

            return new_pl
        else:
            logger.debug('Prefix list {} does not exist'.format(pl_file))
            i = 1
            new = dict()
            for p in pl:
                new[i] = p
                i += 1
            return new

    lem = _merge_pl(lem_prefixes, '{}/fib_optimizer_lem_v4'.format(conf['path']), conf['max_lem_prefixes'])
    lpm = _merge_pl(lpm_prefixes, '{}/fib_optimizer_lpm_v4'.format(conf['path']), conf['max_lpm_prefixes'])

    return lem, lpm


def purge_old_data():
    logger.debug('Purging old data')
    date = datetime.datetime.now() - datetime.timedelta(hours=conf['purge_older_than'])
    date_text = date.strftime('%Y-%m-%dT%H:%M:%S')
    logger.debug('Deleting BGP data older than: {}'.format(date_text))
    sir.purge_bgp(older_than=date_text)
    logger.debug('Deleting flow data older than: {}'.format(date_text))
    sir.purge_flows(older_than=date_text)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print 'You have to specify the base URL. For example: {} http://127.0.0.1:5000'.format(sys.argv[0])
        sys.exit(0)
    elif sys.argv[1] == '-h' or sys.argv[1] == '--help':
        print 'You have to specify the base URL. For example: {} http://127.0.0.1:5000'.format(sys.argv[0])
        sys.exit(1)

    logger.info('Starting fib_optimizer')

    sir = pySIR(sys.argv[1], verify_ssl=False)

    # We get the configuration for our application
    conf = get_variables()

    # The time range we want to process
    start_time, end_time = get_date_range()

    # We get the Top prefixes. Included and excluded prefixes are merged as well
    lem_prefixes, lpm_prefixes = get_top_prefixes()

    # If the prefix list exists already we merge the data
    lem_prefixes, lpm_prefixes = merge_pl()

    # We build the files with the prefix lists
    build_prefix_lists()
    install_prefix_lists()
    purge_old_data()
    logger.info('End fib_optimizer')
