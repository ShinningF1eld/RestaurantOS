"""Best-effort worker observations, outside feature write transactions.

Creation is allowlisted; no payload, exception message, baggage or SQL enters SDKs.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic, time
from typing import Any
from uuid import UUID

from opentelemetry.context import Context
from opentelemetry.metrics import MeterProvider
from opentelemetry.trace import SpanKind, StatusCode

from app.core.trace_context import span_links
from app.modules.events.domain.contracts import SUPPORTED_EVENT_TYPES
from app.modules.events.domain.diagnostics import (
    BACKLOG_STATES,
    safe_category,
    safe_identifier,
)

logger = logging.getLogger("restaurantos.event_telemetry")
CONSUMERS = ("analytics", "alerts", "notification_sink")
OUTCOMES = frozenset(
    {
        "consumer_committed",
        "consumer_failed",
        "consumer_retry_scheduled",
        "claim_superseded",
        "claim_expired",
        "published",
        "claim_lost",
        "transport_failure",
        "observation_failure",
        "interrupted",
    }
)


def runtime() -> Any:
    from app.core.telemetry import worker_lifecycle

    return worker_lifecycle.runtime


def attributes(values: dict[str, Any]) -> dict[str, str | int]:
    result: dict[str, str | int] = {}
    for key, value in values.items():
        if value is None:
            continue
        if key in {"event_id", "delivery_id", "attempt_id", "replay_id", "claim_id"}:
            try:
                result[key] = str(UUID(str(value)))
            except (ValueError, TypeError):
                continue
        elif key == "correlation_id" and isinstance(value, str):
            result[key] = safe_identifier(value)
        elif key == "consumer" and value in CONSUMERS:
            result[key] = value
        elif key == "event_type" and value in SUPPORTED_EVENT_TYPES:
            result[key] = value
        elif (
            key in {"attempt_number", "retry_cycle"}
            and type(value) is int
            and value >= 0
        ):
            result[key] = value
    return result


class WorkerMetrics:
    def __init__(self, provider: MeterProvider, slot: int | None = None) -> None:
        if slot is not None and (type(slot) is not int or not 0 <= slot <= 31):
            raise ValueError("Worker metric slot must be 0–31")
        self.slot = slot
        meter = provider.get_meter("restaurantos.events", "1")
        self.operations = meter.create_counter(
            "restaurantos.worker.operations", unit="1"
        )
        self.duration = meter.create_histogram("restaurantos.worker.duration", unit="s")
        self.routes = meter.create_counter("restaurantos.worker.routes", unit="1")
        self.collection_failures = meter.create_counter(
            "restaurantos.worker.collection.failures", unit="1"
        )
        self.depth = meter.create_gauge("restaurantos.worker.deliveries", unit="1")
        self.age = meter.create_gauge("restaurantos.worker.oldest", unit="s")
        self.progress = meter.create_gauge(
            "restaurantos.worker.receipts.window", unit="1"
        )
        self.latest = meter.create_gauge(
            "restaurantos.worker.receipts.latest", unit="s"
        )
        self.collected = meter.create_gauge("restaurantos.worker.collected", unit="s")

    def completed(self, seconds: float, labels: dict[str, str]) -> None:
        if self.slot is not None:
            labels = {**labels, "worker_slot": str(self.slot)}
            self.operations.add(1, labels)
            self.duration.record(seconds, labels)

    def routed(self, consumer: str, category: str) -> None:
        if self.slot is not None:
            self.routes.add(
                1,
                {
                    "consumer": consumer,
                    "outcome": category,
                    "worker_slot": str(self.slot),
                },
            )

    def collection_failed(self) -> None:
        if self.slot is not None:
            self.collection_failures.add(1, {"worker_slot": str(self.slot)})

    def progress_snapshot(self, rows: list[tuple[str, int, float]]) -> None:
        grouped = {consumer: (count, latest) for consumer, count, latest in rows}
        for consumer in CONSUMERS:
            count, latest = grouped.get(consumer, (0, 0.0))
            self.progress.set(count, {"consumer": consumer})
            self.latest.set(latest, {"consumer": consumer})

    def snapshot(self, rows: list[Any]) -> None:
        # Emit zeros for disappearing groups instead of leaving a stale positive gauge.
        grouped = {(row.consumer, row.state): row for row in rows}
        for consumer in CONSUMERS:
            for state in BACKLOG_STATES:
                row = grouped.get((consumer, state))
                labels = {"consumer": consumer, "state": state}
                self.depth.set(row.depth if row else 0, labels)
                self.age.set(row.oldest_seconds if row else 0, labels)
        self.collected.set(time())


class Operation:
    def __init__(self) -> None:
        self.outcome = "interrupted"
        self.category: str | None = None

    def finish(self, outcome: str, category: str | None = None) -> None:
        self.outcome = outcome if outcome in OUTCOMES else "interrupted"
        self.category = safe_category(category)


@contextmanager
def operation(kind: str, traceparent: str | None, **values: Any) -> Iterator[Operation]:
    observation = Operation()
    started = monotonic()
    span = None
    active = None
    safe = attributes(values)
    try:
        active = runtime()
        if active is not None:
            span = active.tracer.start_span(
                "outbox publish" if kind == "publish" else "consumer attempt",
                context=Context(),
                links=span_links(traceparent),
                kind=SpanKind.PRODUCER if kind == "publish" else SpanKind.CONSUMER,
                attributes=safe,
            )
    except Exception:
        logger.warning("worker telemetry creation failed")
    try:
        yield observation
    finally:
        try:
            labels = {"operation": kind, "outcome": observation.outcome}
            if "consumer" in safe:
                labels["consumer"] = str(safe["consumer"])
            if "event_type" in safe:
                labels["event_type"] = str(safe["event_type"])
            if span is not None:
                span.set_attribute("outcome", observation.outcome)
                if observation.category:
                    span.set_attribute("failure_category", observation.category)
                if observation.outcome in {
                    "consumer_failed",
                    "consumer_retry_scheduled",
                    "transport_failure",
                    "observation_failure",
                }:
                    span.set_status(StatusCode.ERROR)
                span.end()
            if active is not None:
                active.worker_metrics.completed(monotonic() - started, labels)
        except Exception:
            logger.warning("worker telemetry completion failed")


def routing(consumer: str, outcome: str) -> None:
    # Routing does not represent a new effect attempt. Categories are finite.
    category = {
        "durable_receipt_acknowledged": "duplicate",
        "consumer_claim_active": "busy",
        "delivery_missing_or_busy": "busy",
        "durable_failure_acknowledged": "terminal",
        "subscribed_delivery_not_due": "delayed",
    }.get(outcome, "other")
    try:
        active = runtime()
        if active is not None and consumer in CONSUMERS:
            active.worker_metrics.routed(consumer, category)
    except Exception:
        pass
