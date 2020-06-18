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
from pypika import Table, PostgreSQLQuery as Query, Parameter
import lbshared.convert
from datetime import datetime
import sqlparse
from psycopg2.errors import UniqueViolation


router = APIRouter()


@router.put(
    '/{loan_id}',
    tags=['loans'],
    responses={
        200: {'description': 'Success'},
        401: {'description': 'Missing authentication'},
        403: {'description': 'Bad authentication'},
        410: {'description': 'Loan not found'},
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

        query = (
            query.from_(loans)
            .select(Parameter('$1'), Parameter('$2'), Parameter('$3'))
            .where(loans.id == Parameter('$1'))
        )
        query_params = [loan_id, user_id, loan.reason]

        update_query = (
            Query.update(loans)
            .where(loans.id == Parameter('$1'))
        )
        update_params = [loan_id]

        # Principal
        query = query.select(loans.principal_id)
        if loan.principal_minor is None:
            query = query.select(loans.principal_id)
        else:
            usd_amount = (
                loan.principal_minor * (1 / lbshared.convert.convert(itgs, 'USD', currency_code))
            )
            itgs.write_cursor.execute(
                Query.into(moneys).columns(
                    moneys.currency_id,
                    moneys.amount,
                    moneys.amount_usd_cents
                ).insert(
                    *[Parameter('%s') for _ in range(3)]
                ).returning(moneys.id).get_sql(),
                (currency_id, loan.principal_minor, usd_amount)
            )
            (new_principal_id,) = itgs.write_cursor.fetchone()
            query = query.select(Parameter(f'${len(query_params) + 1}'))
            query_params.append(new_principal_id)

            update_query = update_query.set(
                loans.principal_id, Parameter(f'${len(update_params) + 1}'))
            update_params.append(new_principal_id)

        # Principal Repayment
        query = query.select(loans.principal_repayment_id)
        if loan.principal_repayment_minor is None:
            query = query.select(loans.principal_repayment_id)
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
                ).insert(
                    *[Parameter('%s') for _ in range(3)]
                ).returning(moneys.id).get_sql(),
                (currency_id, loan.principal_repayment_minor, usd_amount)
            )
            (new_principal_repayment_id,) = itgs.write_cursor.fetchone()
            query = query.select(Parameter(f'${len(query_params) + 1}'))
            query_params.append(new_principal_repayment_id)

            update_query = update_query.set(
                loans.principal_repayment_id, Parameter(f'${len(update_params) + 1}'))
            update_params.append(new_principal_repayment_id)

        # Created At
        query = query.select(loans.created_at)
        if loan.created_at is None:
            query = query.select(loans.created_at)
        else:
            new_created_at = datetime.fromtimestamp(loan.created_at)
            query = query.select(Parameter(f'${len(query_params) + 1}'))
            query_params.append(new_created_at)

            update_query = update_query.set(
                loans.created_at, Parameter(f'${len(update_params) + 1}'))
            update_params.append(new_created_at)

        # Repaid
        query = query.select(loans.repaid_at)
        if is_repaid is None:
            query = query.select(loans.repaid_at)
        else:
            query = query.select(Parameter(f'${len(query_params) + 1}'))
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
        query = query.select(loans.unpaid_at)
        if is_repaid:
            query = query.select(Parameter(f'${len(query_params) + 1}'))
            update_query = update_query.set(
                loans.unpaid_at, Parameter(f'${len(update_params) + 1}'))
            query_params.append(None)
            update_params.append(None)
        elif loan.unpaid is None:
            query = query.select(loans.unpaid_at)
        else:
            query = query.select(Parameter(f'${len(query_params) + 1}'))
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
        query = query.select(loans.deleted_at)
        if loan.deleted is None:
            query = query.select(loans.deleted_at)
        else:
            query = query.select(Parameter(f'${len(query_params) + 1}'))
            update_query = update_query.set(
                loans.deleted_at, Parameter(f'${len(update_params) + 1}'))
            if loan.deleted:
                val = datetime.now()
                query_params.append(val)
                update_params.append(val)
            else:
                query_params.append(None)
                update_params.append(None)

        admin_event_insert_sql, admin_event_insert_params = (
            lbshared.queries.convert_numbered_args(query.get_sql(), query_params)
        )
        update_loan_sql, update_loan_params = (
            lbshared.queries.convert_numbered_args(update_query.get_sql(), update_params)
        )
        itgs.write_cursor.execute(
            admin_event_insert_sql, admin_event_insert_params
        )

        if update_loan_sql.strip():
            itgs.write_cursor.execute(
                update_loan_sql, update_loan_params
            )

        if not dry_run:
            itgs.write_conn.commit()
            itgs.logger.print(Level.INFO, 'Admin user {} just modified loan {}', user_id, loan_id)
            return Response(status_code=200)
        else:
            itgs.write_conn.rollback()

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
        410: {'description': 'Loan not found'},
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

        usrs = Table('users')
        created_lender = False
        try:
            itgs.write_cursor.execute(
                Query.into(usrs).columns(usrs.username)
                .insert(Parameter('%s')).returning(usrs.id)
                .get_sql(),
                (new_users.lender_name.lower(),)
            )
            created_lender = True
        except UniqueViolation:
            itgs.write_conn.rollback()
            itgs.write_cursor.execute(
                Query.from_(usrs).select(usrs.id)
                .where(usrs.username == Parameter('%s'))
                .get_sql(),
                (new_users.lender_name.lower(),)
            )

        (lender_id,) = itgs.write_cursor.fetchone()

        try:
            itgs.write_cursor.execute(
                Query.into(usrs).columns(usrs.username)
                .insert(Parameter('%s')).returning(usrs.id)
                .get_sql(),
                (new_users.borrower_name.lower(),)
            )
        except UniqueViolation:
            itgs.write_conn.rollback()
            if created_lender:
                itgs.write_cursor.execute(
                    Query.into(usrs).columns(usrs.username)
                    .insert(Parameter('%s')).returning(usrs.id)
                    .get_sql(),
                    (new_users.lender_name.lower(),)
                )
            else:
                # Slight race condition
                itgs.write_cursor.execute(
                    Query.from_(usrs).select(usrs.id)
                    .where(usrs.username == Parameter('%s'))
                    .get_sql(),
                    (new_users.lender_name.lower(),)
                )
            (lender_id,) = itgs.write_cursor.fetchone()
            itgs.write_cursor.execute(
                Query.from_(usrs).select(usrs.id)
                .where(usrs.username == Parameter('%s'))
                .get_sql(),
                (new_users.borrower_name.lower(),)
            )

        (borrower_id,) = itgs.write_cursor.fetchone()

        loans = Table('loans')
        itgs.write_cursor.execute(
            Query.into(loans).columns(
                loans.lender_id,
                loans.borrower_id,
                loans.principal_id,
                loans.principal_repayment_id,
                loans.created_at,
                loans.repaid_at,
                loans.unpaid_at,
                loans.deleted_at
            )
            .from_(loans)
            .select(
                Parameter('%s'),
                Parameter('%s'),
                loans.principal_id,
                loans.principal_repayment_id,
                loans.created_at,
                loans.repaid_at,
                loans.unpaid_at,
                loans.deleted_at
            )
            .where(loans.id == Parameter('%s'))
            .returning(loans.id)
            .get_sql(),
            (lender_id, borrower_id, loan_id)
        )
        (new_loan_id,) = itgs.write_cursor.fetchone()

        admin_events = Table('loan_admin_events')
        base_query = (
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
            ).from_(loans)
            .where(loans.id == Parameter('$1'))
        )
        base_select_params = [
            loans.id,
            Parameter('$2'),
            Parameter('$3'),
            loans.principal_id,
            loans.principal_id,
            loans.principal_repayment_id,
            loans.principal_repayment_id,
            loans.created_at,
            loans.created_at,
            loans.repaid_at,
            loans.repaid_at,
            loans.unpaid_at,
            loans.unpaid_at,
            loans.deleted_at,
            loans.deleted_at
        ]
        base_args = [
            None,
            user_id,
            None
        ]

        new_deleted_at = datetime.now()
        update_old_select_params = base_select_params.copy()
        update_old_select_params[-1] = new_deleted_at
        update_old_args = base_args.copy()
        update_old_args[0] = loan_id
        update_old_args[2] = (
            'This loan had the users changed. '
            + f'The new loan id is {new_loan_id}. '
            + 'Do not modify this loan further.'
        )
        itgs.write_cursor.execute(
            *lbshared.queries.convert_numbered_args(
                base_query.select(*update_old_select_params).get_sql(),
                update_old_args
            )
        )

        itgs.write_cursor.execute(
            Query.update(loans).set(loans.deleted_at, new_deleted_at)
            .where(loans.id == Parameter('%s')).get_sql(),
            (loan_id,)
        )

        creation_infos = Table('loan_creation_infos')
        itgs.write_cursor.execute(
            Query.into(creation_infos).columns(
                creation_infos.loan_id,
                creation_infos.type,
                creation_infos.mod_user_id
            ).insert(
                Parameter('%s'),
                Parameter('%s'),
                Parameter('%s')
            ).get_sql(),
            (new_loan_id, 1, user_id)
        )

        base_args[0] = new_loan_id
        base_args[2] = (
            f'This loan was copied from loan {loan_id}. '
            + 'The users were changed during this operation. Reason: '
            + new_users.reason
        )
        itgs.write_cursor.execute(
            *lbshared.queries.convert_numbered_args(
                base_query.select(*base_select_params).get_sql(),
                base_args
            )
        )
        itgs.write_conn.commit()
        return JSONResponse(
            status_code=200,
            content=edit_models.SingleLoanResponse(loan_id=new_loan_id).dict()
        )


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
        410: {'description': 'Loan not found'},
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
        currencies = Table('currencies')

        itgs.write_cursor.execute(
            Query.from_(currencies).select(currencies.id)
            .where(currencies.code == Parameter('%s'))
            .get_sql(),
            (new_currency.currency_code.upper(),)
        )
        row = itgs.write_cursor.fetchone()
        if row is None:
            return JSONResponse(
                status_code=422,
                content={
                    'detail': [
                        {
                            'loc': ['currency_code'],
                            'msg': 'Must be a recognized currency code',
                            'type': 'value_error'
                        }
                    ]
                }
            )
        (currency_id,) = row

        rate_usd_to_currency = lbshared.convert.convert(
            itgs, 'USD', new_currency.currency_code.upper())

        principal_usd = round(new_currency.principal_minor / rate_usd_to_currency)
        principal_repayment_usd = round(
            new_currency.principal_repayment_minor / rate_usd_to_currency)

        itgs.write_cursor.execute(
            Query.into(moneys).columns(
                moneys.currency_id,
                moneys.amount,
                moneys.amount_usd_cents
            ).insert(*[Parameter('%s') for _ in range(3)])
            .returning(moneys.id)
            .get_sql(),
            (
                currency_id,
                new_currency.principal_minor,
                principal_usd
            )
        )
        (new_principal_id,) = itgs.write_cursor.fetchone()

        itgs.write_cursor.execute(
            Query.into(moneys).columns(
                moneys.currency_id,
                moneys.amount,
                moneys.amount_usd_cents
            ).insert(*[Parameter('%s') for _ in range(3)])
            .returning(moneys.id)
            .get_sql(),
            (
                currency_id,
                new_currency.principal_repayment_minor,
                principal_repayment_usd
            )
        )
        (new_principal_repayment_id,) = itgs.write_cursor.fetchone()

        itgs.write_cursor.execute(
            Query.into(loans).columns(
                loans.lender_id,
                loans.borrower_id,
                loans.principal_id,
                loans.principal_repayment_id,
                loans.created_at,
                loans.repaid_at,
                loans.unpaid_at,
                loans.deleted_at
            ).from_(loans).select(
                loans.lender_id,
                loans.borrower_id,
                Parameter('%s'),
                Parameter('%s'),
                loans.created_at,
                loans.repaid_at,
                loans.unpaid_at,
                loans.deleted_at
            ).where(loans.id == Parameter('%s'))
            .get_sql(),
            (
                new_principal_id,
                new_principal_repayment_id,
                loan_id
            )
        )
        (new_loan_id,) = itgs.write_cursor.fetchone()

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
            ).from_(loans).select(
                loans.id,
                user_id,
                Parameter('%s'),
                loans.principal_id,
                loans.principal_id,
                loans.principal_repayment_id,
                loans.principal_repayment_id,
                loans.created_at,
                loans.created_at,
                loans.repaid_at,
                loans.repaid_at,
                loans.unpaid_at,
                loans.unpaid_at,
                loans.deleted_at
            ).where(loans.id == Parameter('%s'))
        )

        new_deleted_at = datetime.now()
        itgs.write_cursor.execute(
            query.select(Parameter('%s')).get_sql(),
            (
                f'This loan was copied to loan {new_loan_id} then deleted in '
                + f'order to change the currency to {new_currency.currency_code.upper()}. '
                + 'Do not modify this loan further.',
                new_deleted_at,
                loan_id
            )
        )
        itgs.write_cursor.execute(
            Query.update(loans).set(loans.deleted_at, Parameter('%s'))
            .where(loans.id == Parameter('%s')).get_sql(),
            (
                new_deleted_at,
                loan_id
            )
        )

        creation_infos = Table('loan_creation_infos')
        itgs.write_cursor.execute(
            Query.into(creation_infos).columns(
                creation_infos.loan_id,
                creation_infos.type,
                creation_infos.mod_user_id
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            (
                new_loan_id,
                1,
                user_id
            )
        )

        itgs.write_cursor.execute(
            query.select(loans.deleted_at).get_sql(),
            (
                f'This loan was copied from {loan_id} with the currency changed to '
                + f'{new_currency.currency_code.upper()}. Reason: {new_currency.reason}',
                new_loan_id
            )
        )
        itgs.write_conn.commit()
        return JSONResponse(
            status_code=200,
            content=edit_models.SingleLoanResponse(
                loan_id=new_loan_id
            ).dict()
        )
