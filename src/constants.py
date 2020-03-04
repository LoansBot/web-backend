"""Initializes the logger"""
from lblogging import Logger, Level
import os
from pymemcache.client import base as membase
import psycopg2


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


DATABASE = psycopg2.connect('')
LOGGER = _init_logger(DATABASE)
MEMCACHED = _init_memcached()
