"""Contains the models used for responses endpoints"""
from models import SuccessResponse, UserRef
from pydantic import BaseModel
import typing


class ResponseIndex(SuccessResponse):
    """The responses to indexing all responses; provides the names of
    all responses

    @param responses An array of the names of responses in an arbitrary order
    """
    responses: typing.Array[str]


class ResponseShow(SuccessResponse):
    """Describes a single response when we're viewing it. The historical info
    is not included.

    @param id The primary id of the response
    @param name The name of the response
    @param body The current response format
    @param desc A description of the response which is not publicly visible
    @param created_at The time in seconds since utc epoch this was first created
    @param updated_at The time in seconds since utc epoch this was last updated
    """
    id: int
    name: str
    body: str
    desc: str
    created_at: int
    updated_at: int


class ResponseHistoryItem(BaseModel):
    """Describes a single piece of history for a response.

    @param id The id of the response history
    @param edited_by Who made this edit, potentially null if the user was
        deleted
    @param edited_reason The reason the person provided for this edit
    @param old_body The old format for the response or null if this is the
        first piece of history and a response history was generated for
        the creation
    @param new_body The new format for the response
    @param old_desc The old description for the response if available
    @param new_desc The new description of the response
    @param edited_at The time in seconds since utc when this edit occurred
    """
    id: int
    edited_by: UserRef = None
    edited_reason: str
    old_body: str = None
    new_body: str
    old_desc: str = None
    new_desc: str
    edited_at: int


class ResponseHistoryList(BaseModel):
    """Describes the list of edits on a particular response.

    @param items The history items
    """
    items: typing.List[ResponseHistoryItem]


class ResponseHistory(SuccessResponse):
    """The recent response histories on a particular response.

    @param history The recent history of the response
    @param number_truncated The number of history items which were not returned
        for this response history
    """
    history: ResponseHistoryList
    number_truncated: int


class ResponseEditArgs(BaseModel):
    """Describes the arguments that are sent to edit a particular response. The
    URL will provide which response you are editing.

    @param body The new body for the response
    @param desc The new description for the response
    @param edit_reason The reason for making the edit
    """
    body: str
    desc: str
    edit_reason: str


class ResponseCreateArgs(BaseModel):
    """Describes the arguments that are sent to create a new response. Note
    that without any code-changes creating a new response won't actually do
    anything since the response won't ever get sent.

    @param name The name for the response.
    @param body The body for the response.
    @param desc The description for the response
    """
    name: str
    body: str
    desc: str
