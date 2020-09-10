# API

This document explains general rules and guidelines for interacting with this
service. Each folder (e.g. src/users) will have details for how to interact with
that particular section.

## Overview

Clients are strongly encouraged to make HTTP/2 requests in a waterfall style
manner - making many cheap requests while reusing the same connection. Clients
are also strongly encouraged to respect cache-control headers and always
authenticate requests with non-human authentication methods.

In general, what this means is first fetch the ids of the loans you are
interested in, then fetch the data per-loan. This is simple to implement for
both the client and server, easy to track metrics for, and not a significant
throughput cost for HTTP/2 connections. Furthermore, it naturally means that you
can take advantage of the LoansBot site horizontal scaling as much as is
possible and other requests can be interweaved with your requests.

## API Usage Guidelines

Uppercase words in this section are keywords and follow the definitions
outlined in https://tools.ietf.org/rfc/rfc2119.txt

No matter how you plan on interacting with the website, you MUST make a
reasonable effort to avoid amplifying issues with site performance. This section
outlines a set of criteria that meets this standard. It also specifies that for
a certain category of programs this is the minimum set of criteria which meet
this standard.

If there isn't a GUI (such as a website), or it isn't the client making the
request, then it counts as automated traffic. If there is a GUI but the client
sends a request to a non-redditloans server which then makes the request to the
redditloans server then the proxy server definitely MUST respect these limits.
If any person can download and run the program, and it makes requests directly
to redditloans.com and only while the person is actively using it (i.e., human
interaction within the last 60 minutes), it does not need to respect these
limits. This would include a reddit extension that lets one click a user and
check their loan history. On the other hand if it might make requests for more
than 60 minutes since the last human interaction, it will need to respect these
specific guidelines.

If you're not sure if you need to meet these guidelines, you can either
respect them or contact the website administrator for clarification.

You are not expected to restrict human-driven requests, such as a person using
your application intent on repeatedly pressing a force-refresh button, so long
as you make a reasonable effort to understand and explain the cost of the
operation. If you automatically retry the request on failure, without the user
explicitly expressing an intent to retry after each failure, then the retry
logic counts as automated traffic and MUST meet or exceed these guidelines.

The following guidelines apply to automated traffic:

- You SHOULD make authenticated requests for automated traffic.
- You SHOULD use accounts where the reddit inbox is actively monitored
  for any authenticated requests. Note that this can be achieved by
  attaching the reddit account to an email you monitor.
- You SHOULD set a User-Agent in the following form:
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/User-Agent
  Example:
    "User-Agent: MyProgram/0.1 by MyRedditUsername (+http://yourwebsite.com/bot.html)"
- You SHOULD have a link in your User-Agent to a description of the bot. The bot
  page can be very simple, but it should include a brief description of the bot,
  what language it is written in, the anticipated traffic pattern and if there
  is a time where the project should naturally come to an end (to help detect
  programs which were meant to be turned off).
  Examples:
  + MyProgram is written in Python and combines information from various reddit
    bots to produce a behavior score for users upon request. Since the bot is
    triggered by comments on reddit which specifically summon this bot I
    anticipate a low volume of requests which are unequally spaced. This project
    is anticipated to be ongoing. The source code is publicly available at
    https://github.com/MyGitHubAcc/MyProgram
  + MyProgram is written in Go and is part of a research project investigating
    online behavior patterns over time. I typically run the report manually
    while developing it, and it involves iterating the database going back 3
    years. This means I expect extremely high burst traffic with potentially
    long periods of inactivity. This project is anticipated to end Spring 2022.
    The source code is not publicly available.
  The link doesn't have to be as fancy as a domain you completely own; it can
  be as simple as a text file in a GitHub repository. However if it's not
  included I may incorrectly identify expected behavior as a bug and restrict
  your account for more or longer than appropriate if it's causing excessive
  load, whereas I might have allocated more resources for you if I had more
  context. I will not attempt to automatically load the page, so feel free to
  style the page / make it look nice.
- You MUST NOT change your user agent in an automated and frequent basis which
  does not require human intervention, such as by including the timestamp when
  the bot was launched. This does not include incrementing your version when
  the source code changes.
- You MUST use non-human authentication methods for authenticated automated
  traffic. See src/users/API.md
- You MUST NOT mask automated traffic as human traffic. Traffic masking
  techniques, including but not limited to User-Agent spoofing, IP cycling or
  masking, or using multiple accounts to work around rate limits will all be
  treated as actively malicious. This hurts everyone and won't make more server
  resources magically available.
- You MUST wait at least 60 seconds after any 4XX HTTP status codes which your
  program does not specifically anticipate and handle (see "backoff algorithm")
- You SHOULD regularly verify your authorization. Many bots never use endpoints
  which require authorization, and in that case it's recommended to make a
  request to /api/users/me roughly once per hour while you are actively using
  the authorization to check if your credentials were revoked rather than
  relying on 403 responses, which can make caching on our side more difficult
  (i.e., we might want to skip checking your auth and give you a response which
  does not count toward your ratelimit if we can avoid making any database calls
  that way).
