"""Helper functions for testing"""
from contextlib import contextmanager
from pypika import PostgreSQLQuery as Query, Table, Parameter, Interval
from pypika.functions import Now


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


@contextmanager
def user_with_token(
        conn, cursor,
        add_perms=None,
        username='user_with_token',
        token='testtoken'):
    """Creates a user with an authorization token, returning the id of the
    user and the token to pass. This will delete the generated rows when
    finished.
    """
    users = Table('users')
    cursor.execute(
        Query.into(users).columns(users.username)
        .insert(Parameter('%s'))
        .returning(users.id).get_sql(),
        (username,)
    )
    (user_id,) = cursor.fetchone()
    authtokens = Table('authtokens')
    cursor.execute(
        Query.into(authtokens).columns(
            authtokens.user_id, authtokens.token, authtokens.expires_at,
            authtokens.source_type, authtokens.source_id
        ).insert(
            Parameter('%s'), Parameter('%s'), Now() + Interval(hours=1),
            Parameter('%s'), Parameter('%s')
        )
        .returning(authtokens.id)
        .get_sql(),
        (user_id, token, 'other', 1)
    )
    (auth_id,) = cursor.fetchone()
    perms = Table('permissions')
    auth_perms = Table('authtoken_permissions')
    perm_ids_to_delete = []
    if add_perms:
        for perm in add_perms:
            cursor.execute(
                Query.into(perms).columns(perms.name, perms.description)
                .insert(Parameter('%s'), Parameter('%s'))
                .on_conflict(perms.name).do_nothing()
                .returning(perms.id)
                .get_sql(),
                (perm, 'Testing')
            )
            row = cursor.fetchone()
            if row is not None:
                perm_ids_to_delete.append(row[0])
                cursor.execute(
                    Query.from_(perms).select(perms.id)
                    .where(perms.name == Parameter('%s'))
                    .get_sql(),
                    (perm,)
                )
                row = cursor.fetchone()
        cursor.execute(
            Query.into(auth_perms)
            .columns(auth_perms.authtoken_id, auth_perms.permission_id)
            .from_(perms).select(Parameter('%s'), perms.id)
            .where(perms.name.isin([Parameter('%s') for _ in add_perms]))
            .get_sql(),
            [auth_id] + list(add_perms)
        )

    conn.commit()
    try:
        yield (user_id, token)
    finally:
        conn.rollback()
        cursor.execute(
            Query.from_(users).delete().where(users.id == Parameter('%s'))
            .get_sql(),
            (user_id,)
        )
        for perm in perm_ids_to_delete:
            cursor.execute(
                Query.from_(perms).delete()
                .where(
                    perms.id.isin(
                        [Parameter('%s') for _ in perm_ids_to_delete]
                    )
                )
                .get_sql(),
                perm_ids_to_delete
            )
        conn.commit()
