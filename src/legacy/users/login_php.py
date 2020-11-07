"""This handles the deprecated endpoint /api/login.php
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from legacy.helper import find_bearer_token, try_handle_deprecated_call
from legacy.models import PHPErrorResponse, PHPError
import users.helper
from users.models import PasswordAuthentication
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
import security
import time


class ResponseFormat(BaseModel):
    result_type: str = 'LOGIN_SUCCESS'
    success: bool = True
    session_id: str


SLUG = 'login_php'
"""The slug for this legacy endpoint"""

router = APIRouter()


@router.post(
    '/login.php',
    responses={
        200: {'description': 'Success', 'model': ResponseFormat},
        400: {'description': 'Failure', 'model': PHPErrorResponse},
        429: {'description': 'Ratelimited', 'model': PHPErrorResponse}
    }
)
def login(passwd_auth: PasswordAuthentication, request: Request):
    """Logs the user in by setting a cookie. This only works on old php-style endpoints
    and requires that the user have the `bypass-captcha` permission.
    """
    with LazyItgs() as itgs:
        auth = find_bearer_token(request)
        user_id, _, _ = users.helper.get_permissions_from_header(itgs, auth, [])
        resp = try_handle_deprecated_call(itgs, request, SLUG, user_id=user_id)

        if resp is not None:
            return resp

        if user_id is not None:
            return JSONResponse(
                content=PHPErrorResponse(
                    errors=[
                        PHPError(
                            error_type='ALREADY_LOGGED_IN',
                            error_message='You must be logged out to do that!'
                        )
                    ]
                ).dict(),
                status_code=403
            )

        with security.fixed_duration(0.5):
            passwd_auth_id = users.helper.get_valid_passwd_auth(itgs, passwd_auth)

        if passwd_auth_id is None:
            return JSONResponse(
                content=PHPErrorResponse(
                    errors=[
                        PHPError(
                            error_type='BAD_PASSWORD',
                            error_message='That username/password combination is not correct.'
                        )
                    ]
                ).dict(),
                status_code=400
            )

        res = users.helper.create_token_from_passauth(itgs, passwd_auth_id)
        time_until_expiry = res.expires_at_utc - time.time()
        return JSONResponse(
            status_code=200,
            content=ResponseFormat(session_id=res.token).dict(),
            headers={
                'Set-Cookie': (
                    'session_id={}; Secure; SameSite=Strict; HttpOnly; Max-Age={}'
                ).format(
                    res.token, int(time_until_expiry) - 60
                )
            }
        )
