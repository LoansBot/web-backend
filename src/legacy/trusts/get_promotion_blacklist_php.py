"""This handles the deprecated endpoint /api/get_promotion_blacklist.php
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import typing
from legacy.helper import find_bearer_token, try_handle_deprecated_call
import users.helper
import trusts.helper
from lbshared.user_settings import get_settings
from lbshared.queries import convert_numbered_args
from lbshared.pypika_crits import ExistsCriterion as Exists
from pydantic import BaseModel
from legacy.models import PHPErrorResponse, RATELIMIT_RESPONSE
from pypika import PostgreSQLQuery as Query, Table, Parameter
import ratelimit_helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs


SLUG = 'get_promotion_blacklist'
"""The slug for this legacy endpoint"""


class ResponseEntry(BaseModel):
    id: int
    username: str
    mod_username: str = 'LoansBot'
    reason: str
    added_at: float


class ResponseFormat(BaseModel):
    result_type: str = 'PROMOTION_BLACKLIST'
    success: bool = True
    list: typing.List[ResponseEntry]


router = APIRouter()


@router.get(
    '/get_promotion_blacklist.php',
    responses={
        200: {'description': 'Success', 'model': ResponseFormat},
        400: {'description': 'Bad Username', 'model': PHPErrorResponse}
    }
)
def get_promotion_blacklist(
        request: Request, username: str = None, min_id: int = None,
        max_id: int = None, limit: int = 10):
    """Get up to the given limit number of users which match the given criteria
    and are barred from being promoted.

    This requires the `view-others-trust` permission to include results that
    aren't the authenticated user and the `view-self-trust` reason to include
    the authenticated user in the response. The mod username will always be
    replaced with `LoansBot`. Permissions are not consistently checked and this
    information is not considered secure, however these permissions are used to
    avoid this endpoint being used in browser extensions as it's not intended for
    that purpose.

    The reason is replaced with users trust status, so for example "unknown" or
    "bad". Users with the trust status "good" are not returned in this endpoint.
    This attempts to emulate the behavior of the promotion blacklist within the
    new improved trust system.

    Arguments:
    - `username (str, None)`: If specified only users which match the given username
      with an ILIKE query will be returned.
    - `min_id (int, None)`: If specified only TRUSTS which have an id of the given value
      or higher will be returned. This can be used to walk trusts.
    - `max_id (int, None)`: If specified only TRUSTS which have an id of the given value
      or lower will be returned. This can be used to walk trusts.
    - `limit (int)`: The maximum number of results to return. For users for which the
      global ratelimit is applied this is restricted to 3 or fewer. For other users this
      has no explicit limit but does linearly increase the request cost.

    Result:
    ```json
    {
      "result_type": "PROMOTION_BLACKLIST"
      "success": true,
      "list": {
          {
              id: 1,
              username: "johndoe",
              mod_username: "Tjstretchalot",
              reason: "some text here",
              added_at: <utc milliseconds>
          },
          ...
      }
    }
    ```
    """
    with LazyItgs() as itgs:
        auth = find_bearer_token(request)
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, auth, (
                trusts.helper.VIEW_OTHERS_TRUST_PERMISSION,
                trusts.helper.VIEW_SELF_TRUST_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )
        resp = try_handle_deprecated_call(itgs, request, SLUG, user_id=user_id)

        if resp is not None:
            return resp

        if limit <= 0:
            limit = 10

        settings = get_settings(itgs, user_id) if user_id is not None else None
        if limit > 3 and (settings is None or settings.global_ratelimit_applies):
            # Avoid accidentally blowing through the global ratelimit
            limit = 3

        request_cost = 7 * limit
        headers = {'x-request-cost': str(request_cost)}
        if not ratelimit_helper.check_ratelimit(
                itgs, user_id, perms, request_cost, settings=settings):
            return JSONResponse(
                content=RATELIMIT_RESPONSE.dict(),
                status_code=429,
                headers=headers
            )

        can_view_others_trust = trusts.helper.VIEW_OTHERS_TRUST_PERMISSION in perms
        can_view_self_trust = trusts.helper.VIEW_SELF_TRUST_PERMISSION in perms

        if not can_view_others_trust and not can_view_self_trust:
            headers['Cache-Control'] = 'no-store'
            headers['Pragma'] = 'no-cache'
            return JSONResponse(
                content=ResponseFormat(list=[]).dict(),
                status_code=200,
                headers=headers
            )

        if can_view_others_trust and can_view_self_trust:
            headers['Cache-Control'] = 'public, max-age=600'
        else:
            headers['Cache-Control'] = 'no-store'
            headers['Pragma'] = 'no-cache'

        usrs = Table('users')
        trsts = Table('trusts')
        query = (
            Query.from_(usrs)
            .select(
                trsts.id,
                usrs.username,
                trsts.status,
                trsts.created_at
            )
            .where(
                Exists(
                    Query.from_(trsts)
                    .where(trsts.user_id == users.id)
                    .where(trsts.status != Parameter('$1'))
                )
            )
            .limit('$2')
        )
        args = ['good', limit]

        if username is not None:
            query = query.where(usrs.username.ilike(Parameter(f'${len(args) + 1}')))
            args.append(username)

        if min_id is not None:
            query = query.where(trsts.id >= Parameter(f'${len(args) + 1}'))
            args.append(min_id)

        if max_id is not None:
            query = query.where(trsts.id <= Parameter(f'${len(args) + 1}'))
            args.append(max_id)

        if not can_view_self_trust:
            query = query.where(users.id != Parameter(f'${len(args) + 1}'))
            args.append(user_id)

        if not can_view_others_trust:
            query = query.where(users.id == Parameter(f'${len(args) + 1}'))
            args.append(user_id)

        itgs.read_cursor.execute(
            *convert_numbered_args(
                query.get_sql(),
                args
            )
        )

        denylist = []
        row = itgs.read_cursor.fetchone()
        while row is not None:
            (
                trust_id,
                username,
                status,
                trust_created_at
            ) = row
            denylist.append(
                ResponseEntry(
                    id=trust_id,
                    username=username,
                    reason=status,
                    added_at=(trust_created_at.timestamp() * 1000)
                )
            )
            row = itgs.read_cursor.fetchone()

        return JSONResponse(
            content=ResponseFormat(list=denylist),
            status_code=200,
            headers=headers
        )
