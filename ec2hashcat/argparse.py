""" Copyright 2015 Will Boyce """
from __future__ import print_function

import inspect
import sys

import configargparse


class ArgumentParser(configargparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super(ArgumentParser, self).__init__(*args, **kwargs)
        self.subparser_args = {
            'default_config_files': self._default_config_files,
            'allow_unknown_config_file_keys': self._allow_unknown_config_file_keys,
            'args_for_setting_config_path': kwargs['args_for_setting_config_path'],
            'add_config_file_help': self._add_config_file_help
        }
        self.register('action', 'parsers', _SubParsersAction)
        self.register('action', 'store_num', _StoreNumberAction)
        self.subparser_args = inspect.getcallargs(configargparse.ArgumentParser.__init__, self, *args, **kwargs)
        self.subparser_args.pop('self')
        self.subparser_args.pop('description')
        self._subparsers_action = None

    def add_argument_group(self, title, *args, **kwargs):
        """ Look for an existing group with the given name first """
        for group in self._action_groups:
            if group.title == title:
                return group
        return super(ArgumentParser, self).add_argument_group(title, *args, **kwargs)

    def add_subparsers(self, **kwargs):
        """ Keep a reference to the created ``_SubParsersAction`` """
        kwargs['subparser_args'] = self.subparser_args
        action = super(ArgumentParser, self).add_subparsers(**kwargs)
        self._subparsers_action = action
        return action

    def add_command(self, command, **kwargs):
        if self._subparsers_action is None:
            self.add_subparsers(title='commands', dest='command')
        assert self._subparsers_action.dest == 'command'
        return self._subparsers_action.add_parser(command, **kwargs)

    def has_subparsers(self):
        return self._subparsers_action is not None

    def get_subparsers(self):
        return self._subparsers_action

    def get_subparser(self, name):
        if self._subparsers_action is None:
            return None
        return self._subparsers_action._name_parser_map.get(name, None)  # pylint: disable=protected-access

    def error(self, message, show_usage=True):
        """ Print the error message and optional usage information and exit """
        if show_usage:
            self.print_usage(sys.stderr)
        self.exit(2, '{}: error: {}\n'.format(self.prog, message))


class _SubParsersAction(configargparse.argparse._SubParsersAction):  # pylint: disable=too-few-public-methods,protected-access
    def __init__(self, *args, **kwargs):
        self.subparser_args = kwargs.pop('subparser_args')
        super(_SubParsersAction, self).__init__(*args, **kwargs)

    def add_parser(self, name, **kwargs):
        defaults = self.subparser_args.copy()
        defaults.update(kwargs)
        return super(_SubParsersAction, self).add_parser(name, **defaults)


class _StoreNumberAction(configargparse.argparse._StoreAction):
    def __init__(self, **kwargs):
        self.min_value = kwargs.pop('min', None)
        self.max_value = kwargs.pop('max', None)
        super(_StoreNumberAction, self).__init__(**kwargs)

    def __call__(self, parser, namespace, value, option_string=None):
        if self.min_value is not None and value < self.min_value:
            raise configargparse.argparse.ArgumentError(self, 'invalid value: {} is less than {}'
                                                        .format(value, self.min_value))
        if self.max_value is not None and value > self.max_value:
            raise configargparse.argparse.ArgumentError(self, 'invalid value: {} is more than {}'
                                                        .format(value, self.max_value))
        super(_StoreNumberAction, self).__call__(parser, namespace, value, option_string)
