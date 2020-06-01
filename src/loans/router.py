from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from . import models
from . import helper
from models import ErrorResponse
import users.helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs

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
    return JSONResponse(content={'hello': 'there'}, status_code=200)


@router.get(
    '/{loan_id}/?',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.BasicLoanResponse},
        403: {'description': 'Authorization header provided but invalid'},
        404: {'description': 'Loan not found'},
        429: {'description': 'You are doing that too much.'}
    }
)
def show(loan_id: int, authorization: str = Header(None)):
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (helper.DELETED_LOANS_PERM, *helper.RATELIMIT_PERMISSIONS)
        )
        if perms:
            perms = tuple(perms)
        else:
            perms = tuple()

        if not helper.check_ratelimit(itgs, user_id, perms, 1):
            return Response(status_code=429)

        basic = helper.get_basic_loan_info(itgs, loan_id, perms)
        if basic is None:
            return Response(status_code=404)

        etag = helper.calculate_etag(itgs, loan_id)

        return JSONResponse(
            status_code=200,
            content=basic.dict(),
            headers={'etag': etag}
        )


@router.get(
    '/{loan_id}/detailed',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.DetailedLoanResponse},
        404: {'description': 'Loan not found'}
    }
)
def show_detailed(loan_id: int, authorization: str = Header(None)):
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.DELETED_LOANS_PERM,
                helper.VIEW_ADMIN_EVENT_AUTHORS_PERM,
                *helper.RATELIMIT_PERMISSIONS
            )
        )
        if perms:
            perms = tuple(perms)
        else:
            perms = tuple()

        if not helper.check_ratelimit(itgs, user_id, perms, 5):
            return Response(status_code=429)

        basic = helper.get_basic_loan_info(itgs, loan_id, perms)
        if basic is None:
            return Response(status_code=404)

        events = helper.get_loan_events(itgs, loan_id, perms)

        etag = helper.calculate_etag(itgs, loan_id)

        return JSONResponse(
            status_code=200,
            content=models.DetailedLoanResponse(
                events=events, basic=basic
            ).dict(),
            headers={'etag': etag}
        )


@router.patch(
    '/{loan_id}',
    tags=['loans'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Missing authentication'},
        403: {'description': 'Bad authentication'},
        404: {'description': 'Loan not found'},
        412: {'description': 'Etag does not match If-Match header'},
        428: {'description': 'Missing the if-match header'}
    }
)
def update(loan_id: int, if_match: str = Header(None), authorization: str = Header(None)):
    pass
