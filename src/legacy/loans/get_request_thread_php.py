"""This handles the deprecated endpoint /api/get_request_thread.php. See
+get_request_thread+ for details.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from legacy.models import PHPErrorResponse, RATELIMIT_RESPONSE, PHPError
from legacy.helper import find_bearer_token, try_handle_deprecated_call
import users.helper
import ratelimit_helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from pypika import PostgreSQLQuery as Query, Table, Parameter


SLUG = 'get_request_thread'
"""The slug for this legacy endpoint"""


class ResponseFormat(BaseModel):
    result_type: str = 'LOAN_REQUEST_THREAD'
    success: bool = True
    request_thread: str


router = APIRouter()


@router.get(
    '/get_request_thread.php',
    responses={
        200: {'description': 'Success', 'model': ResponseFormat},
        400: {'description': 'Arguments not understood', 'model': PHPErrorResponse}
    }
)
def get_creation_info(loan_id: int, request: Request):
    """Get the fully qualified url to the comment which spawned the given loan,
    if there is a corresponding url (i.e., the loan was spawned via reddit.)

    GET /api/get_creation_info.php?loan_id=57
    {
        "result_type": "LOAN_REQUEST_THREAD",
        "success": true,
        "request_thread": "https://..."
   }

    Arguments:
    - `loan_id (str)`: A single loan id to get the request thread for
    """
    request_cost = 5
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        auth = find_bearer_token(request)
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, auth, ratelimit_helper.RATELIMIT_PERMISSIONS)
        resp = try_handle_deprecated_call(itgs, request, SLUG, user_id=user_id)

        if resp is not None:
            return resp

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return JSONResponse(
                content=RATELIMIT_RESPONSE.dict(),
                status_code=429,
                headers=headers
            )

        creation_infos = Table('loan_creation_infos')
        loans = Table('loans')
        itgs.read_cursor.execute(
            Query.from_(creation_infos)
            .join(loans)
            .on(loans.id == creation_infos.loan_id)
            .select(
                creation_infos.loan_id,
                creation_infos.type,
                creation_infos.parent_fullname,
                creation_infos.comment_fullname
            )
            .where(loans.deleted_at.isnull())
            .where(creation_infos.loan_id == Parameter('%s'))
            .get_sql(),
            (loan_id,)
        )

        row = itgs.read_cursor.fetchone()
        if row is None:
            return JSONResponse(
                content=PHPErrorResponse(
                    errors=[
                        PHPError(
                            error_type='LOAN_NOT_FOUND',
                            error_message='There is no loan with the specified id!'
                        )
                    ]
                ).dict(),
                status_code=404
            )

        (
            this_loan_id,
            this_type,
            this_parent_fullname,
            this_comment_fullname
        ) = row

        if this_type != 0:
            return JSONResponse(
                content=PHPErrorResponse(
                    errors=[
                        PHPError(
                            error_type='LOAN_EXISTS_NOT_BY_THREAD',
                            error_message=(
                                'The specified loan exists and has creation info, '
                                'but not as a reddit url'
                            )
                        )
                    ]
                ).dict(),
                status_code=404
            )

        headers['Cache-Control'] = 'public, max-age=86400'
        return JSONResponse(
            status_code=200,
            content=ResponseFormat(
                request_thread=(
                    'https://www.reddit.com/comments/{}/redditloans/{}'.format(
                        this_parent_fullname[3:],
                        this_comment_fullname[3:]
                    )
                )
            ).dict(),
            headers=headers
        )
