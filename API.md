# API

This document explains general rules and guidelines for interacting with this
service. Each folder (e.g. src/users) will have details for how to interact
with that particular section.

## Overview

Clients are strongly encouraged to make HTTP/2 requests in a waterfall style
manner - making many cheap requests while reusing the same connection. Clients
are also strongly encouraged to respect cache-control headers and always
authenticate requests with non-human authentication methods.

In general, what this means is first fetch the ids of the loans you are
interested in, then fetch the data per-loan. This is simple to implement for
both the client and server, easy to track metrics for, and not a significant
throughput cost for HTTP/2 connections. Furthermore, it naturally means that
you can take advantage of the LoansBot site horizontal scaling as much as is
possible and other requests can be interweaved with your requests.

## API Usage Guidelines

Uppercase words in this section are keywords and follow the definitions
outlined in https://tools.ietf.org/rfc/rfc2119.txt

The term "bot traffic" or "automated traffic" is defined as by
https://www.oreilly.com/library/view/managing-and-mitigating/9781492029380/ch01.html

The minimum any client should do is the following:

- You SHOULD make authenticated requests for automated traffic. You SHOULD use
  accounts where the reddit inbox is actively monitored for any authenticated
  requests. Note that this can be achieved by attaching the reddit account to
  an email you monitor.
- You SHOULD set a User-Agent in the following form:
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/User-Agent
  Example:
    "User-Agent: MyProgram/0.1 by MyRedditUsername (+http://yourwebsite.com/bot.html)"
- You SHOULD have a link in your User-Agent to a description of the bot.
  The bot page can be very simple, but it should include a brief description of
  the bot, what language it is written in, the anticipated traffic pattern and
  if there is a time where the project should naturally come to an end (to help
  detect programs which were meant to be turned off).
  Examples:
  + MyProgram is written in Python and combines information from various
    reddit bots to produce a behavior score for users upon request. Since
    the bot is triggered by comments on reddit which specifically summon
    this bot I anticipate a low volume of requests which are unequally spaced.
    This project is anticipated to be ongoing. The source code is publicly
    available at https://github.com/MyGitHubAcc/MyProgram
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
- You MUST use non-human authentication methods for authenticated automated
  traffic. See src/users/API.md
- You MUST NOT mask automated traffic as human traffic. Traffic
  masking techniques, including but not limited to User-Agent spoofing, IP
  cycling or masking, or using multiple accounts to work around rate limits
  will all be treated as actively malicious. This hurts everyone and won't
  make more server resources magically available.
- You MUST wait at least 60 seconds after any 4XX HTTP status codes which your
  program does not specifically anticipate and handle.
- You SHOULD regularly verify your authorization. Many bots never use endpoints
  which require authorization, and in that case it's recommended to make a
  request to /api/users/me roughly once per hour while you are actively using
  the authorization to check if your credentials were revoked rather than
  relying on 403 responses, which can make caching on our side more difficult
  (i.e., we might want to skip checking your auth and give you a response which
  does not count toward your ratelimit if we can avoid making any database
  calls that way).
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
  to say you SHOULD NOT ratelimit yourself once an HTTP/2 connection is open,
  as long as this does not restrict with any of the above. You MAY test to see
  the number of concurrent requests that gets you the best throughput.
