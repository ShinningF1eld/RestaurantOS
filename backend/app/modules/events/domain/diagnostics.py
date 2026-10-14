"""Allowlisted values for operator output and worker context."""

import re


ERROR_CATEGORIES = frozenset(
    {
        "unsupported_version",
        "invalid_payload",
        "event_constraint",
        "event_transient",
        "handler_failure",
        "worker_interrupted",
        "attempt_limit",
        "postgres_unavailable",
        "dependency_unavailable",
        "redis_unavailable",
        "redis_timeout",
        "redis_connection",
        "redis_command",
        "handler_unavailable",
        "redis_stream_recovered",
        "timeout",
        "connection",
        "command",
    }
)


def safe_category(value: str | None) -> str | None:
    return value if value is None or value in ERROR_CATEGORIES else "redacted"


def safe_identifier(value: str) -> str:
    return (
        value
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
        else "redacted"
    )
