"""Contains some useful security context managers"""
import time
from contextlib import contextmanager
import typing
import os
import integrations as itgs
from lblogging import Level
from datetime import timedelta


@contextmanager
def fixed_duration(duration: float):
    """After yielding, sleeps to buffer until the given duration has elapsed.
    The duration should be chosen so that it's almost always longer than the
    function being run, essentially preventing timing attacks"""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if elapsed < duration:
            time.sleep(duration - elapsed)


def verify_recaptcha(token: typing.Optional[str]) -> bool:
    """Verifies that the given token is a valid recaptcha token str"""
    if token is None:
        return False
    secret_key = os.environ.get('RECAPTCHA_SECRET_KEY')
    if secret_key is None:
        return True
    # TODO
    return True


def ratelimit(cache, environ_key, key_prefix, defaults=None, logger=None) -> bool:
    """Ratelimits a resource by preventing more than a given number of requests
    from occurring in a given interval. The ratelimiting amounts may be
    specified in environment variables. We use an ephemeral cache to store how
    many requests to ratelimit for easier expiration and faster turnaround,
    which could potentially be abused by purposely blowing the cache. Global
    sanity checks on things that add cache keys are recommended.

    If stored in an environment variable, the rate limits would be specified
    as int=int,...,int=int where the first number in a pair is the number of
    seconds for the interval in question and the second is the maximum number
    of requests in that interval.

    In defaults these will be stored as simple key-value pairs in a dict, where
    the keys correspond to the seconds in the interval and the values are the
    maximum number of requests.

    example::
        with itgs.memcached() as cache:
            ratelimit(
                cache,
                'MAX_HUMAN_LOGINS',
                'human_logins',  # will use human_logins_30 for 30 second store
                {30: 5} # No more than 5 logins in 30 seconds
            )

        # example to change to 5 in 30 seconds or 20 in 30 minutes using an
        # environment variable:
        # export MAX_HUMAN_LOGINS="30=5,1800=20"
        #
        # example to disable login ratelimiting:
        # export MAX_HUMAN_LOGINS=0

    A logger may be passed if it's already initialized, however this only logs
    if there is an error with one of the settings or we just reached a rate
    limiting threshold, which won't happen on most requests so if a logger is
    not otherwise going to be used it should be initialized only if needed.
    """
    if os.environ.get('RATELIMIT_DISABLED', '0') != '0':
        return True

    settings = defaults
    env_limiting = os.environ.get(environ_key, '0')
    if env_limiting != '0':
        try:
            kvps = env_limiting.split(',')
            kvps = map(lambda pair: map(int, pair.split('=')), kvps)
            for k, v in kvps:
                if k <= 0 or v <= 0:
                    raise ValueError(f'Weird key-value pair {k}={v}')
            settings = kvps
        except ValueError:
            with itgs.logger(iden='security.py', val=logger) as lgr:
                lgr.exception(
                    Level.WARN,
                    'Environment variable {} is malformed, using defaults',
                    environ_key
                )

    succ = True
    for interval, max_num in settings.items():
        if interval <= 0 or max_num <= 0:
            with itgs.logger(iden='security.py', val=logger) as lgr:
                lgr.print(
                    Level.WARN,
                    'Default settings for {} are malformed',
                    environ_key
                )
            continue

        cache_key = f'{key_prefix}_{interval}'
        cnt_now = cache.incr(cache_key, 1)
        if cnt_now is None:
            if cache.add(cache_key, 1, expire=interval, noreply=False):
                cnt_now = 1
            else:
                cnt_now = cache.incr(cache_key, 1)

        if cnt_now > max_num:
            succ = False

            if cnt_now == max_num + 1:
                with itgs.logger(iden='security.py', val=logger) as lgr:
                    lgr.print(
                        Level.WARN,
                        'Rate-limiting initiated: {} requests in {} exceeds {}',
                        cnt_now, timedelta(seconds=interval), environ_key
                    )

    return succ
