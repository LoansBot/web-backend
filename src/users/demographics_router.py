"""Handles user demographics related endpoints. This includes things like
name and address, and makes use of multiple techniques to reduce the chance
and effectiveness of abuse:

- Strict ratelimits, multiple types (quota and simple)
- hCaptcha required to view any information
- Human logins only, and authtokens older than 1 hours are disallowed
- Detailed records for moderators viewing others informations
- We send a notification to the authorized users reddit account when they
  use demographcis permissions
"""
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from . import demographics_models
from . import demographics_helper
import ratelimit_helper
import security
from lbshared.queries import convert_numbered_args
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from pypika import PostgreSQLQuery as Query, Table, Parameter
from pypika.functions import Now

router = APIRouter()


@router.get(
    '/{req_user_id}/demographics',
    responses={
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization invalid or insufficient.'},
        404: {'description': 'User does not exist or you cannot see their demographics'},
        451: {'description': 'User demographic information has been purged'},
        200: {
            'description': 'User demographic information found',
            'model': demographics_models.UserDemographics
        }
    }
)
def show(req_user_id: int, captcha: str, authorization=Header(None)):
    """View the given users demographic information. This endpoint cannot be
    used on non-official frontends as it's guarded by a captcha.
    """
    if authorization is None:
        return Response(status_code=401)

    attempt_request_cost = 5
    success_request_cost = 95
    with LazyItgs(no_read_only=True) as itgs:
        auth = demographics_helper.get_failure_response_or_user_id_and_perms_for_authorization(
            itgs, authorization, attempt_request_cost, req_user_id,
            None, None, []
        )

        if isinstance(auth, Response):
            return auth

        (user_id, perms) = auth

        headers = {'x-request-cost': str(attempt_request_cost)}
        if not security.verify_captcha(itgs, captcha):
            return Response(status_code=403, headers=headers)

        headers['x-request-cost'] = str(attempt_request_cost + success_request_cost)
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, success_request_cost):
            return Response(status_code=429, headers=headers)

        demos = Table('user_demographics')
        itgs.read_cursor.execute(
            Query.from_(demos)
            .select(
                demos.email,
                demos.name,
                demos.street_address,
                demos.city,
                demos.state,
                demos.zip,
                demos.country,
                demos.deleted
            )
            .where(
                demos.user_id == Parameter('%s')
            )
            .get_sql(),
            (req_user_id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            (
                email, name, street_address, city, state, zip_, country, deleted
            ) = (None, None, None, None, None, None, None, False)
        else:
            (
                email, name, street_address, city, state, zip_, country, deleted
            ) = row

        if deleted:
            return Response(status_code=451, headers=headers)

        demo_views = Table('user_demographic_views')
        itgs.write_cursor.execute(
            Query.into(demo_views).columns(
                demo_views.user_id,
                demo_views.admin_user_id,
                demo_views.lookup_id
            ).insert(
                *[Parameter('%s') for _ in range(3)]
            )
            .get_sql(),
            (req_user_id, user_id, None)
        )
        itgs.write_conn.commit()

        headers['Cache-Control'] = 'no-store'
        headers['Pragma'] = 'no-cache'
        return JSONResponse(
            status_code=200,
            content=demographics_models.UserDemographics(
                user_id=req_user_id,
                email=email, name=name, street_address=street_address,
                city=city, state=state, zip=zip_, country=country
            ).dict(),
            headers=headers
        )


@router.get(
    '/demographics',
    responses={
        400: {'description': 'No filters selected'},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization invalid or insufficient'},
        200: {
            'description': 'Lookup successful',
            'model': demographics_models.UserDemographicsLookup
        }
    }
)
def lookup(
        reason: str, captcha: str, limit: int = None, next_id: int = None,
        email: str = None, name: str = None, street_address: str = None,
        city: str = None, state: str = None, zip: str = None,
        country: str = None, authorization=Header(None)):
    """Searches for users matching the given description. This operation is
    aggressively logged and may result in alerting multiple people. At least
    one filter must be specified; filters are compared using the ILIKE
    operator.
    """
    if authorization is None:
        return Response(status_code=401)

    if limit is None:
        limit = 5
    elif limit <= 0:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['limit'],
                    'msg': 'must be positive',
                    'type': 'range_error'
                }
            }
        )
    elif limit > 10:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['limit'],
                    'msg': 'must be <=10',
                    'type': 'range_error'
                }
            }
        )

    if len(reason) < 3:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['reason'],
                    'msg': 'must be >=3 chars',
                    'type': 'range_error'
                }
            }
        )

    if sum([
            1 if (s is not None and len(s) > 1) else 0
            for s in [email, name, street_address, city, state, zip, country]]) == 0:
        return Response(status_code=400)

    attempt_request_cost = 5
    success_request_cost = 95 + 25 * limit
    with LazyItgs(no_read_only=True) as itgs:
        auth = demographics_helper.get_failure_response_or_user_id_and_perms_for_authorization(
            itgs, authorization, attempt_request_cost, None,
            None, demographics_helper.LOOKUP_DEMOGRAPHICS_PERMISSION, []
        )

        if isinstance(auth, Response):
            return auth

        (user_id, perms) = auth

        headers = {'x-request-cost': str(attempt_request_cost)}
        if not security.verify_captcha(itgs, captcha):
            return Response(status_code=403, headers=headers)

        headers['x-request-cost'] = str(attempt_request_cost + success_request_cost)
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, success_request_cost):
            return Response(status_code=429, headers=headers)

        demos = Table('user_demographics')
        query = (
            Query.from_(demos)
            .select(
                demos.id,
                demos.user_id,
                demos.email,
                demos.name,
                demos.street_address,
                demos.city,
                demos.state,
                demos.zip,
                demos.country
            )
            .where(demos.deleted == Parameter('$1'))
            .orderby(demos.id)
            .limit(Parameter('$2'))
        )
        args = [False, limit + 1]

        if next_id is not None:
            query = query.where(demos.id > Parameter(f'${len(args) + 1}'))
            args.append(next_id)

        search_fields = [
            (email, demos.email),
            (name, demos.name),
            (street_address, demos.street_address),
            (city, demos.city),
            (state, demos.state),
            (zip, demos.zip),
            (country, demos.country)
        ]

        for (query_param, field) in search_fields:
            if query_param is not None:
                query = query.where(field.ilike(Parameter(f'${len(args) + 1}')))
                args.append(query_param)

        itgs.read_cursor.execute(*convert_numbered_args(query.get_sql(), args))

        result = []
        have_more = False
        last_id = None
        row = itgs.read_cursor.fetchone()
        while row is not None:
            (
                row_id,
                row_user_id,
                row_email,
                row_name,
                row_street_address,
                row_city,
                row_state,
                row_zip,
                row_country
            ) = row
            if len(result) >= limit:
                have_more = True
                row = itgs.read_cursor.fetchone()
                continue

            last_id = row_id
            result.append(
                demographics_models.UserDemographics(
                    user_id=row_user_id,
                    email=row_email, name=row_name, street_address=row_street_address,
                    city=row_city, state=row_state, zip=row_zip, country=row_country
                )
            )
            row = itgs.read_cursor.fetchone()

        lookups = Table('user_demographic_lookups')
        itgs.write_cursor.execute(
            Query.into(lookups).columns(
                lookups.admin_user_id,
                lookups.email,
                lookups.name,
                lookups.street_address,
                lookups.city,
                lookups.state,
                lookups.zip,
                lookups.country,
                lookups.reason
            ).insert(*[Parameter('%s') for _ in range(9)])
            .returning(lookups.id)
            .get_sql(),
            (
                user_id, email, name, street_address, city, state,
                zip, country, reason
            )
        )
        (lookup_id,) = itgs.write_cursor.fetchone()

        views = Table('user_demographic_views')
        itgs.write_cursor.execute(
            Query.into(views).columns(
                views.user_id,
                views.admin_user_id,
                views.lookup_id
            ).insert(
                *[tuple(Parameter('%s') for _ in range(3)) for _ in result]
            )
            .get_sql(),
            tuple(
                (
                    demo.user_id,
                    user_id,
                    lookup_id
                )
                for demo in result
            )
        )
        itgs.write_conn.commit()

        headers['Cache-Control'] = 'no-store'
        headers['Pragma'] = 'no-cache'
        return JSONResponse(
            status_code=200,
            content=demographics_models.UserDemographicsLookup(
                hits=result,
                next_id=(last_id if have_more else None)
            )
        )


