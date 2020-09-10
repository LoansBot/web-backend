"""Describes generic models used in legacy code."""
from pydantic import BaseModel
import typing


class PHPError(BaseModel):
    """Describes an error which is the combination of a unique identifier and
    an error message string.

    Attributes:
    - `error_type (str)`: A unique slug which identifies this error within the
      endpoint. There are some common ones, mainly INVALID_ARGUMENT.
    - `error_message (str)`: A human readable string that explains the error
    """
    error_type: str
    error_message: str


class PHPErrorResponse(BaseModel):
    """The typical failure response from the LoansBot-Site-New repository.
    There was nothing particularly wrong with this response style and it was
    very popular at the time as it's pretty convenient when response status
    code checking is tedious for an api.

    Tooling for checking response codes has greatly improved though, so we
    don't need to go through this process anymore. There are also more
    standard response styles which are actually a bit inferior to this
    but ended up becoming more popular (e.g. the FastAPI default 422 or the
    Rails default 422).

    Attributes:
    - `success (bool)`: False
    - `result_type (str)`: The value 'FAILURE'
    - `errors (iterable[PHPError])`: All the errors with the request.
    """
    success: bool = False
    result_type: str = 'FAILURE'
    errors: typing.List[PHPError]
