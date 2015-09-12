""" Copyright 2015 Will Boyce """
from __future__ import print_function

import os
import re

from boto3.session import Session

from ec2hashcat import exceptions


class S3Bucket(object):
    types = ('hashlists', 'dumps', 'wordlists', 'rules')

    def __init__(self, cfg):
        self.cfg = cfg
        aws = Session(aws_access_key_id=self.cfg.aws_key,
                      aws_secret_access_key=self.cfg.aws_secret,
                      region_name=self.cfg.aws_region)
        self.s3_client = aws.client('s3')
        self.bucket = aws.resource('s3').create_bucket(Bucket=self.cfg.s3_bucket)

    def __getattr__(self, name):
        types = [t.rstrip('s') for t in self.types]
        attr_rx = [
            re.compile('(?P<before>download|get|put)_(?P<type>{})_?(?P<after>objects|s|)'.format('|'.join(types))),
            re.compile('(?P<type>{})_(?P<after>exists)'.format('|'.join(types)))]
        for rgx in attr_rx:
            match = rgx.match(name)
            if match:
                groups = match.groupdict()
                groups['type'] = '{}s'.format(groups['type'])
                if groups['after'] == 's':
                    groups['after'] = 'list'
                attr = ['']
                for key in ('before', 'after'):
                    if key in groups and groups[key]:
                        attr.append(groups[key])
                attr = '_'.join(attr)
                return self.__getattribute__(attr)(groups['type'])
        raise AttributeError("'{}' object has no attribute '{}'".format(
            self.__class__.__name__, name))

    def __dir__(self):
        funcs = [
            'delete_object',
            'download_object',
            'get_object',
            'get_objects',
            'get_object_list',
            'object_exists',
            'put_object']
        func_templates = ('delete_{}', 'download_{}', 'get_{}', 'get_{}s', 'get_{}_objects', '{}_exists', 'put_{}')
        obj_types = [t[:-1] for t in self.types]
        func_matrix = zip(sorted(func_templates * len(obj_types)), obj_types * len(func_templates))
        for func_template, obj_type in func_matrix:
            funcs.append(func_template.format(obj_type))
        return sorted(funcs)

    def _delete_object(self, object_type):
        """ Handler for 'download_<type>' """
        return lambda name: self.download_object(object_type, name)

    def _download_object(self, object_type):
        """ Handler for 'download_<type>' """
        return lambda remote, local=None: self.download_object(object_type, remote, local)

    def _get_object(self, object_type):
        """ Handler for 'get_<type>' """
        return lambda name: self.get_object(object_type, name)

    def _get_objects(self, object_type):
        """ Handler for 'get_<type>s' """
        return lambda: self.get_objects(object_type)

    def _get_list(self, object_type):
        """ Handler for 'get_<type>_list' """
        return lambda: self.get_object_list(object_type)

    def _exists(self, object_type):
        """ Handler for '<type>_exists' """
        return lambda name: self.object_exists(object_type, name)

    def _put(self, object_type):
        """ Handler for 'put_<type>' """
        return lambda local, remote=None: self.put_object(object_type, local, remote)

    def delete_object(self, object_type, name):
        if not self.object_exists(object_type, name):
            raise exceptions.S3FileNotFoundError(object_type, name, self.cfg.s3_bucket)
        name = os.path.join(object_type, name)
        print("rm s3://{}/{}".format(self.cfg.s3_bucket, name))
        self.s3_client.delete_object(Bucket=self.cfg.s3_bucket, Key=name)

    def download_object(self, object_type, remote, local=None, quiet=False):
        if not self.object_exists(object_type, remote):
            raise exceptions.S3FileNotFoundError(object_type, remote, self.cfg.s3_bucket)
        if local is None:
            local = os.path.basename(remote)
        remote = os.path.join('{}'.format(object_type), remote)
        if not quiet:
            print("s3://{}/{} -> {}".format(self.cfg.s3_bucket, remote, local))
        self.s3_client.download_file(
            Bucket=self.cfg.s3_bucket,
            Key=remote,
            Filename=local)

    def get_object(self, object_type, name):
        """ Get an object representing the specified file on S3 """
        name = os.path.join(object_type, name)
        for obj in self.bucket.objects.filter(Prefix=name):
            if obj.key == name:
                return obj
        return exceptions.S3FileNotFoundError(object_type, name, self.cfg.s3_bucket)

    def get_objects(self, object_type):
        """ Return objects representing all files of a given type in S3 """
        return [obj for obj in self.bucket.objects.filter(Prefix='{}/'.format(object_type))
                if obj.key != '{}/'.format(object_type)]

    def get_object_list(self, object_type):
        """ List all filenames of a given type in S3 """
        return [o.key.split('/', 1)[1] for o in self.get_objects(object_type)]

    def object_exists(self, object_type, name):
        """ Check if a file exists in S3 """
        return name in self.get_object_list(object_type)

    def put_object(self, object_type, local, remote=None):
        """ Upload the specified file to S3 """
        if not os.path.isfile(local):
            raise exceptions.FileNotFoundError(local)
        if remote is None:
            remote = local
        remote = os.path.join('{}'.format(object_type), os.path.basename(remote))
        print("{} -> s3://{}/{}".format(local, self.cfg.s3_bucket, remote))
        return self.s3_client.upload_file(Filename=local, Bucket=self.cfg.s3_bucket, Key=remote)
