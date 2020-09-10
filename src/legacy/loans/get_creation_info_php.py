"""This handles the deprecated endpoint /api/get_creation_info.php. See
+get_creation_info+ for details.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from legacy.models import PHPErrorResponse, PHPError
from legacy.helper import find_bearer_token, try_handle_deprecated_call
import users.helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from pypika import PostgreSQLQuery as Query, Table, Parameter


SLUG = 'get_creation_info'
"""The slug for this legacy endpoint"""


class ResponseFormat(BaseModel):
    result_type: str = 'LOAN_CREATION_INFO'
    success: bool = True
    results: dict


router = APIRouter()


@router.get(
    '/get_creation_info.php',
    responses={
        200: {'description': 'Success', 'model': ResponseFormat},
        400: {'description': 'Arguments not understood', 'model': PHPErrorResponse}
    }
)
def get_creation_info(loan_id: str, request: Request):
    """Get the creation information for a loan or multiple loans. The loan ids
    should be a space-separated list of loan ids, and this will return how each
    of the loans were created.

    This has been replaced by the event list on loans (see
    /api/loans/{id}/detailed). The result of this endpoint is just the first
    CreationLoanEvent on the Loan.

    GET /api/get_creation_info.php?loan_id=57+58+73+125
    {
        "result_type": "LOAN_CREATION_INFO",
        "success": true,
        "results": {
            "57": null // this means we found no creation info for the loan id 57
            "58": {
                "type": 0, // this means the loan was created due to an action on reddit
                "thread": "a valid url goes here" // where the action took place
            },
            "73": {
                "type": 1, // this means the loan was created on redditloans
                "user_id": 23 // this is the admin that created the loan
                              // Requires perm 'view_admin_event_authors'

            },
            "125": {
                "type": 2 // this is a loan that was created due to a paid
                          //  summon when the database was  being regenerated
                          // in ~march 2016, but no $loan command was ever found.
            }
        }
   }

    Arguments:
    - `loan_id (str)`: A space separated list of loan ids.
    """
    with LazyItgs() as itgs:
        auth = find_bearer_token(request)
        user_id, _, _ = users.helper.get_permissions_from_header(itgs, auth, [])
        resp = try_handle_deprecated_call(itgs, request, SLUG, user_id=user_id)

        if resp is not None:
            return resp

        try:
            loan_ids = tuple(int(str_id) for str_id in loan_id.split(' '))
        except ValueError:
            return JSONResponse(
                status_code=400,
                content=PHPErrorResponse(
                    errors=[PHPError(
                        error_type='INVALID_ARGUMENT',
                        error_message=(
                            'Cannot parse given loan ids to numbers after '
                            'splitting using a space delimiter!'
                        )
                    )]
                ).dict()
            )

        if not loan_ids:
            return JSONResponse(
                status_code=400,
                content=PHPErrorResponse(
                    errors=[PHPError(
                        error_type='INVALID_ARGUMENT',
                        error_message='loan_id is required at this endpoint'
                    )]
                ).dict()
            )

        creation_infos = Table('loan_creation_infos')
        itgs.read_cursor.execute(
            Query.from_(creation_infos)
            .select(
                creation_infos.loan_id,
                creation_infos.type,
                creation_infos.parent_fullname,
                creation_infos.comment_fullname
            )
            .where(
                creation_infos.loan_id.isin(
                    [Parameter('%s') for _ in loan_ids]
                )
            )
            .get_sql(),
            loan_ids
        )

        results = dict([lid, None] for lid in loan_ids)
        row = itgs.read_cursor.fetchone()
        while row is not None:
            (
                this_loan_id,
                this_type,
                this_parent_fullname,
                this_comment_fullname
            ) = row

            if this_type == 0:
                results[this_loan_id] = {
                    'type': 0,
                    'thread': 'https://reddit.com/comments/{}/redditloans/{}'.format(
                        this_parent_fullname[3:],
                        this_comment_fullname[3:]
                    )
                }
            else:
                results[this_loan_id] = {
                    'type': this_type
                }

            row = itgs.read_cursor.fetchone()

        return JSONResponse(
            status_code=200,
            content=ResponseFormat(
                results=results
            ).dict()
        )
