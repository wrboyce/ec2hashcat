""" Copyright 2015 Will Boyce """
from __future__ import print_function

from collections import defaultdict
from datetime import datetime
import hashlib
import os
import tempfile
from time import sleep

import botocore
from boto3.session import Session
from fabric.api import cd, env, hide, open_shell, put, run
from fabric.contrib.files import append

from ec2hashcat import exceptions


class Ec2(object):
    region_ami_map = {
        'us-east-1': 'ami-dbceb0be',
        'eu-west-1': 'ami-e5ad8492',
    }

    def __init__(self, cfg):
        self.cfg = cfg
        self.aws = Session(aws_access_key_id=self.cfg.aws_key,
                           aws_secret_access_key=self.cfg.aws_secret,
                           region_name=self.cfg.aws_region)
        self.ec2 = self.aws.resource('ec2')

    def get_instances(self):
        return self.ec2.instances.filter(Filters=[{
            'Name': 'tag:service',
            'Values': ['ec2hashcat']}])

    def find_running_instance(self, identifier):
        attr, values = '', [identifier]
        if identifier.startswith('i-'):
            attr = 'instance-id'
        else:
            attr = 'tag:ec2hashcat'
        instances = self.get_instances().filter(Filters=[
            {'Name': 'instance-state-name', 'Values': ['running']},
            {'Name': attr, 'Values': values}])
        try:
            return Ec2Instance(self.cfg, instance_id=list(instances)[0].instance_id)
        except ValueError:
            raise

    def get_instance_by_id(self, instance_id):
        return self.ec2.Instance(instance_id)

    def get_instance_by_tag(self, tag):
        instances = self.get_instances().filter(Filters=[
            {'Name': 'tag:ec2hashcat', 'Values': [tag]},
            {'Name': 'instance-state-name', 'Values': ['running']}])
        instance = instances.all()[0]
        return self.ec2.Instance(instance.id)

    def get_spot_prices(self, instance_type=None, meta=True):
        if instance_type is None:
            instance_type = self.cfg.ec2_instance_type
        prices = self.aws.client('ec2').describe_spot_price_history(InstanceTypes=[instance_type],
                                                                    ProductDescriptions=['Linux/UNIX'])
        prices = prices['SpotPriceHistory']
        zone_prices = defaultdict(list)
        for price in prices:
            zone = price['AvailabilityZone']
            zone_prices[zone].append(float(price['SpotPrice']))
        for zone, prices in zone_prices.iteritems():
            zone_prices[zone] = sum(prices) / len(prices)
        data = sorted(zone_prices.items())
        if meta:
            data.append(('min', min(zone_prices.values())))
            data.append(
                ('avg', sum(zone_prices.values()) / len(zone_prices.values())))
            data.append(('max', max(zone_prices.values())))
        return data

    def calculate_spot_price(self):
        prices = dict(self.get_spot_prices())
        if self.cfg.ec2_spot_price in prices:
            return str(prices[self.cfg.ec2_spot_price])
        try:
            float(self.cfg.ec2_spot_price)
            return self.cfg.ec2_spot_price
        except ValueError:
            raise exceptions.EC2InvalidSpotPrice(self.cfg.ec2_spot_price)

    def get_instance_spotprice(self, instance):
        if instance.spot_instance_request_id is not None:
            ec2_client = self.aws.client('ec2')
            data = ec2_client.describe_spot_instance_requests(
                SpotInstanceRequestIds=[instance.spot_instance_request_id])
            return data['SpotInstanceRequests'][0]['SpotPrice']
        return '-'

    def start_instance(self, tag=None):
        instance = Ec2Instance(self.cfg)
        instance.start(tag)
        return instance


