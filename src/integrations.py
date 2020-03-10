"""Contains utility functions to connect with any other services, such as the
database, while processing a request."""
from lblogging import Logger
from pymemcache.client import base as membase
import psycopg2
import pika
import os


def database():
    return psycopg2.connect('')


def logger():
    conn = database()
    logger = Logger(os.environ['APPNAME'], 'integrations.py', database)
    logger.prepare()
    return logger


def memcached():
    memcache_host = os.environ['MEMCACHED_HOST']
    memcache_port = int(os.environ['MEMCACHED_PORT'])
    return membase.Client((memcache_host, memcache_port))


def amqp():
    parameters = pika.ConnectionParameters(
        os.environ['AMQP_HOST'],
        int(os.environ['AMQP_PORT']),
        os.environ['AMQP_VHOST'],
        pika.PlainCredentials(
            os.environ['AMQP_USERNAME'], os.environ['AMQP_PASSWORD']
        )
    )
    amqp = pika.BlockingConnection(parameters)
    channel = amqp.channel()
    channel.confirm_delivery()
    return amqp, channel
