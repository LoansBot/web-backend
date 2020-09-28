"""The main models used in many different endpoints"""
from pydantic import BaseModel, validator


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


class TestPostBody(BaseModel):
    payload: str

    @validator('payload')
    def lte_8_chars(cls, v):
        if len(v) > 8:
            raise ValueError('payload too large')
        return v.strip()
