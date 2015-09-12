""" Copyright 2015 Will Boyce """
from __future__ import print_function


def main():
    """ Main entry point for the `ec2hashcat` command """
    from fabric.state import connections

    from ec2hashcat.commands.base import Handler

    try:
        handler = Handler()
        handler.dispatch()
    finally:
        for key in connections.keys():
            connections[key].close()
            del connections[key]
