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
