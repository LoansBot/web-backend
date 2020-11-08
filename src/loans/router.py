from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from . import models
from . import helper
import users.helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
import lbshared.queries
from pypika import Table, Query, Parameter, Order
import math
from datetime import datetime
import sqlparse
import time
from .edit_router import router as edit_router
from .get_csv_dump import router as get_csv_dump_router
from .stats_router import router as stats_router
import ratelimit_helper
import re


router = APIRouter()
router.include_router(edit_router)
router.include_router(get_csv_dump_router)
router.include_router(stats_router)


@router.get(
    '',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.LoansResponse}
    }
)
def index(
        loan_id: int = None,
        after_id: int = None, before_id: int = None,
        after_time: int = None, before_time: int = None,
        borrower_name: str = None, lender_name: str = None, user_operator: str = 'AND',
        unpaid: bool = None, repaid: bool = None,
        include_deleted: bool = False, order: str = 'natural', limit: int = 25,
        fmt: int = 0, dry_run: bool = False, dry_run_text: bool = False,
        authorization: str = Header(None)):
    if limit <= 0:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['limit'],
                    'msg': 'Must be positive',
                    'type': 'range_error'
                }
            }
        )

    if user_operator not in ('AND', 'OR'):
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['user_operator'],
                    'msg': 'Must be AND or OR (defaults to AND)',
                    'type': 'value_error'
                }
            }
        )

    if lender_name is None or borrower_name is None:
        user_operator = 'AND'

    acceptable_orders = ('natural', 'date_desc', 'date_asc', 'id_desc', 'id_asc')
    if order not in acceptable_orders:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['order'],
                    'msg': f'Must be one of {acceptable_orders}',
                    'type': 'value_error'
                }
            }
        )

    now_time = time.time()
    if before_time is not None and before_time > now_time * 10:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['before_time'],
                    'msg': 'Absurd value; are you using milliseconds instead of seconds?',
                    'type': 'range_error'
                }
            }
        )

    if after_time is not None and after_time > now_time * 10:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['after_time'],
                    'msg': 'Absurd value; are you using milliseconds instead of seconds?',
                    'type': 'range_error'
                }
            }
        )

    if lender_name == '':
        lender_name = None

    if borrower_name == '':
        borrower_name = None

    request_cost = limit

    if order != 'natural':
        # This isn't significantly more theoretically expensive since every
        # sort is indexed, but it is probably less cache-local which is
        # going to inflate the cost
        request_cost *= 2

    if loan_id is not None:
        request_cost = 1

    if fmt == 0:
        # You're doing what we want you to do! The only real cost for us is the
        # postgres computations.
        request_cost = math.ceil(math.log(request_cost + 1))
    elif fmt == 1:
        # This is essentially increasing our cost in exchange for simplifying
        # their implementation. We will punish them for doing this in
        # comparison to the approach we want them to take (fmt 0 then fetch
        # each loan individually), but not too severely for small requests.
        # They are going from log(N) + N to 2N
        request_cost = 25 + request_cost * 2
    else:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['fmt'],
                    'msg': 'Must be 0 or 1 (defaults to 0)',
                    'type': 'range_error'
                }
            }
        )

    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.DELETED_LOANS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        real_req_cost = 1 if dry_run else request_cost
        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, real_req_cost):
            return Response(
                status_code=429,
                headers={'x-request-cost': str(request_cost)}
            )

        loans = Table('loans')
        usrs = Table('users')
        lenders = usrs.as_('lenders')
        borrowers = usrs.as_('borrowers')

        args = []
        if fmt == 0:
            query = Query.from_(loans).select(loans.id)
            joins = set()
        else:
            query = helper.get_basic_loan_info_query()
            joins = {'lenders', 'borrowers'}

        if loan_id is not None:
            query = query.where(loans.id == Parameter(f'${len(args) + 1}'))
            args.append(loan_id)

        if after_id is not None:
            query = query.where(loans.id > Parameter(f'${len(args) + 1}'))
            args.append(after_id)

        if before_id is not None:
            query = query.where(loans.id < Parameter(f'${len(args) + 1}'))
            args.append(before_id)

        if after_time is not None:
            after_datetime = datetime.fromtimestamp(after_time)
            query = query.where(loans.created_at > Parameter(f'${len(args) + 1}'))
            args.append(after_datetime)

        if before_time is not None:
            before_datetime = datetime.fromtimestamp(before_time)
            query = query.where(loans.created_at < Parameter(f'${len(args) + 1}'))
            args.append(before_datetime)

        if borrower_name is not None:
            if 'borrowers' not in joins:
                query = query.join(borrowers).on(borrowers.id == loans.borrower_id)
                joins.add('borrowers')

            if user_operator == 'AND':
                query = query.where(borrowers.username == Parameter(f'${len(args) + 1}'))
                args.append(borrower_name.lower())

        if lender_name is not None:
            if 'lenders' not in joins:
                query = query.join(lenders).on(lenders.id == loans.lender_id)
                joins.add('lenders')

            if user_operator == 'AND':
                query = query.where(lenders.username == Parameter(f'${len(args) + 1}'))
                args.append(lender_name.lower())

        if user_operator == 'OR' and borrower_name is not None and lender_name is not None:
            query = query.where(
                (lenders.username == Parameter(f'${len(args) + 1}'))
                | (borrowers.username == Parameter(f'${len(args) + 2}'))
            )
            args.append(lender_name.lower())
            args.append(borrower_name.lower())

        if unpaid is False:
            query = query.where(loans.unpaid_at.isnull())
        elif unpaid:
            query = query.where(loans.unpaid_at.notnull())

        if repaid is False:
            query = query.where(loans.repaid_at.isnull())
        elif repaid:
            query = query.where(loans.repaid_at.notnull())

        can_see_deleted = helper.DELETED_LOANS_PERM in perms
        if not can_see_deleted or not include_deleted:
            query = query.where(loans.deleted_at.isnull())

        if order == 'date_desc':
            query = query.orderby(loans.created_at, order=Order.desc)
        elif order == 'date_asc':
            query = query.orderby(loans.created_at)
        elif order == 'id_desc':
            query = query.orderby(loans.id, order=Order.desc)
        elif order == 'id_asc':
            query = query.orderby(loans.id)

        query = query.limit(limit)
        sql = query.get_sql()
        sql, args = lbshared.queries.convert_numbered_args(sql, args)

        if dry_run:
            func_args = f'''
                loan_id: {loan_id},
                after_id: {after_id},
                before_id: {before_id},
                after_time: {after_time},
                before_time: {before_time},
                borrower_name: {repr(borrower_name)},
                lender_name: {repr(lender_name)},
                user_operator: '{user_operator}'; (accepts ('AND', 'OR')),
                unpaid: {unpaid},
                repaid: {repaid},
                include_deleted: {include_deleted}; (ignored? ({not can_see_deleted})),
                limit: {limit},
                order: '{order}'; (accepts {acceptable_orders}),
                fmt: {fmt},
                dry_run: {dry_run},
                dry_run_text: {dry_run_text},
                authorization: <REDACTED>; (null? ({authorization is None}))
            '''
            func_args = '\n'.join([l.strip() for l in func_args.splitlines() if l.strip()])
            formatted_sql = sqlparse.format(sql, keyword_case='upper', reindent=True)
            if dry_run_text:
                return Response(
                    status_code=200,
                    content=(
                        f'Your request had the following arguments:\n\n```\n{func_args}\n```\n\n '
                        + 'It would have executed the following SQL:\n\n```\n'
                        + formatted_sql + '\n```\n\n'
                        + 'With the following arguments:\n\n```\n'
                        + '\n'.join([str(s) for s in args])
                        + '\n```\n\n'
                        + f'The request would have cost {request_cost} towards your quota.'
                    ),
                    headers={
                        'Content-Type': 'text/plain',
                        'x-request-cost': '1'
                    }
                )

            return JSONResponse(
                status_code=200,
                content={
                    'func_args': func_args,
                    'query': sql,
                    'formatted_query': formatted_sql,
                    'query_args': args,
                    'request_cost': request_cost
                },
                headers={
                    'x-request-cost': '1'
                }
            )

        itgs.read_cursor.execute(sql, args)
        if fmt == 0:
            result = itgs.read_cursor.fetchall()
            result = [i[0] for i in result]
        else:
            result = []
            row = itgs.read_cursor.fetchone()
            while row is not None:
                result.append(helper.parse_basic_loan_info(row).dict())
                row = itgs.read_cursor.fetchone()

        return JSONResponse(
            content=result, status_code=200, headers={
                'x-request-cost': str(request_cost)
            }
        )


