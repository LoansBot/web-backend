"""This handles the deprecated endpoint /api/get_dump_csv.php
"""
from fastapi import APIRouter, Request
from fastapi.responses import Response, RedirectResponse
from legacy.helper import find_bearer_token, try_handle_deprecated_call
import users.helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs


SLUG = 'get_dump_csv_legacy'
"""The slug for this legacy endpoint"""

router = APIRouter()


@router.get(
    '/get_dump_csv.php',
    responses={
        307: {'description': 'Success'}
    }
)
def get_dump_csv(request: Request):
    """Redirects to /api/loans/loans.csv with the bearer token as a query
    parameter.
    """
    with LazyItgs() as itgs:
        auth = find_bearer_token(request)
        user_id, _, _ = users.helper.get_permissions_from_header(itgs, auth, [])
        resp = try_handle_deprecated_call(itgs, request, SLUG, user_id=user_id)

        if resp is not None:
            return resp

        if auth is None:
            return Response(status_code=401)

        if user_id is None:
            return Response(status_code=403)

        return RedirectResponse(
            url=f'/api/loans/loans.csv?alt_authorization={auth.split(" ", 1)[1]}'
        )
