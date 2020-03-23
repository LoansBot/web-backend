"""Contains utility functions for working with users"""
from . import models
import security
import typing
from pypika import PostgreSQLQuery as Query, Table, Parameter, functions as ppfns
from hashlib import pbkdf2_hmac
from datetime import datetime, timedelta
import secrets
from base64 import b64encode
import os
import math
from lazy_integrations import LazyIntegrations


def get_valid_passwd_auth(
        itgs: LazyIntegrations,
        auth: models.PasswordAuthentication) -> typing.Optional[int]:
    """Gets the id of the password_authentication that is correctly identified
    in the given object if there is one, otherwise returns null. Note that this
    may be sensitive to timing attacks which can be mitigated with sleeps."""
    users = Table('users')
    auths = Table('password_authentications')
    itgs.read_cursor.execute(
        Query.from_(users).select(users.id)
        .where(users.username == Parameter('%s'))
        .limit(1).get_sql(),
        (auth.username,)
    )
    row = itgs.read_cursor.fetchone()
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

    itgs.read_cursor.execute(query.get_sql())
    row = itgs.read_cursor.fetchone()
    if row is None:
        return None

    id_, user_id, human, hash_name, hash_, salt, iters = row
    if human and not security.verify_captcha(auth.captcha_token):
        return None

    provided_hash = b64encode(
        pbkdf2_hmac(
            hash_name,
            auth.password.encode('utf-8'),
            salt.encode('utf-8'),
            iters
        )
    ).decode('ascii')
    if hash_ != provided_hash:
        return None
    return id_


def get_authtoken_from_header(authorization):
    """Converts the string or None value that was passed in an authorization
    header to the corresponding authtoken if possible, otherwise returns
    None"""
    if authorization is None:
        return None
    spl = authorization.split(' ', 2)
    if len(spl) != 2:
        return None
    if spl[0] != 'bearer':
        return None
    return spl[1]


def get_auth_info_from_token_auth(
        itgs: LazyIntegrations,
        auth: models.TokenAuthentication,
        require_user_id=None) -> typing.Optional[
            typing.Tuple[int, int]]:
    """Get the id of the user meeting the given criteria if there is one. This
    will rollback the connection prior to starting, since it will need to
    execute queries which should be immediately committed.
    Returns None or authid, userid, expires_at

    This strictly reads from the database by leveraging the memcached to
    temporarily store deletes, since the authtokens expire (and are cleaned
    up) eventually
    """
    auths = Table('authtokens')
    itgs.read_cursor.execute(
        Query
        .from_(auths)
        .select(auths.id, auths.user_id, auths.expires_at)
        .where(auths.token == Parameter('%s'))
        .limit(1)
        .get_sql(),
        (auth.token,)
    )
    row = itgs.read_cursor.fetchone()
    if row is None:
        return None
    authid, user_id, expires_at = row
    now = datetime.utcnow()
    if expires_at < now:
        return None

    revoke_key = f'auth_token_revoked-{authid}'
    if itgs.cache.get(revoke_key) is not None:
        return None

    if require_user_id is not None and user_id != require_user_id:
        expired_in_secs = int(math.ceil((expires_at - now).total_seconds()))
        expired_in_secs = max(expired_in_secs, 1)
        itgs.cache.set(revoke_key, b'1', expire=expired_in_secs)
        return None

    # TODO: flag a last-seen-at in the cache which can be moved to the
    # database in a background job
    return authid, user_id, expires_at


def create_token_from_passauth(
        itgs: LazyIntegrations, passauth_id: int) -> models.TokenResponse:
    """Creates a fresh authentication token from the given password auth, and
    returns the token. This updates the last seen at for the password auth"""
    pauths = Table('password_authentications')
    pauth_perms = Table('password_auth_permissions')
    authtokens = Table('authtokens')
    authtoken_perms = Table('authtoken_permissions')

    token = secrets.token_urlsafe(95)  # gives 127 characters
    expires_at = datetime.utcnow() + timedelta(days=1)
    itgs.write_cursor.execute(
        Query
        .into(authtokens)
        .columns(authtokens.user_id, authtokens.token, authtokens.expires_at)
        .from_(pauths)
        .select(pauths.user_id, Parameter('%s'), Parameter('%s'))
        .where(pauths.id == Parameter('%s'))
        .returning(authtokens.id, authtokens.user_id)
        .get_sql(),
        (token, expires_at, passauth_id)
    )
    (authtoken_id, user_id) = itgs.write_cursor.fetchone()
    itgs.write_cursor.execute(
        Query
        .update(pauths)
        .set(pauths.last_seen, ppfns.Now())
        .where(pauths.id == Parameter('%s'))
        .get_sql(),
        (passauth_id,)
    )
    itgs.write_cursor.execute(
        Query
        .into(authtoken_perms)
        .columns(authtoken_perms.authtoken_id, authtoken_perms.permission_id)
        .from_(pauth_perms)
        .select(Parameter('%s'), pauth_perms.permission_id)
        .where(pauth_perms.password_authentication_id == passauth_id)
        .get_sql(),
        (authtoken_id,)
    )
    itgs.write_conn.commit()
    return models.TokenResponse(
        user_id=user_id,
        token=token,
        expires_at_utc=expires_at.timestamp()
    )


