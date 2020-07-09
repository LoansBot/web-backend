"""Contains utility functions for working with users"""
from . import models
import security
import typing
from pypika import PostgreSQLQuery as Query, Table, Parameter, functions as ppfns
from hashlib import pbkdf2_hmac, scrypt
from hmac import compare_digest
from datetime import datetime, timedelta
import secrets
from base64 import b64encode
import os
import math
from lbshared.lazy_integrations import LazyIntegrations
from lblogging import Level


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
        (auth.username.lower(),)
    )
    row = itgs.read_cursor.fetchone()
    if row is None:
        itgs.logger.print(
            Level.TRACE,
            'User {} tried to login but they have no account',
            auth.username
        )
        return None
    (user_id,) = row

    query = Query.from_(auths).select(
        auths.id, auths.user_id, auths.human, auths.hash_name, auths.hash,
        auths.salt, auths.iterations
    ).where(auths.deleted.eq(False))
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
    if not security.ratelimit(
            itgs,
            'LOGIN_ONE_AUTH',
            f'login_auth_{id_}',
            {
                int(timedelta(minutes=5).total_seconds()): 5,
                int(timedelta(minutes=10).total_seconds()): 8,
                int(timedelta(hours=1).total_seconds()): 10
            }):
        itgs.logger.print(
            Level.TRACE,
            'User {} (id {}) tried to login but was ratelimited',
            auth.username, id_
        )
        return None

    if human:
        if auth.captcha_token is None:
            # It's helpful when testing locally to bypass the captcha, but you
            # must have permission to do so and the operation is ratelimited
            # to prevent brute-force attacks.
            if not check_permission_on_passwd_auth(itgs, id_, 'bypass_captcha'):
                itgs.logger.print(
                    Level.DEBUG,
                    'There was an attempt to login as {} without a captcha but '
                    'that account does not have permission to do that. The '
                    'permission required is bypass_captcha',
                    auth.username
                )
                return None
        elif not security.verify_captcha(itgs, auth.captcha_token):
            itgs.logger.print(
                Level.TRACE,
                'User {} tried to login, provided a captcha, but it was invalid',
                auth.username
            )
            return None

    if hash_name.startswith('scrypt'):
        _, block_size, dklen = hash_name.split('-')
        block_size = int(block_size)
        dklen = int(dklen)

        provided_hash = b64encode(
            scrypt(
                auth.password.encode('utf-8'),
                salt=salt.encode('utf-8'),
                n=iters,
                r=block_size,
                maxmem=128 * iters * block_size + 1024 * 64,
                dklen=dklen
            )
        ).decode('ascii')
    else:
        provided_hash = b64encode(
            pbkdf2_hmac(
                hash_name,
                auth.password.encode('utf-8'),
                salt.encode('utf-8'),
                iters
            )
        ).decode('ascii')

    if not compare_digest(hash_.encode('ascii'), provided_hash.encode('ascii')):
        itgs.logger.print(
            Level.TRACE,
            'User {} tried to login but provided the wrong password',
            auth.username
        )
        return None

    itgs.logger.print(
        Level.TRACE,
        'User {} successfully logged in',
        auth.username
    )
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
        require_user_id=None):
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
    # database in a background job?
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
        .columns(
            authtokens.user_id, authtokens.token, authtokens.expires_at,
            authtokens.source_type, authtokens.source_id
        )
        .from_(pauths)
        .select(pauths.user_id, *[Parameter('%s') for _ in range(4)])
        .where(pauths.deleted.eq(False))
        .where(pauths.id == Parameter('%s'))
        .returning(authtokens.id, authtokens.user_id)
        .get_sql(),
        (token, expires_at, passauth_id, 'password_authentication', passauth_id)
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
        (username.lower(),)
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