@router.get(
    '/threads',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.LoansResponse}
    }
)
def loans_by_thread(
        url: str = None, parent_fullname: str = None,
        comment_fullname: str = None, fmt: int = 0,
        after_id: int = None, authorization=Header(None)):
    """Fetch the loans that belong to the thread. The thread may be specified
    either as a url, in which the following two are examples of how the url
    must be structured:

    - https://reddit.com/comments/{parent_id}/*
    - https://www.reddit.com/r/*/comments/{parent_id}/*

    or by just by the fullname of the thread (e.g. `t3_foobar`). A comment may
    be supplied (either via a direct link to the comment or by supplying the
    comment fullname), in which case the result is limited to loans created at
    that specific comment.

    If none of `thread`, `parent_fullname`, and `comment_fullname` are set this
    will return a 422.

    In the vast majority of cases there is only 1 loan per thread. But for the
    threads that are reused for creating loans this will paginate using id asc,
    which is the most performant way to paginate.

    Arguments:
    - `url (str, None)`: The full url to parse for a parent fullname and
      potentially a comment fullname. Ignored if parent or comment fullname
      are set.
    - `parent_fullname (str, None)`: The fullname (e.g. `t3_foobar`) of the
      thread to return loans created in. Ignored if `comment_fullname` is set,
      overrides `thread` if set.
    - `comment_fullname (str, None)`: The fullname (e.g. `t1_foobar`) of the
      comment to return loans created in. Overrides `thread` and
      `parent_fullname` if set.
    - `fmt (int)`: Either 0 (return ids) or 1 (return basic info, triples cost)
    - `after_id (int, None)`: If specified only ids with at least this id are
      returned.
    """
    if all((s is None) for s in (url, parent_fullname, comment_fullname)):
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['url'],
                    'msg': 'One of url, parent_fullname, and comment_fullname must be set',
                    'type': 'value_error'
                }
            }
        )

    if comment_fullname is None:
        if parent_fullname is None:
            url_regex = (
                r'^https?://(www.)?reddit.com(/r/[^/]+)?/'
                + r'comments/(?P<parent_fullname>[^\?/]+)'
                + r'(/[^\?/]+/(?P<comment_fullname>[^\?/]+))?.*?$'
            )
            match = re.match(url_regex, url)

            if match is None:
                return JSONResponse(
                    status_code=422,
                    content={
                        'detail': {
                            'loc': ['url'],
                            'msg': 'Must be a thread or comment permalink.',
                            'type': 'value_error'
                        }
                    }
                )

            match_dict = match.groupdict()
            if 'comment_fullname' in match_dict:
                comment_fullname = 't1_' + match_dict['comment_fullname']
            parent_fullname = 't3_' + match_dict['parent_fullname']

    if fmt not in (0, 1):
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['fmt'],
                    'msg': 'must be one of (0, 1)',
                    'type': 'value_error'
                }
            }
        )

    limit = 3
    request_cost = 25 if fmt == 0 else 75
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.DELETED_LOANS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        can_see_deleted = helper.DELETED_LOANS_PERM in perms

        loans = Table('loans')
        creation_infos = Table('loan_creation_infos')
        if fmt == 0:
            query = Query.from_(loans).select(loans.id)
        else:
            query = helper.get_basic_loan_info_query().select(loans.id)

        query = (
            query.join(creation_infos)
            .on(creation_infos.loan_id == loans.id)
        )

        if not can_see_deleted:
            query = query.where(loans.deleted_at.isnull())

        params = []
        if after_id is not None:
            query = query.where(loans.id > Parameter('%s'))
            params.append(after_id)

        if comment_fullname is not None:
            query = query.where(creation_infos.comment_fullname == Parameter('%s'))
            params.append(comment_fullname)
        else:
            query = query.where(creation_infos.parent_fullname == Parameter('%s'))
            params.append(parent_fullname)

        query = (
            query.orderby(loans.id, order=Order.asc)
            .limit(limit + 1)
        )

        result_loans = []
        have_more = False
        last_id = None

        itgs.read_cursor.execute(query.get_sql(), params)
        row = itgs.read_cursor.fetchone()
        while row is not None:
            if len(result_loans) >= limit:
                have_more = True
                row = itgs.read_cursor.fetchone()
                continue

            last_id = row[-1]
            if fmt == 0:
                result_loans.append(row[0])
            else:
                result_loans.append(helper.parse_basic_loan_info(row).dict())

            row = itgs.read_cursor.fetchone()

        result = {'loans': result_loans}
        if have_more:
            result['next_id'] = last_id

        if have_more:
            headers['Cache-Control'] = 'public, max-age=604800'
        else:
            headers['Cache-Control'] = 'public, max-age=86400'

        return JSONResponse(
            content=result,
            status_code=200,
            headers=headers
        )


