from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from . import models
import users.helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from datetime import datetime


router = APIRouter()


@router.get(
    '/',
    tags=['logs'],
    responses={
        200: {'description': 'Success', 'model': models.LogsResponse},
        400: {'description': 'Application ids is not ints comma separated'},
        403: {'description': 'Token authentication failed'}
    }
)
def root(
        min_created_at: int = None,
        min_level: int = None,
        min_id: int = None,
        application_ids: str = None,
        search: str = None,
        limit: int = 25,
        authorization: str = Header(None)):
    """The main endpoint for querying logs. Typically the front-end will need
    to query /applications as well so they can prettily display the
    applications. This supports either id or timestamp forward-pagination

    The endpoint requires the "logs" permission.
    """
    if application_ids is not None:
        app_ids = application_ids.split(',')
        try:
            app_ids = [int(i) for i in app_ids]
        except ValueError:
            return Response(status_code=400)
        if len(app_ids) == 0:
            application_ids = None
            app_ids = None
    with LazyItgs() as itgs:
        if not users.helper.check_permissions_from_header(itgs, authorization, 'logs')[0]:
            return Response(status_code=403)

        log_events = Table('log_events')
        log_identifiers = Table('log_identifiers')
        query = (
            Query.from_(log_events).select(
                log_events.id,
                log_events.level,
                log_events.application_id,
                log_identifiers.identifier,
                log_events.message,
                log_events.created_at
            ).join(log_identifiers).on(
                log_identifiers.id == log_events.identifier_id
            )
        )
        params = []
        if min_created_at is not None:
            query = query.where(log_events.created_at >= Parameter('%s'))
            params.append(datetime.fromtimestamp(min_created_at))
        if min_level is not None:
            query = query.where(log_events.level >= Parameter('%s'))
            params.append(min_level)
        if min_id is not None:
            query = query.where(log_events.id >= Parameter('%s'))
            params.append(min_id)
        if application_ids is not None:
            query = query.where(log_events.application_id.isin([Parameter('%s') for _ in app_ids]))
            for app_id in app_ids:
                params.append(app_id)
        if search is not None:
            query = query.where(log_events.message.like(Parameter('%s')))
            params.append(search)

        if min_created_at is None and min_id is None:
            query = query.orderby(log_events.id, order=Order.desc)
        else:
            query = query.orderby(log_events.id, order=Order.asc)

        query = query.limit(Parameter('%s'))
        if limit is None or limit > 100 or limit <= 0:
            params.append(100)
        else:
            params.append(limit)

        itgs.read_cursor.execute(query.get_sql(), params)
        result = []
        while True:
            row = itgs.read_cursor.fetchone()
            if row is None:
                break
            result.append(models.LogResponse(
                id=row[0],
                level=row[1],
                app_id=row[2],
                identifier=row[3],
                message=row[4],
                created_at=int(row[5].timestamp())
            ))
        return JSONResponse(
            status_code=200,
            content=models.LogsResponse(logs=result).dict()
        )


@router.get(
    '/applications',
    tags=['logs'],
    responses={
        200: {'description': 'Success', 'model': models.LogApplicationsResponse},
        403: {'description': 'Token authentication failed'}
    }
)
def applications(authorization: str = Header(None)):
    """Returns application ids mapped to the corresponding application
    names."""
    with LazyItgs() as itgs:
        if not users.helper.check_permissions_from_header(itgs, authorization, 'logs')[0]:
            return Response(status_code=403)

        apps = Table('log_applications')
        itgs.read_cursor.execute(
            Query.from_(apps).select(apps.id, apps.name).get_sql()
        )
        result = {}

        while True:
            row = itgs.read_cursor.fetchone()
            if row is None:
                break
            result[row[0]] = models.LogApplicationResponse(name=row[1])

        return JSONResponse(
            status_code=200,
            content=models.LogApplicationsResponse(applications=result).dict(),
            headers={
                'Cache-Control': 'public, max-age=86400, stale-if-error=2419200'
            }
        )
