"""Helps with sunsetting endpoints"""
from fastapi import Request
from fastapi.responses import Response, JSONResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from lblogging import Level
from pypika import PostgreSQLQuery as Query, Table, Parameter, Interval
from pypika.functions import Count, Star, Now, Coalesce
from lbshared.pypika_funcs import DateTrunc
from datetime import datetime, timedelta

SUNSETTED_HEADERS = {
    'Cache-Control': (
        'public, max-age=86400, stale-while-revalidate=604800, '
        'stale-if-error=604800'
    )
}
"""The headers that we provide to GET requests to sunsetted endpoints."""


def find_bearer_token(request: Request) -> str:
    """Will take the given request and attempt to find the bearer token that
    they are providing. For non-legacy endpoints this is standardized, but
    we have in the past had other authentication parameters which have since
    been deprecated.

    Arguments:
    - `request (Request)`: The underlying starlette request that we are
      going to look for a bearer token on.

    Returns:
    - `token (str, None)`: The bearer token (including the text `bearer `)
      if one could be found, otherwise this will be None.
    """
    # Current way of doing authorization
    std = request.headers.get('authorization')
    if std:
        return std

    # From the php era
    session_cookie = request.cookies.get('session_id')
    if session_cookie:
        return f'bearer {session_cookie}'

    return None


