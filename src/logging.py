"""Initializes the logger"""
from lblogging import Logger
from database import DATABASE


def _init_logger():
    logger = Logger(os.environ['APPNAME'], 'logging.py', DATABASE)
    logger.prepare()
    logger.print(Level.TRACE, 'Initialized')
    return logger


LOGGER = _init_logger()
