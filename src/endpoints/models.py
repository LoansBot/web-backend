"""The models used for endpoints-related endpoints"""
from pydantic import BaseModel, validator
from datetime import date
import typing


class EndpointsIndexResponse(BaseModel):
    """A paginated endpoint index response.

    Attributes:
    - `endpoint_slugs (list[int])`: The ordered list of endpoint slugs
    - `after_slug (str, None)`: If using ascending slug order, this is the
      slug to pass as "after_slug" for the next page if there is a next
      page. Otherwise None.
    - `before_slug (str, None)`: If using descending slug order, this is the
      slug to pass as "before_slug" for the previous page if there is a
      previous page. Otherwise None.
    """
    endpoint_slugs: typing.List[str]
    after_slug: str = None
    before_slug: str = None


class EndpointsSuggestResponse(BaseModel):
    """The suggestions for endpoint slugs when using /suggest

    Attributes:
    - `suggestions (list[str])`: The suggested endpoint slugs.
    """
    suggestions: typing.List[str]


class EndpointParamShowResponse(BaseModel):
    """Describes a parameter to a single endpoint as returned from
    the endpoint show endpoint.

    Attributes:
    - `location (str)`: Where this parameter is provided. Acts as an enum and
      is one of `query`, `body`, and `header`.
    - `path (list[str])`: An ordered list of strings that describes how to get
      to this endpoint within the location. For example for an example body
      `{"foo": {"bar": 7}}`, the location is `body` and the path for `foo` is
      `[]`, and the path for `bar` is `[foo]`
    - `name (str)`: The name of the variable at the location and path. May be
      blank if and only if the path is blank, in which case this is referring
      to the parameters in this location in general.
    - `var_type (str)`: The type of the variable. Has no fixed form but should
      be displayed in a pre / code block and can be assumed to be one-line and
      short.
    - `description_markdown (str, None)`: The description of this parameter,
      markdown formatted. All parameters have a description however it's not
      returned in listings.
    - `added_date (str)`: The date this parameter was recorded within the
      endpoint. Stored in year-month-date format
    """
    location: str
    path: typing.List[str]
    name: str
    var_type: str
    description_markdown: str = None
    added_date: str


class EndpointShowResponse(BaseModel):
    """The response from using show on an endpoint.

    Attributes:
    - `slug (str)`: The endpoint slug, which is our stable identifier for this
      endpoint. Example: `get_creation_info`
    - `path (str)`: The main path to reach this endpoint currently, for example
      `/api/get_creation_info.php`
    - `verb (str)`: The HTTP verb used for this endpoint. For example, "GET"
    - `description_markdown (str)`: The markdown formatted description for this
      endpoint.
    - `params (list[EndpointParamShowResponse])`: The parameters to this
      endpoint. This will not hydrate the parameter descriptions, which must
      be fetched via a separate api call per parameter to avoid an excessively
      large response.
    - `alternatives (list[str])`: A list of endpoint slugs that we suggest as
      alternatives. Migration information will be available via
      `/api/endpoints/migrate/{from_endpoint_slug}/{to_endpoint_slug}`
    - `deprecation_reason_markdown (str, None)`: None if this endpoint is not
      deprecated. Otherwise, this is the reason we deprecated this endpoint
      formatted in markdown.
    - `deprecated_on (str, None)`: None if this endpoint is not deprecated.
      Otherwise this is the date this endpoint was deprecated. May be in the
      future.
    - `sunsets_on (str, None)`: None if this endpoint is not deprecated.
      Otherwise this is the date this endpoint will stop functioning. May be in
      the past.
    - `created_at (float)`: When this endpoint record was first created. Seconds
      since utc epoch.
    - `updated_at (float)`: When this endpoint record was last updated. Seconds
      since utc epoch.
    """
    slug: str
    path: str
    verb: str
    description_markdown: str
    params: typing.List[EndpointParamShowResponse]
    alternatives: typing.List[str]
    deprecation_reason_markdown: str = None
    deprecated_on: str = None
    sunsets_on: str = None
    created_at: float
    updated_at: float


