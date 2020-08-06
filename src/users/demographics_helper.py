"""Helper functions for user demographics"""
from fastapi.responses import Response
from . import helper
import ratelimit_helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from lblogging import Level
from pypika import Table, Query, Parameter, Interval
from pypika.functions import Now
import os
import secrets
import json
import time
from datetime import datetime


MAX_AUTHTOKEN_AGE_FOR_DEMOGRAPHICS_SECONDS = 3600
"""The maximum age of an authorization token, in seconds, which we will accept
as proof of authorization for a user for the purposes of handling demographics
information. Note we will also prevent non-human authorization methods or
authtokens which were not verified by a captcha."""

VIEW_SELF_DEMOGRAPHICS_PERMISSION = 'view-self-demographics'
"""The required permission to even view your own demographics. This is set as
a permission to ensure that if we are worried a users account is compromised,
revoking permissions on their authtokens will definitely prevent them from
seeing sensitive information. In practice we'd probably completely delete the
password authentications on the user, so this is just defense in depth."""

EDIT_SELF_DEMOGRAPHICS_PERMISSION = 'edit-self-demographics'
"""The required permission to edit ones own demographics."""

PURGE_SELF_DEMOGRAPHICS_PERMISSION = 'purge-self-demographics'
"""The required permission to purge ones own demographic information from the
database. This is treated as a legal request, effecting everything except
backups (since modifying backups on request would jeopardize their
effectiveness and is not in general practical)."""

VIEW_OTHERS_DEMOGRAPHICS_PERMISSION = 'view-others-demographics'
"""The required permission to view other peoples demographics."""

EDIT_OTHERS_DEMOGRAPHICS_PERMISSION = 'edit-others-demographics'
"""The required permission to edit other peoples demographics."""

PURGE_OTHERS_DEMOGRAPHICS_PERMISSION = 'purge-others-demographics'
"""The required permission to purge other peoples demographics. This should
only be done via request by the user, since the less paranoid way of just
clearing their current demographics will maintain a history of who knew
what."""

LOOKUP_DEMOGRAPHICS_PERMISSION = 'lookup-demographics'
"""The required permission to search our database for a user matching a given
set of demographics. Almost exclusively used for fraud prevention, such as a
user concerned about identity theft."""


