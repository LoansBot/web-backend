from pydantic import BaseModel, validator
import typing


class TrustStatus(BaseModel):
    """
    Describes how we return or accept a trust to/from the client.

    Attributes:
    - `user_id (int)`: The primary identifier for the user this trust is for
    - `status (str)`: The trust status for this user. Acts as an enum and takes
        one of the following values:
        - `unknown`: This user has no reputation
        - `good`: This user is in good standing
        - `bad`: This user is in bad standing
    - `reason (str, None)`: The reason they have this trust status. This may
        be omitted based on authentication level or just at an endpoint level.
    """
    user_id: int
    status: str
    reason: str = None

    @validator('status')
    def is_known_value(cls, v):
        if v not in ('unknown', 'good', 'bad'):
            raise ValueError('bad status')
        return v


class UserTrustComment(BaseModel):
    """Describes a comment referring to the trustworthiness of a particular user.

    Attributes:
    - `id (int)`: The id of this comment, required for editing.
    - `author_id (int, None)`: The id of the user which made this comment.
        None if the user was deleted.
    - `target_id (int)`: The id of the person this comment is referring
        to.
    - `comment (str)`: The text of the comment.
    - `editable (bool)`: True if this comment may be edited, false otherwise.
    - `created_at (float)`: The time at which this comment was created in utc
        seconds since epoch.
    - `updated_at (float)`: The time at which this comment was most recently
        edited in utc seconds since epoch.
    """
    id: int
    author_id: int = None
    target_id: int
    comment: str
    editable: bool
    created_at: float
    updated_at: float


class UserTrustCommentRequest(BaseModel):
    """Describes a comment as sent from the client to us.

    Attributes:
    - `comment (str)`: The comment to post
    """
    comment: str

    @validator('comment')
    def comment_not_blank(cls, v: str):
        if len(v.strip()) == 0:
            raise ValueError('cannot be blank')
        return v.strip()

    @validator('comment')
    def comment_under_5000_chars(cls, v: str):
        if len(v) > 5000:
            raise ValueError('must be 5,000 chars or less')
        return v


class UserTrustCommentListResponse(BaseModel):
    """Describes a list of comments regarding a users trust.

    Attributes:
    - `comments (list[int])`: The ids of the comments in this paginated
        section.
    - `after_created_at (float, None)`: If there are comments with a later
        creation date, this is the creation date to pass to this endpoint to
        get the next set of comments.
    - `before_created_at (float, None)`: If there are comments with an earlier
        creation date, this is the creation date to pass to this endpoint to
        get the previous set of comments.
    """
    comments: typing.List[int]
    after_created_at: float = None
    before_created_at: float = None


class TrustQueueItem(BaseModel):
    """Describes a single item in the trust queue. This is a suggestion to
    review the users account at a particular date.

    Attributes:
    - `uuid (str, None)`: If this is used as a return type this is the trust
        queue item uuid.
    - `username (str)`: The username of the user who should be reviewed.
    - `review_at (float)`: The time at which the user should be reviewed, in
        utc seconds since epoch.
    """
    uuid: str = None
    username: str
    review_at: float


class TrustQueueItemUpdate(BaseModel):
    """Describes an update from the client to change the review time for a
    particular trust queue item.

    Attributes:
    - `review_at (float)`: The new review time in fractional utc seconds since
        epoch.
    """
    review_at: float


class TrustLoanDelay(BaseModel):
    """Describes a username who will automatically be added to the trust queue
    with the given review date (or the current date at the time if later) when
    they reach a certain number of loans.

    Attributes:
    - `username (str)`: The username of the user to create a loan delay for
    - `loans_completed_as_lender (int)`: The number of loans completed as
        lender which, once they reach, we will add them to the trust queue.
    - `review_no_earlier_than (float)`: The earliest date which their account
        should be reviewed. This is the earliest value which will be sent to
        the trust queue once they've reached the target number of loans
        completed as lender.
    """
    username: str
    loans_completed_as_lender: int
    review_no_earlier_than: float


class TrustLoanDelayResponse(BaseModel):
    """Describes the response when requesting the trust loan delay status on a
    given user.

    Attributes:
    - `loans_completed_as_lender (int)`: The number of loans completed as
        lender which, once they reach, we will add them to the trust queue.
    - `review_no_earlier_than (float)`: The earliest date which their account
        should be reviewed. This is the earliest value which will be sent to
        the trust queue once they've reached the target number of loans
        completed as lender.
    """
    loans_completed_as_lender: int
    review_no_earlier_than: float


class TrustQueueResponse(BaseModel):
    """Describes the response when requesting the queue of trust responses.

    Attributes:
    - `queue (list[int])`: The trust queue items in this paginated section.
    - `after_review_at (float, None)`: If there are more queue items later in
        time, this is the review time to pass to this endpoint to get the
        next later review items in the queue. UTC seconds since epoch.
    - `before_review_at (float, None)`: If there are more queue items earlier
        in time, this is the review time to pass to this endpoint to get the
        earlier review items in the queue. UTC seconds since epoch.
    """
    queue: typing.List[TrustQueueItem]
    after_review_at: float = None
    before_review_at: float = None
