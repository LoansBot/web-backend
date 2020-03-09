"""Initializes the logger"""
from lblogging import Logger, Level
import os
from pymemcache.client import base as membase
import psycopg2
import pika


def _init_logger(database):
    logger = Logger(os.environ['APPNAME'], 'logging.py', database)
    logger.prepare()
    logger.print(Level.TRACE, 'Initialized')
    logger.connection.commit()
    return logger


def _init_memcached():
    memcache_host = os.environ['MEMCACHED_HOST']
    memcache_port = int(os.environ['MEMCACHED_PORT'])
    return membase.Client((memcache_host, memcache_port))


def _init_amqp():
    parameters = pika.ConnectionParameters(
        os.environ['AMQP_HOST'],
        int(os.environ['AMQP_PORT']),
        os.environ['AMQP_VHOST'],
        pika.PlainCredentials(
            os.environ['AMQP_USERNAME'], os.environ['AMQP_PASSWORD']
        )
    )
    return pika.BlockingConnection(parameters)


def _init_amqp_channel(amqp):
    channel = amqp.channel()
    channel.confirm_delivery()
    return channel


DATABASE = psycopg2.connect('')
LOGGER = _init_logger(DATABASE)
MEMCACHED = _init_memcached()
AMQP = _init_amqp()
AMQP_CHANNEL = _init_amqp_channel(AMQP)
