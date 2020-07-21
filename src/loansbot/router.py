from fastapi import APIRouter, Header
from fastapi.responses import Response
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from . import models
from . import helper
import users.helper
import ratelimit_helper
import json

router = APIRouter()


@router.post(
    '/rechecks',
    responses={
        202: {'description': 'Recheck queued'},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization invalid or insufficient'}
    }
)
def create_recheck(req: models.RecheckRequest, authorization=Header(None)):
    if authorization is None:
        return Response(status_code=401)

    request_attempt_cost = 5
    request_success_cost = 145

    headers = {'x-request-cost': request_attempt_cost}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.RECHECK_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_attempt_cost):
            return Response(status_code=429, headers=headers)

        can_recheck = helper.RECHECK_PERMISSION in perms

        if not can_recheck:
            return Response(status_code=403, headers=headers)

        headers['x-request-cost'] = request_attempt_cost + request_success_cost
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_success_cost):
            return Response(status_code=429, headers=headers)

        itgs.logger.debug(
            'User {} queued a request on https://reddit.com/comments/{}/lb/{}',
            user_id, req.link_fullname[3:], req.comment_fullname[3:]
        )

        itgs.channel.queue_declare('lbrechecks')
        itgs.channel.basic_publish(
            '',
            'lbrechecks',
            json.dumps({
                'link_fullname': req.link_fullname,
                'comment_fullname': req.comment_fullname
            })
        )
        return Response(status_code=202, headers=headers)
