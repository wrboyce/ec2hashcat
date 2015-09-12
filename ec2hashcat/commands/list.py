""" Copyright 2015 Will Boyce """
from __future__ import print_function

from datetime import datetime, timedelta
from collections import defaultdict
import os

import pytz

from ec2hashcat import aws, utils
from ec2hashcat.commands.base import BaseCommand


class List(BaseCommand):
    """ List files, prices or sessions. """
    @classmethod
    def setup_parser(cls, parser):
        type_parsers = parser.add_subparsers(title='types', dest='type')
        for list_type in ('sessions', 'prices', 'files', 'hashlists', 'dumps', 'wordlists', 'rules'):
            type_parsers.add_parser(list_type)
        list_prices_args = type_parsers.choices['prices'].add_argument_group('list prices arguments')
        list_prices_args.add_argument('--ec2-instance-type', default='g2.8xlarge')
        return parser

    def handle(self):
        headers, table = [], []
        if self.cfg.type == 'sessions':
            headers = ['ID', 'Session', 'Type', 'State', 'IP', 'Uptime', 'Spot Price']
            for instance in aws.Ec2(self.cfg).get_instances():
                session_name = ''
                for tag in instance.tags:
                    if tag['Key'] == 'ec2hashcat':
                        session_name = tag['Value']
                        break
                table.append([instance.id,
                              session_name,
                              instance.instance_type,
                              instance.state.get('Name', ''),
                              instance.public_ip_address,
                              self._get_instance_uptime(instance),
                              '${}/h'.format(self._get_instance_price(instance))])
        elif self.cfg.type == 'prices':
            headers = ['Zone', 'Price (USD)']
            table = aws.Ec2(self.cfg).get_spot_prices()
        else:
            types = [self.cfg.type]
            if self.cfg.type == 'files':
                types = aws.S3Bucket.types
            headers = ['Filename', 'Size', 'Last Modified']
            for filetype in types:
                objects = aws.S3Bucket(self.cfg).get_objects(filetype)
                for obj in objects:
                    key = obj.key
                    if self.cfg.type != 'files':
                        key = os.path.basename(key)
                    table.append([key, obj.size, obj.last_modified])

        if headers and table:
            utils.print_table(table, headers)

    @classmethod
    def _get_instance_uptime(cls, instance):
        if instance.state.get('Name', '') != 'running':
            return ''
        uptime = datetime.now(tz=pytz.utc) - instance.launch_time
        uptime_dict = defaultdict(int)
        for name, secs in (('hours', 60 * 60), ('minutes', 60)):
            while uptime.total_seconds() > secs:
                uptime_dict[name] += 1
                uptime -= timedelta(seconds=secs)
        uptime_str = []
        for name in ('hours', 'minutes'):
            if uptime_dict[name] > 0:
                uptime_str.append('{} {}'.format(uptime_dict[name], name))
        if not uptime_str:
            uptime_str.append('{} seconds'.format(round(uptime)))
        return ' '.join(uptime_str)

    def _get_instance_price(self, instance):
        if instance.spot_instance_request_id is None:
            return ''
        return aws.Ec2(self.cfg).get_instance_spotprice(instance)
