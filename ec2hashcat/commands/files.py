""" Copyright 2015 Will Boyce """
from __future__ import print_function

import os
import subprocess
import tempfile

from fabric.api import hide, local

from ec2hashcat import aws, exceptions
from ec2hashcat.commands.base import BaseCommand


class Cat(BaseCommand):
    """ `cat` files from S3 """

    @classmethod
    def setup_parser(cls, parser):
        super(Cat, cls).setup_parser(parser)
        cat_args = parser.add_argument_group('cat arguments')
        cat_args.add_argument('type', choices=aws.S3Bucket.types)
        cat_args.add_argument('filename')

    def handle(self):
        _, local_name = tempfile.mkstemp()
        s3bucket = aws.S3Bucket(self.cfg)
        s3bucket.download_object(self.cfg.type, self.cfg.filename, local_name, quiet=True)
        subprocess.call(['cat', local_name])
        os.unlink(local_name)


class Delete(BaseCommand):
    """ Delete files from S3 """

    @classmethod
    def setup_parser(cls, parser):
        super(Delete, cls).setup_parser(parser)
        del_args = parser.add_argument_group('delete arguments')
        del_args.add_argument('type', choices=aws.S3Bucket.types)
        del_mutex_args = del_args.add_mutually_exclusive_group()
        del_mutex_args.add_argument('-f', '--force', action='store_true')
        del_mutex_args.add_argument('-i', '--interactive', action='store_true')
        del_args.add_argument('files', metavar='name', nargs='*')

    def handle(self):
        if not self.cfg.files and not self.cfg.force:
            if not self.prompt("Really delete all files of type '{}'?".format(self.cfg.type), default=False):
                raise exceptions.Cancelled()
        s3bucket = aws.S3Bucket(self.cfg)
        if not self.cfg.files:
            self.cfg.files = s3bucket.get_object_list(self.cfg.type)
        for name in self.cfg.files:
            if self.cfg.interactive and not self.prompt('Delete {}/{}?'.format(self.cfg.type, name)):
                continue
            s3bucket.delete_object(self.cfg.type, name)


class Get(BaseCommand):
    """ Download files from S3 """
    merge_strategies = {
        'cat': "cat {} > {}",
        'uniq': "sort -u {} > {}",
        'sort': "cat {} | uniq -c | sort -rn | awk '{{print $2}}' > {}"
    }
    default_merge_strategies = {
        'wordlists': 'sort'
    }

    def __init__(self, *args, **kwargs):
        super(Get, self).__init__(*args, **kwargs)
        self.s3bucket = aws.S3Bucket(self.cfg)

    @classmethod
    def setup_parser(cls, parser):
        super(Get, cls).setup_parser(parser)
        get_args = parser.add_argument_group('get arguments')
        get_args.add_argument('-f', '--force', action='store_true')
        get_args.add_argument('-m', '--merge', action='store_true')
        get_args.add_argument('-s', '--merge-strategy', choices=cls.merge_strategies.keys())
        get_args.add_argument('-o', '--outfile', action='store')
        get_args.add_argument('type', choices=aws.S3Bucket.types)
        get_args.add_argument('files', metavar='name', nargs='*')

    def handle(self):
        self._check_args()
        files = self._get_files()
        self._merge(files)

    def _check_args(self):
        if not self.cfg.files:
            self.cfg.files = self.s3bucket.get_object_list(self.cfg.type)
        if not self.cfg.files:
            raise exceptions.Ec2HashcatInvalidArguments('cannot find any files to download')
        if not self.cfg.merge and self.cfg.outfile is not None and len(self.cfg.files) > 1:
            raise exceptions.Ec2HashcatInvalidArguments(
                'cannot specify outfile when not merging and requesting more than one file')

    def _get_files(self):
        local_names = []
        for remote in self.cfg.files:
            local_name = self.cfg.outfile or os.path.basename(remote)
            if self.cfg.merge:
                _, local_name = tempfile.mkstemp()
            else:
                if os.path.isfile(local_name):
                    prompt_txt = "File '{}' already exists, replace with 's3://{}/{}/{}'?"
                    prompt_txt = prompt_txt.format(local_name, self.cfg.s3_bucket, self.cfg.type, remote)
                    if not self.prompt(prompt_txt, default=self.cfg.force, skip=self.cfg.force):
                        continue
            self.s3bucket.download_object(self.cfg.type, remote, local_name)
            local_names.append(local_name)
        return local_names

    def _merge(self, files):
        if self.cfg.merge:
            if self.cfg.outfile is None:
                self.cfg.outfile = '{}.{}'.format(
                    '+'.join(os.path.basename(src).rsplit('.', 1)[0] for src in self.cfg.files),
                    self.cfg.type.rstrip('s'))
            print('Merging files...')
            if self.cfg.merge_strategy is None:
                self.cfg.merge_strategy = self.default_merge_strategies[self.cfg.type]
                if self.cfg.type == 'wordlists':
                    self.cfg.merge_strategy = 'sort'
                else:
                    self.cfg.merge_strategy = 'uniq'
            sort_cmd = self.merge_strategies[self.cfg.merge_strategy]
            with hide('commands'):
                local(sort_cmd.format(' '.join(files), self.cfg.outfile))
            if self.cfg.merge:
                for name in files:
                    os.unlink(name)
            print('Saved as {}'.format(self.cfg.outfile))


class Put(BaseCommand):
    """ Upload files to S3 """

    @classmethod
    def setup_parser(cls, parser):
        super(Put, cls).setup_parser(parser)
        put_args = parser.add_argument_group('put arguments')
        put_args.add_argument('-f', '--force', action='store_true')
        put_args.add_argument('type', choices=aws.S3Bucket.types)
        put_args.add_argument('files', metavar='filename', nargs='+',
                              help='file(s) to upload')

    def handle(self):
        s3bucket = aws.S3Bucket(self.cfg)
        for name in self.cfg.files:
            if s3bucket.object_exists(self.cfg.type, os.path.basename(name)):
                prompt_txt = "File '{}/{}' already exists in S3, replace with '{}'?".format(
                    self.cfg.type, os.path.basename(name), name)
                if not self.prompt(prompt_txt, default=self.cfg.force, skip=self.cfg.force):
                    continue
            s3bucket.put_object(self.cfg.type, name)
