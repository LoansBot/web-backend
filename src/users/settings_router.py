from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from lbshared.queries import convert_numbered_args
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from . import settings_models
from . import helper
from . import settings_helper
from authentication_methods.helper import (
    VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
    CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
    ADD_SELF_AUTHENTICATION_METHODS_PERM,
    ADD_OTHERS_AUTHENTICATION_METHODS_PERM
)
import ratelimit_helper
import math
import os
import secrets
from hashlib import pbkdf2_hmac
from base64 import b64encode

router = APIRouter()


@router.get(
    '/{req_user_id}/authentication_methods/?',
    responses={
        200: {'description': 'Success', 'model': settings_models.UserAuthMethodsList},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'The user does not exist or you cannot see them'}
    }
)
def show_authentication_methods(req_user_id: int, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 1
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(itgs, authorization, (
            VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
            CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM,
            ADD_SELF_AUTHENTICATION_METHODS_PERM,
            ADD_OTHERS_AUTHENTICATION_METHODS_PERM,
            *ratelimit_helper.RATELIMIT_PERMISSIONS
        ))

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers={'x-request-cost': str(request_cost)})

        can_view_others_auth_methods = VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_view_deleted_auth_methods = CAN_VIEW_DELETED_AUTHENTICATION_METHODS_PERM in perms
        can_add_self_auth_methods = ADD_SELF_AUTHENTICATION_METHODS_PERM in perms
        can_add_others_auth_methods = ADD_OTHERS_AUTHENTICATION_METHODS_PERM in perms

        if not can_view_others_auth_methods and req_user_id != user_id:
            return Response(status_code=403, headers={'x-request-cost': str(request_cost)})

        can_add_more = (
            (req_user_id == user_id and can_add_self_auth_methods) or can_add_others_auth_methods
        )
        auth_methods = Table('password_authentications')
        query = (
            Query.from_(auth_methods)
            .select(auth_methods.id)
            .where(auth_methods.user_id == Parameter('%s'))
        )
        args = (req_user_id,)

        if not can_view_deleted_auth_methods:
            query = query.where(auth_methods.deleted.eq(False))
        else:
            query = query.orderby(auth_methods.deleted, order=Order.asc)

        query = query.orderby(auth_methods.id, order=Order.desc)
        itgs.read_cursor.execute(
            query.get_sql(),
            args
        )

        result = itgs.read_cursor.fetchall()
        result = [r[0] for r in result]
        return JSONResponse(
            status_code=200,
            content=settings_models.UserAuthMethodsList(
                authentication_methods=result,
                can_add_more=can_add_more
            ).dict(),
            headers={
                'x-request-cost': str(request_cost),
                'cache-control': 'private, max-age=86400, stale-while-revalidate=86400'
            }
        )


@router.post(
    '/{req_user_id}/authentication_methods/?',
    responses={
        201: {'description': 'Success', 'model': settings_models.AuthMethodCreateResponse},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'The user does not exist or you cannot see them'}
    }
)
def create_authentication_method(req_user_id: int, authorization=Header(None)):
    """Create an authentication method with a randomly assigned password and
    no permissions. The password should be changed before adding permissions."""
    if authorization is None:
        return Response(status_code=401)

    request_cost = 50
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = helper.get_permissions_from_header(itgs, authorization, (
            VIEW_OTHERS_AUTHENTICATION_METHODS_PERM,
            ADD_SELF_AUTHENTICATION_METHODS_PERM,
            ADD_OTHERS_AUTHENTICATION_METHODS_PERM,
            *ratelimit_helper.RATELIMIT_PERMISSIONS
        ))

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=403, headers=headers)

        can_view_others_auth_methods = VIEW_OTHERS_AUTHENTICATION_METHODS_PERM in perms
        can_add_self_auth_methods = ADD_SELF_AUTHENTICATION_METHODS_PERM in perms
        can_add_others_auth_methods = ADD_OTHERS_AUTHENTICATION_METHODS_PERM in perms

        if req_user_id != user_id:
            if not can_view_others_auth_methods:
                return Response(status_code=404, headers=headers)

            users = Table('users')
            itgs.read_cursor.execute(
                Query.from_(users).select(1).where(users.id == Parameter('%s')).get_sql(),
                (req_user_id,)
            )
            if itgs.read_cursor.fetchone() is not None:
                return Response(status_code=404, headers=headers)

        can_add = (
            (user_id == req_user_id and can_add_self_auth_methods) or can_add_others_auth_methods
        )
        if not can_add:
            return Response(status_code=403, headers=headers)

        hash_name = 'sha512'
        passwd = secrets.token_urlsafe(23)
        salt = secrets.token_urlsafe(23)  # 31 chars
        iterations = int(os.environ.get('INITIAL_NONHUMAN_PASSWORD_ITERS', '10000'))

        passwd_digest = b64encode(
            pbkdf2_hmac(
                hash_name,
                passwd.encode('utf-8'),
                salt.encode('utf-8'),
                iterations
            )
        ).decode('ascii')

        auth_methods = Table('password_authentications')
        itgs.write_cursor.execute(
            Query.into(auth_methods).columns(
                auth_methods.user_id, auth_methods.human, auth_methods.hash_name,
                auth_methods.hash, auth_methods.salt, auth_methods.iterations
            ).insert(
                [Parameter('%s') for _ in range(6)]
            ).returning(auth_methods.id).get_sql(),
            (
                req_user_id,
                False,
                hash_name,
                passwd_digest,
                salt,
                iterations
            )
        )
        (row_id,) = itgs.write_cursor.fetchone()
        return JSONResponse(
            status_code=201,
            headers=headers,
            content=settings_models.AuthMethodCreateResponse(id=row_id).dict()
        )


