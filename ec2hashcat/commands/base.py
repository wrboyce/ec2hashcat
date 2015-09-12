""" Copyright 2015 Will Boyce """
from __future__ import print_function

import abc
import sys

import ec2hashcat
from ec2hashcat import argparse, exceptions
from ec2hashcat.aws import Ec2


class Handler(object):
    """ Main handler for CLI """
    def __init__(self, args=None):
        self.args = args or sys.argv[1:]
        self.parser = self.get_parser()
        self.cfg = self.parser.parse_args(self.args)

    @classmethod
    def get_parser(cls):
        """ Return the ArgumentParser, populated with subparsers for discovered commands """
        # build arguments from config file and command line
        default_cfg_files = ['ec2hashcat.yml', '~/.ec2hashcat.yml']
        parser = argparse.ArgumentParser(description='Password Cracking in the Cloud',
                                         default_config_files=default_cfg_files,
                                         args_for_setting_config_path=['-c', '--config'],
                                         add_config_file_help=False,
                                         allow_unknown_config_file_keys=True)
        parser.add_argument('-v', '--version', action='version', version='%(prog)s {}'.format(ec2hashcat.__version__))

        global_args = parser.add_argument_group('global arguments')
        global_args.add_argument('-D', '--debug', action='store_true')
        global_args.add_argument('-q', '--quiet', action='store_true', help='Accept default answers to all questions')
        global_args.add_argument('-y', '--yes', action='store_true', help='Assume "yes" to all questions asked')

        # AWS arguments
        aws_args = parser.add_argument_group('aws arguments')
        aws_args.add_argument('--aws-key', required=True, help='AWS Access Key')
        aws_args.add_argument('--aws-secret', required=True, help='AWS Access Secret')
        aws_args.add_argument('--aws-region', default='us-east-1', choices=Ec2.region_ami_map.keys(),
                              help='AWS Region')
        aws_args.add_argument('--s3-bucket', required=True, help='S3 Bucket Name')

        # subcommands
        for cmd, cmd_cls in Registry.get_commands():
            cmd_parser = parser.add_command(cmd, help=cmd_cls.__doc__)
            cmd_cls.setup_parser(cmd_parser)

        return parser

    def dispatch(self):
        """ Dispatch a command to the appropriate class """
        cmd_cls = Registry.get_command(self.cfg.command)
        try:
            return cmd_cls(self.args, self.parser, self.cfg).handle()
        except exceptions.EC2HashcatException, err:
            self.error(err)
        except KeyboardInterrupt:
            print("\n^C caught, cancelling request...")
            self.error(exceptions.Cancelled())

    def error(self, error):
        """ Propogate an error to the best available subparser """
        err_handler = self.parser.get_subparser(self.cfg.command)
        while err_handler.has_subparsers():
            subparsers = err_handler.get_subparsers()
            err_handler = err_handler.get_subparser(getattr(self.cfg, subparsers.dest))
        err_handler.error(error.message, error.show_usage)


class Registry(abc.ABCMeta):
    _commands = {}

    def __init__(cls, *args, **kwargs):
        super(Registry, cls).__init__(*args, **kwargs)
        if cls.__name__[:4] != 'Base':
            Registry._commands[cls.__name__.lower()] = cls

    @classmethod
    def get_command(mcs, cmd):
        return mcs._commands[cmd]

    @classmethod
    def get_commands(mcs):
        sorted_commands = sorted(mcs._commands.keys())
        for cmd in sorted_commands:
            yield cmd, mcs.get_command(cmd)


class BaseCommand(object):
    __metaclass__ = Registry

    help = None

    def __init__(self, args, parser, cfg):
        self.args = args
        self.parser = parser
        self.cfg = cfg

    @classmethod
    def setup_parser(cls, parser):
        pass

    def prompt(self, question, default=None, skip=False):  # pylint: disable=no-self-use
        if skip:
            assert default is not None
        answers_map = {'y': True, 'n': False}
        answers = '[yn]'
        if default is not None:
            default_chr = 'y' if default else 'n'
            answers_map[''] = default
            answers = answers.replace(default_chr, default_chr.upper())
        prompt_txt = '{} {} '.format(question, answers)
        if skip:
            print(prompt_txt)
            return default
        while True:
            answer = raw_input(prompt_txt).lower()
            if answer in answers_map.keys():
                return answers_map[answer]

    @abc.abstractmethod
    def handle(self):  # pylint: disable=no-self-use
        raise NotImplementedError()