@router.delete(
    '/{req_user_id}/demographics',
    responses={
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization invalid or insufficient'},
        404: {'description': 'Requested user does not exist'},
        451: {'description': 'Info already purged'},
        200: {'description': 'User demographic information purged'}
    }
)
def destroy(req_user_id: int, captcha: str, authorization=Header(None)):
    """Purges our accessible stores of the given users demographics. This
    operation is not reversible and will destroy our history of who knew what
    about this user. We will not allow the user to submit further information
    once they do this.

    This should only be done in extreme circumstances, or by the users request.
    We would much prefer users update their demographic information to all
    blanks, which will _also_ prevent anyone from using the website to access
    the information, but preserves the history in the database.

    If the users information is already purged this returns 451. If the
    user does not have demographic information, we create them an all blank
    record and mark it as purged to ensure they cannot submit new information,
    for consistency.
    """
    if authorization is None:
        return Response(status_code=401)

    attempt_request_cost = 5
    success_request_cost = 95
    with LazyItgs(no_read_only=True) as itgs:
        auth = demographics_helper.get_failure_response_or_user_id_and_perms_for_authorization(
            itgs, authorization, attempt_request_cost, req_user_id,
            demographics_helper.PURGE_SELF_DEMOGRAPHICS_PERMISSION,
            demographics_helper.PURGE_OTHERS_DEMOGRAPHICS_PERMISSION,
            []
        )

        if isinstance(auth, Response):
            return auth

        (user_id, perms) = auth

        headers = {'x-request-cost': str(attempt_request_cost)}
        if not security.verify_captcha(itgs, captcha):
            return Response(status_code=403, headers=headers)

        headers['x-request-cost'] = str(attempt_request_cost + success_request_cost)
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, success_request_cost):
            return Response(status_code=429, headers=headers)

        demos = Table('user_demographics')
        itgs.read_cursor.execute(
            Query.from_(demos).select(demos.id, demos.deleted)
            .where(demos.user_id == Parameter('%s'))
            .get_sql(),
            (req_user_id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is not None and row[1]:
            return Response(status_code=451, headers=headers)

        if row is None:
            users = Table('users')
            itgs.read_cursor.execute(
                Query.from_(users).select(1)
                .where(users.id == Parameter('%s'))
                .limit(1)
                .get_sql(),
                (req_user_id,)
            )
            if itgs.read_cursor.fetchone() is None:
                return Response(status_code=404, headers=headers)

            itgs.write_cursor.execute(
                Query.into(demos).columns(
                    demos.user_id,
                    demos.deleted
                ).insert(*[Parameter('%s') for _ in range(2)])
                .get_sql(),
                (req_user_id, True)
            )
            itgs.write_conn.commit()
            return Response(status_code=200, headers=headers)

        demo_id = row[0]

        demo_history = Table('user_demographic_history')
        itgs.write_cursor.execute(
            Query.update(demo_history)
            .set(demo_history.old_email, None)
            .set(demo_history.new_email, None)
            .set(demo_history.old_name, None)
            .set(demo_history.new_name, None)
            .set(demo_history.old_street_address, None)
            .set(demo_history.new_street_address, None)
            .set(demo_history.old_city, None)
            .set(demo_history.new_city, None)
            .set(demo_history.old_state, None)
            .set(demo_history.new_state, None)
            .set(demo_history.old_zip, None)
            .set(demo_history.new_zip, None)
            .set(demo_history.old_country, None)
            .set(demo_history.new_country, None)
            .set(demo_history.purged_at, Now())
            .where(
                demo_history.user_demographic_id == Parameter('%s')
            )
            .get_sql(),
            (demo_id,)
        )
        itgs.write_cursor.execute(
            Query.into(demo_history).columns(
                demo_history.user_demographic_id,
                demo_history.changed_by_user_id,
                demo_history.old_deleted,
                demo_history.new_deleted,
                demo_history.purged_at
            ).insert(
                *[Parameter('%s') for _ in range(4)],
                Now()
            )
            .get_sql(),
            (
                demo_id,
                user_id,
                False,
                True
            )
        )
        itgs.write_cursor.execute(
            Query.update(demos)
            .set(demos.email, None)
            .set(demos.name, None)
            .set(demos.street_address, None)
            .set(demos.city, None)
            .set(demos.state, None)
            .set(demos.zip, None)
            .set(demos.country, None)
            .set(demos.deleted, True)
            .where(demos.id == Parameter('%s'))
            .get_sql(),
            (demo_id,)
        )
        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.put(
    '/{req_user_id}/demographics',
    responses={
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization invalid or insufficient'},
        404: {'description': 'No such user exists'},
        451: {'description': 'Info already purged'},
        200: {'description': 'Update was successful'}
    }
)
def update(
        req_user_id: int, captcha: str,
        args: demographics_models.UserDemographics,
        authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    if args.user_id != req_user_id:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['body', 'user_id'],
                    'msg': 'must match path parameter req_user_id',
                    'type': 'mismatch_error'
                }
            }
        )

    attempt_request_cost = 5
    success_request_cost = 95
    with LazyItgs(no_read_only=True) as itgs:
        auth = demographics_helper.get_failure_response_or_user_id_and_perms_for_authorization(
            itgs, authorization, attempt_request_cost, req_user_id,
            demographics_helper.EDIT_SELF_DEMOGRAPHICS_PERMISSION,
            demographics_helper.EDIT_OTHERS_DEMOGRAPHICS_PERMISSION,
            []
        )

        if isinstance(auth, Response):
            return auth

        (user_id, perms) = auth

        headers = {'x-request-cost': str(attempt_request_cost)}
        if not security.verify_captcha(itgs, captcha):
            return Response(status_code=403, headers=headers)

        headers['x-request-cost'] = str(attempt_request_cost + success_request_cost)
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, success_request_cost):
            return Response(status_code=429, headers=headers)

        demos = Table('user_demographics')
        itgs.read_cursor.execute(
            Query.from_(demos).select(demos.id, demos.deleted)
            .where(demos.user_id == Parameter('%s'))
            .limit(1)
            .get_sql(),
            (req_user_id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            users = Table('users')
            itgs.read_cursor.execute(
                Query.from_(users).select(1)
                .where(users.id == Parameter('%s'))
                .limit(1)
                .get_sql(),
                (req_user_id,)
            )
            if itgs.read_cursor.fetchone() is None:
                return Response(status_code=404, headers=headers)

            itgs.write_cursor.execute(
                Query.into(demos).columns(
                    demos.user_id
                ).insert(Parameter('%s'))
                .returning(demos.id)
                .get_sql(),
                (req_user_id,)
            )
            row = itgs.write_cursor.fetchone()

        demo_id = row[0]
        demo_history = Table('user_demographic_history')
        itgs.write_cursor.execute(
            Query.into(demo_history).columns(
                demo_history.user_demographic_id,
                demo_history.changed_by_user_id,
                demo_history.old_email,
                demo_history.new_email,
                demo_history.old_name,
                demo_history.new_name,
                demo_history.old_street_address,
                demo_history.new_street_address,
                demo_history.old_city,
                demo_history.new_city,
                demo_history.old_state,
                demo_history.new_state,
                demo_history.old_zip,
                demo_history.new_zip,
                demo_history.old_country,
                demo_history.new_country,
                demo_history.old_deleted,
                demo_history.new_deleted,
            ).from_(demos).select(
                demos.id,
                Parameter('%s'),
                demos.email,
                Parameter('%s'),
                demos.name,
                Parameter('%s'),
                demos.street_address,
                Parameter('%s'),
                demos.city,
                Parameter('%s'),
                demos.state,
                Parameter('%s'),
                demos.zip,
                Parameter('%s'),
                demos.country,
                Parameter('%s'),
                demos.deleted,  # This should be false (we just checked), but
                demos.deleted   # we store the value here just in case
            ).where(demos.id == Parameter('%s'))
            .get_sql(),
            (
                user_id,
                args.email,
                args.name,
                args.street_address,
                args.city,
                args.state,
                args.zip,
                args.country,
                demo_id
            )
        )
        itgs.write_cursor.execute(
            Query.update(demos)
            .set(demos.email, Parameter('%s'))
            .set(demos.name, Parameter('%s'))
            .set(demos.street_address, Parameter('%s'))
            .set(demos.city, Parameter('%s'))
            .set(demos.state, Parameter('%s'))
            .set(demos.zip, Parameter('%s'))
            .set(demos.country, Parameter('%s'))
            .where(demos.id == Parameter('%s'))
            .get_sql(),
            (
                args.email,
                args.name,
                args.street_address,
                args.city,
                args.state,
                args.zip,
                args.country,
                demo_id
            )
        )
        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)
