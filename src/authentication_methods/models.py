from pydantic import BaseModel, validator
import typing


class AuthMethodPermissions(BaseModel):
    granted: typing.List[str]


class AuthMethodHistoryItem(BaseModel):
    event_type: str
    reason: str
    username: str = None
    permission: str = None
    occurred_at: float


class AuthMethodHistory(BaseModel):
    history: typing.List[AuthMethodHistoryItem]
    next_id: int = None


class Reason(BaseModel):
    reason: str

    @validator('reason')
    def atleast_3_chars(cls, v):
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError('must be at least 3 characters stripped')
        return stripped


class ChangePasswordParams(BaseModel):
    password: str
    reason: str

    @validator('password')
    def atleast_6_chars(cls, v):
        stripped = v.strip()
        if len(stripped) < 6:
            raise ValueError('must be at least 6 characters stripped')
        return stripped

    @validator('reason')
    def atleast_3_chars(cls, v):
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError('must be at least 3 characters stripped')
        return stripped


class AuthMethod(BaseModel):
    main: bool
    deleted: bool
    active_grants: int
