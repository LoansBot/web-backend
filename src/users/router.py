from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter
from . import helper
from . import models
from users.settings_router import router as settings_router
import models as main_models
import security
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from datetime import timedelta
import ratelimit_helper
import os
import uuid
import time
import json


router = APIRouter()
router.include_router(settings_router)


@router.post(
    '/login',
    tags=['users', 'auth'],
    responses={
        200: {'model': models.TokenResponse},
        400: {'description': 'Username or password too long'},
        403: {
            'description': (
                'The provided authentication could not be identified'
            )
        }
    }
)
def login(auth: models.PasswordAuthentication):
    if len(auth.username) > 32 or len(auth.password) > 255:
        return Response(status_code=400)

    with LazyItgs() as itgs:
        auth_id = None
        with security.fixed_duration(0.5):
            auth_id = helper.get_valid_passwd_auth(itgs, auth)
        if auth_id is None:
            return Response(status_code=403)

        res = helper.create_token_from_passauth(itgs, auth_id)
        return JSONResponse(status_code=200, content=res.dict())


@router.post(
    '/logout',
    tags=['users', 'auth'],
    responses={
        200: {'description': 'Logout successful'},
        403: {'description': 'Token authentication failed'}
    }
)
def logout(auth: models.TokenAuthentication):
    with LazyItgs(no_read_only=True) as itgs:
        info = helper.get_auth_info_from_token_auth(itgs, auth)
        if info is None:
            return Response(status_code=403)
        auth_id = info[0]

        authtokens = Table('authtokens')
        itgs.write_cursor.execute(
            Query
            .from_(authtokens)
            .delete()
            .where(authtokens.id == Parameter('%s'))
            .get_sql(),
            (auth_id,)
        )
        itgs.write_conn.commit()
        return Response(status_code=200)


