""" Copyright 2015 Will Boyce """
from __future__ import print_function

import json
import urllib

from tabulate import tabulate


def get_external_ip():
    """ Return the external IP address as reported by httpbin.org """
    url = 'http://httpbin.org/ip'
    data = json.loads(urllib.urlopen(url).read())
    return data['origin']


def print_table(table, headers=None):
    """ Print a table via ``tabulate.tabulate`` with fmt=psql """
    print(tabulate(table, headers, tablefmt='psql'))
