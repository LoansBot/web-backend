"""This package provides a class-based version of integrations which has
all of them, but they are lazily initialized. Acts as a context manager,
and any connections which are actually used are cleaned up at the end
of the context."""
import integrations as itgs
from lblogging import Level


class LazyIntegrations:
    """Contains all the integrations as lazy-loaded properties. If they are
    requested they are initialized and cleaned up when this context manager
    exits.

    This will expose a read-only database connection as well as a write
    database connection. Although not currently used, it should be
    anticipated that these might be different connections. If this would
    break things, set "no_read_only" to True to guarrantee the result of the
    read connection is the same as the write connection.
    """
    def __init__(self, no_read_only=False):
        self.closures = []
        self.no_read_only = no_read_only
        self._logger = None
        self._conn = None
        self._cursor = None
        self._amqp = None
        self._channel = None
        self._cache = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        errors = []
        for closure in self.closures:
            try:
                closure(exc_type, exc_value, traceback)
            except Exception as e:  # noqa
                # we need to delay these to give other closures
                # an opportunity
                errors.append(e)

        if len(errors) == 1:
            raise errors[0]
        elif errors:
            raise Exception(f'Many errors while shutting down integrations: {errors}')
        return False

    @property
    def logger(self):
        """Fetch the logger instance, which will auto-commit"""
        if self._logger is not None:
            return self._logger

        ctx = itgs.logger()
        self._logger = ctx.__enter__()
        self.closures.append(ctx.__exit__)
        return self._logger

    @property
    def read_cursor(self):
        """Fetches a database cursor that is only promised to support
        reads. This may be the same connection as write_conn."""
        return self.write_cursor

    @property
    def write_conn(self):
        """Fetch the writable database connection"""
        return self.write_conn_and_cursor[0]

    @property
    def write_cursor(self):
        "Fetch the writable database cursor"
        return self.write_conn_and_cursor[1]

    @property
    def write_conn_and_cursor(self):
        """Returns the writable database connection alongside the cursor. The
        connection can be used to commit."""
        if self._conn is not None:
            return (self._conn, self._cursor)

        ctx = itgs.database()
        self._conn = ctx.__enter__()
        self.closures.append(ctx.__exit__)
        self._cursor = self._conn.cursor()
        return (self._conn, self._cursor)

    @property
    def amqp(self):
        """Get the advanced message queue pika instance, which is really
        only necessary if you need to declare custom channels"""
        return self.amqp_and_channel[0]

    @property
    def channel(self):
        """The AMQP channel to use."""
        return self.amqp_and_channel[1]

    @property
    def amqp_and_channel(self):
        """Get both the AMQP pika instance and the channel we are using"""
        if self._amqp is not None:
            return (self._amqp, self._channel)

        ctx = itgs.amqp()
        self._amqp, self._channel = ctx.__enter__()
        self.closures.append(ctx.__exit__)
        return (self._amqp, self._channel)

    @property
    def cache(self):
        """Get the memcached client"""
        if self._cache is not None:
            return self._cache

        ctx = itgs.memcached()
        self._cache = ctx.__enter__()
        self.closures.append(ctx.__exit__)
        return self._cache
