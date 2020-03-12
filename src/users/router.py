from fastapi import APIRouter
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter
from . import helper
from . import models
import security
import integrations as itgs


router = APIRouter()


@router.post(
    '/login',
    tags=['users', 'auth'],
    responses={
        200: {'model': models.TokenResponse},
        403: {
            'description': (
                'The provided authentication could not be identified'
            )
        }
    }
)
def login(auth: models.PasswordAuthentication):
    with itgs.database() as conn:
        auth_id = None
        with security.fixed_duration(0.5):
            auth_id = helper.get_valid_passwd_auth(conn, auth)
        if auth_id is None:
            return Response(status_code=403)

        res = helper.create_token_from_passauth(conn, auth_id)
        return JSONResponse(status_code=200, content=res.dict())


@router.post(
    '/logout',
    tags=['users', 'auth'],
    responses={
        200: {'description': 'Logout successful'},
        403: {'description': 'Token authentication failed'}
    }
)
def logout(auth: models.TokenAuthentication):
    with itgs.database() as conn:
        auth_id, user_id = helper.get_auth_info_from_token_auth(conn, auth)
        if auth_id is None:
            return Response(status_code=403)

        authtokens = Table('authtokens')
        conn.execute(
            Query
            .from_(authtokens)
            .delete()
            .where(authtokens.id == Parameter('%s'))
            .get_sql(),
            (auth_id,)
        )
        conn.commit()
        return Response(status_code=200)