def create_new_user(
        itgs: LazyIntegrations, username: str, commit=True) -> int:
    """Create a new user with the given username and return the id"""
    users = Table('users')
    itgs.write_cursor.execute(
        Query
        .into(users)
        .columns(users.username)
        .insert(Parameter('%s'))
        .returning(users.id)
        .get_sql(),
        (username,)
    )
    user_id = itgs.write_cursor.fetchone()[0]
    if commit:
        itgs.write_conn.commit()
    return user_id


def create_claim_token(
        itgs: LazyIntegrations, user_id: int, commit=True) -> str:
    """Creates and stores a new claim token for the given user, expiring in
    a relatively short amount of time. Returns the generated token, which is
    url-safe."""
    claim_tokens = Table('claim_tokens')
    itgs.write_cursor.execute(
        Query
        .from_(claim_tokens)
        .delete()
        .where(claim_tokens.user_id == Parameter('%s'))
        .get_sql(),
        (user_id,)
    )

    token = secrets.token_urlsafe(47)  # 63 chars
    expires_at = datetime.utcnow() + timedelta(hours=1)
    itgs.write_cursor.execute(
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
        itgs.write_conn.commit()
    return token


def attempt_consume_claim_token(
        itgs: LazyIntegrations, user_id: int, claim_token: str, commit=True) -> bool:
    """Attempts to consume the given claim token for the given user. If the
    claim token is in the database it will be deleted, but this will only
    return True if the user id also matches."""
    claim_tokens = Table('claim_tokens')
    itgs.write_cursor.execute(
        Query
        .from_(claim_tokens)
        .delete()
        .where(claim_tokens.token == Parameter('%s'))
        .returning(claim_tokens.user_id)
        .get_sql(),
        (claim_token,)
    )
    row = itgs.write_cursor.fetchone()
    if row is None:
        return False
    if commit:
        itgs.write_conn.commit()
    return row[0] == user_id


def create_or_update_human_password_auth(
        itgs: LazyIntegrations, user_id: int, passwd: str, commit=True) -> int:
    """Creates or updates the human password authentication for the given
    user. They are assigned no additional permissions."""
    hash_name = 'sha512'
    salt = secrets.token_urlsafe(23)  # 31 chars
    iterations = int(os.environ.get('HUMAN_PASSWORD_ITERS', '1000000'))

    passwd_digest = b64encode(
        pbkdf2_hmac(
            hash_name,
            passwd.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
    ).decode('ascii')
    itgs.write_cursor.execute(
        'INSERT INTO password_authentications('
            'user_id, human, hash_name, hash, salt, iterations) '  # noqa: E131
        'VALUES(%s, %s, %s, %s, %s, %s)'
        'ON CONFLICT (user_id, human)'
            'DO UPDATE SET hash_name=%s, hash=%s, salt=%s, iterations=%s'  # noqa: E131
        'RETURNING id',
        (user_id, True, hash_name, passwd_digest, salt, iterations,
         hash_name, passwd_digest, salt, iterations)
    )
    (passauth_id,) = itgs.write_cursor.fetchone()
    if commit:
        itgs.write_conn.commit()
    return passauth_id


def check_permission_on_authtoken(
        itgs: LazyIntegrations, authid, perm_name) -> bool:
    """Checks that the given authorization token has the given permission. If
    the authorization token does not exist this returns False"""
    perms = Table('permissions')
    authtoken_perms = Table('authtoken_permissions')
    itgs.read_cursor.execute(
        Query.from_(authtoken_perms).select(1)
        .join(perms).on(authtoken_perms.permission_id == perms.id)
        .where(authtoken_perms.authtoken_id == Parameter('%s'))
        .where(perms.name == Parameter('%s'))
        .limit(1)
        .get_sql(),
        (authid, perm_name)
    )
    row = itgs.read_cursor.fetchone()
    return row is not None


def cache_control_for_expires_at(expires_at, try_refresh_every=None, private=True) -> str:
    """Returns the suggested cache control headers for the given expire-at
    time."""
    time_to_expire = expires_at - datetime.utcnow()
    time_to_expire_secs = int(time_to_expire.total_seconds())
    if try_refresh_every is not None:
        max_age = min(time_to_expire_secs, try_refresh_every)
    else:
        max_age = time_to_expire_secs
    stale_while_revalidate = max(time_to_expire_secs, 3600)
    private_s = 'private' if private else 'public'
    return (
        f'{private_s}, max-age={max_age}, '
        f'stale-while-revalidate={stale_while_revalidate}, '
        f'stale-if-error=86400'
    )
