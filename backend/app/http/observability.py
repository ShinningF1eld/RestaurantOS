"""Small allowlisted HTTP boundary; never inspect payloads or exception contents."""

import logging
from contextlib import ExitStack
from functools import lru_cache
from typing import Any
from time import perf_counter

from opentelemetry import trace
from starlette.routing import compile_path, get_route_path
from starlette.types import Scope

from app.core.telemetry import Telemetry, trusted_context

METHODS = {
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "CONNECT",
    "TRACE",
}
logger = logging.getLogger("restaurantos.telemetry")


def method(scope: Scope) -> str:
    value = scope.get("method", "")
    return value if value in METHODS else "OTHER"


@lru_cache(maxsize=16)
def route_patterns(app: object) -> tuple:
    paths = list(app.openapi()["paths"]) if hasattr(app, "openapi") else []
    paths.extend(
        route.path for route in getattr(app, "routes", ()) if hasattr(route, "path")
    )
    return tuple((path, compile_path(path)[0]) for path in dict.fromkeys(paths))


def route_template(scope: Scope) -> str:
    # Routing has not run for auth/CSRF/CORS rejection or in-flight accounting.
    # Match registered templates without invoking endpoints/dependencies.
    for path, pattern in route_patterns(scope.get("app")):
        if pattern.fullmatch(get_route_path(scope)):
            return str(path)
    return "<unmatched>"


def category(status: int, *, cancelled: bool, failed: bool) -> str:
    if cancelled:
        return "cancelled"
    if failed or status >= 500:
        return "server_error"
    return {
        401: "authentication",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation",
        429: "rate_limit",
    }.get(status, "client_error" if status >= 400 else "success")


class HttpObservation:
    def __init__(self, runtime: Telemetry | None, scope: Scope) -> None:
        self.runtime = runtime
        self.stack = ExitStack()
        self.started = perf_counter()
        self.active = False
        self.attributes = {
            "http.route": "<unmatched>",
            "http.request.method": method(scope),
        }
        if runtime is not None:
            try:
                self.attributes["http.route"] = route_template(scope)
                span = runtime.tracer.start_span(
                    "HTTP request",
                    context=trusted_context(scope, runtime.settings),
                    kind=trace.SpanKind.SERVER,
                )
                self.span = span
                self.stack.enter_context(
                    trace.use_span(
                        span,
                        end_on_exit=True,
                        record_exception=False,
                        set_status_on_exception=False,
                    )
                )
                runtime.inflight.add(1, self.attributes)
                self.active = True
            except Exception:
                logger.warning("telemetry observation failed")

    def finish(
        self, status: int, *, cancelled: bool, failed: bool, request_id: str
    ) -> None:
        try:
            if self.runtime is not None and self.active:
                attributes: dict[str, Any] = {
                    **self.attributes,
                    "http.response.status_code": status,
                    "outcome": category(status, cancelled=cancelled, failed=failed),
                }
                self.runtime.inflight.add(-1, self.attributes)
                self.span.set_attributes({**attributes, "request_id": request_id})
                if failed or status >= 500:
                    self.span.set_status(trace.StatusCode.ERROR)
                self.runtime.completed(
                    attributes, perf_counter() - self.started, request_id
                )
        except Exception:
            logger.warning("telemetry observation failed")
        finally:
            try:
                self.stack.close()
            except Exception:
                logger.warning("telemetry observation failed")
