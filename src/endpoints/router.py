"""Contains the endpoints for collecting what endpoints exist. The process of
documenting endpoints for this purpose is not automated, however it's made
less painful by having some form of an interface.
"""
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from lbshared.queries import convert_numbered_args
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from . import models
import users.helper
import ratelimit_helper
import math

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
                endpoint_slgus=result,
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
        '403': {'description': 'Authorization invalid or insufficient'}
    }
)
def put_endpoint(endpoint: models.EndpointPutRequest, authorization=Header(None)):
    pass


@router.put(
    '/migrate/{from_endpoint_slug}/{to_endpoint_slug}',
    responses={
        '200': {'description': 'Success'},
        '401': {'description': 'Authorization not provided'},
        '403': {'description': 'Authorization invalid or insufficient'},
        '404': {'description': 'One of the endpoints does not exist'}
    }
)
def put_endpoint_alternative(
        endpoint_alternative: models.EndpointAlternativePutRequest,
        from_endpoint_slug: str, to_endpoint_slug: str,
        authorization=Header(None)):
    pass


@router.put(
    '/{endpoint_slug}/params/{location}',
)
def put_endpoint_param(
        endpoint_param: models.EndpointParamPutRequest,
        endpoint_slug: str, location: str, path: str = '', name: str = '',
        authorization=Header(None)):
    pass
