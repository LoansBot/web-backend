from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from . import models
from . import helper
import users.helper
import ratelimit_helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from pypika.functions import Count, Star, Now
from lbshared.pypika_crits import exists
import math
from hashlib import scrypt
from base64 import b64encode
import secrets
import os
import itertools

router = APIRouter()


@router.get(
    '/{id}/permissions',
    tags=['authentication_methods', 'permissions'],
    responses={
        200: {'description': 'Success', 'model': models.AuthMethodPermissions},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header provided but invalid'},
        404: {'description': 'Unknown authentication method or not owned by you.'}
    }
)
def index_permissions(id: int, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 50
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if user_id is None:
            return Response(status_code=403, headers={'x-request-cost': str(request_cost)})

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms

        auth_methods = Table('password_authentications')
        auth_perms = Table('password_auth_permissions')
        permissions = Table('permissions')

        query = (
            Query.from_(auth_methods)
            .select(permissions.name)
            .join(auth_perms).on(auth_perms.password_authentication_id == auth_methods.id)
            .join(permissions).on(permissions.id == auth_perms.permission_id)
            .where(auth_methods.deleted.eq(False))
            .where(auth_methods.id == Parameter('%s'))
        )
        args = [id]

        if not can_view_others_auth_methods:
            query = query.where(auth_methods.user_id == Parameter('%s'))
            args.append(user_id)

        if not can_view_deleted_auth_methods:
            query = query.where(auth_methods.deleted.eq(False))

        itgs.read_cursor.execute(query.get_sql(), args)

        result = []
        row = itgs.read_cursor.fetchone()
        while row is not None:
            result.append(row[0])
            row = itgs.read_cursor.fetchone()

        return JSONResponse(
            status_code=200,
            headers={
                'x-request-cost': str(request_cost),
                'Cache-Control': 'private, max-age=60, stale-while-revalidate=540'
            },
            content=models.AuthMethodPermissions(granted=result).dict()
        )


@router.delete(
    '/{id}/permissions/{perm}',
    tags=['authentication_methods', 'permissions'],
    responses={
        200: {'description': 'Permission revoked'},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or you can see but not modify.'},
        404: {'description': 'Authentication method does not exist or you cannot see it.'},
        409: {'description': 'That authorization method does not have that permission'}
    }
)
def revoke_permission(id: int, perm: str, authorization=Header(None)):
    """This immediately takes effect on all corresponding auth tokens."""
    if authorization is None:
        return Response(status_code=401)

    request_cost = 5
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                perm,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if user_id is None or perm not in perms:
            return Response(status_code=403, headers={'x-request-cost': str(request_cost)})

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_modify_others_auth_methods = (
            helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM in perms)
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms

        auth_methods = Table('password_authentications')
        authtokens = Table('authtokens')
        authtoken_perms = Table('authtoken_permissions')
        permissions = Table('permissions')

        itgs.read_cursor.execute(
            Query.from_(auth_methods).select(auth_methods.user_id, auth_methods.deleted)
            .where(auth_methods.id == Parameter('%s'))
            .get_sql(),
            (id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        (auth_method_user_id, deleted) = row

        if deleted:
            if not can_view_deleted_auth_methods:
                return Response(
                    status_code=404,
                    headers={'x-request-cost': str(request_cost)}
                )
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        if auth_method_user_id != user_id:
            if not can_view_others_auth_methods:
                return Response(
                    status_code=404,
                    headers={'x-request-cost': str(request_cost)}
                )

            if not can_modify_others_auth_methods:
                return Response(
                    status_code=403,
                    headers={'x-request-cost': str(request_cost)}
                )

        auth_perms = Table('password_auth_permissions')
        outer_auth_perms = auth_perms.as_('outer_perms')
        inner_auth_perms = auth_perms.as_('inner_perms')
        itgs.write_cursor.execute(
            Query.from_(outer_auth_perms).delete().where(
                exists(
                    Query.from_(inner_auth_perms)
                    .where(inner_auth_perms.id == outer_auth_perms.id)
                    .join(auth_methods).on(
                        auth_methods.id == inner_auth_perms.password_authentication_id)
                    .join(permissions).on(permissions.id == inner_auth_perms.permission_id)
                    .where(auth_methods.id == Parameter('%s'))
                    .where(permissions.name == Parameter('%s'))
                )
            )
            .returning(outer_auth_perms.id)
            .get_sql(),
            (id, perm.lower())
        )
        found_any = not not itgs.write_cursor.fetchall()

        outer_perms = authtoken_perms.as_('outer_perms')
        inner_perms = authtoken_perms.as_('inner_perms')
        itgs.write_cursor.execute(
            Query.from_(outer_perms).delete().where(
                exists(
                    Query.from_(inner_perms)
                    .where(inner_perms.id == outer_perms.id)
                    .join(authtokens).on(authtokens.id == inner_perms.authtoken_id)
                    .join(permissions).on(permissions.id == inner_perms.permission_id)
                    .where(authtokens.source_type == Parameter('%s'))
                    .where(authtokens.source_id == Parameter('%s'))
                    .where(permissions.name == Parameter('%s'))
                )
            )
            .get_sql(),
            ('password_authentication', id, perm.lower())
        )
        itgs.write_conn.commit()

        if not found_any:
            return Response(
                status_code=409,
                headers={'x-request-cost': str(request_cost)}
            )

        return Response(
            status_code=200,
            headers={'x-request-cost': str(request_cost)}
        )


@router.post(
    '/{id}/permissions/{perm}',
    tags=['authentication_methods', 'permissions'],
    responses={
        201: {'description': 'Permission granted'},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or you can see but not modify'},
        404: {'description': 'Authentication method does not exist or you cannot see it.'},
        409: {'description': 'Authentication method already has that permission'}
    }
)
def grant_permission(id: int, perm: str, authorization=Header(None)):
    """This does not apply to existing auth tokens."""
    if authorization is None:
        return Response(status_code=401)

    request_cost = 5
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                perm,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if (user_id is None) or (perm not in perms):
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_modify_others_auth_methods = (
            helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM in perms)
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms

        auth_methods = Table('password_authentications')

        if (not can_modify_others_auth_methods) or (not can_view_others_auth_methods):
            itgs.read_cursor.execute(
                Query.from_(auth_methods)
                .select(auth_methods.user_id, auth_methods.deleted)
                .where(auth_methods.id == Parameter('%s'))
                .get_sql(),
                (id,)
            )
            row = itgs.read_cursor.fetchone()

            if row is None:
                return Response(
                    status_code=404,
                    headers={'x-request-cost': str(request_cost)}
                )

            (auth_method_user_id, deleted) = row
            if auth_method_user_id != user_id:
                if not can_view_others_auth_methods:
                    return Response(
                        status_code=404,
                        headers={'x-request-cost': str(request_cost)}
                    )

                return Response(
                    status_code=403,
                    headers={'x-request-cost': str(request_cost)}
                )

            if deleted:
                if not can_view_deleted_auth_methods:
                    return Response(
                        status_code=404,
                        headers={'x-request-cost': str(request_cost)}
                    )

                return Response(
                    status_code=403,
                    headers={'x-request-cost': str(request_cost)}
                )

        itgs.write_cursor.execute(
            '''
            INSERT INTO password_auth_permissions (password_authentication_id, permission_id)
            SELECT %s, permissions.id
            FROM permissions
            WHERE
                permissions.name = %s AND
                NOT EXISTS (
                    SELECT FROM password_auth_permissions
                    JOIN permissions ON permissions.id = password_auth_permissions.permission_id
                    WHERE
                        password_authentication_id = %s AND
                        permissions.name = %s
                )
            LIMIT 1
            RETURNING 1 AS one
            ''',
            (id, perm.lower(), id, perm.lower())
        )
        inserted_any = itgs.read_cursor.fetchone() is not None

        itgs.write_conn.commit()

        if not inserted_any:
            return Response(
                status_code=409,
                headers={'x-request-cost': str(request_cost)}
            )

        return Response(
            status_code=200,
            headers={'x-request-cost': str(request_cost)}
        )


@router.get(
    '/{id}/history',
    tags=['authentication_methods'],
    responses={
        200: {'description': 'Success.', 'model': models.AuthMethodHistory},
        204: {'description': 'No more history found'},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid'},
        404: {'description': 'Authentication method does not exist or you cannot see it.'}
    }
)
def index_history(id: int, after_id: int = None, limit: int = None, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    if limit is None:
        limit = 25

    if limit <= 0:
        return JSONResponse(
            status_code=422,
            content={
                'detail': [
                    {
                        'loc': ['query', 'limit'],
                        'msg': 'Must be non-negative',
                        'type': 'value_error'
                    }
                ]
            }
        )

    request_cost = max(5 * math.ceil(math.log(limit)), 5)

    request_cost = 5
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_OTHERS_AUTH_EDIT_NOTES_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if user_id is None:
            return Response(status_code=403, headers={'x-request-cost': str(request_cost)})

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_view_others_edit_notes = helper.CAN_VIEW_OTHERS_AUTH_EDIT_NOTES_PERM in perms
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms

        auth_methods = Table('password_authentications')
        query = (
            Query.from_(auth_methods).select(1)
            .where(auth_methods.id == Parameter('%s'))
        )
        args = [id]
        if not can_view_others_auth_methods:
            query = query.where(auth_methods.user_id == Parameter('%s'))
            args.append(user_id)

        if not can_view_deleted_auth_methods:
            query = query.where(auth_methods.deleted.eq(False))

        itgs.read_cursor.execute(
            query.get_sql(),
            args
        )
        if itgs.read_cursor.fetchone() is None:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        events = Table('password_authentication_events')
        usrs = Table('users')
        query = (
            Query.from_(events)
            .join(usrs).on(usrs.id == events.user_id)
            .where(events.password_authentication_id == Parameter('%s'))
            .select(
                events.id,
                events.type,
                events.reason,
                events.user_id,
                usrs.username,
                events.reason,
                events.created_at
            )
            .orderby(events.id, order=Order.asc)
        )
        args = [id]

        if after_id is not None:
            query = query.where(events.id > Parameter('%s'))
            args.append(after_id)

        query = query.limit(Parameter('%s'))
        args.append(limit + 1)  # add 1 to check if theres more, slightly better UX

        itgs.read_cursor.execute(
            query.get_sql(),
            args
        )

        result = []
        next_id = None
        have_more = False
        row = itgs.read_cursor.fetchone()
        while row is not None:
            (
                this_id,
                event_type,
                event_reason,
                event_user_id,
                event_username,
                event_reason,
                event_created_at
            ) = row

            if len(result) >= limit:
                have_more = True
                itgs.read_cursor.fetchall()
                break

            next_id = this_id

            if (not can_view_others_edit_notes
                    and event_user_id is not None  # system events, deleted users
                    and event_user_id != user_id):
                event_user_id = None
                event_username = None
                event_reason = None

            result.append(models.AuthMethodHistoryItem(
                event_type=event_type,
                reason=event_reason,
                username=event_username,
                occurred_at=event_created_at.timestamp()
            ))
            row = itgs.read_cursor.fetchone()

        if not result:
            return Response(status_code=204, headers={'x-request-cost': str(request_cost)})

        if have_more:
            cache_control = 'private, max-age=604800'
        else:
            cache_control = 'private, max-age=20, stale-while-revalidate=580'
            next_id = None

        return JSONResponse(
            status_code=200,
            content=models.AuthMethodHistory(
                next_id=next_id,
                history=result
            ).dict(),
            headers={
                'cache-control': cache_control,
                'x-request-cost': str(request_cost)
            }
        )


@router.get(
    '/{id}/?',
    responses={
        200: {'description': 'Success', 'model': models.AuthMethod},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'Auth method does not exist or you cannot see it'}
    }
)
def show(id: int, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 1
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if user_id is None:
            return Response(status_code=403, headers={'x-request-cost': str(request_cost)})

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms

        auth_methods = Table('password_authentications')
        query = (
            Query.from_(auth_methods)
            .select(
                auth_methods.human,
                auth_methods.deleted
            )
            .where(auth_methods.id == Parameter('%s'))
        )
        args = [id]

        if not can_view_others_auth_methods:
            query = query.where(auth_methods.user_id == Parameter('%s'))
            args.append(user_id)

        if not can_view_deleted_auth_methods:
            query = query.where(auth_methods.deleted.eq(False))

        itgs.read_cursor.execute(query.get_sql(), args)
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        (main, deleted) = row

        authtokens = Table('authtokens')
        itgs.read_cursor.execute(
            Query.from_(authtokens)
            .select(Count(Star()))
            .where(authtokens.expires_at < Now())
            .where(authtokens.source_type == Parameter('%s'))
            .where(authtokens.source_id == Parameter('%s'))
            .get_sql(),
            ('password_authentication', id)
        )
        (active_grants,) = itgs.read_cursor.fetchone()

        return JSONResponse(
            status_code=200,
            content=models.AuthMethod(
                main=main,
                deleted=deleted,
                active_grants=active_grants
            ).dict(),
            headers={'x-request-cost': str(request_cost)}
        )


@router.put(
    '/{id}/password',
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'Auth method does not exist or you cannot see it.'}
    }
)
def change_password(id: int, args: models.ChangePasswordParams, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    # In reality this is probably closer to ~10000, but we want to make sure
    # everyone could actually save enough tokens to do this. To avoid user error,
    # we will split the ratelimit cost into a pre- and post- part
    check_request_cost = 5
    perform_request_cost = 295
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, check_request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(check_request_cost)}
            )

        if user_id is None:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(check_request_cost)}
            )

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms

        auth_methods = Table('password_authentications')
        itgs.read_cursor.execute(
            Query.from_(auth_methods)
            .select(auth_methods.user_id, auth_methods.deleted)
            .where(auth_methods.id == Parameter('%s'))
            .get_sql(),
            (id,)
        )
        row = itgs.read_cursor.fetchone()

        if row is None:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(check_request_cost)}
            )

        (auth_method_user_id, deleted) = row
        if auth_method_user_id != user_id:
            if not can_view_others_auth_methods:
                return Response(
                    status_code=404,
                    headers={'x-request-cost': str(check_request_cost)}
                )

            return Response(
                status_code=403,
                headers={'x-request-cost': str(check_request_cost)}
            )

        if deleted:
            if not can_view_deleted_auth_methods:
                return Response(
                    status_code=404,
                    headers={'x-request-cost': str(check_request_cost)}
                )

            return Response(
                status_code=403,
                headers={'x-request-cost': str(check_request_cost)}
            )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, perform_request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(check_request_cost + perform_request_cost)}
            )

        salt = secrets.token_urlsafe(23)  # 31 chars
        block_size = int(os.environ.get('NONHUMAN_PASSWORD_BLOCK_SIZE', '8'))
        dklen = int(os.environ.get('NONHUMAN_PASSWORD_DKLEN', '64'))

        # final number is MiB of RAM for the default
        iterations = int(os.environ.get('NONHUMAN_PASSWORD_ITERATIONS', str((1024 * 8) * 64)))
        hash_name = f'scrypt-{block_size}-{dklen}'

        password_digest = b64encode(
            scrypt(
                args.password.encode('utf-8'),
                salt=salt.encode('utf-8'),
                n=iterations,
                r=block_size,
                p=1,
                maxmem=128 * iterations * block_size + 1024 * 64,  # padding not necessary?
                dklen=dklen
            )
        ).decode('ascii')

        itgs.write_cursor.execute(
            Query.update(auth_methods)
            .set(auth_methods.hash_name, Parameter('%s'))
            .set(auth_methods.hash, Parameter('%s'))
            .set(auth_methods.salt, Parameter('%s'))
            .set(auth_methods.iterations, Parameter('%s'))
            .where(auth_methods.id == Parameter('%s'))
            .get_sql(),
            (
                hash_name,
                password_digest,
                salt,
                iterations,
                id
            )
        )

        auth_events = Table('password_authentication_events')
        itgs.write_cursor.execute(
            Query.into(auth_events)
            .columns(
                auth_events.password_authentication_id,
                auth_events.type,
                auth_events.reason,
                auth_events.permission_id,
                auth_events.user_id
            )
            .insert(*[Parameter('%s') for _ in range(5)])
            .get_sql(),
            (
                id,
                'password-changed',
                args.reason,
                None,
                user_id
            )
        )
        itgs.write_conn.commit()
        return Response(
            status_code=200,
            headers={'x-request-cost': str(check_request_cost + perform_request_cost)}
        )


