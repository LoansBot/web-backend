"""The responses and body signatures used in permissions"""
from pydantic import BaseModel
import typing


class Permission(BaseModel):
    """The extra information about a permission."""
    description: str


class PermissionsList(BaseModel):
    """A list of permissions. The list is contains just the names of the
    permissions"""
    permissions: typing.List[str]
