"""ASGI middleware for request-ID propagation without request-body access."""

import logging
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import (
    REQUEST_ID_HEADER,
    reset_request_id,
    select_request_id,
    set_request_id,
)


logger = logging.getLogger("restaurantos.request")


class RequestIdMiddleware:
    """Select, expose, and echo a request ID for every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        incoming = next(
            (
                value.decode("latin-1")
                for name, value in headers
                if name.lower() == REQUEST_ID_HEADER.encode("latin-1").lower()
            ),
            None,
        )
        request_id = select_request_id(incoming)
        token = set_request_id(request_id)
        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = list(message.get("headers", []))
                header_name = REQUEST_ID_HEADER.lower().encode("latin-1")
                if not any(name.lower() == header_name for name, _ in response_headers):
                    response_headers.append((header_name, request_id.encode("latin-1")))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Do not attach the exception here: database exceptions can embed
            # SQL and parameter values. Later error tracking must apply its own
            # sensitive-data filtering.
            logger.error(
                "request failed",
                extra={
                    "http_method": scope.get("method"),
                    "http_path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
        else:
            logger.info(
                "request completed",
                extra={
                    "http_method": scope.get("method"),
                    "http_path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
        finally:
            reset_request_id(token)
