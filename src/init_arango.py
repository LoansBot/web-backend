"""Mainly used for tests; initializes the arango db"""
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from lblogging import Level


def main():
    with LazyItgs(logger_iden='init_arango.py') as itgs:
        itgs.kvs_db.create_if_not_exists()
        itgs.logger.print(
            Level.INFO,
            'Arango database initialized'
        )


if __name__ == '__main__':
    main()
