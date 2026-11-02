"""ASGI middleware for request-ID propagation without request-body access."""

import logging
import asyncio
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from app.core.telemetry import lifecycle
from app.http.observability import HttpObservation, category, method

from app.core.request_id import (
    REQUEST_ID_HEADER,
    reset_request_id,
    select_request_id,
    set_request_id,
)


logger = logging.getLogger("restaurantos.request")


def normalized_route(scope: Scope) -> str:
    """Return a registered route template, never an untrusted request path."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "<unmatched>"


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
        response_started = False
        failed = False
        cancelled = False
        observation = HttpObservation(lifecycle.runtime, scope)

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                response_headers = list(message.get("headers", []))
                header_name = REQUEST_ID_HEADER.lower().encode("latin-1")
                if not any(name.lower() == header_name for name, _ in response_headers):
                    response_headers.append((header_name, request_id.encode("latin-1")))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except asyncio.CancelledError:
            cancelled = True
            if not response_started:
                status_code = 0
            logger.info(
                "request cancelled",
                extra={
                    "http_method": method(scope),
                    "http_path": normalized_route(scope),
                    "status_code": status_code,
                    "outcome": "cancelled",
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
        except Exception:
            failed = True
            # Do not attach the exception here: database exceptions can embed
            # SQL and parameter values. Later error tracking must apply its own
            # sensitive-data filtering.
            logger.error(
                "request failed",
                extra={
                    "http_method": method(scope),
                    "http_path": normalized_route(scope),
                    "status_code": status_code,
                    "outcome": "server_error",
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
        else:
            logger.info(
                "request completed",
                extra={
                    "http_method": method(scope),
                    "http_path": normalized_route(scope),
                    "status_code": status_code,
                    "outcome": category(status_code, cancelled=False, failed=False),
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
        finally:
            try:
                observation.finish(
                    status_code,
                    cancelled=cancelled,
                    failed=failed,
                    request_id=request_id,
                )
            finally:
                reset_request_id(token)
