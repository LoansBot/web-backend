"""This module re-implements the legacy loan index page, which was the most
important, and most complicated, of the v2 website endpoints. It allows users to
fetch loan information in a variety of formats and with many different features.
This reimplements only the most core functionality.

## Responses

Each response is generally structured as

```json
{
    "result_type": str,
    "success": bool = True,
    "loans": list
}
```

Where only the format of each element in `loans` differs. There are 4 different
loan formats:

### UltraCompact

Each loan is represented as a single integer id.

### Compact

Each loan is represented as an array, where the order of the elements indicates
their meaning. This gives all the necesseary information on the loans,
sacrificing some usability and extensibility in return for serialization
performance.

The elements in the array are as follows, where their meaning is documented
under the `Standard` format.

`loan_id`, `lender_id`, `borrower_id`, `principal_cents`,
`principal_repayment_cents`, `unpaid`, `created_at`, `updated_at`

### Standard

Each loan is represented as an object with meaningful keys, but otherwise has
the same information as the `Compact` format. The keys and their meanings are as
follows:

- `loan_id (int)`: The id of the loan this is describing
- `lender_id (int)`: The id of the user who lent money in this loan
- `borrower_id (int)`: The id of the user which received money in this loan
- `principal_cents (int)`: The amount of money that the lender gave the
  borrower, converted to USD and returned in cents.
- `principal_repayment_cents (int)`: The amount of money that the borrower has
  repaid the lender toward the principal, converted to USD and returned in
  cents.
- `unpaid (bool)`: `True` if this loan is considered delinquent / past due,
  `False` otherwise.
- `created_at (int)`: When the lender gave money to the borrower, in
  milliseconds since utc epoch
- `updated_at (int)`: When this loan last meaningfully changed, in milliseconds
  since utc epoch.

### Extended

Each loan is represented as an object, just as in Standard, and has all the keys
that are in standard, plus the following bonus keys:

- `thread (str, None)`: If this loan was created from a comment on reddit, this
  is a permalink to that comment.
- `lender_name (str)`: The username of the user with id `lender_id`.
- `borrower_name (str)`: The username of the user with id `borrower_id`.
"""
from legacy.models import PHPErrorResponse, RATELIMIT_RESPONSE, PHPError
from legacy.helper import find_bearer_token, try_handle_deprecated_call
from fastapi import APIRouter, Request
from fastapi.responses import Response, JSONResponse
from starlette.types import Receive, Scope, Send
from starlette.concurrency import run_until_first_complete
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from lbshared.queries import convert_numbered_args
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from pypika.functions import Count, Star, Extract, Cast, Function
from lbshared.pypika_funcs import Greatest
import users.helper
import ratelimit_helper
import math
from datetime import datetime


SLUG = 'loans_php'
"""The slug for this legacy endpoint"""

router = APIRouter()