@router.get(
    '/{req_user_id}/settings/history',
    responses={
        200: {'description': 'Success', 'model': settings_models.UserSettingsHistory},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'The user does not exist or you cannot see them'}
    }
)
def index_user_history(
        req_user_id: int,
        limit: int = 25,
        before_id: int = None,
        authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

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

    request_cost = max(1, math.log(limit))
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(itgs, authorization, (
            settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION,
            *ratelimit_helper.RATELIMIT_PERMISSIONS
        ))

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=404, headers=headers)

        can_see_others_settings = settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION in perms

        users = Table('users')
        if req_user_id != user_id:
            if not can_see_others_settings:
                return Response(status_code=404, headers=headers)

            itgs.read_cursor.execute(
                Query.from_(users).select(1).where(users.id == Parameter('%s')).get_sql(),
                (req_user_id,)
            )
            if itgs.read_cursor.fetchone() is None:
                return Response(status_code=404, headers=headers)

        events = Table('user_settings_events')
        query = (
            Query.from_(events)
            .select(events.id)
            .where(events.user_id == Parameter('$1'))
            .limit(Parameter('$2'))
            .orderby(events.id, order=Order.desc)
        )
        args = [req_user_id, limit + 1]

        if before_id is not None:
            query = query.where(events.id < Parameter('$3'))
            args.append(before_id)

        itgs.read_cursor.execute(*convert_numbered_args(query, args))
        result = []
        have_more = False
        row = itgs.read_cursor.fetchone()
        while row is not None:
            if len(result) < limit:
                result.append(row[0])
            else:
                have_more = True
            row = itgs.read_cursor.fetchone()

        if before_id is not None:
            headers['Cache-Control'] = 'private, max-age=86400, stale-while-revalidate=518400'

        return JSONResponse(
            status_code=200,
            content=settings_models.UserSettingsHistory(
                before_id=(min(result) if result else None) if have_more else None,
                history=result
            ),
            headers=headers
        )


@router.get(
    '/{req_user_id}/settings/history/{event_id}',
    responses={
        200: {'description': 'Success', 'model': settings_models.UserSettingsEvent},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'The event does not exist or you cannot see it'}
    }
)
def show_user_history_event(req_user_id: int, event_id: int, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(itgs, authorization, (
            settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION,
            settings_helper.VIEW_SETTING_CHANGE_AUTHORS_PERMISSION,
            *ratelimit_helper.RATELIMIT_PERMISSIONS
        ))

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=404, headers=headers)

        can_see_others_settings = settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION in perms
        can_see_change_authors = settings_helper.VIEW_SETTING_CHANGE_AUTHORS_PERMISSION in perms

        changer_users = Table('users').as_('changer_users')
        events = Table('user_settings_events')
        query = (
            Query.from_(events)
            .join(changer_users).on(changer_users.id == events.changer_user_id)
            .select(
                events.user_id, events.changer_user_id, changer_users.username,
                events.property_name, events.old_value, events.new_value,
                events.created_at
            ).where(events.id == Parameter('%s'))
        )
        args = [event_id]
        if not can_see_others_settings:
            query = query.where(events.user_id == Parameter('%s'))
            args.append(user_id)

        itgs.read_cursor.execute(query.get_sql(), args)

        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        (
            event_user_id,
            event_changer_user_id,
            event_changer_username,
            event_property_name,
            event_old_value,
            event_new_value,
            event_created_at
        ) = row

        event = settings_models.UserSettingsEvent(
            name=event_property_name,
            old_value=event_old_value,
            new_value=event_new_value,
            username=(
                event_changer_username
                if (event_changer_user_id == user_id or can_see_change_authors)
                else None
            ),
            occurred_at=event_created_at.timestamp()
        )

        headers['Cache-Control'] = 'private, max-age=604800, immutable'
        return JSONResponse(status_code=200, content=event.dict(), headers=headers)


