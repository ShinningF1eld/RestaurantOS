"""Minimal JSON logging that safely includes request correlation IDs."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.request_id import get_request_id


class JsonFormatter(logging.Formatter):
    """Format allowlisted operational fields; omit arbitrary extras and bodies."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
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
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
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
