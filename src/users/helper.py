"""Contains utility functions for working with users"""
from . import models
import security
import typing
from pypika import PostgreSQLQuery as Query, Table, Parameter, functions as ppfns
from hashlib import pbkdf2_hmac
from datetime import datetime, timedelta
import secrets


def get_valid_passwd_auth(
        conn, cursor,
        auth: models.PasswordAuthentication) -> typing.Optional[int]:
    """Gets the id of the password_authentication that is correctly identified
    in the given object if there is one, otherwise returns null. Note that this
    may be sensitive to timing attacks which can be mitigated with sleeps."""
    users = Table('users')
    auths = Table('password_authentications')
    cursor.execute(
        Query.from_(users).select(users.id)
        .where(users.username == Parameter('%s'))
        .limit(1).get_sql(),
        (auth.username,)
    )
    row = cursor.fetchone()
    if row is None:
        return None
    (user_id,) = row

    query = Query.from_(auths).select(
        auths.id, auths.user_id, auths.human, auths.hash_name, auths.hash,
        auths.salt, auths.iterations
    )
    if auth.password_authentication_id is not None:
        query = query.where(auths.id == auth.password_authentication_id)
    else:
        query = (
            query
            .where(auths.user_id == user_id)
            .where(auths.human == 't')
        )

    cursor.execute(query.get_sql())
    row = cursor.fetchone()
    if row is None:
        return None

    id_, user_id, human, hash_name, hash_, salt, iters = row
    if human and not security.verify_recaptcha(auth.recaptcha_token):
        return None

    provided_hash = pbkdf2_hmac(hash_name, auth.password, salt, iters)
    if hash_ != provided_hash:
        return None
    return id_


def get_auth_info_from_token_auth(
        conn, cursor, auth: models.TokenAuthentication) -> typing.Optional[
            typing.Tuple[int, int]]:
    """Get the id of the user meeting the given criteria if there is one. This
    will rollback the connection prior to starting, since it will need to
    execute queries which should be immediately committed.
    Returns None or authid, userid
    """
    conn.rollback()

    auths = Table('authtokens')
    cursor.execute(
        Query
        .from_(auths)
        .select(auths.id, auths.user_id, auths.expires_at)
        .where(auths.token == Parameter('%s'))
        .limit(1)
        .get_sql(),
        (auth.token,)
    )
    row = cursor.fetchone()
    if row is None:
        return None
    authid, user_id, expires_at = row
    now = datetime.utcnow()
    if expires_at < now:
        cursor.execute(
            Query
            .from_(auths)
            .delete()
            .where(auths.id == Parameter('%s'))
            .get_sql(),
            (authid,)
        )
        conn.commit()
        return None

    cursor.execute(
        Query
        .update(auths)
        .set(auths.last_seen_at, ppfns.Now())
        .where(auths.id == Parameter('%s'))
        .get_sql(),
        (authid,)
    )
    conn.commit()
    return authid, user_id


def create_token_from_passauth(conn, cursor, passauth_id: int) -> models.TokenResponse:
    """Creates a fresh authentication token from the given password auth, and
    returns the token. This updates the last seen at for the password auth"""
    pauths = Table('password_authentications')
    pauth_perms = Table('password_auth_permissions')
    authtokens = Table('authtokens')
    authtoken_perms = Table('authtoken_permissions')

    token = secrets.token_urlsafe(95)  # gives 127 characters
    expires_at = datetime.utcnow() + timedelta(days=1)
    cursor.execute(
        Query
        .into(authtokens)
        .columns(authtokens.user_id, authtokens.token, authtokens.expires_at)
        .from_(pauths)
        .select(pauths.user_id, Parameter('%s'), Parameter('%s'))
        .where(pauths.id == Parameter('%s'))
        .returning(authtokens.id)
        .get_sql(),
        (token, expires_at, passauth_id)
    )
    (authtoken_id,) = cursor.fetchone()
    cursor.execute(
        Query
        .update(pauths)
        .set(pauths.last_seen, ppfns.Now())
        .where(pauths.id == Parameter('%s'))
        .get_sql(),
        (passauth_id,)
    )
    cursor.execute(
        Query
        .into(authtoken_perms)
        .columns(authtoken_perms.authtoken_id, authtoken_perms.permission_id)
        .from_(pauth_perms)
        .select(Parameter('%s'), pauth_perms.permission_id)
        .where(pauth_perms.password_authentication_id == passauth_id)
        .get_sql(),
        (authtoken_id,)
    )
    conn.commit()
    return models.TokenResponse(token=token, expires_at=expires_at.timestamp())


def create_new_user(conn, cursor, username: str, commit=True) -> int:
    """Create a new user with the given username and return the id"""
    users = Table('users')
    cursor.execute(
        Query
        .into(users)
        .columns(users.username)
        .insert(Parameter('%s'))
        .returning(users.id)
        .get_sql(),
        (username,)
    )
    user_id = cursor.fetchone()[0]
    if commit:
        conn.commit()
    return user_id


def create_claim_token(conn, cursor, user_id: int, commit=True) -> str:
    """Creates and stores a new claim token for the given user, expiring in
    a relatively short amount of time. Returns the generated token, which is
    url-safe."""
    claim_tokens = Table('claim_tokens')
    cursor.execute(
        Query
        .from_(claim_tokens)
        .delete()
        .where(claim_tokens.user_id == Parameter('%s'))
        .get_sql(),
        (user_id,)
    )

    token = secrets.token_urlsafe(47)  # 63 chars
    expires_at = datetime.utcnow() + timedelta(hours=1)
    cursor.execute(
        Query
        .into(claim_tokens)
        .columns(
            claim_tokens.user_id,
            claim_tokens.token,
            claim_tokens.expires_at
        )
        .insert(
            Parameter('%s'),
            Parameter('%s'),
            Parameter('%s')
        )
        .get_sql(),
        (user_id, token, expires_at)
    )
    if commit:
        conn.commit()
    return token


def attempt_consume_claim_token(
        conn, cursor, user_id: int, claim_token: str, commit=True) -> bool:
    """Attempts to consume the given claim token for the given user. If the
    claim token is in the database it will be deleted, but this will only
    return True if the user id also matches."""
    claim_tokens = Table('claim_tokens')
    cursor.execute(
        Query
        .from_(claim_tokens)
        .delete()
        .where(claim_tokens.token == Parameter('%s'))
        .returning(claim_tokens.user_id)
        .get_sql(),
        (claim_token,)
    )
    row = cursor.fetchone()
    if row is None:
        return False
    if commit:
        conn.commit()
    return row[0] == user_id


def create_or_update_human_password_auth(
        conn, cursor, user_id: int, passwd: str, commit=True) -> int:
    """Creates or updates the human password authentication for the given
    user. They are assigned no additional permissions."""
    hash_name = 'sha512'
    salt = secrets.token_urlsafe(23)  # 31 chars
    iterations = 1000000
    passwd_digest = pbkdf2_hmac(hash_name, passwd, salt, iterations)
    cursor.execute(
        '''
INSERT INTO password_authentications(user_id, human, hash_name, hash, salt, iterations)
    VALUES(%s, %s, %s, %s, %s)
ON CONSTRAINT ind_passw_auths_on_human_uid
    DO UPDATE SET hash_name=%s, hash=%s, salt=%s, iterations=%s
RETURNING id
        ''',
        (user_id, True, hash_name, passwd_digest, salt, iterations,
         hash_name, passwd_digest, salt, iterations)
    )
    (passauth_id,) = cursor.fetchone()
    if commit:
        conn.commit()
    return passauth_id
