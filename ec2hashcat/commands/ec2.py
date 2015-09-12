""" Copyright 2015 Will Boyce """
from __future__ import print_function

import os
from time import sleep

from ec2hashcat import aws, utils
from ec2hashcat.commands.base import BaseCommand


class BaseEc2Command(BaseCommand):
    @classmethod
    def setup_parser(cls, parser):
        super(BaseEc2Command, cls).setup_parser(parser)
        ec2_args = parser.add_argument_group('ec2 arguments')
        ec2_args.add_argument('--ec2-security-group', default='ec2hashcat', help='EC2 Security Group name')


class BaseEc2Accessor(BaseEc2Command):
    @classmethod
    def setup_parser(cls, parser):
        super(BaseEc2Accessor, cls).setup_parser(parser)
        ec2_args = parser.add_argument_group('ec2 arguments')
        ec2_args.add_argument('--ec2-key-file', required=True,
                              type=lambda fn: os.path.join(os.path.expanduser('~/.ssh'), os.path.expanduser(fn)),
                              help='Path to EC2_KEY_NAME')


class BaseEc2InstanceHelperCommand(BaseEc2Accessor):
    def __init__(self, *args, **kwargs):
        super(BaseEc2InstanceHelperCommand, self).__init__(*args, **kwargs)
        self.instance = aws.Ec2(self.cfg).find_running_instance(self.cfg.instance)

    @classmethod
    def setup_parser(cls, parser):
        super(BaseEc2InstanceHelperCommand, cls).setup_parser(parser)
        cmd_args = parser.add_argument_group('{} arguments'.format(cls.__name__.lower()))
        cmd_args.add_argument('instance', metavar='INSTANCE_ID|SESSION_NAME')


class Attach(BaseEc2InstanceHelperCommand):
    """ Attach to a running session """
    @classmethod
    def setup_parser(cls, parser):
        super(Attach, cls).setup_parser(parser)
        attach_args = parser.add_argument_group('attach arguments')
        attach_args.add_argument('-n', '--screen-name', default='ec2hashcat')

    def handle(self):
        self.instance.attach_screen(self.cfg.screen_name)


class Shell(BaseEc2InstanceHelperCommand):
    """ Open an interactive shell on a running instance """
    def handle(self):
        self.instance.open_shell()


class SecGrp(BaseEc2Command):
    """ Manage the ec2hashcat Security Group """
    def __init__(self, *args, **kwargs):
        super(SecGrp, self).__init__(*args, **kwargs)
        self.secgrp = aws.SecurityGroup(self.cfg)

    @classmethod
    def setup_parser(cls, parser):
        super(SecGrp, cls).setup_parser(parser)
        action_parsers = parser.add_subparsers(title='actions', dest='action')
        # show
        action_parsers.add_parser('show', help='Show masks currently allowed in Security Group')
        # add
        add_parser = action_parsers.add_parser('add', help='Add masks to the Security Group')
        add_secgrp_args = add_parser.add_argument_group('secgrp add arguments')
        add_secgrp_args.add_argument('masks', metavar='MASK', nargs='+', help='CIDR Mask')
        # del
        del_parser = action_parsers.add_parser('del', help='Delete masks from the Security Group')
        del_secgrp_args = del_parser.add_argument_group('secgrp del arguments')
        del_secgrp_args.add_argument('-a', '--all', action='store_true',
                                     help='Delete all masks')
        del_secgrp_args.add_argument('masks', metavar='MASK', nargs='*', help='CIDR Mask')

    def handle(self):
        actions = {
            'add': self._add,
            'del': self._del,
            'show': self._show
        }
        actions[self.cfg.action]()

    def _add(self):
        if not self.cfg.masks:
            self.secgrp.add_ip(utils.get_external_ip())
        else:
            for mask in self.cfg.masks:
                self.secgrp.add_mask(mask)

    def _del(self):
        if self.cfg.all:
            self.cfg.masks = self.secgrp.get_masks()
        for mask in self.cfg.masks:
            self.secgrp.del_mask(mask)

    def _show(self):
        table = [[mask] for mask in self.secgrp.get_masks()]
        utils.print_table(table, ['Mask'])


class Stop(BaseEc2Accessor):
    """ Terminate Instance(s) """

    @classmethod
    def setup_parser(cls, parser):
        super(Stop, cls).setup_parser(parser)
        terminate_args = parser.add_argument_group('terminate arguments')
        terminate_args.add_argument('-f', '--force', action='store_true')
        terminate_args.add_argument('instances', metavar='INSTANCE_ID|INSTANCE_TAG', nargs='+')

    def handle(self):
        ec2 = aws.Ec2(self.cfg)
        for instance in self.cfg.instances:
            instance = ec2.find_running_instance(instance)
            if not self.cfg.force:
                print("Gracefully shutting down Instance '{}'".format(instance.instance.id))
                # unhook the termination handler
                instance.execute_command('screen -XS termination_handler quit')
                # kill and current running hashcat sessions (causing an upload)
                instance.execute_command('killall cudaHashcat64.bin')
                sleep(30)
            instance.terminate()