class Ec2Instance(object):
    """ Utility class for interacting with an EC2 Instance """
    def __init__(self, cfg, instance_id=None):
        self.cfg = cfg
        self.instance = None
        self.secgrp = SecurityGroup(self.cfg)
        aws = Session(aws_access_key_id=self.cfg.aws_key,
                      aws_secret_access_key=self.cfg.aws_secret,
                      region_name=self.cfg.aws_region)
        self.ec2 = aws.resource('ec2')
        self.ec2_client = aws.client('ec2')
        self.tag = None
        if instance_id is not None:
            self.instance = self.ec2.Instance(instance_id)
            env.host_string = 'ubuntu@{}'.format(self.instance.public_ip_address)
            env.key_filename = os.path.expanduser(self.cfg.ec2_key_file)
            env.connection_attempts = 5

    def start(self, tag=None):
        """ Start the instance. """
        ami_id = Ec2.region_ami_map[self.cfg.aws_region]
        ami_blockdevmap = self.ec2_client.describe_images(ImageIds=[ami_id])['Images'][0]['BlockDeviceMappings']
        ami_blockdevmap[0]['Ebs']['VolumeSize'] = self.cfg.ec2_volume_size
        launch_spec = dict(
            ImageId=ami_id,
            KeyName=self.cfg.ec2_key_name,
            SecurityGroups=[self.cfg.ec2_security_group],
            InstanceType=self.cfg.ec2_instance_type,
            BlockDeviceMappings=ami_blockdevmap)
        if not self.cfg.ec2_spot_instance:
            print("Launching EC2 Instance with Type '{}' using AMI '{}'"
                  .format(self.cfg.ec2_instance_type, ami_id))
            self.instance = self.ec2.create_instances(
                MinCount=1,
                MaxCount=1,
                InstanceInitiatedShutdownBehavior='terminate',
                **launch_spec)
        else:
            zone_pricing = Ec2(self.cfg).get_spot_prices(meta=False)
            #zone = zone_pricing[len(zone_pricing) / 2][0]
            zone = min(zone_pricing)[0]
            if self.cfg.ec2_spot_price in zone_pricing:
                zone = self.cfg.ec2_spot_price
            price = Ec2(self.cfg).calculate_spot_price()
            print("Requesting Spot Instance of type '{}' at {} USD/hour using AMI '{}'... this will take a while!"
                  .format(self.cfg.ec2_instance_type, price, ami_id))
            request_id = self.ec2_client.request_spot_instances(
                SpotPrice=price,
                AvailabilityZoneGroup=zone,
                ClientToken='ec2hashcat-{}'.format(datetime.now().strftime('%Y%m%d%H%M%S')),
                InstanceCount=1,
                LaunchSpecification=launch_spec)['SpotInstanceRequests'][0]['SpotInstanceRequestId']
            try:
                waiter = self.ec2_client.get_waiter('spot_instance_request_fulfilled')
                waiter.wait(SpotInstanceRequestIds=[request_id])
            except KeyboardInterrupt:
                self.ec2_client.cancel_spot_instance_requests(SpotInstanceRequestIds=[request_id])
                raise
            except botocore.exceptions.WaiterError:
                self.ec2_client.cancel_spot_instance_requests(SpotInstanceRequestIds=[request_id])
                if self.cfg.debug:
                    raise
                else:
                    raise exceptions.EC2InstanceError(
                        "An error occurred waiting for Spot Request '{}' to be fulfilled."
                        .format(request_id))
            instance_id = self.ec2_client.describe_spot_instance_requests(
                SpotInstanceRequestIds=[request_id])['SpotInstanceRequests'][0]['InstanceId']
            self.instance = self.ec2.Instance(instance_id)

        self.wait_until_ready()
        self.add_tags({'service': 'ec2hashcat'})
        if tag is not None:
            self.set_session_tag(tag)
        self.setup_fabric()
        self.setup_awscli()

    def add_tags(self, tags_dict):
        tags = [dict(Key=key, Value=value) for key, value in tags_dict.iteritems()]
        self.instance.create_tags(Tags=tags)

    def set_session_tag(self, value):
        self.tag = value
        self.add_tags(dict(ec2hashcat=value))

    def wait_until_ready(self, wait_time=90):
        """ Wait until the instance is running and has a public ip address. """
        print("Waiting for Instance '{}'... this will take a while!".format(self.instance.id))
        try:
            self.instance.wait_until_running()
        except botocore.exceptions.WaiterError:
            raise exceptions.EC2InstanceError(
                "An error occurred waiting for Instance '{}' to become available."
                .format(self.instance.id))
        sleep(wait_time)  # yep, takes about 90 seconds for ssh to be ready
        self.instance = self.ec2.Instance(self.instance.id)
        if self.instance.public_ip_address is None:
            return self.wait_until_ready(wait_time)

    def setup_fabric(self):
        """ Setup the fabric env """
        print("Configuring Instance '{}' on IP '{}'..."
              .format(self.instance.id, self.instance.public_ip_address))
        env.host_string = 'ubuntu@{}'.format(self.instance.public_ip_address)
        env.key_filename = os.path.expanduser(self.cfg.ec2_key_file)
        env.connection_attempts = 5

    def setup_awscli(self):
        """ Setup aws cli on the instance """
        aws_config = ['[default]',
                      'aws_access_key_id = {}'.format(self.cfg.aws_key),
                      'aws_secret_access_key = {}'.format(self.cfg.aws_secret),
                      'region = {}'.format(self.cfg.aws_region)]
        self.execute_command('mkdir -p /home/ubuntu/.aws')
        self.create_file('/home/ubuntu/.aws/config', aws_config)

    def set_pretermination_command(self, command):
        """ Sets a command to executed when a spot-instance termination notice is received. """
        metadata_url = 'http://169.254.169.254/latest/meta-data/spot/termination-time'
        cmd = 'while sleep 5; do curl -s {} | grep -q .*T.*Z && {} && break; done'.format(metadata_url, command)
        self.execute_command('screen -dmS termination_handler /bin/bash -c "{}"'
                             .format(cmd), pty=False)

    def terminate(self, wait=False):
        """ Terminate the instance. """
        print("Terminating Instance '{}'...".format(self.instance.id))
        self.instance.terminate()
        if wait:
            print("Waiting for Instance '{}' to Terminate...".format(self.instance.id))
            self.instance.wait_until_terminated()

    def create_file(self, filename, contents, mode=None):
        """ Create a file on the remote host """
        with hide('commands'):
            append(filename, contents)
        if mode is not None:
            self.execute_command('chmod {} {}'.format(mode, filename))

    def create_script(self, commands):
        """ Create a script comprising of ``commands`` and return filename. """
        remote_fn = '{}.sh'.format(hashlib.md5(''.join(commands)).hexdigest())
        remote_fn = os.path.join('/tmp', remote_fn)
        if not commands[0].startswith('#!'):
            commands.insert(0, '#!/bin/bash')
        local_fh = tempfile.NamedTemporaryFile(mode='w')
        local_fh.writelines('{}\n'.format(cmd) for cmd in commands)
        local_fh.flush()
        self.copy_file(local_fh.name, remote_fn, '0755')
        return remote_fn

    @classmethod
    def copy_file(cls, local, remote, mode='0644'):
        """ Copy local file to the instance. """
        with hide('commands'):
            put(local_path=local, remote_path=remote, mode=mode)

    def get_file(self, name, path='/tmp'):
        """ Grab the specified file from the S3 Bucket. """
        dst = os.path.join(path, os.path.basename(name))
        print('s3://{}/{} -> ec2://{}{}'.format(self.cfg.s3_bucket, name, self.instance.id, dst))
        cmd = 'aws s3 cp s3://{}/{} {}'.format(self.cfg.s3_bucket, name, dst)
        self.execute_command(cmd, path='/')

    def get_hashlist(self, name, path='/tmp'):
        """ Grab a hashlist from the S3 Bucket. """
        self.get_file(os.path.join('hashlists', name), path=path)

    def get_wordlist(self, name, path='/tmp'):
        """ Grab a wordlist from the S3 Bucket. """
        self.get_file(os.path.join('wordlists', name), path=path)

    def get_rules(self, name, path='/tmp'):
        """ Grab a rules file from the S3 Bucket. """
        self.get_file(os.path.join('rules', name), path=path)

    def put_file(self, name, path):
        """ Upload a file from the instance to S3 """
        print('ec2://{}{} -> s3://{}/{}'.format(
            self.instance.id, name, self.cfg.s3_bucket, os.path.join(path, os.path.basename(name))))
        with cd('/') and hide('commands'):
            run('aws s3 cp {} s3://{}/{}'.format(
                name, self.cfg.s3_bucket, os.path.join(path, os.path.basename(name))))

    @classmethod
    def execute_command(cls, command, path='/tmp', pty=True, quiet=True):
        """ Execute a command on the instance. """
        with cd(path) and hide('running'):
            run(command, pty=pty, quiet=quiet, warn_only=not quiet)

    @classmethod
    def create_screen(cls, name, command, attach=True, path='/tmp'):
        cmd = 'screen -{}S {} {}'.format('dm' if not attach else '', name, command)
        cls.execute_command(cmd, path=path, pty=attach, quiet=not attach)

    @classmethod
    def attach_screen(cls, name):
        cls.execute_command('screen -r {}'.format(name), quiet=False)

    @classmethod
    def open_shell(cls, path='/tmp'):
        """ Open a shell on the remote instance. """
        with cd(path):
            open_shell()


