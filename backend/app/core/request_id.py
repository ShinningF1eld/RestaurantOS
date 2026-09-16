"""Context-local request correlation identifiers."""

import re
from contextvars import ContextVar, Token
from uuid import uuid4


REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def is_valid_request_id(value: str | None) -> bool:
    """Return whether a client-provided identifier is safe to echo and log."""

    return value is not None and bool(_REQUEST_ID_PATTERN.fullmatch(value))


def new_request_id() -> str:
    """Create an opaque request identifier suitable for logs and response headers."""

    return uuid4().hex


def select_request_id(incoming_request_id: str | None) -> str:
    """Reuse a valid correlation ID, otherwise replace it with an opaque one."""

    if is_valid_request_id(incoming_request_id):
        assert incoming_request_id is not None
        return incoming_request_id
    return new_request_id()


def set_request_id(value: str) -> Token[str | None]:
    """Set the request-local identifier and return a token for later reset."""

    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the request-ID context after the request completes."""

    _request_id.reset(token)


def get_request_id() -> str | None:
    """Get the request ID for the currently executing request, if any."""

    return _request_id.get()