@router.get('/loans.php')
def index_loans(
        request: Request,
        id: int = 0,
        after_time: int = 0,
        before_time: int = 0,
        borrower_id: int = 0,
        lender_id: int = 0,
        includes_user_id: int = 0,
        borrower_name: str = '',
        lender_name: str = '',
        includes_user_name: str = '',
        principal_cents: int = 0,
        principal_repayment_cents: int = -1,
        unpaid: int = -1,
        repaid: int = -1,
        format: int = 2,
        limit: int = 10):
    id = _zero_to_none(id)
    after_time = _zero_to_none(after_time)
    before_time = _zero_to_none(before_time)
    borrower_id = _zero_to_none(borrower_id)
    lender_id = _zero_to_none(lender_id)
    includes_user_id = _zero_to_none(includes_user_id)
    borrower_name = _blank_to_none(borrower_name)
    lender_name = _blank_to_none(lender_name)
    includes_user_name = _blank_to_none(includes_user_name)
    principal_cents = _zero_to_none(principal_cents)
    principal_repayment_cents = _neg1_to_none(principal_repayment_cents)
    unpaid = _neg1_to_none(unpaid)
    repaid = _neg1_to_none(repaid)
    limit = _zero_to_none(limit)

    attempt_request_cost = 5
    headers = {'x-request-cost': str(attempt_request_cost)}
    with LazyItgs() as itgs:
        auth = find_bearer_token(request)
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, auth, ratelimit_helper.RATELIMIT_PERMISSIONS)
        resp = try_handle_deprecated_call(itgs, request, SLUG, user_id=user_id)

        if resp is not None:
            return resp

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, attempt_request_cost):
            return JSONResponse(
                content=RATELIMIT_RESPONSE.dict(),
                status_code=429,
                headers=headers
            )

        if limit is not None and (limit < 0 or limit >= 1000):
            return JSONResponse(
                content=PHPErrorResponse(
                    errors=[
                        PHPError(
                            error_type='INVALID_PARAMETER',
                            error_message=(
                                'Limit must be 0 or a positive integer less than 1000'
                            )
                        )
                    ]
                ).dict(),
                status_code=400
            )

        if format not in (0, 1, 2, 3):
            return JSONResponse(
                content=PHPErrorResponse(
                    errors=[
                        PHPError(
                            error_type='INVALID_PARAMETER',
                            error_message=(
                                'Format must be 0, 1, 2, or 3'
                            )
                        )
                    ]
                ).dict(),
                status_code=400
            )

        loans = Table('loans')
        if limit is None:
            itgs.read_cursor.execute(
                Query.from_(loans)
                .select(Count(Star()))
                .get_sql()
            )
            (real_request_cost,) = itgs.read_cursor.fetchone()
        else:
            real_request_cost = limit

        if format == 0:
            real_request_cost = math.ceil(math.log(real_request_cost + 1))
        elif format < 3:
            # Cost needs to be greater than loans show
            real_request_cost = 25 + real_request_cost * 2
        else:
            # We need to ensure the cost is greater than using the /users show
            # endpoint for getting usernames
            real_request_cost = 25 + math.ceil(real_request_cost * 4.1)

        moneys = Table('moneys')
        principals = moneys.as_('principals')
        principal_repayments = moneys.as_('principal_repayments')

        usrs = Table('users')
        lenders = usrs.as_('lenders')
        borrowers = usrs.as_('borrowers')

        query = (
            Query.from_(loans)
            .where(loans.deleted_at.isnull())
            .orderby(loans.id, order=Order.desc)
        )
        params = []
        joins = set()

        def _add_param(val):
            params.append(val)
            return Parameter(f'${len(params)}')

        def _ensure_principals():
            nonlocal query
            if 'principals' in joins:
                return
            joins.add('principals')
            query = (
                query.join(principals)
                .on(principals.id == loans.principal_id)
            )

        def _ensure_principal_repayments():
            nonlocal query
            if 'principal_repayments' in joins:
                return
            joins.add('principal_repayments')
            query = (
                query.join(principal_repayments)
                .on(principal_repayments.id == loans.principal_repayment_id)
            )

        def _ensure_lenders():
            nonlocal query
            if 'lenders' in joins:
                return
            joins.add('lenders')
            query = (
                query.join(lenders)
                .on(lenders.id == loans.lender_id)
            )

        def _ensure_borrowers():
            nonlocal query
            if 'borrowers' in joins:
                return
            joins.add('borrowers')
            query = (
                query.join(borrowers)
                .on(borrowers.id == loans.borrower_id)
            )

        if after_time is not None:
            query = (
                query.where(
                    loans.created_at > _add_param(
                        datetime.fromtimestamp(after_time / 1000.0)
                    )
                )
            )

        if before_time is not None:
            query = (
                query.where(
                    loans.created_at < _add_param(
                        datetime.fromtimestamp(before_time / 1000.0)
                    )
                )
            )

        if principal_cents is not None:
            _ensure_principals()
            query = (
                query.where(
                    principals.amount_usd_cents == _add_param(principal_cents)
                )
            )

        if principal_repayment_cents is not None:
            _ensure_principal_repayments()
            query = (
                query.where(
                    principal_repayments.amount_usd_cents == _add_param(
                        principal_repayment_cents
                    )
                )
            )

        if borrower_id is not None:
            query = (
                query.where(
                    loans.borrower_id == _add_param(borrower_id)
                )
            )

        if borrower_name is not None:
            _ensure_borrowers()
            query = (
                query.where(
                    borrowers.username == _add_param(borrower_name)
                )
            )

        if lender_name is not None:
            _ensure_lenders()
            query = (
                query.where(
                    lenders.username == _add_param(lender_name)
                )
            )

        if includes_user_id is not None:
            prm = _add_param(includes_user_id)
            query = (
                query.where(
                    (loans.borrower_id == prm) |
                    (loans.lender_id == prm)
                )
            )

        if includes_user_name is not None:
            _ensure_lenders()
            _ensure_borrowers()
            prm = _add_param(includes_user_name)
            query = (
                query.where(
                    (lenders.username == prm) |
                    (borrowers.username == prm)
                )
            )

        if unpaid is not None:
            if unpaid:
                query = query.where(loans.unpaid_at.notnull())
            else:
                query = query.where(loans.unpaid_at.isnull())

        if repaid is not None:
            if repaid:
                query = query.where(loans.repaid_at.notnull())
            else:
                query = query.where(loans.repaid_at.isnull())

        if limit is not None:
            query = query.limit(limit)

        # `loan_id`, `lender_id`, `borrower_id`, `principal_cents`,
        # `principal_repayment_cents`, `unpaid`, `created_at`, `updated_at`
        query = query.select(loans.id)
        if format > 0:
            _ensure_principals()
            _ensure_principal_repayments()
            event_tables = (
                Table('loan_repayment_events'),
                Table('loan_unpaid_events'),
                Table('loan_admin_events')
            )
            latest_events = Table('latest_events')
            query = (
                query.with_(
                    Query.from_(loans)
                    .select(
                        loans.id.as_('loan_id'),
                        Greatest(
                            loans.created_at,
                            *(tbl.created_at for tbl in event_tables)
                        ).as_('latest_event_at')
                    )
                    .groupby(loans.id),
                    'latest_events'
                )
                .left_join(latest_events)
                .on(latest_events.loan_id == loans.id)
                .select(
                    loans.lender_id,
                    loans.borrower_id,
                    principals.amount_usd_cents,
                    principal_repayments.amount_usd_cents,
                    loans.unpaid_at.notnull(),
                    Cast(
                        Extract('epoch', loans.created_at) * 1000,
                        'bigint'
                    ),
                    Cast(
                        Extract('epoch', latest_events.latest_event_at) * 1000,
                        'bigint'
                    )
                )
            )

            if format == 3:
                creation_infos = Table('loan_creation_infos')
                _ensure_borrowers()
                _ensure_lenders()
                query = (
                    query.join(creation_infos)
                    .on(creation_infos.loan_id == loans.id)
                    .select(
                        Function(
                            'SUBSTRING',
                            creation_infos.parent_fullname,
                            4
                        ),
                        Function(
                            'SUBSTRING',
                            creation_infos.comment_fullname,
                            4
                        ),
                        lenders.username,
                        borrowers.username
                    )
                )

        sql, args = convert_numbered_args(query.get_sql(), params)
        if format == 0:
            return _UltraCompactResponse((sql, args))
        elif format == 1:
            return _CompactResponse((sql, args))
        elif format == 2:
            return _StandardResponse((sql, args))
        else:
            return _ExtendedResponse((sql, args))


