#!/usr/bin/env python
""" Copyright 2015 Will Boyce """
from setuptools import setup, find_packages

import ec2hashcat


setup(
    name='ec2hashcat',
    version=ec2hashcat.__version__,
    description='Password Cracking in the Cloud',
    long_description=file('README.rst').read(),
    author='Will Boyce',
    author_email='me@willboyce.com',
    url='https://www.github.com/wrboyce/ec2hashcat',
    license='License :: OSI Approved :: Apache Software License',
    install_requires=[l.strip() for l in file('requirements.in').readlines()],
    packages=find_packages(),
    package_data={'': ['README.rst', 'LICENCE', 'requirements.in']},
    include_package_data=True,
    entry_points={'console_scripts': ['ec2hashcat = ec2hashcat.cli:main']},
    platforms=[
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX',
    ],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 2.7',
        'Topic :: Security'
    ],
)
