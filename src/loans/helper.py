"""Helper file for loans"""
from pypika import PostgreSQLQuery as Query, Table, Parameter
from pypika.functions import Greatest
import lbshared.ratelimits
import hashlib
from pydantic.error_wrappers import ValidationError
from lblogging import Level


RATELIMIT_WHITELIST_PERM = 'ignore_global_api_limits'
"""The name of the permission that exempts a user from global ratelimits. They
both aren't restricted by the global restricted and don't count toward the
global ratelimit"""

RATELIMIT_USER_SPECIFIC_PERM = 'specific_user_api_limits'
"""The name of the permission that gives a user custom ratelimit, including no
ratelimit."""

DELETED_LOANS_PERM = 'view_deleted_loans'
"""The name of the permission that gives a user permission to view deleted
loans"""


RATELIMIT_PERMISSIONS = (
    RATELIMIT_WHITELIST_PERM,
    RATELIMIT_USER_SPECIFIC_PERM
)
"""Contains the permissions that this module cares about for ratelimiting."""


RATELIMIT_PERMS_COLLECTION = 'api_ratelimit_perms'
"""The Arango collection that we expect user-specific ratelimit restrictions to
be stored in. Should be a persistent collection (no TTL)"""


RATELIMIT_TOKENS_COLLECTION = 'api_ratelimit_tokens'
"""The Arango collection that we expect ratelimit tokens to be stored in.
Should have a TTL index."""


USER_RATELIMITS = lbshared.ratelimits.Settings(
    collection_name=RATELIMIT_TOKENS_COLLECTION,
    max_tokens=600,
    refill_amount=10,
    refill_time_ms=2000,
    strict=True
)
"""Default user ratelimits."""


GLOBAL_RATELIMITS = lbshared.ratelimits.Settings(
    collection_name=RATELIMIT_TOKENS_COLLECTION,
    max_tokens=1800,
    refill_amount=1,
    refill_time_ms=66,
    strict=False
)
"""Global ratelimit settings"""


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


def check_ratelimit(itgs, user_id, permissions, cost) -> bool:
    """The goal of ratelimiting is to ensure that no single entity is causing an
    excessive burden on the website while performing meaningful requests. This
    does not do anything to prevent layer 3 or 4 denial of service attacks, and
    although it can mitigate layer 7 denial of service attacks it is only
    effective against unintentional attacks where back-off procedures are in
    place and just need to be triggered.

    The desirable outcome is that anyone which wants to use a small number of
    resources for a short period of time, such as for development or testing,
    they can do so effortlessly. Furthermore, if there are no malicious actors
    than this should be a fairly reliable approach.

    However, if someone either needs to make a lot of requests or a make
    requests over an extended period of time they should contact us for
    whitelisting.

    Users which are not whitelisted all share the same pool of resources, and
    hence any one of them acting maliciously will cause all of them to be
    punished. Users which are whitelisted will be only be punished for their own
    actions so long as there are enough available resources to serve their
    requests.

    This is accomplished as follows:
    - All non-whitelisted users plus non-authenticated requests share a
      a global pool of resources.
    - Authenticated non-whitelisted users also have specific ratelimiting. This
      is under the assumption that they are acting benevolently if they chose
      to authenticate and would want a warning if they are making too many
      requests. Plus we can actually give them a warning since we have contact
      details.
    - A whitelisted user can either have the default per-user ratelimiting, as
      non-whitelisted users do, a custom ratelimit, or no ratelimit at all.
      + The whitelist permission is "ignore_global_api_limits"
      + The permission for a custom ratelimit is "specific_user_api_limits".
        The details are stored in Arango.
      + A user with custom ratelimiting but no details found in Arango will
        have no ratelimiting restrictions.

    The actual algorithm is the same as https://github.com/smyte/ratelimit but
    stored in ArangoDB (on the RocksDB engine) and using a TTL instead of
    compaction filters for cleanup.
    """
    user_specific_settings = USER_RATELIMITS
    if RATELIMIT_USER_SPECIFIC_PERM in permissions:
        coll = itgs.kvs_db.collection(RATELIMIT_PERMS_COLLECTION)
        body = coll.read_doc(str(user_id))
        if body is not None:
            try:
                user_specific_settings = lbshared.ratelimits.Settings(**body)
            except ValidationError:
                itgs.logger.exception(
                    Level.WARN,
                    'Bad user-specific ratelimit settings for user_id={}',
                    user_id
                )
        else:
            user_specific_settings = None

    acceptable = True
    if user_specific_settings is not None:
        acceptable = (
            lbshared.ratelimits.consume(itgs, user_specific_settings, str(user_id), cost)
            and acceptable
        )

    if RATELIMIT_WHITELIST_PERM not in permissions:
        acceptable = (
            lbshared.ratelimits.consume(itgs, GLOBAL_RATELIMITS, 'global', cost)
            and acceptable
        )

    return acceptable
