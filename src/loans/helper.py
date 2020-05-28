"""Helper file for loans"""
from pypika import PostgreSQLQuery as Query, Table, Parameter, Order
from pypika.functions import Greatest
import hashlib


def calculate_etag(itgs, loan_id) -> str:
    """Calculates a valid etag for the loan with the given id. If no such loan
    exists this returns None.
    """
    loans = Table('loans')
    event_tables = [Table(t) for t in [
        'loan_admin_events', 'loan_creation_infos',
        'loan_repayment_events', 'loan_unpaid_events'
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
        q = q.join(tbl).on(loans.id == tbl.loan_id)
    q = q.where(loans.id == Parameter('%s'))

    itgs.read_cursor.execute(
        q.get_sql(),
        (loan_id,)
    )
    row = itgs.cursor.fetchone()

    if row is None:
        return None

    (updated_at,) = row[0]

    raw_str = f'{loan_id}-{updated_at.timestamp()}'
    return hashlib.sha256(raw_str.encode('ASCII')).hexdigest()


def check_ratelimit(itgs, cost) -> bool:
    pass
