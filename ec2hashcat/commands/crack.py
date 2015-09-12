""" Copyright 2015 Will Boyce """
from __future__ import print_function

import os
import shlex

from ec2hashcat import aws, exceptions
from ec2hashcat.commands.runscript import BaseEc2InstanceSessionCommand


class Crack(BaseEc2InstanceSessionCommand):
    """ Launch an EC2 Instance and crack the specified file(s) """
    hashcat_home = '/opt/cudaHashcat-1.37'

    @classmethod
    def setup_parser(cls, parser, final=False):
        super(Crack, cls).setup_parser(parser)
        crack_args = parser.add_argument_group('crack arguments')
        crack_args.add_argument('--no-write-hashlists', action='store_false', dest='update_hashlist', default=True,
                                help='Do not remove cracked hashes from the hashlist')
        crack_args.add_argument('--no-write-dumps', action='store_false', dest='dump_cracked', default=True,
                                help='Do not dump cracked hashes (hash:salt:pass:hex)')
        crack_args.add_argument('--no-write-worlists', action='store_false', dest='make_dict', default=True,
                                help='Do not generate/update a wordlist from cracked passwords from list hashlist')
        crack_args.add_argument('-b', '--batchfile', default=None,
                                help='Execute a batch of `crack` tasks')

        hc_args = parser.add_argument_group('hashcat arguments')
        hc_args.add_argument('-a', '--attack-mode', required=final,
                             help='Hashcat attack mode')
        hc_args.add_argument('-m', '--hash-type', required=final,
                             help='Hash type')
        hc_args.add_argument('-r', '--rules', help='Rules files to use')
        hc_args.add_argument('-A', '--hashcat-args', default='',
                             help='Additional hashcat arguments')
        hc_args.add_argument('target', metavar='HASHLIST', nargs=1 if final else '?',
                             help='filename of hashlist to crack (local or s3)')
        hc_args.add_argument('src', metavar='MASK|WORDLIST', nargs='*',
                             help='wordlists or masks to use in attack (default=all wordlists)')

    def handle(self):
        batch = self._get_batch()
        self._upload_files(batch)
        if self.cfg.session_name is None:
            self.cfg.session_name = '+'.join(set(os.path.basename(cfg.target) for cfg in batch))
        instance = self._bootstrap_instance(batch)
        script = self._generate_script(batch)
        self._start_task(instance, script)

    def _get_batch(self):
        # bit of a hack here to let us override the subparser and rerun it over the batches
        subparser = self.parser.add_command(self.cfg.command)
        self.setup_parser(subparser, final=True)
        if self.cfg.batchfile is None:
            return [self.parser.parse_args(self.args)]
        else:
            if self.cfg.batchfile == '-':
                self.cfg.attach = False
                self.cfg.quiet = True
            return [self.parser.parse_args(shlex.split(line))
                    for line in self._read_file(self.cfg.batchfile, prompt='batch>')]

    def _handle_file(self, s3bucket, filetype, local_fn, error=True):
        exists_local = os.path.isfile(local_fn)
        remote_fn = os.path.basename(local_fn)
        exists_remote = s3bucket.object_exists(filetype, remote_fn)
        if exists_local:
            upload = True
            if exists_remote:
                prompt_txt = "File '{}/{}' already exists in S3, replace with '{}'?".format(
                    filetype, remote_fn, local_fn)
                upload = self.prompt(prompt_txt, default=self.cfg.yes, skip=self.cfg.quiet)
            if upload:
                s3bucket.put_object(filetype, local_fn)
        elif not exists_remote and error:
            raise exceptions.FileNotFoundError(local_fn)

    def _upload_files(self, batch):
        print("Uploading files to S3...")
        s3bucket = aws.S3Bucket(self.cfg)
        uploaded_targets, uploaded_sources, uploaded_rules = set(), set(), set()
        for cfg in batch:
            # upload targets
            cfg.target = cfg.target[0] if isinstance(cfg.target, list) else cfg.target
            if cfg.target not in uploaded_targets:
                self._handle_file(s3bucket, 'hashlists', cfg.target)
                uploaded_targets.add(cfg.target)
            cfg.target = os.path.join('/tmp', os.path.basename(cfg.target))

            # upload sources
            sources = []
            if not cfg.src:  # if no source specified, use all wordlists
                cfg.src = s3bucket.get_wordlists()
            else:
                for src in cfg.src:
                    if '?' not in src:  # a '?' in a source indicates a mask
                        # do not raise errors for missing source files when processing a batch
                        if src not in uploaded_sources:
                            self._handle_file(s3bucket, 'wordlists', src, len(batch) == 1)
                            uploaded_sources.add(src)
                        sources.append(os.path.join('/tmp', os.path.basename(src)))
                    else:
                        sources.append(src)
                cfg.src = sources

            # upload rules
            if cfg.rules is not None:
                if cfg.rules.startswith('builtin:'):
                    cfg.rules = cfg.rules.replace('builtin:', os.path.join(self.hashcat_home, 'rules/'))
                else:
                    if cfg.rule not in uploaded_rules:
                        self._handle_file(s3bucket, 'rules', cfg.rules)
                        uploaded_rules.add(cfg.rules)
                    cfg.rules = os.path.join('/tmp', os.path.basename(cfg.rules))

    def _bootstrap_instance(self, batch):
        instance = self._get_instance()

        # bootstrap instance
        print('Bootstrapping Instance...')
        targets, sources, rules = set(), set(), set()
        for cfg in batch:
            targets.add(cfg.target)
            sources = sources.union(cfg.src)
            rules.add(cfg.rules)

        for target in targets:
            instance.get_hashlist(os.path.basename(target))
        for src in sources:
            if '?' not in src:
                instance.get_wordlist(os.path.basename(src))
        for rule in rules:
            if rule and not rule.startswith(self.hashcat_home):
                instance.get_rules(os.path.basename(rule))

        # detect & upload additional files, rewriting paths
        for cfg in batch:
            hashcat_args = cfg.hashcat_args
            for arg in cfg.hashcat_args.split():
                if '=' in arg:
                    arg = arg.split('=', 1)[1]
                if os.path.isfile(arg):
                    remote = os.path.join('/tmp', os.path.basename(arg))
                    instance.copy_file(arg, remote)
                    hashcat_args = hashcat_args.replace(arg, remote)
            cfg.hashcat_args = hashcat_args

        return instance

    def _generate_script(self, batch):
        # generate script commands
        commands = ['INSTANCE_ID="$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)"']
        hashcat_bin = os.path.join(self.hashcat_home, 'cudaHashcat64.bin')
        for i, cfg in enumerate(batch, start=1):
            target_base = cfg.target.rsplit('.', 1)[0]
            commands.append('# batch {}'.format(i))
            commands.append('test -f {}.orig || cp {} {}.orig'.format(cfg.target, cfg.target, cfg.target))
            commands.append('{} -a{} -m{} --remove {} {} {} {}'.format(
                hashcat_bin,
                cfg.attack_mode,
                cfg.hash_type,
                '-r {}'.format(cfg.rules) if cfg.rules is not None else '',
                cfg.hashcat_args,
                cfg.target,
                ' '.join(cfg.src)))
            if cfg.update_hashlist:
                # update the s3 hashlist with remaining (uncracked) hashes
                commands.append('echo Uploading updated hashlist to S3...')
                commands.append('echo "ec2://$INSTANCE_ID{} -> s3://{}/hashlists/{}"'
                                .format(cfg.target, self.cfg.s3_bucket, os.path.basename(cfg.target)))
                commands.append('aws s3 cp {} s3://{}/hashlists/{} >/dev/null'
                                .format(cfg.target, self.cfg.s3_bucket, os.path.basename(cfg.target)))
            if cfg.dump_cracked:
                commands.append('echo Merging hashdump...')
                # download any previous dumps for this hashlist
                commands.append('aws s3 cp s3://{}/dumps/{}.dmp {}.dmp1 >/dev/null'
                                .format(cfg.s3_bucket, os.path.basename(target_base), target_base))
                # merge with dump for this session
                commands.append('{} --quiet --show --outfile-format=7 --outfile={}.dmp2 {}.orig'
                                .format(hashcat_bin, target_base, cfg.target))
                commands.append('sort -u {}.dmp? > {}.dmp'.format(target_base, target_base))
                # and upload to s3 /dumps/<target>
                commands.append('echo Uploading updated hashdump to S3...')
                commands.append('echo "ec2://$INSTANCE_ID{}.dmp -> s3://{}/dumps/{}.dmp"'
                                .format(target_base, self.cfg.s3_bucket, os.path.basename(target_base)))
                commands.append('aws s3 cp {}.dmp s3://{}/dumps/{}.dmp >/dev/null'
                                .format(target_base, self.cfg.s3_bucket, os.path.basename(target_base)))
            if cfg.make_dict:
                commands.append('echo Merging wordlist...')
                # download previous wordlist for this hashlist
                commands.append('aws s3 cp s3://{}/wordlists/{}.dic {}.dic1 >/dev/null'
                                .format(cfg.s3_bucket, os.path.basename(target_base), target_base))
                # merge with wordlist for this session
                commands.append('{} --quiet --show --outfile-format=2 --outfile={}.dic2 {}.orig'
                                .format(hashcat_bin, target_base, cfg.target))
                commands.append("sort {}.dic? | uniq -c | sort -rn | awk '{{print $2}}' > {}.dic"
                                .format(target_base, target_base))
                # and upload to s3 /wordlists/<target>
                commands.append('echo Uploading updated wordlist to S3...')
                commands.append('echo "ec2://$INSTANCE_ID{}.dic -> s3://{}/wordlists/{}.dic"'
                                .format(target_base, self.cfg.s3_bucket, os.path.basename(target_base)))
                commands.append('aws s3 cp {}.dic s3://{}/wordlists/{}.dic >/dev/null'
                                .format(target_base, self.cfg.s3_bucket, os.path.basename(target_base)))
        for target in set(cfg.target for cfg in batch):
            # delete any cracked hashlists from S3
            commands.append('echo Deleting {} from S3...'.format(os.path.basename(target)))
            commands.append('test -f {} && test -s {} || aws s3 rm s3://{}/hashlists/{} >/dev/null'
                            .format(target, target, self.cfg.s3_bucket, os.path.basename(target)))
        if self.cfg.shell:
            commands.append('bash')
        if self.cfg.shutdown:
            commands.append('sudo poweroff')
        return commands

    def _start_task(self, instance, commands):
        # set pre-termination hook so we don't lose work
        if self.cfg.ec2_spot_instance:
            instance.set_pretermination_command('killall cudaHashcat64.bin')
        # upload scrip to instance
        script_fn = instance.create_script(commands)
        # run script
        print("Starting {}Session with Target '{}'".format('Detached ' if not self.cfg.attach else '', instance.tag))
        instance.create_screen('ec2hashcat', script_fn, attach=self.cfg.attach)