def get_failure_response_or_user_id_and_perms_for_authorization(
        itgs: LazyItgs,
        authorization: str,
        check_request_cost: int,
        req_user_id: int,
        action_self_permission: str, action_other_permission: str,
        additional_permissions_for_result: list):
    """Check that the given authorization header is sufficient for viewing
    the given users demographics and performing the given action. This will
    either return a Response (or JSONResponse) containing the problem with
    the users authorization (check using isinstance(resp, Response)), or it
    will return (user_id, permissions), where user_id is the authorized users
    id and permissions is the subset of permissions on the user that they
    have and we checked.

    Arguments:
    - `itgs (LazyIntegrations)`: The lazy integrations to use for connecting
        to networked services to verify the authtoken.
    - `authorization (str)`: The authorization header passed by the user.
    - `check_requset_cost (int)`: The ratelimiting penalty for even checking if
        they have permission to do the request.
    - `req_user_id (int, None)`: The id of the user whose demographics
        information is being acted on. Should be None for the lookup action.
        If this is set, the view permission is implied.
    - `action_self_permission (str, None)`: The required permission if the
        authorized user is the requested user, e.g.,
        EDIT_SELF_DEMOGRAPHICS_PERMISSION. Should be omitted if `req_user_id`
        is `None`.
    - `action_other_permission (str)`: The required permission if the
        authorized user is not the requested user.
    - `additional_permissions_for_result (iterable[str])`: Permissions which we
        should check for when looking up the authtokens permissions in the
        database, even if this function doesn't use them. Ensures that if the
        token has this permission it will be returned within the permissions
        array in the success response.

    Returns (Failure Response):
    - `resp (fastapi.responses.Response)`: The response that should be
        returned to the user.

    Returns (Success Response):
    - `user_id (int)`: The primary key of the user authorized via the
        authorization header to make this request.
    - `permissions (list[str])`: The subset of permissions which the user has
        and we checked for.
    """
    authtoken_id = None
    user_id = None
    failure_type = None
    headers = {'x-request-cost': str(check_request_cost)}

    authtoken_provided = helper.get_authtoken_from_header(authorization)
    if authtoken_provided is None:
        failure_type = 401
    else:
        max_age = datetime.fromtimestamp(
            time.time() - MAX_AUTHTOKEN_AGE_FOR_DEMOGRAPHICS_SECONDS)
        auths = Table('authtokens')
        password_auths = Table('password_authentications')
        itgs.read_cursor.execute(
            Query.from_(auths)
            .select(auths.id, auths.user_id)
            .join(password_auths).on(password_auths.id == auths.source_id)
            .where(auths.source_type == Parameter('%s'))
            .where(auths.token == Parameter('%s'))
            .where(auths.created_at > Parameter('%s'))
            .where(password_auths.human.eq(True))
            .limit(1)
            .get_sql(),
            (
                'password_authentication',
                authtoken_provided,
                max_age
            )
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            failure_type = 403
        else:
            (authtoken_id, user_id) = row

            revoke_key = f'auth_token_revoked-{authtoken_id}'
            if itgs.cache.get(revoke_key) is not None:
                failure_type = 403
                authtoken_id = None
                user_id = None

    if failure_type is not None:
        if not ratelimit_helper.check_ratelimit(itgs, None, [], check_request_cost):
            return Response(status_code=429, headers=headers)
        return Response(status_code=failure_type, headers=headers)

    view_permission = None
    action_permission = None
    if req_user_id == user_id:
        view_permission = VIEW_SELF_DEMOGRAPHICS_PERMISSION
        action_permission = action_self_permission
    else:
        view_permission = VIEW_OTHERS_DEMOGRAPHICS_PERMISSION
        action_permission = action_other_permission

    check_permissions = []
    if view_permission is not None:
        check_permissions.append(view_permission)

    if action_permission is not None:
        check_permissions.append(action_permission)

    for perm in additional_permissions_for_result:
        check_permissions.append(perm)

    for perm in ratelimit_helper.RATELIMIT_PERMISSIONS:
        check_permissions.add(perm)

    authtoken_perms = Table('authtoken_permissions')
    permissions = Table('permissions')
    itgs.read_cursor.execute(
        Query.from_(authtoken_perms)
        .select(permissions.name)
        .join(permissions).on(permissions.id == authtoken_perms.permission_id)
        .where(authtoken_perms.authtoken_id == Parameter('%s'))
        .where(permissions.name.isin([Parameter('%s') for _ in check_permissions]))
        .get_sql(),
        [
            authtoken_id,
            *check_permissions
        ]
    )

    permissions = []
    row = itgs.read_cursor.fetchone()
    while row is not None:
        permissions.append(row[0])
        row = itgs.read_cursor.fetchone()

    if not ratelimit_helper.check_ratelimit(itgs, user_id, permissions, check_request_cost):
        return Response(status_code=429, headers=headers)

    if view_permission is not None and view_permission not in permissions:
        return Response(status_code=404, headers=headers)

    if req_user_id is not None:
        demos = Table('user_demographics')
        itgs.read_cursor.execute(
            Query.from_(demos).select(1)
            .where(demos.user_id == Parameter('%s'))
            .where(demos.deleted == Parameter('%s'))
            .limit(1)
            .get_sql(),
            (req_user_id, True)
        )
        if itgs.read_cursor.fetchone() is not None:
            return Response(status_code=451, headers=headers)

    if action_permission is not None and action_permission not in permissions:
        return Response(status_code=403, headers=headers)

    # Enrich logs
    users = Table('users')
    itgs.read_cursor.execute(
        Query.from_(users).select(users.username)
        .where(users.id == Parameter('%s'))
        .get_sql(),
        (user_id,)
    )
    username = itgs.read_cursor.fetchone()[0]

    if req_user_id is not None:
        itgs.read_cursor.execute(
            Query.from_(users).select(users.username)
            .where(users.id == Parameter('%s'))
            .get_sql(),
            (req_user_id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is not None:
            req_username = row[0]
        else:
            req_username = f'<UNKNOWN:id={req_user_id}>'
    else:
        req_username = None

    itgs.logger.print(
        Level.DEBUG if user_id == req_user_id else Level.WARN,
        (
            '/u/{} is exercising their ability to view user demographics '
            'information {}. (view_permission = {}, action_permission = {})'
        ),
        username,
        'via a general lookup' if req_username is None else f'on /u/{req_username}',
        view_permission,
        action_permission
    )

    if req_user_id == user_id:
        pm_key = f'demographics_helper/pms/self/{user_id}'
        if itgs.cache.get(pm_key) is None:
            itgs.cache.set(pm_key, b'1', expire=86400)
            url_root = os.environ['ROOT_DOMAIN']
            send_queue = os.environ['AMQP_REDDIT_PROXY_QUEUE']
            itgs.channel.basic_publish(
                exchange='',
                routing_key=send_queue,
                body=json.dumps({
                    'type': 'compose',
                    'response_queue': os.environ['AMQP_RESPONSE_QUEUE'],
                    'uuid': secrets.token_urlsafe(47),
                    'version_utc_seconds': float(os.environ['APP_VERSION_NUMBER']),
                    'sent_at': time.time(),
                    'args': {
                        'recipient': username,
                        'subject': 'RedditLoans: Demographic Information Viewed',
                        'body': (
                            'You just exercised your ability to view or edit your own '
                            'demographic information (email, first name, last name, street '
                            f'address, city, state, and zip) on {url_root} - if this was '
                            f'not you, immediately visit {url_root} and reset your password.'
                        )
                    }
                }).encode('utf-8')
            )
    elif req_user_id is not None:
        pm_key = f'demographics_helper/pms/other/{user_id}'
        if itgs.cache.get(pm_key) is None:
            itgs.cache.set(pm_key, b'1', expire=3600)
            url_root = os.environ['ROOT_DOMAIN']
            send_queue = os.environ['AMQP_REDDIT_PROXY_QUEUE']
            itgs.channel.basic_publish(
                exchange='',
                routing_key=send_queue,
                body=json.dumps({
                    'type': 'compose',
                    'response_queue': os.environ['AMQP_RESPONSE_QUEUE'],
                    'uuid': secrets.token_urlsafe(47),
                    'version_utc_seconds': float(os.environ['APP_VERSION_NUMBER']),
                    'sent_at': time.time(),
                    'args': {
                        'recipient': username,
                        'subject': 'RedditLoans: Demographic Information Viewed',
                        'body': (
                            'You just exercised your ability to view or edit the '
                            'demographic information (email, first name, last name, street '
                            f'address, city, state, and zip) of /u/{req_username} on {url_root} '
                            f'- if this was not you then reset your password on {url_root}, '
                            'contact /u/Tjstretchalot, reset your password on reddit and '
                            f'strip all permissions from your own account on {url_root}.\n\n'
                            f'## Respond to modmail: "Demographic Info Viewed: /u/{req_username}".'
                        )
                    }
                }).encode('utf-8')
            )
            itgs.channel.basic_publish(
                exchange='',
                routing_key=send_queue,
                body=json.dumps({
                    'type': 'compose',
                    'response_queue': os.environ['AMQP_RESPONSE_QUEUE'],
                    'uuid': secrets.token_urlsafe(47),
                    'version_utc_seconds': float(os.environ['APP_VERSION_NUMBER']),
                    'sent_at': time.time(),
                    'args': {
                        'recipient': '/r/borrow',
                        'subject': f'Demographic Info Viewed: /u/{req_username}',
                        'body': (
                            f'/u/{username} exercised his ability to view demographic information '
                            f'on /u/{req_username}. This pm is sent at most once per hour.\n\n '
                            f'/u/{username} should respond here very soon confirming this was him, '
                            'otherwise efforts should be made to contact him. If he cannot be '
                            f'contacted, strip his access on {url_root} by going to Account -> '
                            f'Administrate, type in {username}, fill in a reason, and click '
                            '"Revoke All Permissions". If there are other options under the '
                            '"Authentication Method ID" dropdown, for each one select it and press '
                            '"Revoke All Permissions".\n\n'
                            'Then contact /u/Tjstretchalot if he has not already responded to this '
                            'thread.'
                        )
                    }
                }).encode('utf-8')
            )
            itgs.channel.basic_publish(
                exchange='',
                routing_key=send_queue,
                body=json.dumps({
                    'type': 'compose',
                    'response_queue': os.environ['AMQP_RESPONSE_QUEUE'],
                    'uuid': secrets.token_urlsafe(47),
                    'version_utc_seconds': float(os.environ['APP_VERSION_NUMBER']),
                    'sent_at': time.time(),
                    'args': {
                        'recipient': 'Tjstretchalot',
                        'subject': 'RedditLoans: Demographic Information Viewed',
                        'body': f'Check modmail! Mod user: /u/{username} viewed /u/{req_username}'
                    }
                }).encode('utf-8')
            )

    return (user_id, permissions)
