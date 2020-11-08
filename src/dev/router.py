from fastapi import APIRouter
from fastapi.responses import JSONResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
import dev.models
import ratelimit_helper
import time


router = APIRouter()


@router.get('/global_ratelimit', response_model=dev.models.RatelimitResponse)
def global_ratelimit():
    """This function is mainly for debugging purposes. It returns the current
    state of the global ratelimit.
    """
    with LazyItgs() as itgs:
        settings = ratelimit_helper.GLOBAL_RATELIMITS
        doc = itgs.kvs_db.collection(ratelimit_helper.RATELIMIT_TOKENS_COLLECTION).document('None')
        if not doc.read():
            return JSONResponse(
                status_code=200,
                content=dev.models.RatelimitResponse(
                    effective_tokens=settings.max_tokens,
                    max_tokens=settings.max_tokens,
                    refill_time_ms=settings.refill_time_ms,
                    refill_amount=settings.refill_amount
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
                refill_amount=settings.refill_amount
            ).dict()
        )
