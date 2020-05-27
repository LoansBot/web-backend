from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from . import models
from models import ErrorResponse
import users.helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from datetime import datetime


router = APIRouter()


@router.get(
    '/?',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.LoansResponse},
        422: {'description': 'Arguments could not be interpreted', 'model': ErrorResponse}
    }
)
def index(authorization: str = Header(None)):
    pass


@router.get(
    '/:id/?',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.BasicLoanResponse},
        404: {'description': 'Loan not found'}
    }
)
def show(id: int, authorization: str = Header(None)):
    pass


@router.get(
    '/:id/detailed',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.DetailedLoanResponse},
        404: {'description': 'Loan not found'}
    }
)
def show_detailed(id: int, authorization: str = Header(None)):
    pass


@router.patch(
    '/:id',
    tags=['loans'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Missing authentication'},
        403: {'description': 'Bad authentication'},
        404: {'description': 'Loan not found'},
        412: {'description': 'Etag does not match If-Match header'}
    }
)
def update(id: int, if_match: str = Header(None), authorization: str = Header(None)):
    pass
