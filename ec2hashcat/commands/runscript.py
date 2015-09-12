""" Copyright 2015 Will Boyce """
from __future__ import print_function

from cStringIO import StringIO

import os
import sys
import tempfile
import uuid

from ec2hashcat import aws, utils
from ec2hashcat.commands.ec2 import BaseEc2Accessor


class BaseEc2InstanceSessionCommand(BaseEc2Accessor):
    @classmethod
    def setup_parser(cls, parser):
        super(BaseEc2InstanceSessionCommand, cls).setup_parser(parser)
        ec2_args = parser.add_argument_group('ec2 arguments')
        ec2_args.add_argument('--ec2-key-name', default='ec2hashcat', help='Name of EC2 SSH Key')
        ec2_args.add_argument('--ec2-instance-type', default='g2.8xlarge', help='ec2 instance type')
        ec2_args.add_argument('--ec2-volume-size', action='store_num', default=15, min=15, type=int,
                              help='ec2 root volume size (min=15)')
        ec2_args.add_argument('--ec2-spot-instance', action='store_true', default=True, help='use ec2 spot instance')
        ec2_args.add_argument('-p', '--ec2-spot-price', default='avg',
                              help='bid to place for ec2 spot instance (USD/hour)')

        cmd_args = parser.add_argument_group('{} arguments'.format(cls.__name__.lower()))
        cmd_mutex_args = cmd_args.add_mutually_exclusive_group()
        cmd_mutex_args.add_argument('-s', '--session-name',
                                    help='Override the ec2hashcat session name for the instance')
        cmd_mutex_args.add_argument('-i', '--use-instance', metavar='INSTANCE_ID|SESSION_NAME',
                                    help='Use an existing instance for the Task')
        cmd_args.add_argument('--no-attach', action='store_false', dest='attach', default=True,
                              help='Do not attach to the process one started')
        cmd_args.add_argument('--shell', action='store_true',
                              help='Drop into a shell once the task has completed (this will block shutdown!)')
        cmd_args.add_argument('--no-shutdown', action='store_false', dest='shutdown', default=True,
                              help='Do not shutdown the instance once the task has completed')

    @classmethod
    def _read_file(cls, name, prompt='>'):
        file_h = None
        if name == '-':
            file_h = sys.stdin
        elif name == '+':
            file_h = StringIO()
            while True:
                content = raw_input('{} '.format(prompt.strip()))
                if not content:
                    break
                file_h.writelines([content])
            file_h.seek(0)
        else:
            file_h = file(name)
        return [line.strip() for line in file_h.readlines() if not line.startswith('#')]

    def _get_instance(self):
        # configure security group
        aws.SecurityGroup(self.cfg).add_ip(utils.get_external_ip())

        ec2 = aws.Ec2(self.cfg)
        if self.cfg.use_instance is not None:
            self.cfg.shutdown = False
            return ec2.find_running_instance(self.cfg.use_instance)
        else:
            return ec2.start_instance(tag=self.cfg.session_name)


class RunScript(BaseEc2InstanceSessionCommand):
    """ Launch an EC2 Instance and run the specified script """
    cleanup_required = False

    @classmethod
    def setup_parser(cls, parser):
        super(RunScript, cls).setup_parser(parser)
        rs_args = parser.add_argument_group('runscript arguments')
        rs_args.add_argument('script', metavar='script')

    def handle(self):
        remote_fn = self._resolve_script()
        if self.cfg.session_name is None:
            self.cfg.session_name = os.path.basename(self.cfg.script)
        instance = self._get_instance()
        instance.copy_file(self.cfg.script, remote_fn, mode='0755')
        commands = [remote_fn]
        if self.cfg.shell:
            commands.append('bash')
        if self.cfg.shutdown:
            commands.append('sudo poweroff')
        script_fn = instance.create_script(commands)
        instance.create_screen(self.cfg.session_name, script_fn, attach=self.cfg.attach)

    def _resolve_script(self):
        remote_fn = os.path.join('/tmp', '{}{}'.format(uuid.uuid1().hex, os.path.splitext(self.cfg.script)[1]))
        if self.cfg.script in '+-':
            script_content = self._read_file(self.cfg.script)
            _, self.cfg.script = tempfile.mkstemp(suffix='.sh')
            with open(self.cfg.script, 'w') as script_fh:
                script_fh.writelines(['{}\n'.format(line) for line in script_content])
            self.cleanup_required = True
        return remote_fn
