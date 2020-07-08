"""Helper file for loans"""
from pypika import PostgreSQLQuery as Query, Table, Parameter
import pypika.functions as ppfns
from lbshared.pypika_funcs import Greatest
import hashlib
from . import models

DELETED_LOANS_PERM = 'view_deleted_loans'
"""The name of the permission that gives a user permission to view deleted
loans"""

VIEW_ADMIN_EVENT_AUTHORS_PERM = 'view_admin_event_authors'
"""The name of the permission that gives a user permission to view who made
admin edits"""

EDIT_LOANS_PERMISSION = 'edit_loans'
"""The name of the permission that gives a user the ability to modify loans."""


def calculate_etag(itgs, loan_id) -> str:
    """Calculates a valid etag for the loan with the given id. If no such loan
    exists this returns None.
    """
    loans = Table('loans')
    event_tables = [Table(t) for t in [
        'loan_admin_events', 'loan_repayment_events', 'loan_unpaid_events'
    ]]
    q = (
        Query.from_(loans)
        .select(Greatest(
            loans.created_at,
            loans.unpaid_at,
            loans.deleted_at,
            *[
                tbl.created_at for tbl in event_tables
            ]
        ))
    )
    for tbl in event_tables:
        q = q.left_join(tbl).on(loans.id == tbl.loan_id)
    q = q.where(loans.id == Parameter('%s'))

    itgs.read_cursor.execute(
        q.get_sql(),
        (loan_id,)
    )
    row = itgs.read_cursor.fetchone()

    if row is None:
        return None

    (updated_at,) = row

    raw_str = f'{loan_id}-{updated_at.timestamp()}'
    return hashlib.sha256(raw_str.encode('ASCII')).hexdigest()


def get_basic_loan_info(itgs, loan_id, perms):
    """Get the models.BasicLoanInfo for the given loan if the loan exists and
    the user has permission to view the loan. Otherwise, returns None
    """
    loans = Table('loans')
    query = get_basic_loan_info_query().where(loans.id == Parameter('%s'))

    if DELETED_LOANS_PERM not in perms:
        query = query.where(loans.deleted_at.isnull())

    args = (loan_id,)

    itgs.read_cursor.execute(
        query.get_sql(),
        args
    )
    row = itgs.read_cursor.fetchone()
    if row is None:
        return None

    return parse_basic_loan_info(row)


def get_basic_loan_info_query():
    """Get the basic query that we use for fetching a loans information"""
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
        .left_join(latest_repayments).on(latest_repayments.loan_id == loans.id)
    )

    return query


def parse_basic_loan_info(row):
    """Parses a row returned from a basic loan info query into the basic loan
    response."""
    return models.BasicLoanResponse(
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
    )