def _zero_to_none(val: int):
    if val == 0:
        return None
    return val


def _neg1_to_none(val: int):
    if val == -1:
        return None
    return val


def _blank_to_none(val: str):
    if val.strip() == '':
        return None
    return val


def _int_to_bool(val: int):
    return val == 1


class _CursorStreamedResponse(Response):
    def __init__(self, query):
        self.query = query
        self.status_code = 200
        self.media_type = 'application/json'
        self.background = None
        self.init_headers(None)

    async def listen_for_disconnect(self, receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break

    async def stream_response(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        buffer = bytearray(4096)
        view = memoryview(buffer)
        pos = 0

        async def write(data):
            nonlocal pos
            if pos + len(data) >= len(buffer):
                await send({"type": "http.response.body", "body": view[:pos], "more_body": True})
                pos = 0

            view[pos:pos + len(data)] = data
            pos += len(data)

        with LazyItgs() as itgs:
            await write(b'[')
            itgs.read_cursor.execute(*self.query)
            row = itgs.read_cursor.fetchone()
            if row is None:
                await write(b']')
                return
            await self.write_row(row, write)
            row = itgs.read_cursor.fetchone()
            while row is not None:
                await write(b',')
                await self.write_row(row, write)
                row = itgs.read_cursor.fetchone()
        await write(b']')
        await send({"type": "http.response.body", "body": view[:pos], "more_body": False})

    async def write_row(self, row, write):
        raise NotImplementedError

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await run_until_first_complete(
            (self.stream_response, {"send": send}),
            (self.listen_for_disconnect, {"receive": receive}),
        )


class _UltraCompactResponse(_CursorStreamedResponse):
    async def write_row(self, row, write):
        await write(str(row[0]).encode('ascii'))


class _CompactResponse(_CursorStreamedResponse):
    FORMAT = '[' + '{},' * 7 + '{}]'

    async def write_row(self, row, write):
        await write(
            _CompactResponse.FORMAT.format(
                *row
            ).encode('ascii'))


class _StandardResponse(_CursorStreamedResponse):
    FORMAT = (
        '{{"loan_id":{},"lender_id":{},"borrower_id":{},'
        '"principal_cents":{},"principal_repayment_cents":{},'
        '"unpaid":{},"created_at":{},"updated_at":{}}}'
    )

    async def write_row(self, row, write):
        await write(
            _StandardResponse.FORMAT.format(
                *row
            )
        )


class _ExtendedResponse(_CursorStreamedResponse):
    FORMAT_NO_THREAD = (
        '{{"loan_id":{},"lender_id":{},"borrower_id":{},'
        '"principal_cents":{},"principal_repayment_cents":{},'
        '"unpaid":{},"created_at":{},"updated_at":{},'
        '"thread":null,"lender_name":"{}","borrower_name":"{}"}}'
    )

    FORMAT_WITH_THREAD = (
        '{{"loan_id":{},"lender_id":{},"borrower_id":{},'
        '"principal_cents":{},"principal_repayment_cents":{},'
        '"unpaid":{},"created_at":{},"updated_at":{},'
        '"thread":"https://reddit.com/comments/{}/rl/{}",'
        '"lender_name":"{}","borrower_name":"{}"}}'
    )

    async def write_row(self, row, write):
        if row[8] is None:
            await write(
                _StandardResponse.FORMAT.format(
                    *row[:8],
                    *row[10:]
                )
            )
            return

        await write(
            _StandardResponse.FORMAT.format(*row)
        )
