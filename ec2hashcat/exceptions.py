""" Copyright 2015 Will Boyce """


class EC2HashcatException(Exception):
    """ Base ec2hashcat Exception Class """
    show_usage = True


class Ec2HashcatInvalidArguments(EC2HashcatException):
    """ Raised when invlaid arguments are passed from the CLI. """
    pass


class FileNotFoundError(EC2HashcatException, IOError):
    """ Raised when specified files cannot be found locally. """
    show_usage = False

    def __init__(self, filename):
        message = "No such file or directory: '{}'".format(filename)
        super(FileNotFoundError, self).__init__(message)


class S3FileNotFoundError(EC2HashcatException):
    """ Raised when a requested file does not exist on S3. """
    show_usage = False

    def __init__(self, filetype, filename, bucket):
        message = "File of type '{}' with name '{}' does not exist on S3 bucket '{}'"
        super(S3FileNotFoundError, self).__init__(message.format(filetype, filename, bucket))


class EC2InvalidSpotPrice(EC2HashcatException):
    """ Raised when the provided bid price does not make sense. """
    def __init__(self, price):
        message = "Cannot place bid with value of '{}'".format(price)
        super(EC2InvalidSpotPrice, self).__init__(message)


class EC2InstanceError(EC2HashcatException):
    """ Raised when an issue is encountered starting an instance. """
    show_usage = False


class Cancelled(EC2HashcatException):
    """ Raised when the operation is cancelled by the user. """
    show_usage = False

    def __init__(self):
        message = "Operation was cancelled."
        super(Cancelled, self).__init__(message)
