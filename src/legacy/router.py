"""Handles routing for legacy endpoints. We strive for backwards compatible
support for at least 6 months after an alternative is available, and up to 3
years for architectural changes. This does not constitute a warranty of any
kind.

What this means is breaking changes on an endpoint require up 3 years 8
months to take in to effect (create new endpoint, up to 3 years to
transition, 1 month while the old endpoint is stubbed to an error message,
alias it to new endpoint, 6 months to transition, remove new endpoint, 1
month while the new endpoint is stubbed to an error message).

The transition schedule will be sped up if it's for security, up to and
including no warning. Furthermore, if we have a preponderance of evidence
to suggest that an endpoint is not eing used by anyone we may speed up the
transition process.

Over a transition period this long it's not realistic for anyone to manually
send out updates or to maintain a holistic view of whats going in/out without
some tooling.

Our deprecation schedule works as follows:

- Authenticated users will receive a PM at the end of each month summarizing
  what deprecated endpoints they are using, the sunset schedule for those
  endpoints, and the suggested alternatives for those endpoints. We will also
  suggest adding the `deprecated` query parameter which is set to true to the
  endpoint which suppresses warnings.
- Deprecated endpoints will return an error message for the first 5
  unauthenticated requests from each unique combination of ip address and user
  agent each month, explaining that the endpoint is deprecated and providing the
  sunset schedule and suggested alternatives. This can be suppressed by setting
  the `deprecated` query parameter to true.
- For the last month of sunsetting we will add a query parameter
  `deprecated` which must be set to true or the authenticated user will receive
  a PM once every 3 days.
- For the last month of sunsetting we will increase the frequency of ip/ua
  error rates to once per week unless they send the `deprecated` flag.
- For the last 14 days of sunsetting we will block all requests which do not
  include the deprecated flag.
- For 1 month post-deprecation all requests will receive an error 400 rather
  than a 404 and authenticated requests will continue to receive deprecation
  PMs, now with increased urgency (since their app is broken).
- More than 1 month post-deprecation the endpoint will return 404 and the
  endpoint is considered free for reuse. We will purge all of our history of
  usage for the endpoint at this point and the endpoint will no longer be
  visible under "deprecated endpoints", which frees the endpoint slug and
  path for reuse.
"""
import legacy.loans.router
import legacy.trusts.router
import legacy.users.router

from fastapi import APIRouter


router = APIRouter()
router.include_router(legacy.loans.router.router)
router.include_router(legacy.trusts.router.router)
router.include_router(legacy.users.router.router)
