from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from lbshared.user_settings import get_settings
from pypika import Table, Query, Parameter, Order
from pypika.functions import Count, Star, Max
import users.helper
import ratelimit_helper
import math

router = APIRouter()


async def query_generator(query, first_row):
    yield first_row
    yield "\n"

    with LazyItgs() as itgs:
        itgs.read_cursor.execute(query.get_sql())
        row = itgs.read_cursor.fetchone()
        while row is not None:
            for idx, part in enumerate(row):
                if idx != 0:
                    yield ','
                yield str(part)
            yield "\n"
            row = itgs.read_cursor.fetchone()


@router.get(
    '/loans.csv',
    tags=['loans', 'dump'],
    responses={
        200: {'description': 'Success; response is streamed'},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization invalid'}
    }
)
def get_csv_dump(alt_authorization: str = None, authorization=Header(None)):
    """Get a csv of all loans where the columns are

    id, lender_id, borrower_id, currency, principal_minor, principal_cents,
    principal_repayment_minor, principal_repayment_cents, created_at,
    last_repayment_at, repaid_at, unpaid_at

    This endpoint is _very_ expensive for us. Without a users ratelimit being
    increased they will almost certainly not even be able to use this endpoint
    once. We charge 5 * rows * log(rows) toward the quota and do not allow users
    which contribute to the global ratelimit. It is NOT cheaper to use this
    endpoint compared to just walking the index endpoint.

    This mainly exists for users which are willing to pay for a csv dump. You
    may use a query parameter for authorization instead of a header.
    """
    if authorization is None and alt_authorization is None:
        return Response(status_code=401)

    if authorization is None:
        authorization = f'bearer {alt_authorization}'

    attempt_request_cost = 1
    check_request_cost_cost = 10
    headers = {'x-request-cost': str(attempt_request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, ratelimit_helper.RATELIMIT_PERMISSIONS
        )

        settings = (
            ratelimit_helper.USER_RATELIMITS
            if user_id is None
            else get_settings(itgs, user_id)
        )
        if not ratelimit_helper.check_ratelimit(
                itgs, user_id, perms, attempt_request_cost,
                settings=settings):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=403, headers=headers)

        if settings.global_ratelimit_applies:
            return Response(status_code=403, headers=headers)

        headers['x-request-cost'] = (
            str(attempt_request_cost + check_request_cost_cost)
        )
        if not ratelimit_helper.check_ratelimit(
                itgs, user_id, perms, check_request_cost_cost,
                settings=settings):
            return Response(status_code=429, headers=headers)

        loans = Table('loans')
        itgs.read_cursor.execute(
            Query.from_(loans).select(Count(Star())).get_sql()
        )
        (cnt_loans,) = itgs.read_cursor.fetchone()

        real_request_cost = (
            5 * cnt_loans * max(1, math.ceil(math.log(cnt_loans)))
        )

        headers['x-request-cost'] = (
            str(
                attempt_request_cost
                + check_request_cost_cost
                + real_request_cost
            )
        )
        if not ratelimit_helper.check_ratelimit(
                itgs, user_id, perms, real_request_cost,
                settings=settings):
            return Response(status_code=429, headers=headers)

        moneys = Table('moneys')
        currencies = Table('currencies')
        principals = moneys.as_('principals')
        principal_repayments = moneys.as_('principal_repayments')
        repayment_events = Table('loan_repayment_events')
        query = (
            Query.from_(loans)
            .select(
                loans.id,
                loans.lender_id,
                loans.borrower_id,
                currencies.code,
                principals.amount,
                principals.amount_usd_cents,
                principal_repayments.amount,
                principal_repayments.amount_usd_cents,
                loans.created_at,
                Max(repayment_events.created_at),
                loans.repaid_at,
                loans.unpaid_at
            )
            .joins(principals)
            .on(principals.id == loans.principal_id)
            .joins(currencies)
            .on(currencies.id == principals.currency_id)
            .joins(principal_repayments)
            .on(principal_repayments.id == loans.principal_repayment_id)
            .left_joins(repayment_events)
            .on(repayment_events.loan_id == loans.id)
        )
        query = query.groupby(loans.id)

        headers['Content-Type'] = 'text/csv'
        headers['Content-Disposition'] = 'attachment; filename="loans.csv"'
        return StreamingResponse(
            query_generator(
                query.get_sql(),
                ','.join((
                    'id', 'lender_id', 'borrower_id', 'currency', 'principal_minor',
                    'principal_cents', 'principal_repayment_minor', 'principal_repayment_cents',
                    'created_at', 'last_repayment_at', 'repaid_at', 'unpaid_at'
                ))
            )
        )
