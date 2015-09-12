"""
    Copyright 2015 Will Boyce

    There is some magic below to handle importing everything defined under ec2hashcat.commands
    so the command registry can be populated.
"""
import pkgutil


for loader, module_path, is_pkg in pkgutil.walk_packages(__path__):
    loader.find_module(module_path).load_module(module_path)
