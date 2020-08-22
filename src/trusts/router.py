"""Handles the requests to /api/trusts/**/*"""
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from .models import (
    TrustStatus, UserTrustComment,
    UserTrustCommentListResponse, UserTrustCommentRequest,
    TrustQueueResponse, TrustQueueItem, TrustQueueItemUpdate,
    TrustLoanDelay, TrustLoanDelayResponse
)
import trusts.helper as helper
import ratelimit_helper
import users.helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from pypika.functions import Now, Count, Star
from lbshared.pypika_crits import ExistsCriterion
import lbshared.delayed_queue as delayed_queue
import lbshared.queries
from datetime import datetime, timedelta
import pytz
import babel.dates
from lblogging import Level
from psycopg2 import IntegrityError

router = APIRouter()


@router.get(
    '/queue',
    tags=['trusts'],
    responses={
        200: {'description': 'Success', 'model': TrustQueueResponse},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'}
    }
)
def index_queue(
        after_review_at: float = None, before_review_at: float = None,
        limit: int = 5, order: str = 'asc', authorization=Header(None)):
    """View the list of users which have not been vetted and need to be vetted.
    This endpoint requires the `helper.VIEW_TRUST_QUEUE_PERMISSION`. It's
    recommended that these be displayed alongside trust comments.

    Arguments:
    - `after_review_at (float, None)`: If specified then only items in the queue
        which are set to review after this date (in seconds since utc epoch)
        will be considered. This is only going to be set if the order is 'asc'
    - `before_review_at (float, None)`: If specified then only items in the
        queue which are set to review before this date (in seconds since utc
        epoch) will be considered. This is only going to be set if the order
        is 'desc'
    - `limit (int)`: The maximum number of items to return. This will effect
        the ratelimit quota cost of this request.
    - `order (str)`: The way that the items are ordered in the response object;
        either 'asc' or 'desc' for oldest first or newest first respectively.
    - `authorization (str)`: The bearer token generated at signin
    """
    if authorization is None:
        return Response(status_code=401)

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

    if order not in ('asc', 'desc'):
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['order'],
                    'msg': 'Must be one of "asc", "desc"',
                    'type': 'value_error'
                }
            }
        )

    request_cost = 2 + limit
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_TRUST_QUEUE_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if not user_id:
            return Response(status_code=403, headers=headers)

        has_view_trust_permission = helper.VIEW_TRUST_QUEUE_PERMISSION in perms

        if not has_view_trust_permission:
            return Response(status_code=403, headers=headers)

        result_raw = delayed_queue.index_events(
            itgs, delayed_queue.QUEUE_TYPES['trust'],
            limit + 1,
            before_time=(
                None if before_review_at is None
                else datetime.fromtimestamp(before_review_at)
            ),
            after_time=(
                None if after_review_at is None
                else datetime.fromtimestamp(after_review_at)
            ),
            order=order,
            integrity_failures='delete_and_commit'
        )

        result = []
        new_after_review_at = None
        new_before_review_at = None

        for (ev_uuid, ev_at, ev) in result_raw:
            if len(result) == limit:
                if order == 'asc':
                    new_after_review_at = result[-1].review_at
                else:
                    new_before_review_at = result[-1].review_at
            else:
                result.append(
                    TrustQueueItem(
                        uuid=ev_uuid,
                        username=ev['username'],
                        review_at=ev_at.timestamp()
                    )
                )

        headers['Cache-Control'] = 'no-store'
        return JSONResponse(
            status_code=200,
            content=TrustQueueResponse(
                queue=result,
                after_review_at=new_after_review_at,
                before_review_at=new_before_review_at
            ).dict(),
            headers=headers
        )


