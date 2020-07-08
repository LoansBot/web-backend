"""A collection of useful functions for working with a users settings. We store
user settings in arango with no TTL. A users settings are fixed when created,
meaning that even if you never change your settings and we change the default,
your settings won't be affected.

The exception to this are ratelimits, because although their settings don't
change we have a boolean 'user-specific-ratelimit' which must be set to True
for a users ratelimit to be frozen. This is because our assumption is that
ratelimit changes will _generally_ be beneficial (i.e., reducing restrictions),
so freezing as a default probably won't be beneficial.
"""
from pydantic import BaseModel
import time


VIEW_OTHERS_SETTINGS_PERMISSION = 'view-others-settings'
"""The permission required to view others settings"""

VIEW_SETTING_CHANGE_AUTHORS_PERMISSION = 'view-setting-change-authors'
"""The permission required to view change author usernames on settings
events. With this permission the user can see who modified their settings
if it wasn't them, without it they cannot see who modified their settings
if it wasn't them, although they will know it wasn't them."""

EDIT_OTHERS_STANDARD_SETTINGS_PERMISSION = 'edit-others-standard-settings'
"""The permission required to edit the standard settings on
someone elses behalf, e.g., request opt out."""

EDIT_RATELIMIT_SETTINGS_PERMISSION = 'edit-ratelimit-settings'
"""The permission required to edit ones own ratelimit settings.
"""

EDIT_OTHERS_RATELIMIT_SETTINGS_PERMISSION = 'edit-others-ratelimit-settings'
"""The permission required to edit ratelimit settings for other
people."""


class UserSettings(BaseModel):
    """The actual settings for a user. This is not something we necessarily
    want to expose in its raw format. This is not meant to be returned or
    accepted from any endpoints.

    Attributes:
    - `non_req_response_opt_out (bool)`: False if the user should receive
        a public response from the LoansBot on any non-meta submission to
        the subreddit explaining his/her history, True if they should only
        receive such a response on request posts.
    - `borrower_req_pm_opt_out (bool)`: False if the user should receive
        a reddit private message from the LoansBot if any of their active
        borrowers makes a request thread, True if the user should not
        receive that pm.
    - `user_specific_ratelimit (bool)`: True if the users ratelimit is frozen,
        i.e., their ratelimit has been set such that it's not affected by
        changes to the default user ratelimit.
    - `ratelimit_max_tokens (int, None)`: None if and only if the user does not
        have a specific ratelimit. Otherwise, the maximum number of tokens that
        the user can accumulate.
    - `ratelimit_refill_amount (int, None)`: None if and only if the user does
        not have a specific ratelimit. Otherwise, the amount of tokens refilled
        at each interval.
    - `ratelimit_refill_time_ms (int, None)`: None if and only if the user
        does not have a specific ratelimit. Otherwise, the number of
        milliseconds between the user receiving more ratelimit tokens.
    - `ratelimit_strict (bool, None)`: None if and only if the user does not
        have a specific ratelimit. Otherwise, True if the users ratelimit
        interval should be reset when one of their requests are ratelimited and
        False if their should receive their ratelimit tokens every ratelimit
        interval even if we are actively ratelimiting them.
    """
    non_req_response_opt_out: bool
    borrower_req_pm_opt_out: bool
    global_ratelimit_applies: bool
    user_specific_ratelimit: bool
    ratelimit_max_tokens: int = None
    ratelimit_refill_amount: int = None
    ratelimit_refill_time_ms: int = None
    ratelimit_strict: bool = None


DEFAULTS = [
    UserSettings(
        non_req_response_opt_out=False,
        borrower_req_pm_opt_out=False,
        global_ratelimit_applies=True,
        user_specific_ratelimit=False
    )
]
"""This contains the default settings in the order that they were changed,
in ascending time order. We freeze users to a particular index in this,
whatever the last index is at the time, and then store modifications.
"""

SETTINGS_KEYS = tuple(DEFAULTS[0].dict().keys())
"""The settings keys, which we use for fetching settings programmatically,
stored so we don't have to constantly regenerate them"""


USER_SETTINGS_COLLECTION = 'user-settings'


def get_settings(itgs, user_id: int) -> UserSettings:
    """Get the settings for the given user.

    Arguments:
    - `itgs (LazyIntegrations)`: The connections to use to connect to networked
        components.
    - `user_id (int)`: The id of the user whose settings should be fetched

    Returns:
    - `settings (UserSettings)`: The settings for that user.
    """
    doc = itgs.kvs_db.collection(USER_SETTINGS_COLLECTION).document(str(user_id))

    if not doc.read():
        doc.body['frozen'] = len(DEFAULTS) - 1
        if not doc.create():
            doc.read()

    base_settings = DEFAULTS[doc.body['frozen']]

    return UserSettings(
        **dict(
            [nm, doc.body.get(nm, getattr(base_settings, nm))]
            for nm in SETTINGS_KEYS
        )
    )


def set_settings(itgs, user_id: int, **values) -> list:
    """Set the given settings on the user. It's more efficient to do fewer
    calls with more values than more calls with fewer values. This guarrantees
    that the entire change is made, however of course if several calls
    occur at the same time, it's a race condition for who wins if their is
    overlap in the settings being changed.

    Attributes:
    - `itgs (LazyIntegrations)`: The integrations to use to connect to the store
    - `user_id (int)`: The id of the user whose settings should be changed.
    - `values (dict[any])`: The values to set, where the key is the key in
        UserSettings and the value is the new value to set.

    Returns:
    - `changes (dict[str, dict])`: The actual changes which were applied. This
        has keys which are a subset of the keys of values. The keys from values
        which were going to be set to the same value they are currently are
        stripped. Each value in change has the following keys:
        + `old (any)`: The old value for this property
        + `new (any)`: The new value for this property
    """
    doc = itgs.kvs_db.collection(USER_SETTINGS_COLLECTION).document(str(user_id))
    if not doc.read():
        doc.body['frozen'] = len(DEFAULTS) - 1
        if not doc.create():
            if not doc.read():
                raise Exception('High contention on user settings object!')

    for i in range(10):
        if i > 0:
            time.sleep(0.1 * (2 ** i))

        base_settings = DEFAULTS[doc.body['frozen']]

        changes = {}
        for key, val in values.items():
            def_val = getattr(base_settings, key)
            old_val = doc.body.get(key, def_val)
            if old_val != val:
                changes[key] = {
                    'old': old_val,
                    'new': val
                }

            if val == def_val:
                if key in doc.body:
                    del doc.body[key]
            else:
                doc.body[key] = val

        if doc.compare_and_swap():
            return changes

        if not doc.read():
            doc.body = {}
            doc.body['frozen'] = len(DEFAULTS) - 1
            if not doc.create():
                raise Exception(f'Ludicrously high contention on user settings for {user_id}')

    raise Exception('All 10 attempts to set user settings failed')
