"""Handles the requests to /api/responses/**/*"""
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from . import models
import users.helper
from lazy_integrations import LazyIntegrations as LazyItgs


router = APIRouter()


@router.get(
    '/?',
    tags=['responses'],
    responses={
        200: {'description': 'Success', 'model': models.ResponseIndex},
        403: {'description': 'Token authentication failed'}
    }
)
def root(authorization: str = Header(None)):
    with LazyItgs() as itgs:
        if not users.helper.check_permissions_from_header(itgs, authorization, 'responses')[0]:
            return Response(status_code=403)
        responses = Table('responses')
        itgs.read_cursor.execute(
            Query.from_(responses).select(responses.name)
            .orderby(responses.name).get_sql()
        )
        resps = itgs.read_cursor.fetchall()
        return JSONResponse(
            status_code=200,
            content=models.ResponseIndex(responses=resps).dict()
        )