@router.put(
    '/queue/{item_uuid}',
    tags=['trusts'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'},
        404: {'description': 'Item not found'}
    }
)
def set_queue_time(item_uuid: str, item: TrustQueueItemUpdate, authorization=Header(None)):
    """Change the desired review date on the trust queue item with the given
    id. This requires the `helper.EDIT_TRUST_QUEUE_PERMISSION` permission.

    Arguments:
    - `item_uuid (str)`: The uuid of the trust queue item to modify
    - `item (TrustQueueItemUpdate)`: The new values for the item
    - `authorization (str)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.EDIT_TRUST_QUEUE_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if helper.EDIT_TRUST_QUEUE_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        del_queue = Table('delayed_queue')
        itgs.write_cursor.execute(
            Query.update(del_queue)
            .set(del_queue.event_at, Parameter('%s'))
            .where(del_queue.uuid == Parameter('%s'))
            .returning(del_queue.id)
            .get_sql(),
            (
                datetime.fromtimestamp(item.review_at),
                item_uuid
            )
        )
        if itgs.write_cursor.fetchone() is None:
            return Response(status_code=404, headers=headers)

        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.get(
    '/queue/{item_uuid}',
    tags=['trusts'],
    responses={
        200: {'description': 'Success', 'model': TrustQueueItem},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'},
        404: {'description': 'Item not found'}
    }
)
def show_trust_item(item_uuid: str, authorization=Header(None)):
    """Get the trust queue item with the given uuid. This requires the
    `helper.VIEW_TRUST_QUEUE_PERMISSION` permission.

    Arguments:
    - `item_uuid (str)`: The uuid for the trust item to view
    - `authorization (str)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.VIEW_TRUST_QUEUE_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if helper.VIEW_TRUST_QUEUE_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        del_queue = Table('delayed_queue')
        itgs.read_cursor.execute(
            Query.from_(del_queue).select(del_queue.event_at)
            .where(del_queue.uuid == Parameter('%s'))
            .get_sql(),
            (item_uuid,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)
        (review_at,) = row

        coll = itgs.kvs_db.collection('delayed_queue')
        doc = coll.read_doc(item_uuid)
        if doc is None:
            return Response(status_code=404, headers=headers)

        headers['cache-control'] = 'private, max-age=15'
        return Response(
            status_code=200,
            content=TrustQueueItem(
                uuid=item_uuid,
                username=doc['username'],
                review_at=review_at.timestamp()
            ).dict(),
            headers=headers
        )


@router.post(
    '/queue',
    tags=['trusts'],
    responses={
        200: {'description': 'Success', 'model': TrustQueueItem},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'}
    }
)
def add_queue_item(item: TrustQueueItem, authorization=Header(None)):
    """Add a given item to the trust queue. This endpoint requires the
    `helper.ADD_TRUST_QUEUE_PERMISSION` permission. This will remove any loan
    delays that are on the given user.

    Arguments:
    - `item (TrustQueueItem)`: The item to add to the queue.
    - `authorization (str)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.ADD_TRUST_QUEUE_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if helper.ADD_TRUST_QUEUE_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        loan_delays = Table('trust_loan_delays')
        usrs = Table('users')
        itgs.read_cursor.execute(
            Query.from_(usrs).select(1)
            .where(usrs.username == Parameter('%s'))
            .get_sql(),
            (item.username.lower(),)
        )
        if itgs.read_cursor.fetchone() is None:
            users.helper.create_new_user(itgs, item.username.lower(), commit=False)

        itgs.write_cursor.execute(
            Query.from_(loan_delays).delete()
            .where(
                ExistsCriterion(
                    Query.from_(usrs)
                    .where(usrs.id == loan_delays.user_id)
                    .where(usrs.username == Parameter('%s'))
                )
            )
            .returning(loan_delays.id)
            .get_sql(),
            (item.username.lower(),)
        )
        if itgs.write_cursor.fetchone() is not None:
            helper.create_server_trust_comment(
                itgs,
                (
                    'Since this user was added to the trust queue early I '
                    'will no longer automatically add them to the trust queue '
                    'later'
                ),
                username=item.username
            )

        uuid = delayed_queue.store_event(
            itgs,
            delayed_queue.QUEUE_TYPES['trust'],
            datetime.fromtimestamp(item.review_at),
            {'username': item.username.lower()},
            commit=True
        )
        return Response(
            status_code=200,
            content=TrustQueueItem(
                uuid=uuid,
                username=item.username.lower(),
                review_at=item.review_at
            ).dict(),
            headers=headers
        )


