"""Helper functions for testing"""
from contextlib import contextmanager


@contextmanager
def clear_tables(conn, cursor, tbls):
    """truncates each of the given tables at the end of the block"""
    try:
        yield
    finally:
        conn.rollback()
        for tbl in tbls:
            cursor.execute(f'TRUNCATE {tbl} CASCADE')
        conn.commit()
