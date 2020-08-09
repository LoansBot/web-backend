"""Request and return types for user demographics endpoints"""
from pydantic import BaseModel
import typing


class UserDemographics(BaseModel):
    """Describes demographics for a particular user.

    - `user_id (int)`: The id of the user this info belongs to
    - `email (str, None)`: The users email, typically unconfirmed, that they
        would like to be reached at for legal inquiry or questions. For most
        users they should never receive an email from us.
    - `name (str, None)`: The users full legal name.
    - `street_address (str, None)`: The users mailing street address or closest
        equivalent.
    - `city (str, None)`: The users city or closest equivalent.
    - `state (str, None)`: The users state or closest equivalent in abbreviated
        form (for the U.S., 2 uppercase letters)
    - `zip (str, None)`: The users zip or closest equivalent
    - `country (str, None)`: The users country
    """
    user_id: int
    email: str = None
    name: str = None
    street_address: str = None
    city: str = None
    state: str = None
    zip: str = None
    country: str = None


class UserDemographicsLookup(BaseModel):
    """Describes a user searching the user demographics table for users
    matching a given description. We return a nested object in order to
    avoid having admins do an absurd number of captchas in a row.

    Attributes:
    - `hits (list[UserDemographics])`: The users we found which match the
        description given, in an arbitrary but consistent order.
    - `next_id (int, None)`: If there were more hits that were not returned
        from this search, this is the id to pass as "next_id" to the lookup
        endpoint to get the next batch of results.
    """
    hits: typing.List[UserDemographics]
    next_id: int = None