@router.get(
    '/{req_user_id}',
    tags=['users'],
    responses={
        200: {'description': 'Success', 'model': models.UserShowResponse},
        404: {'description': 'No such user exists or you cannot see them.'}
    }
)
def show(req_user_id: int, authorization=Header(None)):
    request_cost = 1

    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        users = Table('users')
        itgs.read_cursor.execute(
            Query.from_(users).select(users.username)
            .where(users.id == Parameter('%s')).get_sql(),
            (req_user_id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        headers['Cache-Control'] = 'public, max-age=604800, immutable'
        return JSONResponse(
            status_code=200,
            content=models.UserShowResponse(username=row[0]).dict(),
            headers=headers
        )


@router.get(
    '/lookup',
    tags=['users'],
    responses={
        200: {'description': 'Success', 'model': models.UserLookupResponse},
        404: {'description': 'No such user exists or you cannot see them'}
    }
)
def lookup(q: str, authorization=Header(None)):
    """Allows looking up a user id by a username. q is the username to lookup"""
    request_cost = 1

    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS)

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        users = Table('users')
        itgs.read_cursor.execute(
            Query.from_(users).select(users.id)
            .where(users.username == Parameter('%s')).get_sql(),
            (q.lower(),)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        headers['Cache-Control'] = 'public, max-age=604800, immutable'
        return JSONResponse(
            status_code=200,
            content=models.UserLookupResponse(id=row[0]).dict(),
            headers=headers
        )


@router.get(
    '/suggest',
    responses={
        200: {'description': 'Success', 'model': models.UserSuggestResponse},
        204: {'description': 'Success; no suggestions'}
    }
)
def suggest(q: str, limit: int = 3, authorization=Header(None)):
    """Suggest some usernames that partially match the query. q is the partial
    username string"""
    if limit <= 0:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['limit'],
                    'msg': 'Must be positive',
                    'type': 'range_error'
                }
            }
        )

    # This is actually moderately expensive since we don't use the correct
    # index for this, but we could switch to a real searching technique to
    # speed it up if this endpoint is problematic, so we'll under-charge here.
    request_cost = 10 + limit

    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS)

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        users = Table('users')
        itgs.read_cursor.execute(
            Query.from_(users).select(users.id)
            .where(users.username.like(Parameter('%s')))
            .limit(limit)
            .get_sql(),
            ('%' + q.lower() + '%',)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=204)
        result = []
        while row is not None:
            result.append(row)
            row = itgs.read_cursor.fetchone()

        headers['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=518400'
        return JSONResponse(
            status_code=200,
            content=models.UserSuggestResponse(suggestions=result).dict(),
            headers=headers
        )


@router.get(
    '/{user_id}/me',
    tags=['users'],
    responses={
        200: {'description': 'Authtoken accepted', 'model': models.UserShowSelfResponse},
        403: {'description': 'Token authentication failed'}
    }
)
def me(user_id: int, authorization: str = Header(None)):
    """Get an extremely small amount of information about the user specified
    in the token. This endpoint is expected to be used for the client verifying
    tokens and will indicate so in the cache-control."""
    authtoken = helper.get_authtoken_from_header(authorization)
    if authtoken is None:
        return Response(status_code=403)

    with LazyItgs() as itgs:
        info = helper.get_auth_info_from_token_auth(
            itgs, models.TokenAuthentication(token=authtoken),
            require_user_id=user_id
        )
        if info is None:
            return Response(status_code=403)
        auth_id, authed_user_id, expires_at = info[:3]

        users = Table('users')
        itgs.read_cursor.execute(
            Query.from_(users).select(users.username)
            .where(users.id == Parameter('%s'))
            .get_sql(),
            (authed_user_id,)
        )
        (username,) = itgs.read_cursor.fetchone()

        return JSONResponse(
            status_code=200,
            content=models.UserShowSelfResponse(username=username).dict(),
            headers={
                'Cache-Control': helper.cache_control_for_expires_at(
                    expires_at, try_refresh_every=60)
            }
        )


@router.get(
    '/{user_id}/permissions',
    tags=['users', 'auth'],
    responses={
        200: {'description': 'Success', 'model': models.UserPermissions},
        403: {'description': 'Token authentication failed'}
    }
)
def check_permissions(user_id: int, authorization: str = Header(None)):
    """Checks the given authorization tokens permission level. This should NOT
    be used to check if the user is logged in. This response has cache-control
    headers set to roughly the length of a token, since it's assumed that for
    a given client permissions change fairly rarely and clients being somewhat
    out of date about their permissions isn't a security issue (as the server
    will recheck).

    In the event of logging out and logging in on a new account, the fact that
    the user id is in the url will more than suffice
    """
    authtoken = helper.get_authtoken_from_header(authorization)
    if authtoken is None:
        return Response(status_code=403)

    with LazyItgs() as itgs:
        info = helper.get_auth_info_from_token_auth(
            itgs, models.TokenAuthentication(token=authtoken),
            require_user_id=user_id
        )
        if info is None:
            return Response(status_code=403)
        authid = info[0]
        expires_at = info[2]

        perms = Table('permissions')
        auth_perms = Table('authtoken_permissions')
        itgs.read_cursor.execute(
            Query.from_(auth_perms)
            .select(perms.name)
            .join(perms).on(perms.id == auth_perms.permission_id)
            .where(auth_perms.authtoken_id == Parameter('%s'))
            .get_sql(),
            (authid,)
        )
        res = itgs.read_cursor.fetchall()
        permissions = [row[0] for row in res]
        return JSONResponse(
            status_code=200,
            content=models.UserPermissions(permissions=permissions).dict(),
            headers={
                'Cache-Control': helper.cache_control_for_expires_at(expires_at)
            }
        )


@router.post(
    '/request_claim_token',
    tags=['users', 'auth'],
    responses={
        200: {'description': 'Claim token sent'},
        400: {'description': 'Arguments invalid', 'model': main_models.ErrorResponse},
        429: {'description': 'You are doing that too much'}
    }
)
def request_claim_token(args: models.ClaimRequestArgs):
    """Sends a link to the reddit user with the given username which can be
    used to prove identity."""
    username = args.username.lower()
    token = args.captcha_token
    if len(username) > 32:
        return JSONResponse(
            status_code=400,
            content=main_models.ErrorResponse(message='username invalid').dict()
        )

    with LazyItgs(no_read_only=True) as itgs:
        if not security.verify_captcha(itgs, token):
            return JSONResponse(
                status_code=400,
                content=main_models.ErrorResponse(message='captcha invalid').dict()
            )

        if not security.ratelimit(
                itgs, 'MAX_REQUEST_CLAIM_TOKEN', 'request_claim_token',
                defaults={60: 5, 600: 30}):
            return Response(status_code=429)

        if not security.ratelimit(
                itgs, 'MAX_REQUEST_CLAIM_TOKEN_INDIV',
                f'request_claim_token_{username}',
                defaults={
                    int(timedelta(minutes=2).total_seconds()): 1,
                    int(timedelta(minutes=10).total_seconds()): 2,
                    int(timedelta(days=1).total_seconds()): 3,
                    int(timedelta(weeks=1).total_seconds()): 5
                }):
            return Response(status_code=429)

        users = Table('users')
        itgs.read_cursor.execute(
            Query.from_(users).select(users.id)
            .where(users.username == Parameter('%s'))
            .get_sql(),
            (username,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            user_id = helper.create_new_user(itgs, username, commit=False)
        else:
            user_id = row[0]

        token = helper.create_claim_token(itgs, user_id, commit=True)
        send_queue = os.environ['AMQP_REDDIT_PROXY_QUEUE']
        url_root = os.environ['ROOT_DOMAIN']
        itgs.channel.queue_declare(queue=send_queue)
        itgs.channel.basic_publish(
            exchange='',
            routing_key=send_queue,
            body=json.dumps({
                'type': 'compose',
                'response_queue': os.environ['AMQP_RESPONSE_QUEUE'],
                'uuid': token,
                'version_utc_seconds': float(os.environ['APP_VERSION_NUMBER']),
                'sent_at': time.time(),
                'args': {
                    'recipient': username,
                    'subject': 'RedditLoans: Claim your account',
                    'body': (
                        f'To claim your account on {url_root} '
                        ' by proving you own this reddit account, '
                        f'[click here]({url_root}/claim.html?user_id={user_id}&token={token})'
                        '\n\n'
                        'If you did not request this, ignore this message '
                        'and feel free to block future pms by clicking '
                        '"block user" below this message.'
                    )
                }
            }).encode('utf-8')
        )
    return Response(status_code=200)


@router.post(
    '/claim',
    tags=['users', 'auth'],
    responses={
        200: {'description': 'Password set'},
        400: {'description': 'Password or recatpcha invalid', 'model': main_models.ErrorResponse},
        403: {'description': 'Invalid or expired claim token', 'model': main_models.ErrorResponse},
        429: {'description': 'You are doing that too much'}
    }
)
def set_human_passauth_with_claim_token(args: models.ClaimArgs):
    """Sets the human password for the given user to the given password using
    the given claim token as proof of account ownership.
    """
    if not (5 < len(args.password) < 256):
        return JSONResponse(
            status_code=400,
            content=main_models.ErrorResponse(
                message='Password must be more than 5 and less than 256 characters'
            )
        )

    with LazyItgs(no_read_only=True) as itgs:
        if not security.ratelimit(
                itgs, 'MAX_USE_CLAIM_TOKEN', 'use_claim_token',
                defaults={60: 5, 600: 30}):
            return Response(status_code=429)

        if not security.ratelimit(
                itgs, 'MAX_USE_CLAIM_TOKEN_INDIV',
                f'use_claim_token_{args.user_id}',
                defaults={
                    int(timedelta(minutes=2).total_seconds()): 1,
                    int(timedelta(minutes=10).total_seconds()): 2,
                    int(timedelta(days=1).total_seconds()): 3,
                    int(timedelta(weeks=1).total_seconds()): 5
                }):
            return Response(status_code=429)

        if not helper.attempt_consume_claim_token(itgs, args.user_id, args.claim_token):
            return Response(status_code=403)
        helper.create_or_update_human_password_auth(
            itgs, args.user_id, args.password, commit=True
        )
    return Response(status_code=200)