class EndpointAlternativeShowResponse(BaseModel):
    """Explains how one endpoint can be replaced with another endpoint. The
    endpoint slugs are presumably specified in path parameters.

    Attributes:
    - `explanation_markdown (str)`: The explanation of how to replace the
      first endpoint with the second.
    - `created_at (float)`: The time this alternative explanation was first
      added. Seconds since utc epoch.
    - `updated_at (float)`: When this explanation was last updated. Seconds
      since utc epoch.
    """
    explanation_markdown: str
    created_at: float
    updated_at: float


class EndpointPutRequest(BaseModel):
    """The body parameters for creating or updating an endpoint object itself.
    The slug is presumably specified in a path parameter.

    Arguments:
    - `path (str)`: The path that the endpoint can be accessed at
    - `verb (str)`: The HTTP verb used with this endpoint, e.g., GET
    - `description_markdown (str)`: The new description for the endpoint.
    - `deprecation_reason_markdown (str, None)`: The new reason for deprecating
      this endpoint, if this endpoint is deprecated
    - `deprecated_on (str, None)`: The new deprecation date for the endpoint, if
      this endpoint is deprecated. ISO 8601 formatted date without time
    - `sunsets_on (str, None)`: The new sunset date for this endpoint, if this
      endpoint is deprecated. ISO 8601 formatted date without time
    """
    path: str
    verb: str
    description_markdown: str
    deprecation_reason_markdown: str = None
    deprecated_on: str = None
    sunsets_on: str = None

    @validator('path')
    def path_present(cls, v):
        v = v.strip()
        if len(v) < 1:
            raise ValueError('must not be blank')
        return v

    @validator('verb')
    def verb_is_allowed(cls, v):
        if v not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
            raise ValueError('must be uppercased http verb')
        return v

    @validator('description_markdown')
    def description_present(cls, v):
        v = v.strip()
        if len(v) < 5:
            raise ValueError('must be >=5 chars stripped')
        return v + '\n'

    @validator('deprecation_reason_markdown')
    def deprecation_reason_markdown_present_or_none(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) < 5:
            raise ValueError('must be >=5 chars stripped')
        return v + '\n'

    @validator('deprecated_on', 'sunsets_on')
    def present_iff_reason_present(cls, v, values):
        if (v is None) != (values.get('deprecation_reason_markdown') is None):
            raise ValueError('present iff deprecation_reason_markdown present')
        return v

    @validator('deprecated_on', 'sunsets_on')
    def iso_formatted_date_or_none(cls, v):
        if v is None:
            return v
        parts = v.split('-', 2)
        if len(parts) != 3:
            raise ValueError('malformatted (too few hyphens)')
        if len(parts[0]) != 4:
            raise ValueError('malformatted (year not 4 chars)')
        if len(parts[1]) != 2:
            raise ValueError('malformatted (month not 2 chars)')
        if len(parts[2]) != 2:
            raise ValueError('malformatted (day not 2 chars)')
        if not parts[0].isdigit():
            raise ValueError('malformatted (year not numeric)')
        if not parts[1].isdigit():
            raise ValueError('malformatted (month not numeric)')
        if not parts[2].isdigit():
            raise ValueError('malformatted (day not numeric)')
        date.fromisoformat(v)
        return v


class EndpointParamPutRequest(BaseModel):
    """The body parameters for creating or updating an endpoint parameter.
    The slug for the endpoint and the location of the parameter are specified
    in path parameters whereas the path and name are specified in query
    parameters. This is consistent with identifying parameters being in the
    url string.

    Arguments:
    - `var_type (str)`: The type of this endpoint parameter
    - `description_markdown (str)`: The description for this parameter
    """
    var_type: str
    description_markdown: str

    @validator('var_type')
    def is_not_totally_blank(cls, v):
        v = v.strip()
        if len(v) < 1:
            raise ValueError('must be at least 1 char')
        return v

    @validator('description_markdown')
    def is_not_essentially_blank(cls, v):
        v = v.strip()
        if len(v) < 5:
            raise ValueError('must be at least 5 chars')
        return v + '\n'


class EndpointAlternativePutRequest(BaseModel):
    """The body parameters for creating or updating an endpoint alternative.
    The slugs for both endpoints are presumably in path parameters.

    Arguments:
    - `explanation_markdown (str)`: An explanation for how to migrate from the
      old endpoint to this endpoint.
    """
    explanation_markdown: str

    @validator('explanation_markdown')
    def is_not_blank(cls, v):
        v = v.strip()
        if len(v) < 5:
            raise ValueError('must be at least 5 chars')
        return v + '\n'
