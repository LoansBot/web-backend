"""Contains the endpoints for collecting what endpoints exist. The process of
documenting endpoints for this purpose is not automated, however it's made
less painful by having some form of an interface.
"""
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from lbshared.queries import convert_numbered_args
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from pypika.functions import Now
from psycopg2 import IntegrityError
from . import models
from . import helper
import users.helper
import ratelimit_helper
import math
from datetime import date

router = APIRouter()


@router.get(
    '/?',
    responses={
        '200': {'description': 'Success', 'model': models.EndpointsIndexResponse}
    }
)
def index(before_slug: str = None, after_slug: str = None, order='asc',
          limit: int = 5, authorization=Header(None)):
    """Fetch all of the endpoints in a paginated manner, where you can choose
    between ascending and descending alphabetical order of the slugs.

    Arguments:
    - `before_slug (str, None)`: If specified we only include endpoints whose
      slug is alphabetically below the given slug.
    - `after_slug (str, None)`:O If specified we only include endpoints whose
      slug is alphabetically after the given slug.
    - `order (str)`: Either 'asc' or 'desc', dictates if returned values are
      ordered by slugs alphabetically in ascending or descending order
      respsectively.
    - `limit (int)`: The maximum number of results to return. Affects the
      amount of ratelimit tokens consumed. Max of 20 for unauthenticated
      requests.
    - `authorization (str, None)`: If specified this should be the bearer token
      generated at login.
    """
    if order not in ('asc', 'desc'):
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['order'],
                    'msg': 'Must be one of \'asc\', \'desc\'',
                    'type': 'value_error'
                }
            }
        )

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

    attempt_request_cost = 1
    headers = {'x-request-cost': str(attempt_request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, attempt_request_cost):
            return Response(status_code=429, headers=headers)

        real_limit = min(limit, 20) if user_id is None else limit
        request_cost = real_limit * max(1, math.ceil(math.log(real_limit))) - attempt_request_cost
        if request_cost > 0:
            headers['x-request-cost'] = str(request_cost + attempt_request_cost)
            if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
                return Response(status_code=429, headers=headers)

        endpoints = Table('endpoints')
        query = (
            Query.from_(endpoints)
            .select(endpoints.slug)
        )
        num_args = []

        def next_arg_param(arg):
            num_args.append(arg)
            return f'${len(num_args)}'

        if before_slug is not None:
            query = query.where(endpoints.slug < Parameter(next_arg_param(before_slug)))

        if after_slug is not None:
            query = query.where(endpoints.slug > Parameter(next_arg_param(after_slug)))

        query = query.orderby(endpoints.slug, order=getattr(Order, order))

        if limit > 0:
            query = query.limit(Parameter(next_arg_param(real_limit + 1)))

        itgs.read_cursor.execute(*convert_numbered_args(query.get_sql(), num_args))

        result = []
        has_more = False

        row = itgs.read_cursor.fetchone()
        while row is not None:
            if len(result) >= real_limit:
                has_more = True
                row = itgs.read_cursor.fetchone()
                continue

            (row_slug,) = row
            result.append(row_slug)
            row = itgs.read_cursor.fetchone()

        new_before_slug = None
        new_after_slug = None
        if has_more:
            if order == 'desc':
                new_before_slug = result[-1]
            else:
                new_after_slug = result[-1]

        headers['Cache-Control'] = (
            'public, max-age=60, stale-while-revalidate=540, stale-if-error=86400'
        )
        return JSONResponse(
            status_code=200,
            content=models.EndpointsIndexResponse(
                endpoint_slugs=result,
                after_slug=new_after_slug,
                before_slug=new_before_slug
            ).dict(),
            headers=headers
        )


@router.get(
    '/suggest',
    responses={
        '200': {'description': 'Success', 'model': models.EndpointsSuggestResponse}
    }
)
def suggest(q: str = '', limit: int = 3, authorization=Header(None)):
    """Searches for an endpoint slug using the given query string.

    Arguments:
    - `q (str)`: The query string to search on
    - `limit (int)`: The maximum number of results to return. This affects the
      ratelimit cost for this endpoint. Unauthenticated users can specify at
      most 15.
    """
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

    attempt_request_cost = 1
    headers = {'x-request-cost': str(attempt_request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, attempt_request_cost):
            return Response(status_code=429, headers=headers)

        real_limit = min(limit, 15) if user_id is None else limit
        request_cost = real_limit * max(1, math.ceil(math.log(real_limit))) - attempt_request_cost
        if request_cost > 0:
            headers['x-request-cost'] = str(request_cost + attempt_request_cost)
            if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
                return Response(status_code=429, headers=headers)

        endpoints = Table('endpoints')
        itgs.read_cursor.execute(
            Query.from_(endpoints)
            .select(endpoints.slug)
            .where(endpoints.slug.ilike(Parameter('%s')))
            .limit(real_limit)
            .get_sql(),
            (f'%{q}%',)
        )

        result = itgs.read_cursor.fetchall()
        result = [row[0] for row in result]

        if len(q) <= 2:
            headers['Cache-Control'] = 'public, max-age=600'

        return JSONResponse(
            status_code=200,
            content=models.EndpointsSuggestResponse(suggestions=result).dict(),
            headers=headers
        )


@router.get(
    '/{slug}',
    responses={
        '200': {'description': 'Success', 'model': models.EndpointShowResponse},
        '404': {'description': 'No endpoint with that slug exists'}
    }
)
def show(slug: str, authorization=Header(None)):
    """Fetch the description for the endpoint with the given slug. This is
    aggressively cached; the front-end should include a way to bust the cache
    (e.g. a refresh button).

    Arguments:
    - `slug (str)`: The endpoint slug to fetch
    - `authorization (str, None)`: If specified this should be the bearer
      token generated at login.
    """
    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        endpoints = Table('endpoints')
        itgs.read_cursor.execute(
            Query.from_(endpoints)
            .select(
                endpoints.id,
                endpoints.path,
                endpoints.verb,
                endpoints.description_markdown,
                endpoints.deprecation_reason_markdown,
                endpoints.deprecated_on,
                endpoints.sunsets_on,
                endpoints.created_at,
                endpoints.updated_at
            )
            .where(endpoints.slug == Parameter('%s'))
            .get_sql(),
            (slug,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        (
            endpoint_id,
            endpoint_path,
            endpoint_verb,
            endpoint_description_markdown,
            endpoint_deprecation_reason_markdown,
            endpoint_deprecated_on,
            endpoint_sunsets_on,
            endpoint_created_at,
            endpoint_updated_at
        ) = row

        endpoint_params = Table('endpoint_params')
        itgs.read_cursor.execute(
            Query.from_(endpoint_params)
            .select(
                endpoint_params.location,
                endpoint_params.path,
                endpoint_params.name,
                endpoint_params.var_type,
                endpoint_params.added_date
            )
            .where(endpoint_params.endpoint_id == Parameter('%s'))
            .get_sql(),
            (endpoint_id,)
        )

        params_result = []
        row = itgs.read_cursor.fetchone()
        while row is not None:
            (
                param_location,
                param_path,
                param_name,
                param_var_type,
                param_added_date
            ) = row

            params_result.append(
                models.EndpointParamShowResponse(
                    location=param_location,
                    path=param_path.split('.'),
                    name=param_name,
                    var_type=param_var_type,
                    added_date=param_added_date.isoformat()
                )
            )
            row = itgs.read_cursor.fetchone()

        endpoint_alts = Table('endpoint_alternatives')
        itgs.read_cursor.execute(
            Query.from_(endpoint_alts)
            .join(endpoints).on(endpoints.id == endpoint_alts.new_endpoint_id)
            .select(endpoints.slug)
            .where(endpoint_alts.old_endpoint_id == Parameter('%s'))
            .get_sql(),
            (endpoint_id,)
        )
        alts_result = [row[0] for row in itgs.read_cursor.fetchall()]

        headers['Cache-Control'] = (
            'public, max-age=86400, stale-while-revalidate=86400, stale-if-error=604800'
        )
        return JSONResponse(
            status_code=200,
            content=models.EndpointShowResponse(
                slug=slug,
                path=endpoint_path,
                verb=endpoint_verb,
                description_markdown=endpoint_description_markdown,
                params=params_result,
                alternatives=alts_result,
                deprecation_reason_markdown=endpoint_deprecation_reason_markdown,
                deprecated_on=endpoint_deprecated_on,
                sunsets_on=endpoint_sunsets_on,
                created_at=endpoint_created_at.timestamp(),
                updated_at=endpoint_updated_at.timestamp()
            ).dict(),
            headers=headers
        )


@router.get(
    '/{endpoint_slug}/params/{location}',
    responses={
        '200': {'description': 'Success', 'model': models.EndpointParamShowResponse},
        '404': {
            'description': (
                'No parameter at that location with that path and name '
                'on that endpoint exists'
            )
        }
    }
)
def show_param(endpoint_slug: str, location: str, path: str = '', name: str = '',
               authorization=Header(None)):
    """Get details on the given parameter for the given endpoint. This is the
    main way to fetch the actual description of the parameter; everything else
    about it is returned from the endpoint show response.

    - `endpoint_slug (str)`: The slug for the endpoint that the parameter is
      for.
    - `location (str)`: The location where the parameter is passed within the
      endpoint. This acts as an enum and is one of "query", "header", "body".
    - `path (str)`: The path to the endpoint within the location but before
      the name. For query and header parameters this is a blank string.
      For a body parameter that's nested this is a dot-separated list that
      takes you to the dictionary storing the variable (as if by javascript).
      For example the body `{"foo": { "bar": { "baz": 3 }}}` has a parameter
      with location `body`, path `foo.bar`, and name `baz`.
    - `name (str)`: The name for this parameter. Case-sensitive; for headers
      this should be all lowercase.
    - `authorization (str, None)`: If provided this should be the bearer token
      generated at login.
    """
    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}

    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, header=headers)

        endpoint_params = Table('endpoint_params')
        endpoints = Table('endpoints')
        itgs.read_cursor.execute(
            Query.from_(endpoint_params)
            .join(endpoints).on(endpoint_params.endpoint_id == endpoints.id)
            .select(
                endpoint_params.var_type,
                endpoint_params.description_markdown,
                endpoint_params.added_date
            )
            .where(endpoints.slug == Parameter('%s'))
            .where(endpoint_params.location == Parameter('%s'))
            .where(endpoint_params.path == Parameter('%s'))
            .where(endpoint_params.name == Parameter('%s'))
            .get_sql(),
            (
                endpoint_slug,
                location,
                path,
                name
            )
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        (
            param_var_type,
            param_description_markdown,
            param_added_date
        ) = row

        headers['Cache-Control'] = (
            'public, max-age=86400, stale-while-revalidate=86400, stale-if-error=604800'
        )
        return JSONResponse(
            status_code=200,
            content=models.EndpointParamShowResponse(
                location=location,
                path=path.split('.'),
                name=name,
                var_type=param_var_type,
                description_markdown=param_description_markdown,
                added_date=param_added_date.isoformat()
            ).dict(),
            headers=headers
        )


@router.get(
    '/migrate/{from_endpoint_slug}/{to_endpoint_slug}',
    responses={
        '200': {'description': 'Success', 'model': models.EndpointAlternativeShowResponse},
        '404': {
            'description': (
                'We do not have any official recommendation for how to '
                'go from from_endpoint_slug to to_endpoint_slug'
            )
        }
    }
)
def show_alternative(from_endpoint_slug: str, to_endpoint_slug: str,
                     authorization=Header(None)):
    """Provides details on how to migrate undirectionally between the given
    endpoints. The existence of an alternative can be discovered through the
    endpoint show endpoint.

    Arguments:
    - `from_endpoint_slug (str)`: The endpoint slug you want to transfer away
      from.
    - `to_endpoint_slug (str)`: The endpoint slug you want to transfer to.
    - `authorization (str, None)`: If provided, this should be the bearer token
      generated at login.
    """
    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        endpoints = Table('endpoints')
        old_endpoints = endpoints.as_('old_endpoints')
        new_endpoints = endpoints.as_('new_endpoints')
        endpoint_alts = Table('endpoint_alternatives')
        itgs.read_cursor.execute(
            Query.from_(endpoint_alts)
            .join(old_endpoints).on(old_endpoints.id == endpoint_alts.old_endpoint_id)
            .join(new_endpoints).on(new_endpoints.id == endpoint_alts.new_endpoint_id)
            .select(
                endpoint_alts.explanation_markdown,
                endpoint_alts.created_at,
                endpoint_alts.updated_at
            )
            .where(old_endpoints.slug == Parameter('%s'))
            .where(new_endpoints.slug == Parameter('%s'))
            .get_sql(),
            (
                from_endpoint_slug,
                to_endpoint_slug
            )
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        (
            alt_explanation_markdown,
            alt_created_at,
            alt_updated_at
        ) = row
        headers['Cache-Control'] = (
            'public, max-age=86400, stale-while-revalidate=86400, stale-if-error=604800'
        )
        return JSONResponse(
            status_code=200,
            content=models.EndpointAlternativeShowResponse(
                explanation_markdown=alt_explanation_markdown,
                created_at=alt_created_at.timestamp(),
                updated_at=alt_updated_at.timestamp()
            ).dict(),
            headers=headers
        )


@router.put(
    '/{slug}/?',
    responses={
        '200': {'description': 'Success'},
        '401': {'description': 'Authorization not provided'},
        '403': {'description': 'Authorization invalid or insufficient'},
        '503': {'description': 'There was a integrity conflict, try again'}
    }
)
def put_endpoint(slug: str, endpoint: models.EndpointPutRequest, authorization=Header(None)):
    """Create or update the endpoint with the given slug. Requires the
    `helper.CREATE_ENDPOINT_PERMISSION` permission to create a new endpoint,
    requires the `helper.UPDATE_ENDPOINT_PERMISSION` to update an existing
    endpoint.

    Arguments:
    - `endpoint (models.EndpointPutRequest)`: What the new value for the
      endpoint should be
    - `authorization (str, None)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.CREATE_ENDPOINT_PERMISSION,
                helper.UPDATE_ENDPOINT_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if not user_id:
            return Response(status_code=403, headers=headers)

        has_create_perm = helper.CREATE_ENDPOINT_PERMISSION in perms
        has_update_perm = helper.UPDATE_ENDPOINT_PERMISSION in perms

        if not has_create_perm and not has_update_perm:
            return Response(status_code=403, headers=headers)

        endpoints = Table('endpoints')
        itgs.read_cursor.execute(
            Query.from_(endpoints)
            .select(
                endpoints.path,
                endpoints.verb,
                endpoints.description_markdown,
                endpoints.deprecation_reason_markdown,
                endpoints.deprecated_on,
                endpoints.sunsets_on,
                endpoints.updated_at
            )
            .where(endpoints.slug == Parameter('%s'))
            .get_sql(),
            (slug,)
        )
        row = itgs.read_cursor.fetchone()

        if row is None:
            if not has_create_perm:
                return Response(status_code=403, headers=headers)
            (
                old_endpoint_path,
                old_endpoint_verb,
                old_description_markdown,
                old_deprecation_reason_markdown,
                old_deprecated_on,
                old_sunsets_on,
                old_updated_at,
                old_in_endpoints
            ) = (None, None, None, None, None, None, None, False)
        else:
            if not has_update_perm:
                return Response(status_code=403, headers=headers)
            (
                old_endpoint_path,
                old_endpoint_verb,
                old_description_markdown,
                old_deprecation_reason_markdown,
                old_deprecated_on,
                old_sunsets_on,
                old_updated_at
            ) = row
            old_in_endpoints = True

        endpoint_history = Table('endpoint_history')
        itgs.write_cursor.execute(
            Query.into(endpoint_history)
            .columns(
                endpoint_history.user_id,
                endpoint_history.slug,
                endpoint_history.old_path,
                endpoint_history.new_path,
                endpoint_history.old_verb,
                endpoint_history.new_verb,
                endpoint_history.old_description_markdown,
                endpoint_history.new_description_markdown,
                endpoint_history.old_deprecation_reason_markdown,
                endpoint_history.new_deprecation_reason_markdown,
                endpoint_history.old_deprecated_on,
                endpoint_history.new_deprecated_on,
                endpoint_history.old_sunsets_on,
                endpoint_history.new_sunsets_on,
                endpoint_history.old_in_endpoints,
                endpoint_history.new_in_endpoints
            ).insert(*[Parameter('%s') for _ in range(14)])
            .get_sql(),
            (
                user_id,
                slug,
                old_endpoint_path,
                endpoint.path,
                old_endpoint_verb,
                endpoint.verb,
                old_description_markdown,
                endpoint.description_markdown,
                old_deprecation_reason_markdown,
                endpoint.description_markdown,
                old_deprecated_on,
                (
                    date.fromisoformat(endpoint.deprecated_on)
                    if endpoint.deprecated_on is not None
                    else None
                ),
                old_sunsets_on,
                (
                    date.fromisoformat(endpoint.sunsets_on)
                    if endpoint.sunsets_on is not None
                    else None
                ),
                old_in_endpoints,
                True
            )
        )

        if old_in_endpoints:
            itgs.write_cursor.execute(
                Query.update(endpoints)
                .set(
                    endpoints.path,
                    Parameter('%s')
                )
                .set(
                    endpoints.verb,
                    Parameter('%s')
                )
                .set(
                    endpoints.description_markdown,
                    Parameter('%s')
                )
                .set(
                    endpoints.deprecation_reason_markdown,
                    Parameter('%s')
                )
                .set(
                    endpoints.deprecated_on,
                    Parameter('%s')
                )
                .set(
                    endpoints.sunsets_on,
                    Parameter('%s')
                )
                .set(
                    endpoints.updated_at,
                    Now()
                )
                .where(endpoints.slug == Parameter('%s'))
                .where(endpoints.updated_at == Parameter('%s'))
                .returning(endpoints.id)
                .get_sql(),
                (
                    endpoint.path,
                    endpoint.verb,
                    endpoint.description_markdown,
                    endpoint.deprecation_reason_markdown,
                    (
                        date.fromisoformat(endpoint.deprecated_on)
                        if endpoint.deprecated_on is not None
                        else None
                    ),
                    (
                        date.fromisoformat(endpoint.sunsets_on)
                        if endpoint.sunsets_on is not None
                        else None
                    ),
                    slug,
                    old_updated_at
                )
            )
            if itgs.write_cursor.fetchone() is None:
                itgs.write_conn.rollback()
                return Response(status_code=503, headers=headers)
        else:
            try:
                itgs.write_cursor.execute(
                    Query.into(endpoints)
                    .columns(
                        endpoints.slug,
                        endpoints.path,
                        endpoints.verb,
                        endpoints.description_markdown,
                        endpoints.deprecation_reason_markdown,
                        endpoints.deprecated_on,
                        endpoints.sunsets_on
                    )
                    .insert(*[Parameter('%s') for _ in range(7)])
                    .get_sql(),
                    (
                        slug,
                        endpoint.path,
                        endpoint.verb,
                        endpoint.description_markdown,
                        endpoint.deprecation_reason_markdown,
                        (
                            date.fromisoformat(endpoint.deprecated_on)
                            if endpoint.deprecated_on is not None
                            else None
                        ),
                        (
                            date.fromisoformat(endpoint.sunsets_on)
                            if endpoint.sunsets_on is not None
                            else None
                        )
                    )
                )
            except IntegrityError:
                itgs.write_conn.rollback()
                return Response(status_code=503, headers=headers)

        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.put(
    '/migrate/{from_endpoint_slug}/{to_endpoint_slug}',
    responses={
        '200': {'description': 'Success'},
        '401': {'description': 'Authorization not provided'},
        '403': {'description': 'Authorization invalid or insufficient'},
        '404': {'description': 'One of the endpoints does not exist'},
        '503': {'description': 'Integrity error, try again'}
    }
)
def put_endpoint_alternative(
        endpoint_alternative: models.EndpointAlternativePutRequest,
        from_endpoint_slug: str, to_endpoint_slug: str,
        authorization=Header(None)):
    """Create or update the description for an endpoint alternative. This
    requires the `helper.UPDATE_ENDPOINT_PERMISSION` permission regardless
    of it's a create or an update.

    Arguments:
    - `endpoint_alternative (models.EndpointAlternativePutRequest)`: The new
      description for how to migrate from endpoint `from_endpoint_slug` to
      to endpoint `to_endpoint_slug`
    - `from_endpoint_slug (str)`: The slug of the endpoint this explains how to
      migrate from.
    - `to_endpoint_slug (str)`: The slug of the endpoint this explains how to
      migrate to.
    - `authorization (str, None)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.UPDATE_ENDPOINT_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        has_edit_perm = helper.UPDATE_ENDPOINT_PERMISSION in perms

        if not has_edit_perm:
            return Response(status_code=403, headers=headers)

        endpoints = Table('endpoints')
        itgs.read_cursor.execute(
            Query.from_(endpoints)
            .select(endpoints.slug, endpoints.id)
            .where(endpoints.slug.isin([Parameter('%s') for _ in range(2)]))
            .get_sql(),
            (
                from_endpoint_slug,
                to_endpoint_slug
            )
        )

        slug_to_id = dict(itgs.read_cursor.fetchall())
        if len(slug_to_id) != 2:
            return Response(status_code=404, headers=headers)

        endpoint_alternatives = Table('endpoint_alternatives')
        itgs.read_cursor.execute(
            Query.from_(endpoint_alternatives)
            .select(
                endpoint_alternatives.explanation_markdown,
                endpoint_alternatives.updated_at
            )
            .where(endpoint_alternatives.old_endpoint_id == Parameter('%s'))
            .where(endpoint_alternatives.new_endpoint_id == Parameter('%s'))
            .get_sql(),
            (slug_to_id[from_endpoint_slug], slug_to_id[to_endpoint_slug])
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            (
                old_explanation_markdown,
                old_updated_at,
                old_in_endpoint_alternatives
            ) = (None, None, False)
        else:
            (
                old_explanation_markdown,
                old_updated_at
            ) = row
            old_in_endpoint_alternatives = True

        ep_alt_history = Table('endpoint_alternative_history')
        itgs.write_cursor.execute(
            Query.into(ep_alt_history)
            .columns(
                ep_alt_history.user_id,
                ep_alt_history.old_endpoint_slug,
                ep_alt_history.new_endpoint_slug,
                ep_alt_history.old_explanation_markdown,
                ep_alt_history.new_explanation_markdown,
                ep_alt_history.old_in_endpoint_alternatives,
                ep_alt_history.new_in_endpoint_alternatives
            )
            .insert(*[Parameter('%s') for _ in range(7)])
            .get_sql(),
            (
                user_id,
                from_endpoint_slug,
                to_endpoint_slug,
                old_explanation_markdown,
                endpoint_alternative.explanation_markdown,
                old_in_endpoint_alternatives,
                True
            )
        )

        if old_in_endpoint_alternatives:
            itgs.write_cursor.execute(
                Query.update(endpoint_alternatives)
                .set(
                    endpoint_alternatives.explanation_markdown,
                    Parameter('%s')
                )
                .set(
                    endpoint_alternatives.updated_at,
                    Now()
                )
                .where(endpoint_alternatives.old_endpoint_id == Parameter('%s'))
                .where(endpoint_alternatives.new_endpoint_id == Parameter('%s'))
                .where(endpoint_alternatives.updated_at == Parameter('%s'))
                .returning(endpoint_alternatives.id)
                .get_sql(),
                (
                    endpoint_alternative.explanation_markdown,
                    slug_to_id[from_endpoint_slug],
                    slug_to_id[to_endpoint_slug],
                    old_updated_at
                )
            )
            if itgs.write_cursor.fetchone() is None:
                return Response(status_code=503, headers=headers)
        else:
            try:
                itgs.write_cursor.execute(
                    Query.into(endpoint_alternatives)
                    .columns(
                        endpoint_alternatives.old_endpoint_id,
                        endpoint_alternatives.new_endpoint_id,
                        endpoint_alternatives.explanation_markdown
                    )
                    .insert(*[Parameter('%s') for _ in range(4)])
                    .returning(endpoint_alternatives.id)
                    .get_sql(),
                    (
                        slug_to_id[from_endpoint_slug],
                        slug_to_id[to_endpoint_slug],
                        endpoint_alternative.explanation_markdown
                    )
                )
            except IntegrityError:
                return Response(status_code=503, headers=headers)

        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.put(
    '/{endpoint_slug}/params/{location}',
    responses={
        '200': {'description': 'Success'},
        '401': {'description': 'Authorization not provided'},
        '403': {'description': 'Authorization invalid or insufficient'},
        '404': {'description': 'The endpoint does not exist'}
    }
)
def put_endpoint_param(
        endpoint_param: models.EndpointParamPutRequest,
        endpoint_slug: str, location: str, path: str = '', name: str = '',
        authorization=Header(None)):
    """Create or update the specified endpoint parameter. This requires the
    `helper.UPDATE_ENDPOINT_PERMISSION`, regardless of if it is a create or
    an update.

    Arguments:
    - `endpoint_param (models.EndpointParamPutRequest)`: The new type and
      description for this parameter.
    - `endpoint_slug (str)`: The slug of the endpoint this parameter is
      in.
    - `location (str)`: The location of this parameter; acts as an enum
      and is one of "query", "body", and "header"
    - `path (str)`: The path to the endpoint within the location but before
      the name. For query and header parameters this is a blank string.
      For a body parameter that's nested this is a dot-separated list that
      takes you to the dictionary storing the variable (as if by javascript).
      For example the body `{"foo": { "bar": { "baz": 3 }}}` has a parameter
      with location `body`, path `foo.bar`, and name `baz`.
    - `name (str)`: The name for this parameter. Case-sensitive; for headers
      this should be all lowercase.
    - `authorization (str, None)`: If provided this should be the bearer token
      generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    if location not in ('query', 'body', 'header'):
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['location'],
                    'msg': 'Must be one of query, body, header',
                    'type': 'value_error'
                }
            }
        )

    if path and any(not p.strip() for p in path.split('.')):
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['path'],
                    'msg': 'Must be blank or have non-blank elements',
                    'type': 'value_error'
                }
            }
        )

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.UPDATE_ENDPOINT_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        can_edit = helper.UPDATE_ENDPOINT_PERMISSION in perms

        if not can_edit:
            return Response(status_code=403, headers=headers)

        endpoints = Table('endpoints')
        itgs.read_cursor.execute(
            Query.from_(endpoints)
            .select(endpoints.id)
            .where(endpoints.slug == Parameter('%s'))
            .get_sql(),
            (endpoint_slug,)
        )
        row = itgs.read_cursor.fetchone()
        if not row:
            return Response(status_code=404, headers=headers)

        (endpoint_id,) = row

        endpoint_params = Table('endpoint_params')
        itgs.read_cursor.execute(
            Query.from_(endpoint_params)
            .select(
                endpoint_params.var_type,
                endpoint_params.description_markdown,
                endpoint_params.updated_at
            )
            .where(endpoint_params.endpoint_id == Parameter('%s'))
            .where(endpoint_params.location == Parameter('%s'))
            .where(endpoint_params.path == Parameter('%s'))
            .where(endpoint_params.name == Parameter('%s'))
            .get_sql(),
            (
                endpoint_id,
                location,
                path,
                name
            )
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            (
                old_var_type,
                old_description_markdown,
                old_updated_at,
                old_in_endpoint_params
            ) = (None, None, None, False)
        else:
            (
                old_var_type,
                old_description_markdown,
                old_updated_at
            ) = row
            old_in_endpoint_params = True

        ep_history = Table('endpoint_param_history')
        itgs.write_cursor.execute(
            Query.into(ep_history)
            .columns(
                ep_history.user_id,
                ep_history.endpoint_slug,
                ep_history.location,
                ep_history.path,
                ep_history.name,
                ep_history.old_var_type,
                ep_history.new_var_type,
                ep_history.old_description_markdown,
                ep_history.new_description_markdown,
                ep_history.old_in_endpoint_params,
                ep_history.new_in_endpoint_params
            )
            .insert(*[Parameter('%s') for _ in range(11)])
            .get_sql(),
            (
                user_id,
                endpoint_slug,
                location,
                path,
                name,
                old_var_type,
                endpoint_param.var_type,
                old_description_markdown,
                endpoint_param.description_markdown,
                old_in_endpoint_params,
                True
            )
        )

        if old_in_endpoint_params:
            itgs.write_cursor.execute(
                Query.update(endpoint_params)
                .set(endpoint_params.var_type, Parameter('%s'))
                .set(endpoint_params.description_markdown, Parameter('%s'))
                .set(endpoint_params.updated_at, Now())
                .where(endpoint_params.endpoint_id == Parameter('%s'))
                .where(endpoint_params.location == Parameter('%s'))
                .where(endpoint_params.path == Parameter('%s'))
                .where(endpoint_params.updated_at == Parameter('%s'))
                .returning(endpoint_params.id)
                .get_sql(),
                (
                    endpoint_param.var_type,
                    endpoint_param.description_markdown,
                    endpoint_id,
                    location,
                    path,
                    old_updated_at
                )
            )
            if itgs.write_cursor.fetchone() is None:
                itgs.write_conn.rollback()
                return Response(status_code=503, headers=headers)
        else:
            try:
                itgs.write_cursor.execute(
                    Query.into(endpoint_params)
                    .columns(
                        endpoint_params.endpoint_id,
                        endpoint_params.location,
                        endpoint_params.path,
                        endpoint_params.name,
                        endpoint_params.var_type,
                        endpoint_params.description_markdown
                    )
                    .insert(*[Parameter('%s') for _ in range(6)])
                    .get_sql(),
                    (
                        endpoint_id,
                        location,
                        path,
                        name,
                        endpoint_param.var_type,
                        endpoint_param.description_markdown
                    )
                )
            except IntegrityError:
                itgs.write_conn.rollback()
                return Response(status_code=503, headers=headers)

        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.delete(
    '/{slug}/?',
    responses={
        '200': {'description': 'Success'},
        '401': {'description': 'Authorization not provided'},
        '403': {'description': 'Authorization invalid or insufficient'},
        '404': {'description': 'That endpoint does not exist'}
    }
)
def destroy_endpoint(slug: str, authorization=Header(None)):
    """Deletes the endpoint with the given slug. We store a complete history
    of an endpoint which is not deleted from this, so this operation is
    reversible.

    This requires the `helper.DELETE_ENDPOINT_PERMISSION` permission.

    Arguments:
    - `slug (str)`: The slug of the endpoint to delete
    - `authorization (str, None)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    attempt_request_cost = 1
    perform_request_cost = 99
    headers = {'x-request-cost': str(attempt_request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.DELETE_ENDPOINT_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, attempt_request_cost):
            return Response(status_code=429, headers=headers)

        if helper.DELETE_ENDPOINT_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        endpoints = Table('endpoints')
        ep_history = Table('endpoint_history')
        itgs.write_cursor.execute(
            Query.into(ep_history)
            .columns(
                ep_history.user_id,
                ep_history.slug,
                ep_history.old_path,
                ep_history.new_path,
                ep_history.old_verb,
                ep_history.new_verb,
                ep_history.old_description_markdown,
                ep_history.new_description_markdown,
                ep_history.old_deprecation_reason_markdown,
                ep_history.new_deprecation_reason_markdown,
                ep_history.old_deprecated_on,
                ep_history.new_deprecated_on,
                ep_history.old_sunsets_on,
                ep_history.new_sunsets_on,
                ep_history.old_in_endpoints,
                ep_history.new_in_endpoints
            )
            .from_(endpoints)
            .select(
                Parameter('%s'),
                endpoints.slug,
                endpoints.path,
                endpoints.path,
                endpoints.verb,
                endpoints.verb,
                endpoints.description_markdown,
                endpoints.description_markdown,
                endpoints.deprecation_reason_markdown,
                endpoints.deprecation_reason_markdown,
                endpoints.deprecated_on,
                endpoints.deprecated_on,
                endpoints.sunsets_on,
                endpoints.sunsets_on,
                True,
                False
            )
            .where(endpoints.slug == Parameter('%s'))
            .returning(1)
            (user_id, slug)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        headers['x-request-cost'] = str(attempt_request_cost + perform_request_cost)
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, perform_request_cost):
            itgs.write_conn.rollback()
            return Response(status_code=429, headers=headers)

        itgs.read_cursor.execute(
            Query.from_(endpoints)
            .select(endpoints.id)
            .where(endpoints.slug == Parameter('%s'))
            .get_sql(),
            (slug,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            itgs.write_conn.rollback()
            return Response(status_code=503, headers=headers)

        (endpoint_id,) = row

        endpoint_params = Table('endpoint_params')
        ep_param_history = Table('endpoint_param_history')
        itgs.write_cursor.execute(
            Query.into(ep_param_history)
            .columns(
                ep_param_history.user_id,
                ep_param_history.endpoint_slug,
                ep_param_history.location,
                ep_param_history.path,
                ep_param_history.name,
                ep_param_history.old_var_type,
                ep_param_history.new_var_type,
                ep_param_history.old_description_markdown,
                ep_param_history.new_description_markdown,
                ep_param_history.old_in_endpoint_params,
                ep_param_history.new_in_endpoint_params
            )
            .from_(endpoint_params)
            .select(
                Parameter('%s'),
                Parameter('%s'),
                endpoint_params.location,
                endpoint_params.path,
                endpoint_params.name,
                endpoint_params.var_type,
                endpoint_params.var_type,
                endpoint_params.description_markdown,
                endpoint_params.description_markdown,
                True,
                False
            )
            .where(endpoint_params.endpoint_id == Parameter('%s'))
            .get_sql(),
            (user_id, slug, endpoint_id)
        )

        endpoint_alts = Table('endpoint_alternatives')
        old_endpoints = endpoints.as_('old_endpoints')
        new_endpoints = endpoints.as_('new_endpoints')
        ep_alt_history = Table('endpoint_alternative_history')
        itgs.write_cursor.execute(
            Query.into(ep_alt_history)
            .columns(
                ep_alt_history.user_id,
                ep_alt_history.old_endpoint_slug,
                ep_alt_history.new_endpoint_slug,
                ep_alt_history.old_explanation_markdown,
                ep_alt_history.new_explanation_markdown,
                ep_alt_history.old_in_endpoint_alternatives,
                ep_alt_history.new_in_endpoint_alternatives
            )
            .from_(endpoint_alts)
            .select(
                Parameter('%s'),
                old_endpoints.slug,
                new_endpoints.slug,
                ep_alt_history.explanation_markdown,
                ep_alt_history.explanation_markdown,
                True,
                False
            )
            .where(
                (endpoint_alts.old_endpoint_id == Parameter('%s'))
                | (endpoint_alts.new_endpoint_id == Parameter('%s'))
            )
            .get_sql(),
            (user_id, endpoint_id, endpoint_id)
        )
        itgs.write_cursor.execute(
            Query.from_(endpoints)
            .delete()
            .where(endpoints.id == Parameter('%s'))
            .get_sql(),
            (endpoint_id,)
        )
        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.delete(
    '/migrate/{from_endpoint_slug}/{to_endpoint_slug}',
    responses={
        '200': {'description': 'Success'},
        '401': {'description': 'Authorization not provided'},
        '403': {'description': 'Authorization invalid or insufficient'},
        '404': {
            'description': (
                'One of the endpoints does not exist '
                'or the association does not exist'
            )
        }
    }
)
def destroy_endpoint_alternative(
        from_endpoint_slug: str, to_endpoint_slug: str,
        authorization=Header(None)):
    """Destroy the documentation for how to migrate from the endpoint with
    slug `from_endpoint_slug` to the endpoint `to_endpoint_slug`. We maintain
    a full history for this table even through deletes so this operation is
    reversible.

    This requires the `helper.UPDATE_ENDPOINT_PERMISSION` permission.

    Arguments:
    - `from_endpoint_slug (str)`: The slug of the endpoint from which there is
      documentation that should be deleted.
    - `to_endpoint_slug (str)`: The slug of the endpoint to which there is
      documentation that should be deleted.
    - `authorization (str, None)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    attempt_request_cost = 5
    perform_request_cost = 20
    headers = {'x-request-cost': str(attempt_request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.UPDATE_ENDPOINT_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, attempt_request_cost):
            return Response(status_code=429, headers=headers)

        if helper.UPDATE_ENDPOINT_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        endpoints = Table('endpoints')
        old_endpoints = endpoints.as_('old_endpoints')
        new_endpoints = endpoints.as_('new_endpoints')
        endpoint_alts = Table('endpoint_alternatives')
        ep_alt_history = Table('endpoint_alternative_history')
        itgs.write_cursor.execute(
            Query.into(ep_alt_history)
            .columns(
                ep_alt_history.user_id,
                ep_alt_history.old_endpoint_slug,
                ep_alt_history.new_endpoint_slug,
                ep_alt_history.old_explanation_markdown,
                ep_alt_history.new_explanation_markdown,
                ep_alt_history.old_in_endpoint_alternatives,
                ep_alt_history.new_in_endpoint_alternatives
            )
            .from_(endpoint_alts)
            .join(old_endpoints).on(old_endpoints.id == endpoint_alts.old_endpoint_id)
            .join(new_endpoints).on(new_endpoints.id == endpoint_alts.new_endpoint_id)
            .select(
                Parameter('%s'),
                old_endpoints.slug,
                new_endpoints.slug,
                endpoint_alts.explanation_markdown,
                endpoint_alts.explanation_markdown,
                True,
                False
            )
            .where(old_endpoints.slug == Parameter('%s'))
            .where(new_endpoints.slug == Parameter('%s'))
            .returning(1)
            .get_sql(),
            (user_id, from_endpoint_slug, to_endpoint_slug)
        )
        row = itgs.write_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        headers['x-request-cost'] = str(attempt_request_cost + perform_request_cost)
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, perform_request_cost):
            itgs.write_conn.rollback()
            return Response(status_code=429, headers=headers)

        itgs.write_cursor.execute(
            Query.from_(endpoint_alts)
            .delete()
            .join(old_endpoints).on(old_endpoints.id == endpoint_alts.old_endpoint_id)
            .join(new_endpoints).on(new_endpoints.id == endpoint_alts.new_endpoint_id)
            .where(old_endpoints.slug == Parameter('%s'))
            .where(new_endpoints.slug == Parameter('%s'))
            .get_sql(),
            (from_endpoint_slug, to_endpoint_slug)
        )
        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.delete(
    '/{endpoint_slug}/params/{location}',
    responses={
        '200': {'description': 'Success'},
        '401': {'description': 'Authorization not provided'},
        '403': {'description': 'Authorization invalid or insufficient'},
        '404': {'description': 'That endpoint or param does not exist'}
    }
)
def destroy_endpoint_param(
        endpoint_slug: str, location: str, path: str = '', name: str = '',
        authorization=Header(None)):
    """Destroy the given endpoint parameter. We maintain a history of endpoint
    parameters that persists through deletions so this operation is reversible.

    This requires the `helper.UPDATE_ENDPOINT_PERMISSION` permission.

    Arguments:
    - `endpoint_slug (str)`: The slug of the endpoint this parameter is for
    - `location (str)`: The location (one of query, body, header) where this
      parameter lives.
    - `path (str)`: The path to the parameter (see show_endpoint_param)
    - `name (str)`: The name of the parameter (see show_endpoint_param)
    - `authorization (str, None)`: The bearer token generated at login
    """
    if authorization is None:
        return Response(status_code=401)

    attempt_request_cost = 1
    perform_request_cost = 24
    headers = {'x-request-cost': str(attempt_request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.UPDATE_ENDPOINT_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, attempt_request_cost):
            return Response(status_code=429, headers=headers)

        if helper.UPDATE_ENDPOINT_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        endpoints = Table('endpoints')
        endpoint_params = Table('endpoint_params')
        ep_param_history = Table('endpoint_param_history')
        itgs.write_cursor.execute(
            Query.into(ep_param_history)
            .columns(
                ep_param_history.user_id,
                ep_param_history.endpoint_slug,
                ep_param_history.location,
                ep_param_history.path,
                ep_param_history.name,
                ep_param_history.old_var_type,
                ep_param_history.new_var_type,
                ep_param_history.old_description_markdown,
                ep_param_history.new_description_markdown,
                ep_param_history.old_in_endpoint_params,
                ep_param_history.new_in_endpoint_params
            )
            .from_(endpoint_params)
            .join(endpoints).on(endpoints.id == endpoint_params.endpoint_id)
            .select(
                Parameter('%s'),
                endpoints.slug,
                endpoint_params.location,
                endpoint_params.path,
                endpoint_params.name,
                endpoint_params.var_type,
                endpoint_params.var_type,
                endpoint_params.description_markdown,
                endpoint_params.description_markdown,
                True,
                False
            )
            .where(endpoints.slug == Parameter('%s'))
            .where(endpoint_params.location == Parameter('%s'))
            .where(endpoint_params.path == Parameter('%s'))
            .where(endpoint_params.name == Parameter('%s'))
            .returning(1)
            .get_sql(),
            (user_id, endpoint_slug, location, path, name)
        )
        if itgs.write_cursor.fetchone() is None:
            itgs.write_conn.rollback()
            return Response(status_code=404, headers=headers)

        headers['x-request-cost'] = str(attempt_request_cost + perform_request_cost)
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, perform_request_cost):
            itgs.write_conn.rollback()
            return Response(status_code=429, headers=headers)

        itgs.write_cursor.execute(
            Query.from_(endpoint_params)
            .delete()
            .join(endpoints).on(endpoints.id == endpoint_params.endpoint_id)
            .where(endpoints.slug == Parameter('%s'))
            .where(endpoint_params.location == Parameter('%s'))
            .where(endpoint_params.path == Parameter('%s'))
            .where(endpoint_params.name == Parameter('%s'))
            .get_sql(),
            (endpoint_slug, location, path, name)
        )
        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)