@router.get(
    '/{req_user_id}/settings/{setting_name}',
    responses={
        200: {'description': 'Success', 'model': settings_models.UserSetting},
        401: {'description': 'Authorization header missing'},
        403: {'description': 'Authorization header invalid or insufficient'},
        404: {'description': 'The user or setting does not exist or you cannot see it'}
    }
)
def show_setting(
        req_user_id: int, setting_name: str, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    if '_' in setting_name:
        setting_name_fixed = setting_name.replace('_', '-')
        return Response(
            status_code=301,
            headers={
                'Location': f'/api/users/{req_user_id}/settings/{setting_name_fixed}'
            }
        )

    known_settings = frozenset((
        'non-req-response-opt-out',
        'borrower-req-pm-opt-out',
        'ratelimit'
    ))
    if setting_name not in known_settings:
        return Response(status_code=404)

    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(itgs, authorization, (
            settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION,
            settings_helper.EDIT_OTHERS_STANDARD_SETTINGS_PERMISSION,
            settings_helper.EDIT_RATELIMIT_SETTINGS_PERMISSION,
            settings_helper.EDIT_OTHERS_RATELIMIT_SETTINGS_PERMISSION,
            *ratelimit_helper.RATELIMIT_PERMISSIONS
        ))

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=404, headers=headers)

        can_view_others_settings = settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION in perms
        can_edit_others_standard_settings = (
            settings_helper.EDIT_OTHERS_STANDARD_SETTINGS_PERMISSION in perms)
        can_edit_self_ratelimit_settings = (
            settings_helper.EDIT_RATELIMIT_SETTINGS_PERMISSION in perms)
        can_edit_others_ratelimit_settings = (
            settings_helper.EDIT_OTHERS_RATELIMIT_SETTINGS_PERMISSION in perms)

        users = Table('users')
        if user_id != req_user_id:
            if not can_view_others_settings:
                return Response(status_code=404, headers=headers)

            itgs.read_cursor.execute(
                Query.from_(users).select(1).where(users.id == Parameter('%s')).get_sql(),
                (req_user_id,)
            )
            if itgs.read_cursor.fetchone() is None:
                return Response(status_code=404, headers=headers)

        settings = settings_helper.get_settings(itgs, req_user_id)

        if setting_name == 'non-req-response-opt-out':
            setting = settings_models.UserSetting(
                can_modify=(req_user_id == user_id or can_edit_others_standard_settings),
                value=settings.non_req_response_opt_out
            )
        elif setting_name == 'borrower-req-pm-opt-out':
            setting = settings_models.UserSetting(
                can_modify=(req_user_id == user_id or can_edit_others_standard_settings),
                value=settings.borrower_req_pm_opt_out
            )
        elif setting_name == 'ratelimit':
            setting = settings_models.UserSetting(
                can_modify=(
                    can_edit_self_ratelimit_settings
                    if req_user_id == user_id
                    else can_edit_others_ratelimit_settings
                ),
                value={
                    'global_applies': settings.global_ratelimit_applies,
                    'user_specific': settings.user_specific_ratelimit,
                    'max_tokens': (
                        settings.ratelimit_max_tokens
                        or ratelimit_helper.USER_RATELIMITS.max_tokens),
                    'refill_amount': (
                        settings.ratelimit_refill_amount
                        or ratelimit_helper.USER_RATELIMITS.refill_amount
                    ),
                    'refill_time_ms': (
                        settings.ratelimit_refill_time_ms
                        or ratelimit_helper.USER_RATELIMITS.refill_time_ms
                    ),
                    'strict': (
                        settings.ratelimit_strict
                        if settings.ratelimit_strict is not None
                        else ratelimit_helper.USER_RATELIMITS.strict
                    )
                }
            )

        headers['Cache-Control'] = 'no-store'
        return JSONResponse(
            status_code=200,
            content=setting.dict(),
            headers=headers
        )


