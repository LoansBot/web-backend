"""This router contains the edit-a-loan endpoints that only moderators use.
"""
from lblogging import Level
import users.helper
from . import edit_models
from . import helper
from fastapi import APIRouter, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, JSONResponse
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs
import lbshared.queries
from pypika import Table, Query, Parameter
import lbshared.convert
from datetime import datetime
import sqlparse


router = APIRouter()


@router.put(
    '/{loan_id}',
    tags=['loans'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Missing authentication'},
        403: {'description': 'Bad authentication'},
        404: {'description': 'Loan not found'},
        412: {'description': 'Etag does not match If-Match header'},
        428: {'description': 'Missing the if-match header'}
    }
)
def update(
        loan_id: int, loan: edit_models.LoanBasicFields, dry_run: bool = False,
        dry_run_text: bool = False, if_match: str = Header(None),
        authorization: str = Header(None)):
    """Allows modifying the standard fields on a loan. Must provide an If-Match
    header which is the etag of the loan being modified.
    """
    if if_match is None:
        return Response(status_code=428)

    with LazyItgs(no_read_only=True) as itgs:
        has_perm, user_id = users.helper.check_permissions_from_header(
            itgs, authorization, (helper.EDIT_LOANS_PERMISSION,)
        )

        if not has_perm:
            return Response(status_code=403)

        etag = helper.calculate_etag(itgs, loan_id)
        if etag is None:
            return Response(status_code=410)

        if etag != if_match:
            return Response(status_code=412)

        loans = Table('loans')
        moneys = Table('moneys')
        principals = moneys.as_('principals')
        principal_repayments = moneys.as_('principal_repayments')
        currencies = Table('currencies')

        itgs.read_cursor.execute(
            Query.from_(loans).select(currencies.id, currencies.code)
            .join(principals).on(principals.id == loans.principal_id)
            .join(currencies).on(currencies.id == principals.currency_id)
            .where(loans.id == Parameter('%s'))
            .get_sql(),
            (loan_id,)
        )
        (currency_id, currency_code) = itgs.read_cursor.fetchone()

        is_repaid = None
        if (loan.principal_minor is None) != (loan.principal_repayment_minor is None):
            itgs.read_cursor.execute(
                Query.from_(loans)
                .select(principals.amount, principal_repayments.amount)
                .join(principals).on(principals.id == loans.principal_id)
                .join(principal_repayments).on(
                    principal_repayments.id == loans.principal_repayment_id)
                .where(loans.id == Parameter('%s'))
                .get_sql(),
                (loan_id,)
            )
            princ_amt, princ_repay_amt = itgs.read_cursor.fetchone()
            new_princ_amt = loan.principal_minor or princ_amt
            new_princ_repay_amt = loan.principal_repayment_minor or princ_repay_amt
            if new_princ_amt < new_princ_repay_amt:
                return JSONResponse(
                    status_code=422,
                    content={
                        'detail': {
                            'loc': [
                                'loan',
                                (loan.principal_minor is None and 'principal_minor'
                                 or 'principal_repayment_minor')
                            ],
                            'msg': 'Cannot have principal repayment higher than principal',
                            'type': 'value_error'
                        }
                    }
                )
            is_repaid = new_princ_amt == new_princ_repay_amt
        elif loan.principal_minor is not None:
            is_repaid = loan.principal_minor == loan.principal_repayment_minor

        admin_events = Table('loan_admin_events')
        query = (
            Query.into(admin_events).columns(
                admin_events.loan_id,
                admin_events.admin_id,
                admin_events.reason,
                admin_events.old_principal_id,
                admin_events.new_principal_id,
                admin_events.old_principal_repayment_id,
                admin_events.new_principal_repayment_id,
                admin_events.old_created_at,
                admin_events.new_created_at,
                admin_events.old_repaid_at,
                admin_events.new_repaid_at,
                admin_events.old_unpaid_at,
                admin_events.new_unpaid_at,
                admin_events.old_deleted_at,
                admin_events.new_deleted_at
            )
        )

        select_query = (
            Query.select(Parameter('$1'), Parameter('$2'), Parameter('$3'))
            .from_(loans)
            .where(loans.id == Parameter('$1'))
        )
        query_params = [loan_id, user_id, loan.reason]

        update_query = (
            Query.update(loans)
            .where(loans.id == Parameter('$1'))
        )
        update_params = [loan_id]

        # Principal
        select_query = select_query.select(loans.principal_id)
        if loan.principal_minor is None:
            select_query = select_query.select(loans.principal_id)
        else:
            usd_amount = (
                loan.principal_minor * (1 / lbshared.convert.convert(itgs, 'USD', currency_code))
            )
            itgs.write_cursor.execute(
                Query.into(moneys).columns(
                    moneys.currency_id,
                    moneys.amount,
                    moneys.amount_usd_cents
                ).insert(*[Parameter('%s') for _ in range(3)])
                .returning(moneys.id)
                .get_sql(),
                (currency_id, loan.principal_minor, usd_amount)
            )
            (new_principal_id,) = itgs.write_cursor.fetchone()
            select_query = select_query.select(Parameter(f'${len(query_params) + 1}'))
            query_params.append(new_principal_id)

            update_query = update_query.set(
                loans.principal_id, Parameter(f'${len(update_params) + 1}'))
            update_params.append(new_principal_id)

        # Principal Repayment
        select_query = select_query.select(loans.principal_repayment_id)
        if loan.principal_repayment_minor is None:
            select_query = select_query.select(loans.principal_repayment_id)
        else:
            usd_amount = (
                loan.principal_repayment_minor * (
                    1 / lbshared.convert.convert(itgs, 'USD', currency_code)
                )
            )
            itgs.write_cursor.execute(
                Query.into(moneys).columns(
                    moneys.currency_id,
                    moneys.amount,
                    moneys.amount_usd_cents
                ).insert(*[Parameter('%s') for _ in range(3)])
                .returning(moneys.id)
                .get_sql(),
                (currency_id, loan.principal_repayment_minor, usd_amount)
            )
            (new_principal_repayment_id,) = itgs.write_cursor.fetchone()
            select_query = select_query.select(Parameter(f'${len(query_params) + 1}'))
            query_params.append(new_principal_repayment_id)

            update_query = update_query.set(
                loans.principal_repayment_id, Parameter(f'${len(update_params) + 1}'))
            update_params.append(new_principal_repayment_id)

        # Created At
        select_query = select_query.select(loans.created_at)
        if loan.created_at is None:
            select_query = select_query.select(loans.created_at)
        else:
            new_created_at = datetime.fromtimestamp(loan.created_at)
            select_query = select_query.select(Parameter(f'${len(query_params) + 1}'))
            query_params.append(new_created_at)

            update_query = update_query.set(
                loans.created_at, Parameter(f'${len(update_params) + 1}'))
            update_params.append(new_created_at)

        # Repaid
        select_query = select_query.select(loans.repaid_at)
        if is_repaid is None:
            select_query = select_query.select(loans.repaid_at)
        else:
            select_query = select_query.select(Parameter(f'${len(query_params) + 1}'))
            update_query = update_query.set(
                loans.repaid_at, Parameter(f'${len(update_params) + 1}'))
            if is_repaid:
                val = datetime.now()
                query_params.append(val)
                update_params.append(val)
            else:
                query_params.append(None)
                update_params.append(None)

        # Unpaid
        select_query = select_query.select(loans.unpaid_at)
        if is_repaid:
            select_query = select_query.select(Parameter(f'${len(query_params) + 1}'))
            update_query = update_query.set(
                loans.unpaid_at, Parameter(f'${len(update_params) + 1}'))
            query_params.append(None)
            update_params.append(None)
        elif loan.unpaid is None:
            select_query = select_query.select(loans.unpaid_at)
        else:
            select_query = select_query.select(Parameter(f'${len(query_params) + 1}'))
            update_query = update_query.set(
                loans.unpaid_at, Parameter(f'${len(update_params) + 1}'))
            if loan.unpaid:
                val = datetime.now()
                query_params.append(val)
                update_params.append(val)
            else:
                query_params.append(None)
                update_params.append(None)

        # Deleted
        select_query = select_query.select(loans.deleted_at)
        if loan.deleted is None:
            select_query = select_query.select(loans.deleted_at)
        else:
            select_query = select_query.select(Parameter(f'${len(query_params) + 1}'))
            update_query = update_query.set(
                loans.unpaid_at, Parameter(f'${len(update_params) + 1}'))
            if loan.deleted:
                val = datetime.now()
                query_params.append(val)
                update_params.append(val)
            else:
                query_params.append(None)
                update_params.append(None)

        query = query.insert(select_query)

        admin_event_insert_sql, admin_event_insert_params = (
            lbshared.queries.convert_numbered_args(query.get_sql(), query_params)
        )
        update_loan_sql, update_loan_params = (
            lbshared.queries.convert_numbered_args(update_query.get_sql(), update_params)
        )
        # itgs.write_cursor.execute(
        #     admin_event_insert_sql, admin_event_insert_params
        # )
        # itgs.write_cursor.execute(
        #     update_loan_sql, update_loan_params
        # )

        if not dry_run:
            itgs.conn.commit()
            itgs.logger.print(Level.INFO, 'Admin user {} just modified loan {}', user_id, loan_id)
            return Response(status_code=200)
        else:
            itgs.conn.rollback()

            fmtted_admin_event_insert_sql = sqlparse.format(
                admin_event_insert_sql, keyword_case='upper', reindent=True
            )
            fmtted_update_loan_sql = sqlparse.format(
                update_loan_sql, keyword_case='upper', reindent=True
            )
            if not dry_run_text:
                return JSONResponse(
                    status_code=200,
                    content={
                        'loan_id': loan_id,
                        'loan': loan.dict(),
                        'dry_run': dry_run,
                        'dry_run_text': dry_run_text,
                        'admin_event_insert_sql': fmtted_admin_event_insert_sql,
                        'admin_event_insert_params': jsonable_encoder(admin_event_insert_params),
                        'update_loan_sql': fmtted_update_loan_sql,
                        'update_loan_params': jsonable_encoder(update_loan_params)
                    }
                )

            spaces = ' ' * 20
            return Response(
                status_code=200,
                headers={'Content-Type': 'plain/text'},
                content=(
                    "\n".join((line[20:] if line[:20] == spaces else line) for line in f"""
                    loan_id: {loan_id},
                    loan:
                        principal_minor: {loan.principal_minor},
                        principal_repayment_minor: {loan.principal_repayment_minor},
                        unpaid: {loan.unpaid},
                        created_at: {loan.created_at}
                        deleted: {loan.deleted}
                        reason: {repr(loan.reason)}
                    admin_event_insert_sql:

                    {fmtted_admin_event_insert_sql}

                    admin_event_insert_params: {admin_event_insert_params}

                    update_loan_sql:

                    {fmtted_update_loan_sql}

                    update_loan_params:

                    {update_loan_params}
                    """.splitlines())
                )
            )


