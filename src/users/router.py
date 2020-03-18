from fastapi import APIRouter, Cookie
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter
from . import helper
from . import models
import models as main_models
import security
import integrations as itgs
from datetime import timedelta
import os
import uuid
import time
import json
from lblogging import Level


router = APIRouter()


@router.post(
    '/login',
    tags=['users', 'auth'],
    responses={
        200: {'model': models.TokenResponse},
        403: {
            'description': (
                'The provided authentication could not be identified'
            )
        }
    }
)
def login(auth: models.PasswordAuthentication):
    with itgs.database() as conn:
        cursor = conn.cursor()
        auth_id = None
        with security.fixed_duration(0.5):
            auth_id = helper.get_valid_passwd_auth(conn, cursor, auth)
        if auth_id is None:
            return Response(status_code=403)

        res = helper.create_token_from_passauth(conn, cursor, auth_id)
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
    with itgs.database() as conn:
        cursor = conn.cursor()
        info = helper.get_auth_info_from_token_auth(conn, cursor, auth)
        if info is None:
            return Response(status_code=403)
        auth_id = info[0]

        authtokens = Table('authtokens')
        cursor.execute(
            Query
            .from_(authtokens)
            .delete()
            .where(authtokens.id == Parameter('%s'))
            .get_sql(),
            (auth_id,)
        )
        conn.commit()
        return Response(status_code=200)


@router.get(
    '/{user_id}/me',
    tags=['users'],
    responses={
        200: {'description': 'Authtoken accepted', 'model': models.UserShowSelfResponse},
        403: {'description': 'Token authentication failed'}
    }
)
def me(user_id: int, authtoken: str = Cookie(None)):
    if authtoken is None:
        return Response(status_code=403)
    with itgs.database() as conn:
        cursor = conn.cursor()
        info = helper.get_auth_info_from_token_auth(
            conn, cursor, models.TokenAuthentication(token=authtoken)
        )
        if info is None:
            return Response(status_code=403)
        auth_id, authed_user_id = info
        if authed_user_id != user_id:
            with itgs.logger('users/router.py') as lgr:
                lgr.print(
                    Level.DEBUG,
                    'Someone proved their identity as {} with an authtoken, '
                    'but they pretended they were {}. Their authtoken was '
                    'revoked',
                    authed_user_id, user_id
                )
            authtokens = Table('authtokens')
            cursor.execute(
                Query.from_(authtokens).delete()
                .where(authtokens.id == Parameter('%s')).get_sql(),
                (auth_id,)
            )
            conn.commit()
            return Response(status_code=403)
        users = Table('users')
        cursor.execute(
            Query.from_(users).select(users.username)
            .where(users.id == Parameter('%s'))
            .get_sql(),
            (authed_user_id,)
        )
        (username,) = cursor.fetchone()
        return JSONResponse(
            status_code=200,
            content=models.UserShowSelfResponse(username=username).dict()
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
def request_claim_token(username: models.Username):
    """Sends a link to the reddit user with the given username which can be
    used to prove identity."""
    username = username.username
    if len(username) > 32:
        return main_models.ErrorResponse(message='username invalid')

    # rate limit
    with itgs.memcached() as cache:
        if not security.ratelimit(
                cache, 'MAX_REQUEST_CLAIM_TOKEN', 'request_claim_token',
                defaults={60: 5, 600: 30}):
            return Response(status_code=429)

        if not security.ratelimit(
                cache, 'MAX_REQUEST_CLAIM_TOKEN_INDIV',
                f'request_claim_token_{username}',
                defaults={
                    int(timedelta(minutes=2).total_seconds()): 1,
                    int(timedelta(minutes=10).total_seconds()): 2,
                    int(timedelta(days=1).total_seconds()): 3,
                    int(timedelta(weeks=1).total_seconds()): 5
                }):
            return Response(status_code=429)

    users = Table('users')
    with itgs.database() as conn:
        cursor = conn.cursor()
        cursor.execute(
            Query.from_(users).select(users.id)
            .where(users.username == Parameter('%s'))
            .get_sql(),
            (username,)
        )
        row = cursor.fetchone()
        if row is None:
            user_id = helper.create_new_user(conn, cursor, username, commit=False)
        else:
            user_id = row[0]

        token = helper.create_claim_token(conn, cursor, user_id, commit=True)
        with itgs.amqp() as (amqp, channel):
            send_queue = os.environ['AMQP_REDDIT_PROXY_QUEUE']
            url_root = os.environ['ROOT_DOMAIN']
            channel.queue_declare(queue=send_queue)
            token = str(uuid.uuid4())
            channel.basic_publish(
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
    if not security.verify_recaptcha(args.recaptcha_token):
        return JSONResponse(
            status_code=400,
            content=main_models.ErrorResponse(
                message='Invalid recaptcha token'
            )
        )

    with itgs.memcached() as cache:
        if not security.ratelimit(
                cache, 'MAX_USE_CLAIM_TOKEN', 'use_claim_token',
                defaults={60: 5, 600: 30}):
            return Response(status_code=429)

        if not security.ratelimit(
                cache, 'MAX_USE_CLAIM_TOKEN_INDIV',
                f'use_claim_token_{args.user_id}',
                defaults={
                    int(timedelta(minutes=2).total_seconds()): 1,
                    int(timedelta(minutes=10).total_seconds()): 2,
                    int(timedelta(days=1).total_seconds()): 3,
                    int(timedelta(weeks=1).total_seconds()): 5
                }):
            return Response(status_code=429)

    with itgs.database() as conn:
        cursor = conn.cursor()
        if not helper.attempt_consume_claim_token(conn, cursor, args.user_id, args.claim_token):
            return Response(status_code=403)
        helper.create_or_update_human_password_auth(
            conn, cursor, args.user_id, args.password
        )
    return Response(status_code=200)
