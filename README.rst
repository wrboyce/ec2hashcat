ec2hashcat
==========

Password Cracking in the Cloud

``ec2hashcat`` is a utility to automate the process of password cracking on the AWS Cloud using GPU Instances.


Installation
------------

::

    % pip install ec2hashcat

Thats it!


Configuration
--------------

All arguments beginning with ``--`` can be specified in ``~/.ec2hashcat.yml`` and ``$PWD/ec2hashcat.yml``

.. code:: yaml

    aws-key: AWS_KEY
    aws-secret: AWS_SECRET
    aws-region: AWS_REGION

    ec2-key-name: EC2_KEY_NAME
    ec2-key-file: EC2_KEY_FILE

    s3-bucket: S3_BUCKET_NAME


Usage
-----

For more information, check the online help::

    % ec2hashcat --help
    % ec2hashcat <command> --help

Example
~~~~~~~

A working example using the provided sample files::

    % ec2hashcat crack -b examples/batch.ec2
    % ec2hashcat list sessions
    % ec2hashcat list files
    % ec2hashcat cat wordlists hashlist.dic
    % ec2hashcat get wordlists hashlist.dic
    % ec2hashcat delete dumps hashlist.dmp

Cracking
~~~~~~~~

Handles the uploading/downloading of files to/from S3/EC2, starting/stopping of instances and running ``cudaHashcat``.

Basic usage is very similar to the ``hashcat`` family of programs::

    % ec2hashcat crack -a3 -m0 <hashlist> <mask>
    % ec2hashcat crack -a0 -m0 <hashlist> <wordlist>
    % ec2hashcat crack -a0 -m0 -r <rulesfile> <hashlist> <wordlist>

Any arguments not directly handled by ``ec2hashcat`` can be passed to ``cudaHashcat`` using the ``--hashcat-args`` argument::

    % ec2hashcat crack -a3 -m0 --hashcat-args='--increment' <hashlist> <mask>

``ec2hashcat`` will attempt to detect any filenames passed via ``--hashcat-args`` and handle them appropriatly.

When using the ``--rules`` argument, ``ec2hashcat`` will store any custom rules in S3 and exposes access to the builtin rules using the ``builtin:`` keyword::

    % ec2hashcat crack -a0 -m0 -r builtin:<rulesfile> <hashlist> <wordlist>

By default ``crack`` will write an updated ``hashlist``, ``dump``, and ``wordlist`` to S3, you can use the ``--no-write-hashlists``, ``--no-write-dumps``, and ``--no-write-wordlists`` arguments respectively.

Once the main ``crack`` task has completed and any files updated, the machine will be shut down. To keep the instance alive, use the ``--no-shutdown`` argument. Additionally, to drop into a shell once the task has completed, used the ``--shell`` argument. Note that dropping into a shell will block the shutdown until the shell is exited.

``crack`` can also operate in a batch mode, combining multiple attacks into a single session. The batchfile is specified using the ``--batchfile`` argument, and follows the same rules as script name in ``runscript``::

    % ec2hashcat crack -b+
    batch> crack -a3 -m0 <hashlist> <mask>
    batch> crack -a0 -m0 <hashlist> <wordlist>

    % cat <<EOF | ec2hashcat -b-
    crack -a3 -m0 <hashlist> <mask>
    crack -a0 -m0 <hashlist> <wordlist>

    % cat batch.ec2
    #!/usr/bin/env ec2hashcat -b
    crack -a3 -m0 <hashlist> <mask>
    crack -a0 -m0 <hashlist> <wordlist>
    % ec2hashcat crack -b ./batch.ec2
    % ./batch.ec2

For more information on hashcat usage, see `the hashcat wiki`_.

.. _the hashcat wiki: http://hashcat.net/wiki/

Running Scripts
~~~~~~~~~~~~~~~

Arbitrary scripts can be run against new or running sessions by following similar syntax to ``crack``. Scripts are executed inside a screen named after the local filename.

Run a script on a new instance::

    % ec2hashcat runscript <script>

If the provided ``script`` is ``-`` the script contents will be read from ``STDIN`` and if ``script`` is ``+`` the contents will be promted for.

Run a script on an existing instance (as with ``crack``, the ``--use-instance`` flag implies ``--no-shutdown``)::

    % ec2hashcat runscript -i <session-name> <script>

The ``--no-attach``, ``--shell``, and ``--no-shutdown`` arguments can be used as with the ``crack`` command.

Spot Prices
~~~~~~~~~~~

By default, ``ec2hashcat`` will place a bid at the average price in your selected region.

To check the spot current instance prices::

    % ec2hashcat list prices

File Handling
~~~~~~~~~~~~~

``ec2hashcat`` stores all files in S3 and offers ``delete``, ``get``, ``list``, and ``put`` commands for manipulating them.
There are 4 types of file: ``dumps``, ``hashlists``, ``rules``, and ``wordlists``.

Show all files::

    % ec2hashcat list files

Show all files of a specific type::

    % ec2hashcat list <type>

Download a specific file::

    % ec2hashcat get <type> <name>

Download all wordlists; this will download all wordlists into the current directory::

    % ec2hashcat get wordlists

Download all wordlists and merge into a single wordlist with a specified filename::

    % ec2hashcat get wordlists --merge --outfile=master.lst

Cat a file::

    % ec2hashcat cat <type> <name>

Delete all files of a specified type (prompting for each file)::

    % ec2hashcat delete <type>

Delete all files of a specified type without prompting::

    % ec2hashcat delete -f <type>

Delete the specified files without prompting::

    % ec2hashcat delete <type> <file> <file> ...

Delete the specified files (prompting for each file)::

    % ec2hashcat delete -i <type> <file> <file> ...

Session Handling
~~~~~~~~~~~~~~~~

The session name can be specified by using the ``-s`` or ``--session-name`` argument to the ``crack`` and ``runscript`` commands.

List all active sessions::

    % ec2hashcat list sessions

Attaching to a running ``crack`` session::

    % ec2hashcat crack ... <hashlist>
    % ec2hashcat attach <hashlist>

Attaching to a running ``runscript`` session::

    % ec2hashcat runscript ... <script>
    % ec2hashcat attach -n <script> <script>

Sessions can be attached via the session name or the instance ID::

    % ec2hashcat attach <instance-id>
    % ec2hashcat attach <session-name>

Alternatively, a shell can be opened on the instance using the same syntax as ``attach``::

    % ec2hashcat shell <instance-id>
    % ec2hashcat shell <session-name>

Terminating an instance, giving it a chance to commit work to S3::

    % ec2hashcat stop <instance-id>
    % ec2hashcat stop <session-name>

The ``--force`` flag can be used to initiate immediate termination::

    % ec2hashcat stop -f <instance-id>
    % ec2hashcat stop -f <session-name>

Security Groups
~~~~~~~~~~~~~~~

Manages inbound rules on port 22 for the specified Security Group

View the current allowed masks::

    % ec2hashcat secgrp show

Add the current external IP address::

    % ec2hashcat secgrp add

Add a specified mask::

    % ec2hashcat secgrp add <mask>

Delete a specified mask::

    % ec2hashcat secgrp del <mask>

Delete all masks::

    % ec2hashcat secgrp del -a

Known Issues
------------

- spaces in filenames were an afterthought, for now assume the world will end if you have spaces
- the required AMI is only available in us-east-1 and eu-west-1, if you need another region `open an issue`_.

.. _open an issue: https://github.com/wrboyce/ec2hashcat/issues/new