def try_handle_deprecated_call(
        itgs: LazyItgs,
        request: Request,
        endpoint_slug: str,
        user_id: int = None) -> Response:
    """Attempts to fully handle the deprecated call. If the underlying
    functionality on this call should not be provided then this will
    return the Response that should be given instead.

    Arguments:
    - `itgs (LazyItgs)`: The lazy integrations to use for connecting to
      networked components.
    - `request (Request)`: The underlying starlette request, which we will
      use for checking for shared query parameters like `deprecated`.
    - `endpoint_slug (str)`: The internal name we have for this
      endpoint, which will let us find the description, reason for deprecation,
      and list of alternatives in the database (main table: `endpoints`).
    - `user_id (int, None)`: If the request was authenticated in any way that
      could be recognized with `find_bearer_token`, and the token was valid,
      this should be the id of the authenticated user.

    Returns:
        - `resp (Response, None)`: If the response for the endpoint should be
          overriden, this is the response that should be used. Otherwise this
          is None.
    """
    endpoints = Table('endpoints')
    itgs.read_cursor.execute(
        Query.from_(endpoints).select(
            endpoints.id,
            endpoints.deprecated_on,
            endpoints.sunsets_on
        ).where(endpoints.slug == Parameter('%s'))
        .get_sql(),
        (endpoint_slug,)
    )
    row = itgs.read_cursor.fetchone()
    if row is None:
        return None
    (
        endpoint_id,
        deprecated_on,
        sunsets_on
    ) = row

    if deprecated_on is None:
        return None

    if sunsets_on is None:
        itgs.logger.print(
            Level.WARN,
            'The endpoint slug {} is deprecated but does not have a sunset '
            'date set! This should not happen; the maximum sunsetting time '
            'of 36 months will be assigned'
        )
        itgs.write_cursor.execute(
            Query.update(endpoints)
            .set(
                endpoints.sunsets_on,
                Coalesce(endpoints.sunsets_on, Now() + Interval(months=36))
            )
            .where(endpoints.slug == Parameter('%s'))
            .returning(endpoints.sunsets_on)
            .get_sql(),
            (endpoint_slug,)
        )
        (sunsets_on,) = itgs.write_cursor.fetchone()
        itgs.write_conn.commit()

    curtime = datetime.utcnow()

    if curtime.date() < deprecated_on:
        return None

    # 2pm UTC = 10am est = 7am pst
    sunset_time = datetime(
        sunsets_on.year, sunsets_on.month, sunsets_on.day,
        14, tzinfo=curtime.tzinfo
    )

    if curtime >= sunset_time + timedelta(days=31):
        # No logging, can't be suppressed, provides no info
        if request.method not in ('GET', 'HEAD'):
            return Response(
                status_code=405,
                headers={
                    'Allow': 'GET, HEAD'
                }
            )

        return Response(
            status_code=404,
            headers=SUNSETTED_HEADERS
        )

    if curtime >= sunset_time:
        # No logging, can't be suppressed, provides info
        if request.method == 'HEAD':
            return Response(status_code=400)

        return JSONResponse(
            status_code=400,
            content={
                'deprecated': True,
                'sunsetted': True,
                'retryable': False,
                'error': (
                    'This endpoint has been deprecated since {} and was sunsetted on {}, '
                    'meaning that it can no longer be used. For the reason for deprecation '
                    'and how to migrate off, visit {}://{}/endpoints.html?slug={}'
                ).format(
                    deprecated_on.strftime('%B %d, %Y'),
                    sunsets_on.strftime('%B %d, %Y'),
                    request.url.scheme,
                    request.url.netloc,
                    endpoint_slug
                )
            },
            headers=SUNSETTED_HEADERS if request.method == 'GET' else None
        )

    if request.query_params.get('deprecated') == 'true':
        # This flag suppresses all behavior before sunset, including logging
        return None

    ip_address = request.headers.get('x-real-ip', '')
    user_agent = request.headers.get('user-agent', '')

    if user_id is not None:
        ip_address = None
        user_agent = None

    if curtime >= sunset_time - timedelta(days=14):
        store_response(itgs, user_id, ip_address, user_agent, endpoint_id, 'error')
        return JSONResponse(
            status_code=400,
            content={
                'deprecated': True,
                'sunsetted': False,
                'retryable': False,
                'error': (
                    'This endpoint has been deprecated since {deprecated_on} and will sunset '
                    'on {sunsets_on}. For the reason for deprecation and how to migrate off, '
                    'visit {scheme}://{netloc}/endpoints.html?slug={slug}. To continue using '
                    'this endpoint until {sunsets_on} you must acknowledge this warning by '
                    'setting the query parameter "deprecated" with the value "true". For '
                    'example: {scheme}://{netloc}{path}?{query_params}{opt_ambersand}'
                    'deprecated=true{opt_hashtag}{fragment}'
                ).format(
                    deprecated_on=deprecated_on.strftime('%B %d, %Y'),
                    sunsets_on=sunsets_on.strftime('%B %d, %Y'),
                    scheme=request.url.scheme,
                    netloc=request.url.netloc,
                    path=request.url.path,
                    query_params=request.url.query_params,
                    opt_ambersand='' if request.url.query_params == '' else '&',
                    opt_hashtag='' if request.url.fragment == '' else '#',
                    fragment=request.url.fragment,
                    slug=endpoint_slug
                )
            },
            headers={
                'Cache-Control': 'no-store'
            }
        )

    if user_id is None:
        endpoint_users = Table('endpoint_users')
        itgs.read_cursor.execute(
            Query.from_(endpoint_users)
            .select(Count(Star()))
            .where(endpoint_users.ip_address == Parameter('%s'))
            .where(endpoint_users.user_agent == Parameter('%s'))
            .where(endpoint_users.response_type == Parameter('%s'))
            .where(endpoint_users.created_at > DateTrunc('month', Now()))
            # These are just to make sure postgres is aware it can use the index
            .where(endpoint_users.ip_address.notnull())
            .where(endpoint_users.user_agent.notnull())
            .get_sql(),
            (
                ip_address,
                user_agent,
                'error'
            )
        )
        (errors_this_month,) = itgs.read_cursor.fetchone()

        if errors_this_month < 5:
            store_response(itgs, None, ip_address, user_agent, endpoint_id, 'error')
            return JSONResponse(
                status_code=400,
                content={
                    'deprecated': True,
                    'sunsetted': False,
                    'retryable': True,
                    'error': (
                        'This endpoint has been deprecated since {deprecated_on} and will '
                        'sunset on {sunsets_on}. Since your request is not authenticated '
                        'the only means to alert you of the sunset date is to fail some of '
                        'your requests. You may pass the query parameter `deprecated=true` '
                        'to suppress this behavior. We will only fail 5 requests per month '
                        'until it gets closer to the sunset date.\n\n'
                        'Check {schema}://{netloc}/endpoints.html?slug={slug} for information '
                        'about why this endpoint was deprecated and how to migrate.'
                    ).format(
                        deprecated_on=deprecated_on.strftime('%B %d, %Y'),
                        sunsets_on=sunsets_on.strftime('%B %d, %Y'),
                        schema=request.url.schema,
                        netloc=request.url.netloc,
                        slug=endpoint_slug
                    )
                },
                headers={
                    'Cache-Control': 'no-store'
                }
            )

    store_response(itgs, user_id, ip_address, user_agent, endpoint_id, 'passthrough')
    return None


def store_response(itgs, user_id, ip_address, user_agent, endpoint_id, response_type):
    """Store that we made the given type of response to the given endpoint. This
    will commit the write cursor.

    Arguments:
    - `itgs (LazyItgs)`: The lazy integrations to use for connecting to networked
      components.
    - `user_id (int, None)`: The id of the user which made the request, if the request
      was authenticated. If provided the ip address and user agent should be None
    - `ip_address (str, None)`: The ip address that the request was sent from.
    - `user_agent (str, None)`: The user agent header sent with the request.
    - `endpoint_id (int)`: The id of the endpoitn used
    - `response_type (str)`: One of 'error', 'passthrough'
    """
    endpoint_users = Table('endpoint_users')
    itgs.write_cursor.execute(
        Query.into(endpoint_users)
        .columns(
            endpoint_users.endpoint_id,
            endpoint_users.user_id,
            endpoint_users.ip_address,
            endpoint_users.user_agent,
            endpoint_users.response_type
        )
        .insert(*[Parameter('%s') for _ in range(5)])
        .get_sql(),
        (
            endpoint_id,
            user_id,
            ip_address,
            user_agent,
            response_type
        )
    )
    itgs.write_conn.commit()