- You SHOULD anticipate 403 responses from all endpoints if your credentials are
  revoked and the request is more expensive than the ratelimit check, to help
  with runaway bots. If you get a 403 response you should try to relogin.
- If you then get a 403 from the login endpoint you SHOULD gracefully shutdown
  as your credentials have been revoked.
- If you get a 403 from the login endpoint you MUST treat it as an
  unanticipated response for the purposes of backoff.
- You SHOULD use multiplexed HTTP/2 connections which are reused for short
  periods of high requests.
- You MUST close any open connections and back off exponentionally if you
  receive a 5XX HTTP status code. See "backoff algorithm" for the recommended
  algorithm with source code examples.
- You MUST NOT have more than 1 connection open at a time, (HTTP/2 or HTTP/1),
  for a single program.
- You MUST NOT open more than 1 HTTP connection within a 2 second window for a
  single program.
- You SHOULD use up to 100 concurrent requests over HTTP/2 connections. That is
  to say you SHOULD NOT ratelimit yourself once an HTTP/2 connection is open, as
  long as this does not conflict with any of the above. You MAY test to see the
  number of concurrent requests that gets you the best throughput.
- You MUST NOT waterfall more than 4 layers within a single HTTP/2 connection,
  that is to say, you must not have any request made within a single HTTP/2
  connection which requires waiting for more than 4 loopbacks. Example: search
  users -> search loans in user -> check loan -> check other user can be made in
  a single connection, but at that point you must close the connection and wait
  at least 2 seconds before reopening. Note this is not saying you can only make
  4 requests, you could easily do list loan ids -> check each one. Checking all
  the loan ids in this case is done in parallel, whereas in the earlier example
  you needed to wait for the responses of 4 chained requests before continuing.
- You SHOULD check 400 Bad Request responses to see if the body is present and
  include it in your logs. You MAY attempt to parse the body as JSON if it is
  present. If you do so you MAY check for the boolean `retryable`. If it has the
  value `true` you MUST still treat the request as a client-side error for
  back-off. If it has the value `false` the request will definitely not succeed
  without modification and you MAY cache the response. You MAY check for the
  additional boolean values `deprecated` and `sunsetted`. If `deprecated` is
  `true` and `sunsetted` is `false` you MAY automatically append the
  `deprecated=true` query parameter. If `sunsetted` is `true` the request will
  not succeed and you MAY cache the response. You SHOULD alert the program
  maintainer to visit the "Developer" -> "Endpoints" section of the website to
  see the deprecation schedule for the endpoint, the reason for deprecation, and
  how to migrate.


## Backoff Algorithm

This section describes the recommended calculation for the earliest time at
which you can open a new connection to the website.

Definitions:

- A *successful request* is any request where the response from the server was
  in a format that your program expected to happen during normal operations.
  Most of the time, this is a 2XX response, but it can also include 404
  responses for resources you suspect might not exist or 412 responses when you
  are purposely protecting against mid-flight collisions, etc. A 5XX response,
  however, should _never_ be treated as successful.
- An *unsuccessful request* is any request which is not successful. There are
  two types of unsuccessful requests: *client-side unsuccessful requests* and
  *server-side unsuccessful requests*. A *server-side unsuccessful request* is
  any unsuccessful request with a 5XX status code. Any unsuccessful request
  which is not a *server-side unsuccessful request* is a
  *client-side unsuccessful request*.

Variables:

- Suppose you last closed a connection at time `time_of_last_connection` in
  seconds since UTC epoch. If you open a connection at time T and close it
  at T + 2 seconds, this should be T + 2 seconds.
- Suppose that there have been `number_of_sequential_errors` connections which
  have been opened with any unsuccessful requests since the last connection
  which contained only successful requests.
- Suppose that `saw_clientside_unsuccessful_request` is true only if
  `number_of_sequential_errors` is positive and, in any of those unsuccessful
  requests, there was at least 1 client-side unsuccessful request.


Then the algorithm should be as follows, where `clip(n, min, max)` returns
the closest value to n in the inclusive range [min, max]

```
base_sleep_factor = 2
if saw_clientside_unsuccessful_request
  base_sleep_factor = 60
end if

next_sleep_time = time_of_last_connection + (
  base_sleep_factor * pow(2, clip(number_of_sequential_errors, 0, 7))
)
```

Sleeps for sequential server-side errors:
`4, 8, 16, 32, 64, 128, 256, 256`

Max backoff: 6 minutes, 16 seconds

Sleeps for sequential client-side errors:
`120, 240, 480, 960, 1920, 3840, 7680, 7680`

Max backoff: 2 hours, 8 minutes

Python implementation:

```py
from datetime import datetime, timedelta

def get_earliest_time_to_open_connection(
    time_of_last_connection: datetime,
    number_of_sequential_errors: int,
    saw_clientside_unsuccessful_request: bool) -> datetime:
  base_sleep_factor = 2
  if saw_clientside_unsuccessful_request:
    base_sleep_factor = 60

  sleep_time_seconds = (
    base_sleep_factor * (2 ** (
      max(min(number_of_sequential_errors, 7), 0)
    ))
  )

  return time_of_last_connection + timedelta(seconds=sleep_time_seconds)
```