@router.put(
    '/loan_delays',
    tags=['trusts'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'}
    }
)
def upsert_loan_delay(item: TrustLoanDelay, authorization=Header(None)):
    """Adds a loan delay to the given user if they don't otherwise have one,
    otherwise replaces the existing loan delay for the user with the specified
    one.

    A loan delay causes us to add the user to the trust queue with the given
    review date (or the date at the time if newer) as soon as they reach a
    certain number of loans completed as lender.

    This requires the `helper.ADD_TRUST_QUEUE_PERMISSION` permission and the
    `helper.EDIT_TRUST_QUEUE_PERMISSION`

    Arguments:
    - `item (TrustLoanDelay)`: The trust loan delay to upsert
    - `authorization (str)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.ADD_TRUST_QUEUE_PERMISSION,
                helper.EDIT_TRUST_QUEUE_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if helper.ADD_TRUST_QUEUE_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        if helper.EDIT_TRUST_QUEUE_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        usrs = Table('users')
        itgs.read_cursor.execute(
            Query.from_(usrs).select(usrs.id)
            .where(usrs.username == Parameter('%s'))
            .get_sql(),
            (item.username.lower(),)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            target_user_id = users.helper.create_new_user(itgs, item.username, commit=False)
        else:
            (target_user_id,) = row

        loans = Table('loans')
        itgs.read_cursor.execute(
            Query.from_(loans).select(Count(Star()))
            .where(loans.repaid_at.notnull())
            .where(loans.lender_id == Parameter('%s'))
            .get_sql(),
            (target_user_id,)
        )
        (num_completed_as_lender,) = itgs.read_cursor.fetchone()
        if num_completed_as_lender >= item.loans_completed_as_lender:
            return JSONResponse(
                status_code=422,
                headers=headers,
                content={
                    'detail': {
                        'loc': ['body', 'loans_completed_as_lender'],
                        'msg': 'Must be more than their current total',
                        'type': 'range_error'
                    }
                }
            )

        min_review_at = (
            pytz.timezone('America/Los_Angeles')
            .localize(datetime.fromtimestamp(item.review_no_earlier_than))
        )

        itgs.write_cursor.execute(
            lbshared.queries.convert_numbered_args(
                'INSERT INTO trust_loan_delays '
                '(user_id, loans_completed_as_lender, min_review_at) '
                'VALUES ($1, $2, $3) '
                'ON CONFLICT (user_id) '
                'DO UPDATE SET loans_completed_as_lender=$2, min_review_at=$3',
                (
                    target_user_id,
                    item.loans_completed_as_lender,
                    min_review_at
                )
            )
        )

        itgs.read_cursor.execute(
            Query.from_(usrs).select(usrs.usrename)
            .where(usrs.id == Parameter('%s'))
            .get_sql(),
            (user_id,)
        )
        (author_username,) = itgs.read_cursor.fetchone()

        helper.create_server_trust_comment(
            itgs,
            (
                'I will add [/u/{target}](https://reddit.com/u/{target}) '
                'back to the queue with a review date no earlier than '
                '{min_review_date} at {min_review_time} '
                '{min_review_tz_pretty} ({min_review_tz}) when '
                '[/u/{target}](https://reddit.com/u/{target}) reaches '
                '{num_loans} completed loans as lender by the request of '
                '[/u/{author}](https://reddit.com/u/{author}). They '
                'currently have {num_completed_already} loans completed as '
                'lender.'
            ).format(
                min_review_date=babel.dates.format_date(min_review_at, locale='en_US'),
                min_review_time=babel.dates.format_time(min_review_at, locale='en_US'),
                min_review_tz_pretty=min_review_at.strftime('%Z'),
                min_review_tz=min_review_at.strftime('%z'),
                target=item.username.lower(),
                num_loans=item.loans_completed_as_lender,
                author=author_username,
                num_completed_already=num_completed_as_lender
            ),
            user_id=target_user_id
        )
        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.delete(
    '/loan_delays/{req_user_id}',
    tags=['trusts'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'},
        404: {'description': 'User or their loan delay not found'}
    }
)
def delete_loan_delay(req_user_id: int, authorization=Header(None)):
    """Delete the request to re-add the given user to the trust check queue
    when they reach a given number of loans coimpleted as lender.

    This requires the `helper.REMOVE_TRUST_QUEUE_PERMISSION` permission.

    Arguments:
    - `req_user_id (int)`: The id of the user who we should not automatically
        re-add to the trust queue after they reach a certain number of loans
        completed as lender.
    - `authorization (str)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.REMOVE_TRUST_QUEUE_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if helper.REMOVE_TRUST_QUEUE_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        loan_delays = Table('trust_loan_delays')
        itgs.write_cursor.execute(
            Query.from_(loan_delays).delete()
            .where(loan_delays.user_id == Parameter('%s'))
            .returning(loan_delays.id)
            .get_sql(),
            (req_user_id,)
        )
        if itgs.write_cursor.fetchone() is None:
            return Response(status_code=404, headers=headers)

        usrs = Table('users')
        itgs.read_cursor.execute(
            Query.from_(usrs).select(usrs.username)
            .where(usrs.id == Parameter('%s'))
            .get_sql(),
            (user_id,)
        )
        (author_username,) = itgs.read_cursor.fetchone()

        helper.create_server_trust_comment(
            itgs,
            (
                '[/u/{author}](https://reddit.com/u/{author}) removed '
                'the automated re-entry to the trust queue based on loans '
                'completed as lender for this user.'
            ).format(
                author=author_username
            ),
            user_id=req_user_id
        )
        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)


@router.get(
    '/loan_delays/{req_user_id}',
    tags=['trusts'],
    responses={
        200: {'description': 'Success', 'model': TrustLoanDelayResponse},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'},
        404: {'description': 'User or their loan delay not found'}
    }
)
def show_loan_delay(req_user_id: int, authorization=Header(None)):
    """Get the loan delay on the given user, if they have a loan delay. This
    requires the `helper.VIEW_TRUST_QUEUE_PERMISSION` permission.

    Arguments:
    - `req_user_id (int)`: The id of the user whose loan delay is desired
    - `authorization (str)`: Bearer token generated at login
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.VIEW_TRUST_QUEUE_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if helper.VIEW_TRUST_QUEUE_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        loan_delays = Table('trust_loan_delays')
        itgs.read_cursor.execute(
            Query.from_(loan_delays).select(
                loan_delays.loans_completed_as_lender,
                loan_delays.min_review_at
            ).where(loan_delays.user_id == Parameter('%s'))
            .get_sql(),
            (req_user_id,)
        )

        headers['Cache-Control'] = 'private, max-age=3600'

        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404, headers=headers)

        return JSONResponse(
            status_code=200,
            headers=headers,
            content=TrustLoanDelayResponse(
                loans_completed_as_lender=row[0],
                min_review_at=row[1].timestamp()
            ).dict()
        )


@router.delete(
    '/queue/{item_uuid}',
    tags=['trusts'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'},
        404: {'description': 'Item not found'}
    }
)
def delete_queue_item(item_uuid: str, authorization=Header(None)):
    """Delete the trust item with the given id from the queue. This requires
    the `helper.REMOVE_TRUST_QUEUE_PERMISSION` permission.

    Arguments:
    - `item_uuid (str)`: The uuid of the trust queue item to delete
    - `authorization (str)`: The bearer token generated at login
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.REMOVE_TRUST_QUEUE_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if helper.REMOVE_TRUST_QUEUE_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        succ = lbshared.delayed_queue.delete_event(itgs, item_uuid, commit=True)

        if not succ:
            return Response(status_code=404, headers=headers)

        return Response(status_code=200, headers=headers)


@router.get(
    '/comments/?',
    tags=['trusts'],
    responses={
        200: {'description': 'Success', 'model': UserTrustCommentListResponse},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'}
    }
)
def index_trust_comments(
        target_user_id: int, created_after: float = None, created_before: float = None,
        order: str = 'desc', limit: int = 5, authorization=Header(None)):
    """
    Get the list of trust-related comments on the particular user. This
    requires the `helper.VIEW_TRUST_COMMENTS` permission.

    Arguments:
    - `user_id (int)`: The id of the user to view trust comments on
    - `created_after (float, None)`: If specified this should be in fractional
        seconds since utc epoch. Only comments posted strictly after that time
        will be included.
    - `created_before (float, None)`: If specified this should be in fractional
        seconds since utc epoch. Only comments posted strictly before that time
        will be included.
    - `order (str)`: How to sort the results; results are sorted based on the
        creation date. This must be 'asc' or 'desc' for oldest-first and
        newest-first order respectively.
    - `limit (int)`: How many comments to return. Affects the amount toward the
        ratelimit quota.
    - `authorization (str)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

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

    if order not in ('asc', 'desc'):
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['order'],
                    'msg': 'Must be one of "asc", "desc"',
                    'type': 'value_error'
                }
            }
        )

    request_cost = 2 + limit
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                helper.VIEW_TRUST_COMMENTS_PERMISSION,
                *ratelimit_helper.RATELIMIT_PERMISSIONS
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if not user_id:
            return Response(status_code=403, headers=headers)

        if helper.VIEW_TRUST_COMMENTS_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        trust_comments = Table('trust_comments')
        query = (
            Query.from_(trust_comments).select(
                trust_comments.id,
                trust_comments.created_at
            ).where(
                trust_comments.target_id == Parameter('%s')
            )
            .orderby(trust_comments.created_at, getattr(Order, order))
            .limit(limit + 1)
        )
        args = [target_user_id]

        if created_after is not None:
            query = query.where(trust_comments.created_at > Parameter('%s'))
            args.append(datetime.fromtimestamp(created_after))

        if created_before is not None:
            query = query.where(trust_comments.created_at < Parameter('%s'))
            args.append(datetime.fromtimestamp(created_before))

        itgs.read_cursor.execute(query.get_sql(), args)

        result = []
        have_more = False
        last_created_at = None
        row = itgs.read_cursor.fetchone()
        while row is not None:
            if len(result) >= limit:
                have_more = True
                row = itgs.read_cursor.fetchone()
                continue

            (
                comment_id,
                comment_created_at
            ) = row

            last_created_at = comment_created_at
            result.append(comment_id)
            row = itgs.read_cursor.fetchone()

        new_created_after = None
        new_created_before = None
        if have_more:
            if order == 'asc':
                new_created_after = last_created_at
            else:
                new_created_before = last_created_at

        headers['Cache-Control'] = 'no-store'
        return JSONResponse(
            status_code=200,
            headers=headers,
            content=UserTrustCommentListResponse(
                comments=result,
                after_created_at=(
                    None if new_created_after is None
                    else new_created_after.timestamp()
                ),
                before_created_at=(
                    None if new_created_before is None
                    else new_created_before.timestamp()
                )
            ).dict()
        )


