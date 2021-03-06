"""Helper functions and constants for trusts. Where not specified, permissions
are strictly enforced. If they are not strictly enforced it's to support more
aggressive caching, so that most requests can be served very quickly."""
from pypika import PostgreSQLQuery as Query, Table, Parameter
import users.helper

VIEW_SELF_TRUST_PERMISSION = 'view-self-trust'
"""The permission required to view ones own trust status. This permission
is not strictly enforced."""

VIEW_OTHERS_TRUST_PERMISSION = 'view-others-trust'
"""The permission required to view others trust status. This permission
is not strictly enforced."""

VIEW_TRUST_REASON_PERMISSION = 'view-trust-reasons'
"""The permission required to view the reason behind trust statuses."""

UPSERT_TRUST_PERMISSION = 'upsert-trusts'
"""The permission to add or edit trust statuses on users."""

VIEW_TRUST_QUEUE_PERMISSION = 'view-trust-queue'
"""The permission required to view the trust queue"""

EDIT_TRUST_QUEUE_PERMISSION = 'edit-trust-queue'
"""The permission required to edit existing items on the trust queue"""

ADD_TRUST_QUEUE_PERMISSION = 'add-trust-queue'
"""The permission required to add items to the trust queue"""

REMOVE_TRUST_QUEUE_PERMISSION = 'remove-trust-queue'
"""The permission required to remove items from the trust queue"""

VIEW_TRUST_COMMENTS_PERMISSION = 'view-trust-comments'
"""The permission required to view trust comments and edit ones own trust
comments within 24 hours of posting the comment."""

CREATE_TRUST_COMMENTS_PERMISSION = 'create-trust-comments'
"""The permission required to create trust comments"""


def create_server_trust_comment(itgs, comment, user_id=None, username=None):
    """Create an autogenerated comment on the given users trustworthiness,
    where the user is specified either via id or username. This does not
    commit the comment. This will create the user if specified via username
    and they do not exist.

    Arguments:
    - `itgs (LazyIntegrations)`: The lazy integrations to use
    - `comment (str)`: The comment to post
    - `user_id (int, None)`: The id of the user to post the comment on or
        None if the user is specified via the username.
    - `username (str, None)`: The username of the user to post the comment on
        or None if the user is specified via the user id.
    """
    assert (user_id is None) != (username is None), f'user_id={user_id}, username={username}'

    usrs = Table('users')
    if user_id is None:
        itgs.read_cursor.execute(
            Query.from_(usrs).select(usrs.id)
            .where(usrs.username == Parameter('%s'))
            .get_sql(),
            (username.lower(),)
        )
        row = itgs.read_cursor.fetchone()
        if row is None:
            user_id = users.helper.create_new_user(itgs, username.lower())
        else:
            (user_id,) = row

    itgs.read_cursor.execute(
        Query.from_(usrs).select(usrs.id)
        .where(usrs.username == Parameter('%s'))
        .get_sql(),
        ('loansbot',)
    )
    row = itgs.read_cursor.fetchone()
    if row is None:
        loansbot_user_id = users.helper.create_new_user(itgs, 'loansbot')
    else:
        (loansbot_user_id,) = row

    trust_comments = Table('trust_comments')
    itgs.write_cursor.execute(
        Query.into(trust_comments).columns(
            trust_comments.author_id,
            trust_comments.target_id,
            trust_comments.comment
        ).insert(*[Parameter('%s') for _ in range(3)])
        .get_sql(),
        (loansbot_user_id, user_id, comment)
    )