@router.get(
    '/{loan_id}',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.BasicLoanResponse},
        403: {'description': 'Authorization header provided but invalid'},
        404: {'description': 'Loan not found'},
        429: {'description': 'You are doing that too much.'}
    }
)
def show(loan_id: int, authorization: str = Header(None)):
    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.DELETED_LOANS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        basic = helper.get_basic_loan_info(itgs, loan_id, perms)
        if basic is None:
            return Response(status_code=404, headers=headers)

        etag = helper.calculate_etag(itgs, loan_id)
        headers['etag'] = etag
        headers['Cache-Control'] = 'public, max-age=604800'
        return JSONResponse(
            status_code=200,
            content=basic.dict(),
            headers=headers
        )


@router.get(
    '/{loan_id}/detailed',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.DetailedLoanResponse},
        404: {'description': 'Loan not found'}
    }
)
def show_detailed(loan_id: int, authorization: str = Header(None)):
    request_cost = 5
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.DELETED_LOANS_PERM,
                helper.VIEW_ADMIN_EVENT_AUTHORS_PERM,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        basic = helper.get_basic_loan_info(itgs, loan_id, perms)
        if basic is None:
            return Response(status_code=404, headers=headers)

        events = helper.get_loan_events(itgs, loan_id, perms)

        etag = helper.calculate_etag(itgs, loan_id)
        headers['etag'] = etag
        headers['Cache-Control'] = 'public, max-age=604800'
        return JSONResponse(
            status_code=200,
            content=models.DetailedLoanResponse(
                events=events, basic=basic
            ).dict(),
            headers=headers
        )
