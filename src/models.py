"""The main models used in many different endpoints"""
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Indicates the operation did not succeed. Usually identified with the
    status code"""
    message: str = None


class SuccessResponse(BaseModel):
    """Indicates the operation succeeded. Usually identified with the status
    code"""
    pass


class UserRef(BaseModel):
    """A reference to a particular user."""
    id: int
    username: str
