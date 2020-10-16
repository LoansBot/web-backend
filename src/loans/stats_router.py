"""This router is used for statistics endpoints. In general we update our
statistics in the background (see LoansBot/runners/statistics.py), so these
endpoints just serve the most recent cached version (if it exists).
"""
from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
import loans.stats_models as models
import ratelimit_helper
import users.helper

router = APIRouter()


@router.get(
    '/stats/{unit}/{frequency}',
    responses={
        404: {'description': 'No cached value for that graph available'}
    },
    tags=['loans', 'stats'],
    response_model=models.LinePlot
)
def show_stats(unit: str, frequency: str, request: Request, authorization=Header(None)):
    """Fetches the most recently calculated statistics using the given unit
    (either count or usd) and frequency (either monthly or quarterly). This
    endpoint normally costs nothing toward the ratelimit quota, however if
    cache-busting is detected (query parameters or via headers) then a cost
    is associated with the request.
    """
    request_cost = 25 if ratelimit_helper.is_cache_bust(request) else 0
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        if request_cost > 0:
            user_id, _, perms = users.helper.get_permissions_from_header(
                itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS
            )
            if not ratelimit_helper.check_ratelimit(
                    itgs, user_id, perms, request_cost):
                return Response(status_code=429, headers=headers)

        if unit not in ('count', 'usd'):
            return JSONResponse(
                status_code=422,
                content={
                    'detail': {
                        'loc': ['unit'],
                        'msg': 'Must be one of count, usd',
                        'type': 'value_error'
                    }
                }
            )

        if frequency not in ('monthly', 'quarterly'):
            return JSONResponse(
                status_code=422,
                content={
                    'detail': {
                        'loc': ['frequency'],
                        'msg': 'Must be one of monthly, quarterly',
                        'type': 'value_error'
                    }
                }
            )

        cache_key = f'stats/loans/{unit}/{frequency}'
        val = itgs.cache.get(cache_key)
        if val is None:
            return Response(status_code=404, headers=headers)

        headers['Cache-Control'] = (
            'public, max-age=86400, stale-if-error=86400, stale-while-revalidate=86400'
        )
        return Response(
            status_code=200, content=val,
            headers=headers, media_type="application/json"
        )
