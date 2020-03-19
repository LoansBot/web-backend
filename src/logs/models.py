"""Contains the models that are used for logging"""
from models import SuccessResponse
from pydantic import BaseModel
import typing


class LogApplicationResponse(BaseModel):
    """Describes a single log application in a response"""
    name: str


class LogApplicationsResponse(SuccessResponse):
    """A response that indicates all of the log applications that we support
    logs for. This currently doesn't paginate as it's not expected to go
    above 10-20 results for the forseeable future."""
    applications = typing.Dict[int, LogApplicationResponse]


class LogResponse(BaseModel):
    """Describes the response for a single log event

    @param app_id The id of the application which made this response
    @param identifier Typically the name of the file which issued the
      event
    @param level The level of the event, from 0-4 where 0 = trace (see
      https://github.com/LoansBot/logging/blob/master/src/lblogging/level.py)
    @param message The message associated with the event
    @param created_at When the message was issued in seconds since utc epoch
    """
    app_id: int
    identifier: str
    level: int
    message: str
    created_at: int


class LogsResponse(SuccessResponse):
    """The response that is sent when a list of logs are requested"""
    logs: list  # items are LogResponse
