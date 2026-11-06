"""Strict W3C version-00 context only; no propagation headers or vendor state."""

import re

from opentelemetry import trace

_PATTERN = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})")


def parse_traceparent(value: object) -> trace.SpanContext | None:
    if not isinstance(value, str) or len(value) != 55:
        return None
    match = _PATTERN.fullmatch(value)
    if match is None:
        return None
    trace_id, span_id, flags = (int(part, 16) for part in match.groups())
    context = trace.SpanContext(
        trace_id, span_id, is_remote=True, trace_flags=trace.TraceFlags(flags)
    )
    return context if context.is_valid else None


def capture_traceparent() -> str | None:
    """Capture only a recording local span; failures cannot reject an append."""
    try:
        span = trace.get_current_span()
        context = span.get_span_context()
        if not span.is_recording() or not context.is_valid:
            return None
        value = (
            f"00-{context.trace_id:032x}-{context.span_id:016x}-"
            f"{int(context.trace_flags):02x}"
        )
        return value if parse_traceparent(value) is not None else None
    except Exception:
        return None


def span_links(value: object) -> list[trace.Link]:
    context = parse_traceparent(value)
    return [trace.Link(context)] if context is not None else []