def get_loan_events(itgs, loan_id, perms):
    """Get the loan events for the given loan if the user has access to view
    the loan. The details of each event may also depend on what the user has
    access to. Returns the events in ascending (oldest to newest) order.
    """
    loans = Table('loans')
    usrs = Table('users')
    moneys = Table('moneys')

    q = (
        Query.from_(loans)
        .select(loans.created_at)
        .where(loans.id == Parameter('%s'))
    )
    if DELETED_LOANS_PERM not in perms:
        q = q.where(loans.deleted_at.isnull())

    itgs.read_cursor.execute(
        q.get_sql(),
        (loan_id,)
    )
    row = itgs.read_cursor.fetchone()
    if row is None:
        return []
    (created_at,) = row

    result = []

    creation_infos = Table('loan_creation_infos')
    itgs.read_cursor.execute(
        Query.from_(creation_infos)
        .select(
            creation_infos.type,
            creation_infos.parent_fullname,
            creation_infos.comment_fullname
        )
        .where(creation_infos.loan_id == Parameter('%s'))
        .get_sql(),
        (loan_id,)
    )
    row = itgs.read_cursor.fetchone()
    if row is not None:
        (creation_type, parent_fullname, comment_fullname) = row
        result.append(
            models.CreationLoanEvent(
                event_type='creation',
                occurred_at=created_at.timestamp(),
                creation_type=creation_type,
                creation_permalink=(
                    None
                    if creation_type != 0
                    else
                    'https://reddit.com/comments/{}/redditloans/{}'.format(
                        parent_fullname[3:], comment_fullname[3:]
                    )
                )
            )
        )

    admin_events = Table('loan_admin_events')
    admins = usrs.as_('admins')
    old_principals = moneys.as_('old_principals')
    new_principals = moneys.as_('new_principals')
    old_principal_repayments = moneys.as_('old_principal_repayments')
    new_principal_repayments = moneys.as_('new_principal_repayments')
    itgs.read_cursor.execute(
        Query.from_(admin_events)
        .select(
            admins.username,
            admin_events.reason,
            old_principals.amount,
            new_principals.amount,
            old_principal_repayments.amount,
            new_principal_repayments.amount,
            admin_events.old_created_at,
            admin_events.new_created_at,
            admin_events.old_repaid_at,
            admin_events.new_repaid_at,
            admin_events.old_unpaid_at,
            admin_events.new_unpaid_at,
            admin_events.old_deleted_at,
            admin_events.new_deleted_at,
            admin_events.created_at
        )
        .join(admins).on(admins.id == admin_events.admin_id)
        .join(old_principals).on(old_principals.id == admin_events.old_principal_id)
        .join(new_principals).on(new_principals.id == admin_events.new_principal_id)
        .join(old_principal_repayments)
        .on(old_principal_repayments.id == admin_events.old_principal_repayment_id)
        .join(new_principal_repayments)
        .on(new_principal_repayments.id == admin_events.new_principal_repayment_id)
        .where(admin_events.loan_id == Parameter('%s'))
        .get_sql(),
        (loan_id,)
    )
    can_view_admins = VIEW_ADMIN_EVENT_AUTHORS_PERM in perms
    row = itgs.read_cursor.fetchone()
    while row is not None:
        result.append(
            models.AdminLoanEvent(
                event_type='admin',
                occurred_at=row[-1].timestamp(),
                admin=(row[0] if can_view_admins else None),
                reason=(row[1] if can_view_admins else None),
                old_principal_minor=row[2],
                new_principal_minor=row[3],
                old_principal_repayment_minor=row[4],
                new_principal_repayment_minor=row[5],
                old_created_at=row[6].timestamp(),
                new_created_at=row[7].timestamp(),
                old_repaid_at=row[8].timestamp() if row[8] is not None else None,
                new_repaid_at=row[9].timestamp() if row[9] is not None else None,
                old_unpaid_at=row[10].timestamp() if row[10] is not None else None,
                new_unpaid_at=row[11].timestamp() if row[11] is not None else None,
                old_deleted_at=row[12].timestamp() if row[12] is not None else None,
                new_deleted_at=row[13].timestamp() if row[13] is not None else None
            )
        )
        row = itgs.read_cursor.fetchone()

    repayment_events = Table('loan_repayment_events')
    repayments = moneys.as_('repayments')
    itgs.read_cursor.execute(
        Query.from_(repayment_events)
        .select(
            repayments.amount,
            repayment_events.created_at
        )
        .join(repayments).on(repayments.id == repayment_events.repayment_id)
        .where(repayment_events.loan_id == Parameter('%s'))
        .get_sql(),
        (loan_id,)
    )
    row = itgs.read_cursor.fetchone()
    while row is not None:
        result.append(
            models.RepaymentLoanEvent(
                event_type='repayment',
                occurred_at=row[1].timestamp(),
                repayment_minor=row[0]
            )
        )
        row = itgs.read_cursor.fetchone()

    unpaid_events = Table('loan_unpaid_events')
    itgs.read_cursor.execute(
        Query.from_(unpaid_events)
        .select(
            unpaid_events.unpaid,
            unpaid_events.created_at
        )
        .where(unpaid_events.loan_id == Parameter('%s'))
        .get_sql(),
        (loan_id,)
    )
    row = itgs.read_cursor.fetchone()
    while row is not None:
        result.append(
            models.UnpaidLoanEvent(
                event_type='unpaid',
                occurred_at=row[1].timestamp(),
                unpaid=row[0]
            )
        )
        row = itgs.read_cursor.fetchone()

    result.sort(key=lambda x: x.occurred_at)
    return result