class SecurityGroup(object):
    def __init__(self, cfg):
        self.cfg = cfg
        aws = Session(aws_access_key_id=self.cfg.aws_key,
                      aws_secret_access_key=self.cfg.aws_secret,
                      region_name=self.cfg.aws_region)
        ec2 = aws.resource('ec2')
        try:
            self.secgrp = list(ec2.security_groups.filter(GroupNames=[self.cfg.ec2_security_group]))[0]
        except botocore.exceptions.ClientError:
            self.secgrp = ec2.create_security_group(GroupName=self.cfg.ec2_security_group, Description='ec2hashcat')

    def get_masks(self):
        for perm in self.secgrp.ip_permissions:
            if perm['ToPort'] == 22:
                return [d['CidrIp'] for d in perm['IpRanges']]
        return []

    def add_mask(self, mask):
        if mask in self.get_masks():
            return
        print("Adding '{}' to Security Group '{}'".format(mask, self.cfg.ec2_security_group))
        self.secgrp.authorize_ingress(
            IpProtocol='tcp',
            FromPort=22,
            ToPort=22,
            CidrIp=mask)

    def del_mask(self, mask):
        print("Removing '{}' from Security Group '{}'".format(mask, self.cfg.ec2_security_group))
        self.secgrp.revoke_ingress(
            IpProtocol='tcp',
            FromPort=22,
            ToPort=22,
            CidrIp=mask)

    def add_ip(self, ip_addr):
        return self.add_mask('{}/32'.format(ip_addr))

    def del_ip(self, ip_addr):
        return self.del_mask('{}/32'.format(ip_addr))