@router.get(
    '/comments/{comment_id}',
    responses={
        200: {'description': 'Success', 'model': UserTrustComment},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'}
    }
)
def show_trust_comment(comment_id: int, authorization=Header(None)):
    """View the given comment by its id. You must have the
    `helper.VIEW_TRUST_COMMENTS_PERMISSION` permission to perform this action.

    Arguments:
    - `comment_id (int)`: The primary key of the comment to fetch
    - `authorization (str)`: The bearer token generated at login
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs,
            authorization,
            (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.VIEW_TRUST_COMMENTS_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=403, headers=headers)

        if helper.VIEW_TRUST_COMMENTS_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        trust_comments = Table('trust_comments')
        itgs.read_cursor.execute(
            Query.from_(trust_comments)
            .select(
                trust_comments.author_id,
                trust_comments.target_id,
                trust_comments.comment,
                trust_comments.created_at,
                trust_comments.updated_at
            )
            .where(trust_comments.id == Parameter('%s'))
            .get_sql(),
            (comment_id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=403, headers=headers)

        (
            comment_author_id,
            comment_target_id,
            comment_comment,
            comment_created_at,
            comment_updated_at
        ) = row

        time_since_comment = datetime.now() - comment_created_at
        editable = (
            comment_author_id == user_id
            and time_since_comment < timedelta(days=1)
        )

        headers['Cache-Control'] = 'private, stale-while-revalidate=3600'
        return JSONResponse(
            status_code=200,
            headers=headers,
            content=UserTrustComment(
                id=comment_id,
                author_id=comment_author_id,
                target_id=comment_target_id,
                comment=comment_comment,
                editable=editable,
                created_at=comment_created_at.timestamp(),
                updated_at=comment_updated_at.timestamp()
            ).dict()
        )


@router.post(
    '/comments',
    responses={
        201: {'description': 'Success', 'model': UserTrustComment},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'}
    }
)
def create_trust_comment(
        target_user_id: int, comment: UserTrustCommentRequest,
        authorization=Header(None)):
    """Post a comment about the given users trustworthiness. Returns the newly
    created comment.

    Arguments:
    - `target_user_id (int)`: The id of the user to post a comment about
    - `comment (UserTrustCommentRequest)`: The comment to post
    - `authorization (str)`: The bearer token generated at login
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.CREATE_TRUST_COMMENTS_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=403, headers=headers)

        if helper.CREATE_TRUST_COMMENTS_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        usrs = Table('users')
        itgs.read_cursor.execute(
            Query.from_(usrs).select(1).where(usrs.id == Parameter('%s')).get_sql(),
            (target_user_id,)
        )
        if itgs.read_cursor.fetchone() is None:
            itgs.logger.print(
                Level.DEBUG,
                (
                    'A user (id={}) tried to post a trust comment on a nonexistent '
                    'user (id={})'
                ),
                user_id, target_user_id
            )
            return Response(status_code=403, headers=headers)

        trust_comments = Table('trust_comments')
        itgs.write_cursor.execute(
            Query.into(trust_comments).columns(
                trust_comments.author_id,
                trust_comments.target_id,
                trust_comments.comment
            ).insert(*[Parameter('%s') for _ in range(3)])
            .returning(
                trust_comments.id,
                trust_comments.created_at,
                trust_comments.updated_at
            )
            .get_sql(),
            (
                user_id,
                target_user_id,
                comment.comment
            )
        )

        (
            comment_id,
            comment_created_at,
            comment_updated_at
        ) = itgs.write_cursor.fetchone()

        itgs.write_conn.commit()

        return JSONResponse(
            status_code=201,
            headers=headers,
            content=UserTrustComment(
                id=comment_id,
                author_id=user_id,
                target_id=target_user_id,
                comment=comment.comment,
                editable=True,
                created_at=comment_created_at.timestamp(),
                updated_at=comment_updated_at.timestamp()
            ).dict()
        )


