from pydantic import BaseModel, validator
import re


COMMENT_FULLNAME_REGEX = r't1_[A-Za-z0-9]{1,15}'
"""Regex for a comment fullname"""

LINK_FULLNAME_REGEX = r't3_[A-Za-z0-9]{1,15}'
"""Regex for a link fullname"""


class RecheckRequest(BaseModel):
    """A request sent from the client to the server to recheck a particular
    comment.

    Attributes:
    - `comment_fullname (str)`: The fullname of the comment to recheck, e.g.,
        t1_xyz
    - `link_fullname (str)`: The fullname of the link the comment to recheck
        is in, e.g., t3_abc
    """
    comment_fullname: str
    link_fullname: str

    @validator('comment_fullname')
    def meets_comment_regex(cls, v):
        if not re.match(COMMENT_FULLNAME_REGEX, v):
            raise ValueError(f'to match regex {COMMENT_FULLNAME_REGEX}')
        return v

    @validator('link_fullname')
    def meets_link_regex(cls, v):
        if not re.match(LINK_FULLNAME_REGEX, v):
            raise ValueError(f'to match regex {LINK_FULLNAME_REGEX}')
        return v