@router.put(
    '/{loan_id}/users',
    tags=['loans'],
    responses={
        200: {
            'description': 'Success. Response contains new loan id',
            'model': edit_models.SingleLoanResponse
        },
        401: {'description': 'Missing authentication'},
        403: {'description': 'Bad authentication'},
        404: {'description': 'Loan not found'},
        412: {'description': 'Etag does not match If-Match header'},
        428: {'description': 'Missing the if-match header'}
    }
)
def update_users(
        loan_id: int, new_users: edit_models.ChangeLoanUsers,
        if_match: str = Header(None), authorization: str = Header(None)):
    """Allows modifying the users on a loan. Must provide an If-Match header
    which is the etag of the loan being modified.
    """
    pass


@router.put(
    '/{loan_id}/currency',
    tags=['loans'],
    responses={
        200: {
            'description': 'Success. Response contains new loan id',
            'model': edit_models.SingleLoanResponse
        },
        401: {'description': 'Missing authentication'},
        403: {'description': 'Bad authentication'},
        404: {'description': 'Loan not found'},
        412: {'description': 'Etag does not match If-Match header'},
        428: {'description': 'Missing the if-match header'}
    }
)
def update_currency(
        loan_id: int, new_currency: edit_models.ChangeLoanCurrency,
        if_match: str = Header(None), authorization: str = Header(None)):
    """Allows modifying the currency on a loan. Must provide an If-Match header
    which is the etag of the loan being modified.
    """
    pass
