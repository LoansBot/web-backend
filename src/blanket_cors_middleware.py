import functools

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ALL_METHODS = ("DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT")


class BlanketCORSMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        headers = Headers(scope=scope)
        origin = headers.get("origin")

        if origin is None:
            await self.app(scope, receive, send)
            return

        if method == "OPTIONS" and "access-control-request-method" in headers:
            response = self.preflight_response(request_headers=headers)
            await response(scope, receive, send)
            return

        await self.simple_response(scope, receive, send, request_headers=headers)

    def preflight_response(self, request_headers: Headers) -> Response:
        requested_origin = request_headers["origin"]
        requested_headers = request_headers.get("access-control-request-headers")

        headers = {
            'Access-Control-Allow-Methods': ', '.join(ALL_METHODS),
            'Access-Control-Max-Age': '600',
            'Access-Control-Allow-Origin': requested_origin
        }
        headers["Access-Control-Allow-Headers"] = requested_headers

        return PlainTextResponse("OK", status_code=200, headers=headers)

    async def simple_response(
        self, scope: Scope, receive: Receive, send: Send, request_headers: Headers
    ) -> None:
        send = functools.partial(self.send, send=send, request_headers=request_headers)
        await self.app(scope, receive, send)

    async def send(
        self, message: Message, send: Send, request_headers: Headers
    ) -> None:
        if message["type"] != "http.response.start":
            await send(message)
            return

        origin = request_headers["Origin"]
        if origin is None:
            origin = request_headers['Referer']
        if origin is None:
            origin = '*'

        message.setdefault("headers", [])
        headers = MutableHeaders(scope=message)
        headers['Access-Control-Allow-Origin'] = origin
        await send(message)
