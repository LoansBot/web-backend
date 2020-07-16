"""Contains the models that are used for users"""
from models import SuccessResponse
from pydantic import BaseModel, validator
import typing
import re


class PasswordAuthentication(BaseModel):
    """Describes the password authentication that the client can send to the
    server to prove their identity."""
    username: str
    password: str
    password_authentication_id: int = None
    captcha_token: str = None


class TokenAuthentication(BaseModel):
    """Describes a token authorization that the client can send to the server
    to prove their identity."""
    token: str


class TokenResponse(SuccessResponse):
    """Describes a token response that the server can provide to the client
    when they prove their identity using a non-token authorization so they
    can use token authentication in the future"""
    user_id: int
    token: str
    expires_at_utc: float


class ClaimRequestArgs(BaseModel):
    """A username and captcha token"""
    username: str
    captcha_token: str

    @validator('username')
    def matches_username_regex(cls, v):
        if not re.match(r'[A-Za-z0-9_-]{3,20}', v):
            raise ValueError('be a valid username')
        return v


class ClaimArgs(BaseModel):
    """Claim an account using a claim token, setting the human password to
    the given value"""
    user_id: int
    claim_token: str
    password: str


class UserShowSelfResponse(BaseModel):
    """The response that's provided if you GET yourself; where your identity
    is proven using a token"""
    username: str


class UserShowResponse(BaseModel):
    """The response for showing a particular user by id"""
    username: str


class UserPermissions(BaseModel):
    """The response that's provided for a users permissions."""
    permissions: typing.List[str]


class UserLookupResponse(BaseModel):
    """The success response to looking up a user by their username

    Attributes:
    - `id (int)`: The users id
    """
    id: int


class UserSuggestResponse(BaseModel):
    """The success response to searching for users with a partial
    match.

    Attributes:
    - `suggestions (list[str])`: The list of usernames we suggest
    """
    suggestions: typing.List[str]
