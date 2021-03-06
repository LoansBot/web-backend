"""Contains some useful security context managers"""
import time
from contextlib import contextmanager
import typing
import os
from lblogging import Level
from datetime import timedelta
import requests


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


def verify_captcha(itgs, token: typing.Optional[str]) -> bool:
    """Verifies that the given token is a valid captcha token str"""
    if token is None:
        return False
    if os.environ.get('HCAPTCHA_DISABLED', '0') == '1':
        return True
    secret_key = os.environ.get('HCAPTCHA_SECRET_KEY')
    if secret_key == '0':
        secret_key = None
    response = requests.post(
        'https://hcaptcha.com/siteverify',
        data={
            'secret': secret_key,
            'response': token
        }
    )
    try:
        json = response.json()
    except:  # noqa
        itgs.logger.print(
            Level.WARN,
            'hCaptcha siteverify did not return json! Instead I got: '
            '{} (status code={})', response.content, response.status_code
        )
        return False
    if json.get('success') is None:
        itgs.logger.print(
            Level.WARN,
            'Unexpected response type from hcaptcha siteverify. Expected json '
            'response with a \'success\' field but got {} (status_code={})',
            json, response.status_code
        )
        return False
    return json['success']


def ratelimit(itgs, environ_key, key_prefix, defaults=None, cost=1) -> bool:
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
        with LazyItgrs() as itgs
            if not ratelimit(
                    itgs,
                    'MAX_HUMAN_LOGINS',
                    'human_logins',  # will use human_logins_30 for 30 second store
                    {30: 5}): # No more than 5 logins in 30 seconds
                return Response(status_code=429)

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

    The cost of the request may be any integer value, and it will decide how
    much of the ratelimit is consumed by this request. Typically this is 1.
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
            itgs.logger.exception(
                Level.WARN,
                'Environment variable {} is malformed, using defaults',
                environ_key
            )

    succ = True
    for interval, max_num in settings.items():
        if interval <= 0 or max_num <= 0:
            itgs.logger.print(
                Level.WARN,
                'Default settings for {} are malformed',
                environ_key
            )
            continue

        cache_key = f'{key_prefix}_{interval}'
        cnt_now = itgs.cache.incr(cache_key, cost)
        if cnt_now is None:
            if itgs.cache.add(cache_key, cost, expire=interval, noreply=False):
                cnt_now = cost
            else:
                cnt_now = itgs.cache.incr(cache_key, cost)

        if cnt_now > max_num:
            succ = False

            if cnt_now - cost < max_num:
                itgs.logger.print(
                    Level.WARN,
                    'Rate-limiting initiated: {} requests in {} exceeds {}',
                    cnt_now, timedelta(seconds=interval), environ_key
                )

    return succ
