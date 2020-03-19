from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter
from . import models
import users.helper
import integrations as itgs
from datetime import datetime
from lblogging import Level


router = APIRouter()


@router.get(
    '/?',
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
        application_ids: str = None,
        limit: int = 25,
        authorization: str = Header(None)):
    """The main endpoint for querying logs. Typically the front-end will need
    to query /applications as well so they can prettily display the
    applications.

    The endpoint requires the "logs" permission.
    """
    authtoken = users.helper.get_authtoken_from_header(authorization)
    if authtoken is None:
        return Response(status_code=403)
    if application_ids is not None:
        app_ids = application_ids.split(',')
        try:
            app_ids = [int(i) for i in app_ids]
        except ValueError:
            return Response(status_code=400)
        if len(app_ids) == 0:
            application_ids = None
            app_ids = None
    with itgs.database() as conn:
        cursor = conn.cursor()
        info = users.helper.get_auth_info_from_token_auth(
            conn, cursor, users.models.TokenAuthentication(token=authtoken)
        )
        if info is None:
            return Response(status_code=403)
        authid = info[0]
        if not users.helper.check_permission_on_authtoken(conn, cursor, authid, 'logs'):
            return Response(status_code=403)

        log_events = Table('log_events')
        log_identifiers = Table('log_identifiers')
        query = (
            Query.from_(log_events).select(
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
        if application_ids is not None:
            query = query.where(log_events.application_id.isin([Parameter('%s') for _ in app_ids]))
            for app_id in app_ids:
                params.append(app_id)
        query = query.limit(Parameter('%s'))
        if limit is None or limit > 100 or limit <= 0:
            params.append(100)
        else:
            params.append(limit)

        cursor.execute(query.get_sql(), params)
        result = []
        while True:
            row = cursor.fetchone()
            if row is None:
                break
            row_cat: datetime = row[4]
            result.append(models.LogResponse(
                level=row[0],
                app_id=row[1],
                identifier=row[2],
                message=row[3],
                created_at=int(row_cat.timestamp())
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
    authtoken = users.helper.get_authtoken_from_header(authorization)
    if authtoken is None:
        return Response(status_code=403)
    with itgs.database() as conn:
        cursor = conn.cursor()
        info = users.helper.get_auth_info_from_token_auth(
            conn, cursor, users.models.TokenAuthentication(token=authtoken)
        )
        if info is None:
            return Response(status_code=403)
        authid = info[0]
        if not users.helper.check_permission_on_authtoken(conn, cursor, authid, 'logs'):
            return Response(status_code=403)

        apps = Table('log_applications')
        cursor.execute(
            Query.from_(apps).select(apps.id, apps.name).get_sql()
        )
        with itgs.logger() as lgr:
            lgr.print(Level.DEBUG, 'Executed query {}', cursor.query.decode('utf-8'))
        result = {}

        while True:
            row = cursor.fetchone()
            if row is None:
                break
            result[row[0]] = models.LogApplicationResponse(name=row[1])
            with itgs.logger() as lgr:
                lgr.print(Level.DEBUG, 'Found row {}', row)

        with itgs.logger() as lgr:
            lgr.print(Level.DEBUG, 'Returning result={}', result)
        return JSONResponse(
            status_code=200,
            content=models.LogApplicationsResponse(applications=result).dict(),
            headers={
                'Cache-Control': 'public, max-age=86400, stale-if-error=2419200'
            }
        )
