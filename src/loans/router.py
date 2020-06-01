from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from pypika import PostgreSQLQuery as Query, Table, Parameter
import pypika.functions as ppfns
from . import models
from . import helper
from models import ErrorResponse
import users.helper
from lbshared.lazy_integrations import LazyIntegrations as LazyItgs

router = APIRouter()


@router.get(
    '/?',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.LoansResponse},
        422: {'description': 'Arguments could not be interpreted', 'model': ErrorResponse}
    }
)
def index(authorization: str = Header(None)):
    return JSONResponse(content={'hello': 'there'}, status_code=200)


@router.get(
    '/{loan_id}/?',
    tags=['loans'],
    responses={
        200: {'description': 'Success', 'model': models.BasicLoanResponse},
        403: {'description': 'Authorization header provided but invalid'},
        404: {'description': 'Loan not found'},
        429: {'description': 'You are doing that too much.'}
    }
)
def show(loan_id: int, authorization: str = Header(None)):
    with LazyItgs() as itgs:
        user_id, _, perms = users.helper.get_permissions_from_header(
            itgs, authorization, (helper.DELETED_LOANS_PERM, *helper.RATELIMIT_PERMISSIONS)
        )
        if perms:
            perms = tuple(perms)
        else:
            perms = tuple()

        if not helper.check_ratelimit(itgs, user_id, perms, 1):
            return Response(status_code=429)

        loans = Table('loans')
        usrs = Table('users')
        moneys = Table('moneys')
        lenders = usrs.as_('lenders')
        borrowers = usrs.as_('borrowers')
        principals = moneys.as_('principals')
        principal_currencies = Table('currencies').as_('principal_currencies')
        principal_repayments = moneys.as_('principal_repayments')
        repayment_events = Table('loan_repayment_events')
        latest_repayments = Table('latest_repayments')

        query = (
            Query
            .with_(
                Query
                .from_(repayment_events)
                .select(
                    repayment_events.loan_id,
                    ppfns.Max(repayment_events.created_at).as_('latest_created_at')
                )
                .groupby(repayment_events.loan_id),
                'latest_repayments'
            )
            .from_(loans)
            .select(
                lenders.username,
                borrowers.username,
                principal_currencies.code,
                principal_currencies.symbol,
                principal_currencies.symbol_on_left,
                principal_currencies.exponent,
                principals.amount,
                principal_repayments.amount,
                loans.created_at,
                latest_repayments.latest_created_at,
                loans.repaid_at,
                loans.unpaid_at,
                loans.deleted_at
            )
            .join(lenders).on(lenders.id == loans.lender_id)
            .join(borrowers).on(borrowers.id == loans.borrower_id)
            .join(principals).on(principals.id == loans.principal_id)
            .join(principal_currencies).on(principal_currencies.id == principals.currency_id)
            .join(principal_repayments).on(principal_repayments.id == loans.principal_repayment_id)
            .join(latest_repayments).on(latest_repayments.loan_id == loans.id)
            .where(loans.id == Parameter('%s'))
        )
        args = (loan_id,)

        if helper.DELETED_LOANS_PERM not in perms:
            query = query.where(loans.deleted_at.isnull())

        itgs.read_cursor.execute(
            query.get_sql(),
            args
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            return Response(status_code=404)

        return JSONResponse(
            status_code=200,
            content=models.BasicLoanResponse(
                lender=row[0],
                borrower=row[1],
                currency_code=row[2],
                currency_symbol=row[3],
                currency_symbol_on_left=row[4],
                currency_exponent=row[5],
                principal_minor=row[6],
                principal_repayment_minor=row[7],
                created_at=row[8].timestamp(),
                last_repaid_at=row[9].timestamp() if row[9] is not None else None,
                repaid_at=row[10].timestamp() if row[10] is not None else None,
                unpaid_at=row[11].timestamp() if row[11] is not None else None,
                deleted_at=row[12].timestamp() if row[12] is not None else None
            ).dict()
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
    pass


@router.patch(
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
def update(loan_id: int, if_match: str = Header(None), authorization: str = Header(None)):
    pass
