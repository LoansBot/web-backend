"""Handles the requests to /api/responses/**/*"""
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order, functions as ppfns
from models import UserRef
from . import models
import users.helper as users_helper
from lazy_integrations import LazyIntegrations as LazyItgs


router = APIRouter()


@router.get(
    '/?',
    tags=['responses'],
    responses={
        200: {'description': 'Success', 'model': models.ResponseIndex},
        403: {'description': 'Token authentication failed'}
    }
)
def root(authorization: str = Header(None)):
    with LazyItgs() as itgs:
        if not users_helper.check_permissions_from_header(itgs, authorization, 'responses')[0]:
            return Response(status_code=403)
        responses = Table('responses')
        itgs.read_cursor.execute(
            Query.from_(responses).select(responses.name)
            .orderby(responses.name).get_sql()
        )
        resps = itgs.read_cursor.fetchall()
        return JSONResponse(
            status_code=200,
            content=models.ResponseIndex(responses=[r for (r,) in resps]).dict()
        )


@router.get(
    '/{name}/?',
    tags=['responses'],
    responses={
        200: {'description': 'Success', 'model': models.ResponseShow},
        403: {'description': 'Token authentication failed'},
        404: {'description': 'Response not found'}
    }
)
def show(name: str, authorization: str = Header(None)):
    with LazyItgs() as itgs:
        if not users_helper.check_permissions_from_header(itgs, authorization, 'responses')[0]:
            return Response(status_code=403)
        responses = Table('responses')
        itgs.read_cursor.execute(
            Query.from_(responses).select(
                responses.id,
                responses.name,
                responses.response_body,
                responses.description,
                responses.created_at,
                responses.updated_at
            ).where(responses.name == Parameter('%s'))
            .get_sql(),
            (name,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404)
        return JSONResponse(
            status_code=200,
            content=models.ResponseShow(
                id=row[0],
                name=row[1],
                body=row[2],
                desc=row[3],
                created_at=int(row[4].timestamp()),
                updated_at=int(row[5].timestamp())
            ).dict()
        )


@router.get(
    '/{name}/histories',
    tags=['responses'],
    responses={
        200: {'description': 'Success', 'model': models.ResponseHistoryList},
        403: {'description': 'Token authentication failed'},
        404: {'description': 'Response not found'}
    }
)
def histories(name: str, limit: int = 10, authorization: str = Header(None)):
    with LazyItgs() as itgs:
        if not users_helper.check_permissions_from_header(itgs, authorization, 'responses')[0]:
            return Response(status_code=403)
        responses = Table('responses')
        itgs.read_cursor.execute(
            Query.from_(responses).select(responses.id)
            .where(responses.name == Parameter('%s'))
            .get_sql(),
            (name,)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404)
        (respid,) = row
        resp_histories = Table('response_histories')
        users = Table('users')
        itgs.read_cursor.execute(
            Query
            .from_(resp_histories)
            .left_join(users).on(users.id == resp_histories.user_id)
            .select(
                resp_histories.id,
                users.id,
                users.username,
                resp_histories.reason,
                resp_histories.old_raw,
                resp_histories.new_raw,
                resp_histories.old_desc,
                resp_histories.new_desc,
                resp_histories.created_at
            )
            .where(resp_histories.response_id == Parameter('%s'))
            .orderby(resp_histories.id, order=Order.desc)
            .limit(limit)
            .get_sql(),
            (respid,)
        )

        result = []
        row = itgs.read_cursor.fetchone()
        while row is not None:
            if row[1] is None:
                edited_by = None
            else:
                edited_by = UserRef(
                    id=row[1],
                    username=row[2]
                )
            result.append(
                models.ResponseHistoryItem(
                    id=row[0],
                    edited_by=edited_by,
                    edited_reason=row[3],
                    old_body=row[4],
                    new_body=row[5],
                    old_desc=row[6],
                    new_desc=row[7],
                    edited_at=int(row[8].timestamp())
                )
            )
            row = itgs.read_cursor.fetchone()

        if len(result) < limit:
            number_truncated = 0
        else:
            itgs.read_cursor.execute(
                Query.from_(resp_histories).select(ppfns.Count('*'))
                .where(resp_histories.response_id == Parameter('%s'))
                .get_sql(),
                (respid,)
            )
            (num_total,) = itgs.read_cursor.fetchone()
            number_truncated = num_total - len(result)

        return JSONResponse(
            status_code=200,
            content=models.ResponseHistory(
                history=models.ResponseHistoryList(
                    items=result
                ),
                number_truncated=number_truncated
            ).dict()
        )


@router.post(
    '/?',
    tags=['responses'],
    responses={
        200: {'description': 'Success'},
        403: {'description': 'Token authentication failed'},
        409: {'description': 'Response name already taken'}
    }
)
def create_response(response: models.ResponseCreateArgs, authorization: str = Header(None)):
    with LazyItgs(no_read_only=True) as itgs:
        authed, user_id = users_helper.check_permissions_from_header(
            itgs, authorization, 'responses'
        )
        if not authed:
            return Response(status_code=403)
        responses = Table('responses')

        itgs.write_cursor.execute(
            Query.into(responses).columns(
                responses.name,
                responses.response_body,
                responses.description
            ).insert(*[Parameter('%s') for _ in range(3)])
            .returning(responses.id).get_sql(),
            (response.name, response.body, response.desc)
        )
        row = itgs.write_cursor.fetchone()
        if row is None:
            itgs.write_conn.rollback()
            return Response(status_code=409)
        (resp_id,) = row

        resp_hists = Table('response_histories')
        itgs.write_cursor.execute(
            Query.into(resp_hists).columns(
                resp_hists.response_id,
                resp_hists.user_id,
                resp_hists.old_raw,
                resp_hists.new_raw,
                resp_hists.reason,
                resp_hists.old_desc,
                resp_hists.new_desc
            ).insert(*[Parameter('%s') for _ in range(7)])
            .get_sql(),
            (
                resp_id,
                user_id,
                '',
                response.body,
                'Created',
                '',
                response.desc
            )
        )
        itgs.write_conn.commit()
        return Response(status_code=200)


@router.post(
    '/{name}/?',
    tags=['responses'],
    responses={
        200: {'description': 'Success'},
        403: {'description': 'Token authentication failed'},
        404: {'description': 'Response not found'}
    }
)
def update_response(name: str, change: models.ResponseEditArgs, authorization: str = Header(None)):
    if len(change.edit_reason) < 5:
        return JSONResponse(
            status_code=422,
            content={
                'detail': {
                    'loc': ['body', 'edit_reason']
                },
                'msg': 'minimum 5 characters',
                'type': 'too_short'
            }
        )

    with LazyItgs(no_read_only=True) as itgs:
        authed, user_id = users_helper.check_permissions_from_header(
            itgs, authorization, 'responses'
        )
        if not authed:
            return Response(status_code=403)
        users = Table('users')
        itgs.write_cursor.execute(
            Query.from_(users).select(users.id)
            .where(users.id == Parameter('%s'))
            .get_sql() + ' FOR SHARE',
            (user_id,)
        )
        row = itgs.write_cursor.fetchone()
        if row is None:
            itgs.write_conn.rollback()
            return Response(status_code=403)
        responses = Table('responses')
        itgs.write_cursor.execute(
            Query.from_(responses).select(
                responses.id,
                responses.response_body,
                responses.description
            ).where(responses.name == Parameter('%s'))
            .get_sql() + ' FOR UPDATE',
            (name,)
        )
        row = itgs.write_cursor.fetchone()
        if row is None:
            itgs.write_conn.rollback()
            return Response(status_code=404)
        (resp_id, old_body, old_desc) = row
        resp_hists = Table('response_histories')
        itgs.write_cursor.execute(
            Query.into(resp_hists).columns(
                resp_hists.response_id,
                resp_hists.user_id,
                resp_hists.old_raw,
                resp_hists.new_raw,
                resp_hists.reason,
                resp_hists.old_desc,
                resp_hists.new_desc
            ).insert(*[Parameter('%s') for _ in range(7)])
            .get_sql(),
            (
                resp_id,
                user_id,
                old_body,
                change.body,
                change.edit_reason,
                old_desc,
                change.desc
            )
        )
        itgs.write_cursor.execute(
            Query.update(responses)
            .set(responses.response_body, Parameter('%s'))
            .set(responses.description, Parameter('%s'))
            .set(responses.updated_at, ppfns.Now())
            .where(responses.id == Parameter('%s'))
            .get_sql(),
            (
                change.body,
                change.desc,
                resp_id
            )
        )
        itgs.write_conn.commit()
        return Response(status_code=200)
