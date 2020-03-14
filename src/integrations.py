"""Contains utility functions to connect with any other services, such as the
database, while processing a request."""
from lblogging import Logger
from pymemcache.client import base as membase
import psycopg2
import pika
import os
from contextlib import contextmanager


@contextmanager
def database(val=None):
    if val is not None:
        yield val
        return

    conn = psycopg2.connect('')
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def logger(iden='integrations.py', val=None):
    if val is not None:
        yield val.with_iden(iden)
        return

    with database() as conn:
        conn.autocommit = True
        logger = Logger(os.environ['APPNAME'], iden, conn)
        logger.prepare()
        yield logger


@contextmanager
def memcached(val=None):
    if val is not None:
        yield val
        return

    memcache_host = os.environ['MEMCACHED_HOST']
    memcache_port = int(os.environ['MEMCACHED_PORT'])
    client = membase.Client((memcache_host, memcache_port))
    try:
        yield client
    finally:
        client.close()


@contextmanager
def amqp(val=None):
    if val is not None:
        yield val
        return

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
    try:
        yield amqp, channel
    finally:
        channel.close()
        amqp.close()
