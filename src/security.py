"""Contains some useful security context managers"""
import time
from contextlib import contextmanager
import typing


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
            time.sleep(elapsed - duration)


def verify_recaptcha(token: typing.Optional[str]) -> bool:
    """Verifies that the given token is a valid recaptcha token str"""
    if token is None:
        return False
    # TODO
    return True
