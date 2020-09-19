"""This handles the deprecated endpoint /api/get_loans_by_thread.php
"""
from fastapi import APIRouter, Request
from fastapi.responses import Response, JSONResponse
from legacy.helper import find_bearer_token, try_handle_deprecated_call
from pydantic import BaseModel
from legacy.models import PHPErrorResponse, RATELIMIT_RESPONSE, PHPError
from pypika import PostgreSQLQuery as Query, Table, Parameter
import users.helper
import ratelimit_helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
import re


SLUG = 'get_loans_by_thread_legacy'
"""The slug for this legacy endpoint"""

URL_REGEX = re.compile(
    r'^https?://(www.)?reddit.com(/r/[^/]+)?/'
    + r'comments/(?P<parent_fullname>[^\?/]+)'
    + r'(/[^\?/]+/(?P<comment_fullname>[^\?/]+))?.*?$'
)
"""The regex we use for parsing the url into a parent and comment
fullname
"""


class ResponseFormat(BaseModel):
    result_type: str = 'LOANS_ULTRACOMPACT'
    success: bool = True
    loans: list


router = APIRouter()


@router.get(
    '/get_loans_by_thread.php',
    responses={
        200: {'description': 'Success'}
    }
)
def get_loans_by_thread(thread: str, request: Request):
    """Fetch the loans created from the given comment permalink.

    Result:

    ```json
    {
      "result_type": "LOANS_ULTRACOMPACT"
      "success": true,
      "loans": [loan_id, loan_id, ....]
    }
    ```
    """
    request_cost = 5
    if ratelimit_helper.is_cache_bust(request, params=('thread',)):
        request_cost = 15

    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        auth = find_bearer_token(request)
        user_id, _, perms = users.helper.get_permissions_from_header(itgs, auth, [])
        resp = try_handle_deprecated_call(itgs, request, SLUG, user_id=user_id)

        if resp is not None:
            return resp

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return JSONResponse(
                content=RATELIMIT_RESPONSE.dict(),
                status_code=429,
                headers=headers
            )

        match = URL_REGEX.match(thread)
        if match is None:
            headers['Cache-Control'] = 'immutable'
            return JSONResponse(
                content=ResponseFormat(loans=[]).dict(),
                status_code=200,
                headers=headers
            )

        matchdict = match.groupdict()
        if 'comment_fullname' not in matchdict:
            headers['Cache-Control'] = 'immutable'
            return JSONResponse(
                content=ResponseFormat(loans=[]).dict(),
                status_code=200,
                headers=headers
            )

        comment_fullname = 't1_' + matchdict['comment_fullname']
        loans = Table('loans')
        creation_infos = Table('creation_infos')
        itgs.read_cursor.execute(
            Query.from_(loans)
            .join(creation_infos)
            .on(creation_infos.loan_id == loans.id)
            .select(loans.id)
            .where(creation_infos.comment_fullname == Parameter('%s'))
            .where(loans.deleted_at.isnull())
            .get_sql(),
            (comment_fullname,)
        )
        result_loans = [r[0] for r in itgs.read_cursor.fetchall()]

        if result_loans:
            headers['Cache-Control'] = 'public, max-age=604800'
        else:
            headers['Cache-Control'] = 'public, max-age=600, stale-while-revalidate=1200'

        return JSONResponse(
            content=ResponseFormat(loans=result_loans).dict(),
            status_code=200,
            headers=headers
        )