@router.put(
    '/comments/{comment_id}',
    responses={
        200: {'description': 'Success', 'model': UserTrustComment},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'},
        405: {'description': 'Editing this comment is not allowed'}
    }
)
def edit_trust_comment(
        comment_id: int, comment: UserTrustCommentRequest,
        authorization=Header(None)):
    """Edit the given trust comment. This will only work if the comment is
    editable by you (see the response to show or create).

    Arguments:
    - `comment_id (int)`: The id of the comment to edit
    - `comment (UserTrustCommentRequest)`: The new value for the comment
    - `authorization (str)`: The bearer token generated at login
    """
    if authorization is None:
        return Response(status_code=401)

    # Edits aren't particularly expensive for us to handle but a bunch of edits
    # back-to-back is eyebrow raising
    check_request_cost = 5
    request_cost = 95
    headers = {'x-request-cost': str(check_request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.VIEW_TRUST_COMMENTS_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(
                itgs, user_id, perms, check_request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=403, headers=headers)

        if helper.VIEW_TRUST_COMMENTS_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        trust_comments = Table('trust_comments')
        itgs.read_cursor.execute(
            Query.from_(trust_comments)
            .select(trust_comments.author_id, trust_comments.created_at)
            .where(trust_comments.id == Parameter('%s'))
            .get_sql(),
            (comment_id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None or row[0] != user_id:
            return Response(status_code=403, headers=headers)

        (_, comment_created_at) = row
        if datetime.now() - comment_created_at > timedelta(days=1):
            return Response(status_code=405, headers=headers)

        headers['x-request-cost'] = str(check_request_cost + request_cost)
        if not ratelimit_helper.check_ratelimit(
                itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        itgs.write_cursor.execute(
            Query.update(trust_comments)
            .set(trust_comments.comment, Parameter('%s'))
            .set(trust_comments.updated_at, Now())
            .where(trust_comments.id == Parameter('%s'))
            .get_sql(),
            (
                comment.comment,
                comment_id
            )
        )
        itgs.write_conn.commit()

        itgs.read_cursor.execute(
            Query.from_(trust_comments)
            .select(
                trust_comments.author_id,
                trust_comments.target_id,
                trust_comments.comment,
                trust_comments.created_at,
                trust_comments.updated_at
            )
            .where(trust_comments.id == Parameter('%s'))
            .get_sql(),
            (comment_id,)
        )
        (
            comment_author_id,
            comment_target_id,
            comment_comment,
            comment_created_at,
            comment_updated_at
        ) = itgs.read_cursor.fetchone()
        return JSONResponse(
            status_code=200,
            headers=headers,
            content=UserTrustComment(
                id=comment_id,
                author_id=comment_author_id,
                target_id=comment_target_id,
                comment=comment_comment,
                editable=True,
                created_at=comment_created_at.timestamp(),
                updated_at=comment_updated_at.timestamp()
            ).dict()
        )


@router.get(
    '/{target_user_id}',
    tags=['trusts'],
    responses={
        200: {'description': 'Success', 'model': TrustStatus},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'},
        404: {'description': 'No such user exists'}
    }
)
def show_status(target_user_id: int, authorization=Header(None)):
    """Check the trust status on the given user, specified by id.
    This never returns trust reasons to improve cacheability.

    This endpoint requires authorization and uses the ratelimit if
    it is not cached. If the user matches the authorized user, then
    the permission required is `helper.VIEW_SELF_TRUST_PERMISSION`.
    Otherwise the required permission is
    `helper.VIEW_OTHERS_TRUST_PERMISSION`. These permissions are
    not considered strong guards due to the caching, but rather
    just suggestions.

    We do, in general, allow third-party applications to display this
    information publicly with permission, so long as the information is
    presented in an acceptable way.

    Arguments:
    - `target_user_id (int)`: The id of the user to fetch trust information for.
    - `authorization (str)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    request_cost = 1
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.VIEW_SELF_TRUST_PERMISSION,
                helper.VIEW_OTHERS_TRUST_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if user_id is None:
            return Response(status_code=403, headers=headers)

        can_view_self_trust = helper.VIEW_SELF_TRUST_PERMISSION in perms
        can_view_others_trust = helper.VIEW_OTHERS_TRUST_PERMISSION in perms
        has_perm = (
            (can_view_self_trust and user_id == target_user_id)
            or (can_view_others_trust and user_id != target_user_id)
        )
        if not has_perm:
            return Response(status_code=403, headers=headers)

        if user_id != target_user_id:
            usrs = Table('users')
            itgs.read_cursor.execute(
                Query.from_(usrs).select(1).where(usrs.id == Parameter('%s')).get_sql(),
                (target_user_id,)
            )
            if itgs.read_cursor.fetchone() is None:
                return Response(status_code=404, headers=headers)

        trusts = Table('trusts')
        itgs.read_cursor.execute(
            Query.from_(trusts)
            .select(trusts.status)
            .where(trusts.user_id == Parameter('%s'))
            .get_sql(),
            (target_user_id,)
        )

        row = itgs.read_cursor.fetchone()
        if row is None:
            status = 'unknown'
        else:
            (status,) = row

        headers['Cache-Control'] = 'public, max-age=86400'
        return JSONResponse(
            status_code=200,
            headers=headers,
            content=TrustStatus(
                user_id=target_user_id,
                status=status,
                reason=None
            ).dict()
        )


@router.put(
    '/?',
    tags=['trusts'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Authorization missing'},
        403: {'description': 'Authorization insufficient'},
        404: {'description': 'No such user exists'}
    }
)
def upsert_trust_status(item: TrustStatus, authorization=Header(None)):
    """Create or update the trust status, which is unique to the user
    id. This requires the `helper.UPSERT_TRUST_PERMISSION` permission.

    Arguments:
    - `item (TrustStatus)`: The trust status to upsert
    - `authorization (str)`: The bearer token generated at login.
    """
    if authorization is None:
        return Response(status_code=401)

    if item.reason is None or len(item.reason.strip()) == 0:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['body', 'reason'],
                    'msg': 'must not be blank',
                    'type': 'value_error'
                }
            }
        )

    request_cost = 25
    headers = {'x-request-cost': str(request_cost)}
    with LazyItgs(no_read_only=True) as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (
                *ratelimit_helper.RATELIMIT_PERMISSIONS,
                helper.UPSERT_TRUST_PERMISSION
            )
        )

        if not ratelimit_helper.check_ratelimit(itgs, user_id, perms, request_cost):
            return Response(status_code=429, headers=headers)

        if helper.UPSERT_TRUST_PERMISSION not in perms:
            return Response(status_code=403, headers=headers)

        usrs = Table('users')
        itgs.read_cursor.execute(
            Query.from_(usrs).select(1)
            .where(usrs.id == Parameter('%s'))
            .get_sql(),
            (item.user_id,)
        )
        if itgs.read_cursor.fetchone() is None:
            return Response(status_code=404, headers=headers)

        trusts = Table('trusts')
        # We'd rather race and get better data than use conflict
        # updates
        itgs.read_cursor.execute(
            Query.from_(trusts).select(trusts.status, trusts.reason)
            .where(trusts.user_id == Parameter('%s'))
            .get_sql(),
            (item.user_id,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            try:
                itgs.write_cursor.execute(
                    Query.into(trusts).columns(
                        trusts.user_id, trusts.status, trusts.reason
                    ).insert(*[Parameter('%s') for _ in range(3)])
                    .returning(trusts.id)
                    .get_sql(),
                    (
                        item.user_id,
                        item.status,
                        item.reason
                    )
                )
            except IntegrityError as ex:
                if ex.pgcode == '23505':  # unique violation
                    return Response(status_code=503, headers=headers)
                itgs.logger.exception(Level.WARN)
                return Response(status_code=500, headers=headers)

            (trust_id,) = itgs.write_cursor.fetchone()
            old_status = None
            old_reason = None
        else:
            (old_status, old_reason) = row
            itgs.write_cursor.execute(
                Query.update(trusts)
                .set(trusts.status, Parameter('%s'))
                .set(trusts.reason, Parameter('%s'))
                .where(trusts.user_id == Parameter('%s'))
                .where(trusts.status == Parameter('%s'))
                .where(trusts.reason == Parameter('%s'))
                .returning(trusts.id)
                .get_sql(),
                (
                    item.status,
                    item.reason,
                    item.user_id,
                    old_status,
                    old_reason
                )
            )
            row = itgs.read_cursor.fetchone()
            if row is None:
                return Response(status_code=503, headers=headers)
            (trust_id,) = row

        trust_events = Table('trust_events')
        itgs.write_cursor.execute(
            Query.into(trust_events).columns(
                trust_events.trust_id,
                trust_events.mod_user_id,
                trust_events.old_status,
                trust_events.new_status,
                trust_events.old_reason,
                trust_events.new_reason
            ).insert(*[Parameter('%s') for _ in range(6)])
            .get_sql(),
            (
                trust_id,
                user_id,
                old_status,
                item.status,
                old_reason,
                item.reason
            )
        )
        itgs.write_conn.commit()
        return Response(status_code=200, headers=headers)
