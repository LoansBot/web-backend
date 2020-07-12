from pydantic import BaseModel, validator
import typing
from datetime import datetime


class AuthMethodCreateResponse(BaseModel):
    """The result from creating a new authentication method

    Attributes:
    - `id (int)`: The id of the newly created authentication method
    """
    id: int


class UserAuthMethodsList(BaseModel):
    """The list authentication method ids for a user.

    Attributes:
    - `authentication_methods (list[int])`: An array containing the id of every
        authentication method the user has. No pagination since we anticipate this
        is short, plus it's just ints
    - `can_add_more (bool)`: True if the authorized user can add more
        authentication methods to this user, false if they cannot.
    """
    authentication_methods: typing.List[int]
    can_add_more: bool


class UserSettingsEvent(BaseModel):
    """Describes a value that changed within a users settings.

    Attributes:
    - `name (str)`: The name of the property which changed
    - `old_value (any)`: The old value for the setting
    - `new_value (any)`: The new value for the setting
    - `username (str, None)`: The username of the user who made the change,
        null if the user was deleted or the recipient of the event does not
        have access to this information.
    - `occurred_at (datetime)`: When the change occurerd
    """
    name: str
    old_value: typing.Any
    new_value: typing.Any
    username: str = None
    occurred_at: datetime


class UserSettingsHistory(BaseModel):
    """Describes the history for user settings, in a paginated form.

    Attributes:
    - `before_id (int)`: An id above all the remaining ids. This can be used to
        paginate backwards.
    - `history (list[int])`: A list of history event ids from newest to oldest.
    """
    before_id: int
    history: typing.List[int]


class UserSetting(BaseModel):
    """Describes the value of a particular setting for a particular user.

    Attributes:
    - `can_modify (bool)`: True if the authorized user is allowed to modify
        this value, false if they are not.
    - `value (any)`: The value for the setting currently.
    """
    can_modify: bool
    value: typing.Any


class UserSettingBoolChangeRequest(BaseModel):
    """Describes a request to change a users setting, where the setting has
    the bool type.
    """
    new_value: bool


class UserSettingRatelimit(BaseModel):
    """The user ratelimit settings from an API perspective.

    Attributes:
    - `global_applies (bool)`: True if the global ratelimit effects and is
        effected by this user. False if this user does not require global
        tokens nor do they consume global tokens.
    - `user_specific (bool)`: True if this user has specific ratelimit
        settings not associated with the default ratelimit settings for
        users. False if the users ratelimit should be the current default.
    - `max_tokens (int, None)`: None if not user_specific. Otherwise, this
        is the maximum number of ratelimit tokens the user can accumulate.
    - `refill_amount (int, None)`: None if not user_specific. Otherwise, this
        is the number of tokens refilled at each interval.
    - `refill_time_ms (int, None)`: None if not user_specific. Otherwise, this
        is the time between token refills.
    - `strict (bool, None)`: None if not user_specific. Otherwise, this is true
        if they are punished for ratelimited requests by resetting their refresh
        interval and false if they are not punished for ratelimited requests.
    """
    global_applies: bool
    user_specific: bool
    max_tokens: int = None
    refill_amount: int = None
    refill_time_ms: int = None
    strict: bool = None

    @validator('max_tokens', 'refill_amount', 'refill_time_ms')
    def positive(cls, v):
        if v is None and v <= 0:
            raise ValueError('must be positive')
        return v

    @validator('max_tokens', 'refill_amount', 'refill_time_ms', 'strict')
    def only_set_if_user_specific(cls, v, values):
        if values['user_specific']:
            if v is None:
                raise ValueError('user_specific implies not None')
        elif v is not None:
            raise ValueError('not user_specific implies None')
        return v


class UserSettingRatelimitChangeRequest(BaseModel):
    """Describes a request to change a users ratelimit settings.

    - `new_value (UserSettingRatelimit)`: The new ratelimit settings for the
        user.
    """
    new_value: UserSettingRatelimit
