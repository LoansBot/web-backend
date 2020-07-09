from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
import users.helper
import ratelimit_helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from . import models
from pypika import Query, Table, Parameter


router = APIRouter()


@router.get(
    '/{permission}/?',
    tags=['permissions'],
    responses={
        200: {'description': 'Success', 'model': models.Permission},
        403: {'description': 'Authorization header provided but invalid'},
        404: {'description': 'Unknown permission'}
    }
)
def show(self, permission: str, authorization=Header(None)):
    request_cost = 1

    with LazyItgs() as itgs:
        user_id, provided, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (*ratelimit_helper.RATELIMIT_PERMISSIONS)
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if provided and user_id is None:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        permissions = Table('permissions')
        itgs.read_cursor.execute(
            Query.from_(permissions)
            .select(permissions.description)
            .where(permissions.name == Parameter('%s'))
            .get_sql(),
            (permission,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(
                status_code=400,
                headers={'x-request-cost': str(request_cost)}
            )

        return JSONResponse(
            status_code=200,
            headers={
                'x-request-cost': str(request_cost),
                'cache-control': 'public, max-age=604800, stale-while-revalidate=604800'
            },
            content=models.Permission(description=row[0]).dict()
        )


@router.get(
    '/?',
    responses={
        200: {'model': models.PermissionsList, 'description': 'Success'},
        403: {'description': 'Authorization provided but invalid'}
    }
)
def index(self, authorization=Header(None)):
    request_cost = 25

    with LazyItgs() as itgs:
        user_id, provided, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (*ratelimit_helper.RATELIMIT_PERMISSIONS)
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        if provided and user_id is None:
            return Response(
                status_code=403,
                headers={'x-request-cost': str(request_cost)}
            )

        permissions = Table('permissions')
        itgs.read_cursor.execute(
            Query.from_(permissions).select(permissions.name).get_sql(),
            []
        )

        result = []
        row = itgs.read_cursor.fetchone()
        while row is not None:
            result.append(row[0])
            row = itgs.read_cursor.fetchone()

        return Response(
            status_code=200,
            content=models.PermissionsList(permissions=result).dict(),
            headers={
                'x-request-cost': str(request_cost),
                'cache-control': 'public, max-age=604800, stale-while-revalidate=604800'
            }
        )
