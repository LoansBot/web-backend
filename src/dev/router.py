from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
import lbshared.user_settings
import users.helper
import dev.models
import ratelimit_helper
import time


router = APIRouter()


@router.get('/global_ratelimit', response_model=dev.models.RatelimitResponse)
def global_ratelimit():
    """This function returns the current state of the global ratelimit. Note
    that the ratelimit status can and will change as requests come in.
    """
    settings = ratelimit_helper.GLOBAL_RATELIMITS
    with LazyItgs() as itgs:
        return _ratelimit_from_key_and_settings(itgs, 'global', settings)


@router.get('/unauthed_ratelimit', response_model=dev.models.RatelimitResponse)
def unauthed_ratelimit():
    """This function returns the current state of the ratelimit for all
    unauthenticated requests.
    """
    settings = ratelimit_helper.USER_RATELIMITS
    with LazyItgs() as itgs:
        return _ratelimit_from_key_and_settings(itgs, 'None', settings)


@router.get(
    '/ratelimit',
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Missing authentication'},
        403: {'description': 'Bad authentication'},
    },
    response_model=dev.models.RatelimitResponse
)
def ratelimit(authorization: str = Header(None)):
    """This function returns the current state of the logged in users ratelimit.
    Note that the ratelimit status can and will change as requests come in.
    """
    if authorization is None:
        return Response(status_code=401)

    with LazyItgs() as itgs:
        _, user_id = users.helper.check_permissions_from_header(itgs, authorization, [])
        if user_id is None:
            return Response(status_code=403)

        user_specific_settings = lbshared.user_settings.get_settings(itgs, user_id)

        default_settings = ratelimit_helper.USER_RATELIMITS
        settings = lbshared.ratelimits.Settings(
            collection_name=default_settings.collection_name,
            max_tokens=user_specific_settings.ratelimit_max_tokens or default_settings.max_tokens,
            refill_amount=(
                user_specific_settings.ratelimit_refill_amount or default_settings.refill_amount),
            refill_time_ms=(
                user_specific_settings.ratelimit_refill_time_ms or default_settings.refill_time_ms),
            strict=(
                default_settings.strict
                if user_specific_settings.ratelimit_strict is None
                else user_specific_settings.ratelimit_strict
            )
        )
        return _ratelimit_from_key_and_settings(itgs, str(user_id), settings)


def _ratelimit_from_key_and_settings(itgs, key, settings):
    doc = itgs.kvs_db.collection(ratelimit_helper.RATELIMIT_TOKENS_COLLECTION).document(key)
    if not doc.read():
        return JSONResponse(
            status_code=200,
            content=dev.models.RatelimitResponse(
                effective_tokens=settings.max_tokens,
                max_tokens=settings.max_tokens,
                refill_time_ms=settings.refill_time_ms,
                refill_amount=settings.refill_amount,
                strict=settings.strict
            ).dict()
        )

    cur_time = time.time()
    time_since_refill = cur_time - doc.body['last_refill']
    num_refills = int((time_since_refill * 1000) / settings.refill_time_ms)
    effective_tokens = min(
        settings.max_tokens,
        doc.body['tokens'] + num_refills * settings.refill_amount
    )
    new_last_refill = doc.body['last_refill'] + num_refills * (settings.refill_time_ms / 1000.0)
    return JSONResponse(
        status_code=200,
        content=dev.models.RatelimitResponse(
            current_tokens=doc.body['tokens'],
            last_refill=doc.body['last_refill'],
            time_since_refill=time_since_refill,
            num_refills=num_refills,
            effective_tokens=effective_tokens,
            new_last_refill=new_last_refill,
            max_tokens=settings.max_tokens,
            refill_time_ms=settings.refill_time_ms,
            refill_amount=settings.refill_amount,
            strict=settings.strict
        ).dict()
    )
