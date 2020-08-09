"""Contains helpful functions for ratelimiting API calls. Any API call which
is not moderator-only should be ratelimited in some fashion.
"""
import lbshared.ratelimits
from lbshared.user_settings import get_settings


RATELIMIT_PERMISSIONS = tuple()
"""Contains the permissions that this module cares about for ratelimiting."""


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


def check_ratelimit(itgs, user_id, permissions, cost, settings=None) -> bool:
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

    Arguments:
    - `itgs (LazyIntegrations)`: The lazy integrations to use to connect to
        networked services.
    - `user_id (int, None)`: The id of the user making the request or None if
        the request was not authenticated.
    - `permissions (list[str])`: The list of permissions the user has; only
        the permissions in `RATELIMIT_PERMISSIONS` will be considered.
    - `cost (int)`: The amount toward their quota they are attempting to use.
    - `settings (lbshared.user_settings.UserSettings, None)`: If the users
        settings have already been fetched they can be included here to avoid
        unnecessarily duplicating the request. Otherwise this is None and the
        user settings will be fetched.

    Returns:
    - `success (bool)`: True if they had enough resources to consume, False if
        they did not.
    """
    acceptable = True
    global_applies = True

    user_specific_settings = USER_RATELIMITS
    if settings is None and user_id is not None:
        settings = get_settings(itgs, user_id)
        global_applies = settings.global_ratelimit_applies

    if user_id is not None and settings.user_specific_ratelimit:
        user_specific_settings = lbshared.ratelimits.Settings(
            collection_name=user_specific_settings.collection_name,
            max_tokens=settings.ratelimit_max_tokens or user_specific_settings.max_tokens,
            refill_amount=(
                settings.ratelimit_refill_amount or user_specific_settings.refill_amount),
            refill_time_ms=(
                settings.ratelimit_refill_time_ms or user_specific_settings.refill_time_ms),
            strict=(
                user_specific_settings.strict
                if settings.ratelimit_strict is None
                else settings.ratelimit_strict
            )
        )

    if user_specific_settings is not None:
        acceptable = (
            lbshared.ratelimits.consume(itgs, user_specific_settings, str(user_id), cost)
            and acceptable
        )

    if global_applies:
        if acceptable:
            acceptable = lbshared.ratelimits.consume(itgs, GLOBAL_RATELIMITS, 'global', cost)
        else:
            # This request is definitely going to be cheap since we're
            # not doing anything, so we're not going to punish everyone
            # else for more than just a simple request
            lbshared.ratelimits.consume(itgs, GLOBAL_RATELIMITS, 'global', 1)

    return acceptable