@router.delete(
    '/{id}',
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'Auth method does not exist or you cannot see it'},
        409: {'description': 'That auth method is already deleted'}
    }
)
def delete(id: int, reason_wrapped: models.Reason, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 5
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if user_id is None:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms
        can_modify_others_auth_methods = (
            helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM in perms)

        auth_methods = Table('password_authentications')
        itgs.read_cursor.execute(
            Query.from_(auth_methods)
            .select(auth_methods.human, auth_methods.deleted, auth_methods.user_id)
            .where(auth_methods.id == Parameter('%s'))
            .get_sql(),
            (id,)
        )

        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        (human, deleted, auth_method_user_id) = row
        if deleted and not can_view_deleted_auth_methods:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        if auth_method_user_id != user_id and not can_view_others_auth_methods:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        if human:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        if auth_method_user_id != user_id and not can_modify_others_auth_methods:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        if deleted:
            return Response(
                status_code=409,
                headers={'x-request-cost': str(request_cost)}
            )

        itgs.write_cursor.execute(
            Query.update(auth_methods)
            .set(auth_methods.deleted, True)
            .where(auth_methods.id == Parameter('%s'))
            .get_sql(),
            (id,)
        )

        auth_events = Table('password_authentication_events')
        itgs.write_cursor.execute(
            Query.into(auth_events)
            .columns(
                auth_events.password_authentication_id,
                auth_events.type,
                auth_events.reason,
                auth_events.user_id,
                auth_events.permission_id
            )
            .insert(*[Parameter('%s') for _ in range(5)])
            .get_sql(),
            (id, 'deleted', reason_wrapped.reason, user_id, None)
        )

        authtokens = Table('authtokens')
        itgs.write_cursor.execute(
            Query.from_(authtokens).delete()
            .where(authtokens.source_type == Parameter('%s'))
            .where(authtokens.source_id == Parameter('%s'))
            .get_sql(),
            ('password_authentication', id)
        )
        itgs.write_conn.commit()
        return Response(
            status_code=200,
            headers={'x-request-cost': str(request_cost)}
        )


@router.delete(
    '/{id}/permissions',
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'Auth method does not exist or you cannot see it'}
    }
)
def delete_all_permissions(id: int, reason_wrapped: models.Reason, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 5
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if user_id is None:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms
        can_modify_others_auth_methods = (
            helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM in perms)

        auth_methods = Table('password_authentications')
        itgs.read_cursor.execute(
            Query.from_(auth_methods)
            .select(auth_methods.deleted, auth_methods.user_id)
            .where(auth_methods.id == Parameter('%s'))
            .get_sql(),
            (id,)
        )

        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        (deleted, auth_method_user_id) = row
        if deleted and not can_view_deleted_auth_methods:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        if auth_method_user_id != user_id and not can_view_others_auth_methods:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        if auth_method_user_id != user_id and not can_modify_others_auth_methods:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        if deleted:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        authtoken = users.helper.get_authtoken_from_header(authorization)
        info = users.helper.get_auth_info_from_token_auth(
            itgs, models.TokenAuthentication(token=authtoken)
        )
        auth_id = info[0]

        # You can only delete permissions from someone that you yourself have!
        itgs.write_cursor.execute(
            '''
            DELETE FROM password_auth_permissions AS outer
            WHERE
                password_authentication_id = %s AND
                EXISTS (
                    SELECT FROM password_auth_permissions
                    WHERE
                        password_authentication_id = %s AND
                        permission_id = outer.permission_id
                )
            RETURNING outer.permission_id
            ''',
            (id, auth_id)
        )

        rows = itgs.write_cursor.fetchall()
        if rows:
            auth_events = Table('password_authentication_events')
            authtokens = Table('authtokens')
            itgs.write_cursor.execute(
                Query.into(auth_events)
                .columns(
                    auth_events.password_authentication_id,
                    auth_events.type,
                    auth_events.reason,
                    auth_events.user_id,
                    auth_events.permission_id
                )
                .insert(
                    *[[Parameter('%s') for _ in range(5)] for _ in rows]
                )
                .get_sql(),
                tuple(
                    itertools.chain.from_iterable(
                        (
                            id,
                            'permission-revoked',
                            reason_wrapped.reason,
                            user_id,
                            row[0]
                        )
                        for row in rows
                    )
                )
            )
            itgs.write_cursor.execute(
                Query.from_(authtokens).delete()
                .where(authtokens.source_type == Parameter('%s'))
                .where(authtokens.source_id == Parameter('%s'))
                .get_sql(),
                ('password_authentication', id)
            )
        itgs.write_conn.commit()
        return Response(status_code=200)


@router.delete(
    '/{id}/sessions',
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'Auth method does not exit or you cannot see it'}
    }
)
def delete_all_sessions(id: int, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 5
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
                helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
                helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if user_id is None:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        can_view_others_auth_methods = helper.VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_view_deleted_auth_methods = helper.CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms
        can_modify_others_auth_methods = (
            helper.CAN_MODIFY_OTHERS_AUTHENTICATION_METHODS_PERM in perms)

        auth_methods = Table('password_authentications')
        itgs.read_cursor.execute(
            Query.from_(auth_methods)
            .select(auth_methods.deleted, auth_methods.user_id)
            .where(auth_methods.id == Parameter('%s'))
            .get_sql(),
            (id,)
        )

        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        (deleted, auth_method_user_id) = row
        if deleted and not can_view_deleted_auth_methods:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        if auth_method_user_id != user_id and not can_view_others_auth_methods:
            return Response(
                status_code=404,
                headers={'x-request-cost': str(request_cost)}
            )

        if auth_method_user_id != user_id and not can_modify_others_auth_methods:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        authtokens = Table('authtokens')
        itgs.write_cursor.execute(
            Query.from_(authtokens).delete()
            .where(authtokens.source_type == Parameter('%s'))
            .where(authtokens.source_id == Parameter('%s'))
            .get_sql(),
            ('password_authentication', id)
        )
        itgs.write_conn.commit()
        return Response(
            status_code=200,
            headers={'x-request-cost': str(request_cost)}
        )
