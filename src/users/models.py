"""Contains the models that are used for users"""
from models import SuccessResponse
from pydantic import BaseModel
import typing


class PasswordAuthentication(BaseModel):
    """Describes the password authentication that the client can send to the
    server to prove their identity."""
    username: str
    password: str
    password_authentication_id: int = None
    recaptcha_token: str = None


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


class Username(BaseModel):
    """A username"""
    username: str


class ClaimArgs(BaseModel):
    """Claim an account using a claim token, setting the human password to
    the given value"""
    user_id: int
    claim_token: str
    password: str
    recaptcha_token: str


class UserShowSelfResponse(BaseModel):
    """The response that's provided if you GET yourself; where your identity
    is proven using a token"""
    username: str


class UserPermissions(BaseModel):
    """The response that's provided for a users permissions."""
    permissions: typing.List[str]
