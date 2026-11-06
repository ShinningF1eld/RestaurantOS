"""Worker privacy and real SDK link construction without service dependencies."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from app.core.trace_context import capture_traceparent, parse_traceparent, span_links
from app.modules.events import telemetry

PARENT = "00-1234567890abcdef1234567890abcdef-1234567890abcdef-00"
CANARY = "CANARY62_SECRET_cookie_payload_password"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "x" * 10000,
        PARENT.upper(),
        PARENT[:-1],
        PARENT.replace("00-", "ff-", 1),
        "00-" + "0" * 32 + "-1234567890abcdef-01",
        "00-1234567890abcdef1234567890abcdef-" + "0" * 16 + "-01",
    ],
)
def test_invalid_context_is_omitted(value):
    assert parse_traceparent(value) is None
    assert span_links(value) == []


def test_capture_and_link_independence():
    assert capture_traceparent() is None
    provider = TracerProvider(shutdown_on_exit=False)
    with provider.get_tracer("test").start_as_current_span("origin") as span:
        value = capture_traceparent()
        parsed = parse_traceparent(value)
        assert parsed.trace_id == span.get_span_context().trace_id
        assert parsed.trace_state.to_header() == ""
        assert (
            span_links(value)[0].context.trace_flags
            == span.get_span_context().trace_flags
        )
    with trace.use_span(trace.NonRecordingSpan(parse_traceparent(PARENT))):
        assert capture_traceparent() is None
    provider.shutdown()


def test_actual_sdk_spans_filter_secrets_and_use_independent_links(monkeypatch):
    spans = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
    monkeypatch.setattr(
        telemetry,
        "runtime",
        lambda: SimpleNamespace(
            tracer=provider.get_tracer("test"),
            worker_metrics=telemetry.WorkerMetrics(meter, 0),
        ),
    )
    for outcome in (
        "consumer_retry_scheduled",
        "consumer_failed",
        "consumer_committed",
    ):
        with telemetry.operation(
            "consumer",
            PARENT,
            consumer="analytics",
            event_type="order.completed.v1",
            event_id=str(uuid4()),
            payload=CANARY,
            correlation_id="bad/" + CANARY,
            attempt_number=1,
        ) as observation:
            observation.finish(outcome, CANARY)
    exported = spans.get_finished_spans()
    assert len(exported) == 3
    assert all(span.parent is None and len(span.links) == 1 for span in exported)
    assert all(
        span.links[0].context.trace_id == parse_traceparent(PARENT).trace_id
        for span in exported
    )
    assert len({span.context.trace_id for span in exported}) == 3
    assert CANARY not in str([dict(span.attributes) for span in exported])
    data = reader.get_metrics_data()
    assert CANARY not in str(data)
    provider.shutdown()
    meter.shutdown()


def test_disabled_and_creation_failure_preserve_caller(monkeypatch):
    for active in (None, SimpleNamespace()):
        monkeypatch.setattr(telemetry, "runtime", lambda: active)
        with telemetry.operation("consumer", None) as observation:
            observation.finish("consumer_committed")
        with pytest.raises(ValueError, match="caller"):
            with telemetry.operation("consumer", None):
                raise ValueError("caller")


def test_capture_failure_is_safe(monkeypatch):
    def fail():
        raise RuntimeError(CANARY)

    monkeypatch.setattr(trace, "get_current_span", fail)
    assert capture_traceparent() is None


def test_snapshot_zeros_and_routing_do_not_count_attempts(monkeypatch):
    from app.modules.events.repo.worker_queries import BacklogSample

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
    worker = telemetry.WorkerMetrics(provider, 0)
    monkeypatch.setattr(
        telemetry, "runtime", lambda: SimpleNamespace(worker_metrics=worker)
    )
    worker.snapshot([BacklogSample("analytics", "queued", 12, 100)])
    worker.snapshot([])
    worker.progress_snapshot([])
    telemetry.routing("analytics", "durable_receipt_acknowledged")
    data = {
        m.name: m
        for r in reader.get_metrics_data().resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
    }
    assert "restaurantos.worker.operations" not in data
    depth = data["restaurantos.worker.deliveries"].data.data_points
    assert len(depth) == 15 and all(p.value == 0 for p in depth)
    routes = data["restaurantos.worker.routes"].data.data_points
    assert len(routes) == 1 and routes[0].attributes == {
        "consumer": "analytics",
        "outcome": "duplicate",
        "worker_slot": "0",
    }
    assert all(set(p.attributes) <= {"consumer", "state"} for p in depth)
    provider.shutdown()


@pytest.mark.parametrize("slot", [-1, 32, "private", True])
def test_worker_metric_slot_is_bounded(slot):
    provider = MeterProvider(shutdown_on_exit=False)
    try:
        with pytest.raises(ValueError):
            telemetry.WorkerMetrics(provider, slot)
    finally:
        provider.shutdown()


def test_unassigned_worker_emits_only_durable_gauges():
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
    worker = telemetry.WorkerMetrics(provider)
    worker.completed(1, {"outcome": "consumer_committed"})
    worker.routed("analytics", "duplicate")
    worker.collection_failed()
    worker.snapshot([])
    worker.progress_snapshot([])
    data = [
        m
        for r in reader.get_metrics_data().resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
    ]
    assert all(
        m.name
        not in {
            "restaurantos.worker.operations",
            "restaurantos.worker.duration",
            "restaurantos.worker.routes",
            "restaurantos.worker.collection.failures",
        }
        for m in data
    )
    assert all(
        "worker_slot" not in p.attributes for m in data for p in m.data.data_points
    )
    provider.shutdown()
