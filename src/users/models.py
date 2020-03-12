"""Contains the models that are used for users"""
import typing
from pydantic import BaseModel


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


class TokenResponse(BaseModel):
    """Describes a token response that the server can provide to the client
    when they prove their identity using a non-token authorization so they
    can use token authentication in the future"""
    token: str
    expires_at_utc: float