def check_permission_on_passwd_auth(
        itgs: LazyIntegrations, passwd_auth_id, perm_name) -> bool:
    """Checks if the given password authentication id has the given permission.
    """
    perms = Table('permissions')
    passwd_perms = Table('password_auth_permissions')
    itgs.read_cursor.execute(
        Query.from_(passwd_perms).select(1)
        .join(perms).on(passwd_perms.permission_id == perms.id)
        .where(passwd_perms.password_authentication_id == Parameter('%s'))
        .where(perms.name == Parameter('%s'))
        .limit(1)
        .get_sql(),
        (passwd_auth_id, perm_name)
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


def get_permissions_from_header(itgs, authorization, permissions):
    """A convenience method to get if authorization was provided, if it was
    valid, and which (if any) of the specified permissions they have. This is
    a good balance of convenience and versatility.

    Example responses:
        Omitted authorization header
        (None, False, [])

        Invalid authorization header
        (None, True, [])

        Valid authorization header for user 3, no permissions from list
        (3, True, [])

        Valid authorization header for user 7, with some permissions
        (7, True, ['permission1', 'permission2'])

    @param itgs The lazy integrations to use
    @param authorization The authorization header provided
    @param permissions The list of interesting permissions for this endpoint;
        this will return the subset of these permissions which the user
        actually has.
    @return (int, bool, list) If they authorized successfully then the user id
        otherwise None, if they provided an authorization header, and what
        permissions from the given list of permissions they have.
    """
    if isinstance(permissions, str):
        permissions = [permissions]

    authtoken = get_authtoken_from_header(authorization)
    if authtoken is None:
        return (None, False, [])
    info = get_auth_info_from_token_auth(
        itgs, models.TokenAuthentication(token=authtoken)
    )
    if info is None:
        return (None, True, [])
    auth_id, user_id = info[:2]
    if not permissions:
        return (user_id, True, [])

    perms = Table('permissions')
    authtoken_perms = Table('authtoken_permissions')
    itgs.read_cursor.execute(
        Query.from_(authtoken_perms).select(perms.name)
        .join(perms).on(perms.id == authtoken_perms.permission_id)
        .where(perms.name.isin([Parameter('%s') for _ in permissions]))
        .where(authtoken_perms.authtoken_id == Parameter('%s'))
        .get_sql(),
        (*permissions, auth_id)
    )
    perms_found = itgs.read_cursor.fetchall()
    return (user_id, True, [i[0] for i in perms_found])


def check_permissions_from_header(itgs, authorization, permissions):
    """A convenience method to check that the given authorization header is
    formatted correctly, corresponds to a real unexpired token, and that
    token has all of the given list of permissions.

    For most endpoints, calling this immediately after initializing the lazy
    integrations is the fastest and easiest way to check permissions.

    @param itgs The lazy integrations to use
    @param authorization The authorization header provided
    @param permissions The list of permissions required, where each item is
        the string name of the permission. May be an empty list or a single
        string
    @return (True, user_id) if the authorization is valid and has
        all of the required permissions, (False, None) otherwise.
    """
    if isinstance(permissions, str):
        permissions = [permissions]

    authtoken = get_authtoken_from_header(authorization)
    if authtoken is None:
        return (False, None)
    info = get_auth_info_from_token_auth(
        itgs, models.TokenAuthentication(token=authtoken)
    )
    if info is None:
        return (False, None)
    auth_id, user_id = info[:2]
    if not permissions:
        return (True, user_id)

    perms = Table('permissions')
    authtoken_perms = Table('authtoken_permissions')
    itgs.read_cursor.execute(
        Query.from_(authtoken_perms).select(ppfns.Count('*'))
        .join(perms).on(perms.id == authtoken_perms.permission_id)
        .where(perms.name.isin([Parameter('%s') for _ in permissions]))
        .where(authtoken_perms.authtoken_id == Parameter('%s'))
        .get_sql(),
        (*permissions, auth_id)
    )
    (num_perms_found,) = itgs.read_cursor.fetchone()
    if num_perms_found == len(permissions):
        return (True, user_id)
    return (False, None)
