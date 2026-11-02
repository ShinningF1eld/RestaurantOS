"""Minimal JSON logging that safely includes request correlation IDs."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.request_id import get_request_id
from app.core.telemetry import correlation

# Never render third-party messages, interpolation arguments, traceback text or
# exception reprs. Operational messages are code-owned constants, not data.
SAFE_MESSAGES = frozenset(
    {
        "request completed",
        "request failed",
        "request cancelled",
        "diagnostic event",
        "Catalog cache invalidation failed",
        "Catalog Redis cache circuit recovered",
        "Catalog Redis cache circuit opened",
        "Authentication operation abandoned",
        "Authentication limiter transition",
        "Redis shutdown failed (%s)",
        "telemetry startup failed",
        "telemetry shutdown failed",
        "telemetry retiring",
        "telemetry observation failed",
        "telemetry shutdown timed out",
        "event_worker_started",
        "event_worker_stopped",
        "event_worker_reference_retry_scheduled",
        "event_worker_redis_failure",
        "event_worker_database_failure",
        "event_worker_relay_loop_failed",
        "event_worker_publication_observed",
        "event_worker_recovery_scan",
        "event_worker_recovery_loop_failed",
        "event_worker_consumer_loop_failed",
        "event_worker_reference_routed",
        "event_worker_reference_rejected",
        "event_consumer_attempt",
        "event_consumer_contract_rejected",
        "event_delivery_replayed",
    }
)


class JsonFormatter(logging.Formatter):
    """Format allowlisted operational fields; omit arbitrary extras and bodies."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name
            if record.name.startswith(
                ("app.", "restaurantos.", "opentelemetry.", "uvicorn")
            )
            else "external",
            "message": record.msg
            if isinstance(record.msg, str) and record.msg in SAFE_MESSAGES
            else "diagnostic event",
            "request_id": get_request_id(),
            **correlation(),
        }
        if record.name.startswith("opentelemetry."):
            # SDK diagnostics can contain remote reason phrases or exceptions.
            # Preserve the operational category without formatting their data.
            message = record.msg if isinstance(record.msg, str) else ""
            payload["event"] = (
                "telemetry_queue_full"
                if message.startswith("Queue full,")
                else "telemetry_export_diagnostic"
            )
        for field in (
            "http_method",
            "http_path",
            "status_code",
            "duration_ms",
            "event",
            "failure_kind",
            "process_id",
            "reason",
            "duration_seconds",
            "attempt_id",
            "attempt_number",
            "retry_cycle",
            "replay_id",
            "event_id",
            "consumer_name",
            "worker_id",
            "claim_id",
            "correlation_id",
            "failure_category",
            "outcome",
            "transport_message_id",
            "retry_delay_ms",
            "stream_size",
            "pending_count",
            "unfinished_count",
            "retained_event_count",
            "retained_delivery_count",
            "retained_receipt_count",
            "retained_attempt_count",
            "recovery_count",
        ):
            value = getattr(record, field, None)
            if value is not None and (
                record.name.startswith(("app.", "restaurantos."))
                or (record.name == "events" and record.msg in SAFE_MESSAGES)
            ):
                payload[field] = value
        if record.exc_info:
            payload["exception"] = "exception details suppressed"
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_json_logging(*, level: str = "INFO") -> None:
    """Configure the root logger with a single structured stderr handler.

    Application wiring deliberately calls this once at startup. This module never
    logs request payloads, headers, or settings values.
    """

    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.handlers = [handler]
    # Uvicorn otherwise bypasses the root formatter with access URLs/tracebacks.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = []
        target.propagate = True
