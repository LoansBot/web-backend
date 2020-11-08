from pydantic import BaseModel


class RatelimitResponse(BaseModel):
    """Describes the state of a tokenized ratelimit. The underlying algorithm
    for ratelimiting is based on https://github.com/smyte/ratelimit.

    Attributes:
    - `current_tokens (int, None)`: The number of tokens we had when we last
      granted tokens to this bucket. None if the bucket is full.
    - `last_refill (float, None)`: The time at which we last refilled this
      bucket. None if the bucket is full.
    - `time_since_refill (float, None)`: The number of seconds which have
      passed since we last refilled this bucket.
    - `num_refills (int, None)`: The number of refills that should have
      occurred since we last refilled this bucket. We _actually_ refill only
      when consuming tokens from a bucket.
    - `effective_tokens (int)`: The number of tokens that can be consumed
      from this bucket right now.
    - `new_last_refill (float, None)`: The `last_refill` value that would be
      set on this bucket if we refilled tokens right now. None if the bucket
      is full.
    - `max_tokens (int)`: The maximum number of tokens that can be in this
      bucket.
    - `refill_time_ms (int)`: The time between refills, in whole milliseconds,
      for this bucket.
    - `refill_amount (int)`: The number of tokens refilled every `refill_time_ms`
      within this bucket.
    - `strict (bool)`: True if the user is punished for requests that exceed the
      ratelimit by consuming all available tokens even though the request is
      ultimately failed. False if the user is not punished for requests that are
      ratelimited.
    """
    current_tokens: int = None
    last_refill: float = None
    time_since_refill: float = None
    num_refills: int = None
    effective_tokens: int
    new_last_refill: float = None
    max_tokens: int
    refill_time_ms: int
    refill_amount: int
    strict: bool