@router.put(
    '/{req_user_id}/settings/non-req-response-opt-out',
    responses={
        200: {'description': 'Successfully updated.'},
        401: {'description': 'Authorization header missing.'},
        403: {'description': 'Authorization header invalid or insufficient.'},
        404: {'description': 'No such user exists or you cannot see their settings.'}
    }
)
def update_non_req_response_opt_out(
        req_user_id: int,
        new_value: settings_models.UserSettingBoolChangeRequest,
        authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 5
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(itgs, authorization, (
            settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION,
            settings_helper.EDIT_OTHERS_STANDARD_SETTINGS_PERMISSION,
            *ratelimit_helper.RATELIMIT_PERMISSIONS
        ))

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=404, headers=headers)

        can_view_others_settings = settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION in perms
        can_edit_others_standard_settings = (
            settings_helper.EDIT_OTHERS_STANDARD_SETTINGS_PERMISSION in perms)

        if user_id != req_user_id:
            if not can_view_others_settings:
                return Response(status_code=404, headers=headers)

            users = Table('users')
            itgs.read_cursor.execute(
                Query.from_(users).select(1).where(users.id == Parameter('%s')).get_sql(),
                (req_user_id,)
            )

            if itgs.read_cursor.fetchone() is None:
                return Response(status_code=404, headers=headers)

            if not can_edit_others_standard_settings:
                return Response(status_code=403, headers=headers)

        settings_helper.set_settings(
            itgs, req_user_id, non_req_response_opt_out=new_value.new_value)
        return Response(status_code=200, headers=headers)


@router.put(
    '/{req_user_id}/settings/borrower-req-pm-opt-out',
    responses={
        200: {'description': 'Successfully updated.'},
        401: {'description': 'Authorization header missing.'},
        403: {'description': 'Authorization header invalid or insufficient.'},
        404: {'description': 'No such user exists or you cannot see their settings.'}
    }
)
def update_borrower_req_pm_opt_out(
        req_user_id: int,
        new_value: settings_models.UserSettingBoolChangeRequest,
        authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 5
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(itgs, authorization, (
            settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION,
            settings_helper.EDIT_OTHERS_STANDARD_SETTINGS_PERMISSION,
            *ratelimit_helper.RATELIMIT_PERMISSIONS
        ))

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=404, headers=headers)

        can_view_others_settings = settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION in perms
        can_edit_others_standard_settings = (
            settings_helper.EDIT_OTHERS_STANDARD_SETTINGS_PERMISSION in perms)

        if user_id != req_user_id:
            if not can_view_others_settings:
                return Response(status_code=404, headers=headers)

            users = Table('users')
            itgs.read_cursor.execute(
                Query.from_(users).select(1).where(users.id == Parameter('%s')).get_sql(),
                (req_user_id,)
            )

            if itgs.read_cursor.fetchone() is None:
                return Response(status_code=404, headers=headers)

            if not can_edit_others_standard_settings:
                return Response(status_code=403, headers=headers)

        settings_helper.set_settings(
            itgs, req_user_id, borrower_req_pm_opt_out=new_value.new_value)
        return Response(status_code=200, headers=headers)


@router.put(
    '/{req_user_id}/settings/ratelimit',
    responses={
        200: {'description': 'Successfully updated.'},
        401: {'description': 'Authorization header missing.'},
        403: {'description': 'Authorization header invalid or insufficient.'},
        404: {'description': 'No such user exists or you cannot see their settings.'}
    }
)
def update_ratelimit(
        req_user_id: int,
        new_value: settings_models.UserSettingRatelimitChangeRequest,
        authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_cost = 5
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = helper.get_permissions_from_header(itgs, authorization, (
            settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION,
            settings_helper.EDIT_RATELIMIT_SETTINGS_PERMISSION,
            settings_helper.EDIT_OTHERS_RATELIMIT_SETTINGS_PERMISSION,
            *ratelimit_helper.RATELIMIT_PERMISSIONS
        ))

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=404, headers=headers)

        can_view_others_settings = settings_helper.VIEW_OTHERS_SETTINGS_PERMISSION in perms
        can_edit_self_ratelimit_settings = (
            settings_helper.EDIT_RATELIMIT_SETTINGS_PERMISSION in perms)
        can_edit_others_ratelimit_settings = (
            settings_helper.EDIT_OTHERS_RATELIMIT_SETTINGS_PERMISSION in perms)

        if user_id != req_user_id:
            if not can_view_others_settings:
                return Response(status_code=404, headers=headers)

            users = Table('users')
            itgs.read_cursor.execute(
                Query.from_(users).select(1).where(users.id == Parameter('%s')).get_sql(),
                (req_user_id,)
            )

            if itgs.read_cursor.fetchone() is None:
                return Response(status_code=404, headers=headers)

            if not can_edit_others_ratelimit_settings:
                return Response(status_code=403, headers=headers)
        elif not can_edit_self_ratelimit_settings:
            return Response(status_code=403, headers=headers)

        settings_helper.set_settings(
            itgs, req_user_id,
            global_ratelimit_applies=new_value.new_value.global_applies,
            user_specific_ratelimit=new_value.new_value.user_specific,
            ratelimit_max_tokens=new_value.new_value.max_tokens,
            ratelimit_refill_amount=new_value.new_value.refill_amount,
            ratelimit_refill_time_ms=new_value.new_value.refill_time_ms,
            ratelimit_strict=new_value.new_value.strict
        )
        return Response(status_code=200, headers=headers)
