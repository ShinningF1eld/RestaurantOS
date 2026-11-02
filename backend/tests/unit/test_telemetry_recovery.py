"""Actual SDK batching, per-collection budgets and partial resource ownership."""

from threading import Event, enumerate as threads

import pytest
import requests
from requests.adapters import BaseAdapter
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, MetricExportResult
from opentelemetry.exporter.otlp.proto.common.metrics_encoder import encode_metrics

from app.core import telemetry
from app.core.config import Settings


class RecordingAdapter(BaseAdapter):
    def __init__(self, clock=None):
        self.bodies = []
        self.timeouts = []
        self.closed = False
        self.clock = clock
        self.cost = 0
        self.timeout_error = False

    def send(self, request, **kwargs):
        self.bodies.append(request.body)
        self.timeouts.append(kwargs["timeout"])
        if self.clock is not None:
            self.clock[0] += self.cost
        if self.timeout_error:
            raise requests.ReadTimeout("synthetic export timeout")
        response = requests.Response()
        response.status_code = 200
        response.reason = "OK"
        response._content = b""
        response._content_consumed = True
        return response

    def close(self):
        self.closed = True


def point_count(request):
    return sum(
        len(getattr(metric, metric.WhichOneof("data")).data_points)
        for resource in request.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    )


@pytest.fixture
def large_metrics(monkeypatch, unit_settings_kwargs):
    settings = Settings(_env_file=None, **unit_settings_kwargs)
    reader = InMemoryMetricReader()
    captured = []
    original_exporter = telemetry.BudgetedMetricExporter
    adapter = RecordingAdapter()

    def capture(**kwargs):
        kwargs["session"].mount("http://", adapter)
        exporter = original_exporter(**kwargs)
        captured.append(exporter)
        return exporter

    monkeypatch.setattr(telemetry, "BudgetedMetricExporter", capture)
    monkeypatch.setattr(
        telemetry, "PeriodicExportingMetricReader", lambda *a, **kw: reader
    )
    runtime = telemetry.Telemetry(settings)
    # A finite registered-template fixture, not raw user paths or IDs.
    for index in range(50):
        route = f"/registered-{index}/{{item_id}}"
        for status, outcome in (
            (200, "success"),
            (401, "authentication"),
            (403, "forbidden"),
            (404, "not_found"),
            (422, "validation"),
            (500, "server_error"),
        ):
            attrs = {
                "http.route": route,
                "http.request.method": "GET",
                "http.response.status_code": status,
                "outcome": outcome,
            }
            runtime.requests.add(1, attrs)
            runtime.duration.record(0.02, attrs)
        runtime.inflight.add(0, {"http.route": route, "http.request.method": "GET"})
    runtime.observed.set(1)
    try:
        yield runtime, reader, captured[0], adapter
    finally:
        assert runtime.shutdown()
        # The substituted in-memory reader does not own the captured exporter.
        captured[0].shutdown()


def test_large_cumulative_snapshot_is_split_and_idle_collection_remains_exportable(
    large_metrics,
):
    runtime, reader, exporter, adapter = large_metrics
    data = reader.get_metrics_data()
    encoded = encode_metrics(data)
    assert len(encoded.SerializeToString()) > 65536
    expected_points = point_count(encoded)
    assert exporter.export(data) == MetricExportResult.SUCCESS
    batches = [ExportMetricsServiceRequest.FromString(body) for body in adapter.bodies]
    assert len(batches) > 1
    assert all(len(body) <= 65536 for body in adapter.bodies)
    assert all(point_count(batch) <= 16 for batch in batches)
    assert sum(point_count(batch) for batch in batches) == expected_points
    adapter.bodies.clear()
    assert exporter.export(reader.get_metrics_data()) == MetricExportResult.SUCCESS
    idle = [ExportMetricsServiceRequest.FromString(body) for body in adapter.bodies]
    assert sum(point_count(batch) for batch in idle) == expected_points
    counters = [
        point.as_int
        for batch in idle
        for resource in batch.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "restaurantos.http.requests"
        for point in metric.sum.data_points
    ]
    assert len(counters) == 300 and set(counters) == {1}


def test_split_collection_has_shared_send_budget_and_next_collection_recovers(
    large_metrics, monkeypatch
):
    _, reader, exporter, adapter = large_metrics
    clock = [100.0]
    monkeypatch.setattr(telemetry, "monotonic", lambda: clock[0])
    adapter.clock = clock
    adapter.cost = 0.02
    exporter.budget_seconds = 0.05
    data = reader.get_metrics_data()
    assert exporter.export(data) == MetricExportResult.FAILURE
    assert len(adapter.bodies) == 3
    assert adapter.timeouts[0] == pytest.approx(0.05)
    assert adapter.timeouts[1] < adapter.timeouts[0]
    assert telemetry._export_deadline.get() is None
    # No expired deadline sticks to a later collection on the same SDK exporter.
    adapter.cost = 0
    adapter.bodies.clear()
    assert exporter.export(reader.get_metrics_data()) == MetricExportResult.SUCCESS
    assert len(adapter.bodies) > 3
    assert telemetry._export_deadline.get() is None


def test_timeout_at_collection_deadline_is_terminal_and_later_collection_recovers(
    large_metrics, monkeypatch
):
    _, reader, exporter, adapter = large_metrics
    clock = [100.0]
    monkeypatch.setattr(telemetry, "monotonic", lambda: clock[0])
    adapter.clock = clock
    adapter.cost = 0.05
    adapter.timeout_error = True
    exporter.budget_seconds = 0.05
    assert exporter.export(reader.get_metrics_data()) == MetricExportResult.FAILURE
    assert len(adapter.bodies) == 1
    assert telemetry._export_deadline.get() is None
    adapter.timeout_error = False
    adapter.cost = 0
    adapter.bodies.clear()
    assert exporter.export(reader.get_metrics_data()) == MetricExportResult.SUCCESS
    assert len(adapter.bodies) > 3
    assert telemetry._export_deadline.get() is None


@pytest.mark.parametrize(
    "boundary",
    [
        "trace_processor",
        "log_processor",
        "metric_reader",
        "meter_provider",
        "instruments",
    ],
)
def test_partial_initialization_closes_every_created_resource_before_retry(
    monkeypatch, unit_settings_kwargs, boundary
):
    settings = Settings(
        _env_file=None,
        **unit_settings_kwargs,
        monitoring_enabled=True,
        monitoring_export_interval_ms=30000,
    )
    adapters = []
    original_session = telemetry.ExportSession

    def session():
        result = original_session()
        adapter = RecordingAdapter()
        result.mount("http://", adapter)
        adapters.append(adapter)
        return result

    monkeypatch.setattr(telemetry, "ExportSession", session)
    manager = telemetry.TelemetryLifecycle()
    before = {thread for thread in threads() if thread.name.startswith("Otel")}

    def fail(*args, **kwargs):
        raise RuntimeError("injected SDK construction failure")

    targets = {
        "trace_processor": "BatchSpanProcessor",
        "log_processor": "BatchLogRecordProcessor",
        "metric_reader": "PeriodicExportingMetricReader",
        "meter_provider": "MeterProvider",
    }
    with monkeypatch.context() as fault:
        if boundary == "instruments":
            fault.setattr(telemetry.MeterProvider, "get_meter", fail)
        else:
            fault.setattr(telemetry, targets[boundary], fail)
        for _ in range(2):
            assert manager.acquire(settings) is None
            assert manager.retired.wait(3)
            assert manager.retiring is None and manager.owners == 0
            assert {
                thread for thread in threads() if thread.name.startswith("Otel")
            } == before
            assert all(adapter.closed for adapter in adapters)
    healthy = manager.acquire(settings)
    assert healthy is not None
    assert manager.release(healthy).wait(3)
    assert {thread for thread in threads() if thread.name.startswith("Otel")} == before
    assert all(adapter.closed for adapter in adapters)


def test_failed_startup_is_nonblocking_and_fences_retry_until_reader_cleanup(
    monkeypatch, unit_settings_kwargs
):
    settings = Settings(
        _env_file=None,
        **unit_settings_kwargs,
        monitoring_enabled=True,
        monitoring_export_interval_ms=30000,
    )
    entered, release = Event(), Event()
    readers = []
    original_reader = telemetry.PeriodicExportingMetricReader

    def reader(*args, **kwargs):
        result = original_reader(*args, **kwargs)
        shutdown = result.shutdown

        def delayed_shutdown(*a, **kw):
            entered.set()
            assert release.wait(3)
            return shutdown(*a, **kw)

        result.shutdown = delayed_shutdown
        readers.append(result)
        return result

    def fail(*args, **kwargs):
        raise RuntimeError("injected metric-provider failure")

    monkeypatch.setattr(telemetry, "PeriodicExportingMetricReader", reader)
    monkeypatch.setattr(telemetry, "MeterProvider", fail)
    manager = telemetry.TelemetryLifecycle()
    try:
        assert manager.acquire(settings) is None
        assert entered.wait(1)
        assert not manager.retired.is_set()
        assert manager.acquire(settings) is None
        assert len(readers) == 1 and manager.retiring is not None
    finally:
        release.set()
        assert manager.retired.wait(3)
    assert manager.retiring is None


def test_cleanup_failure_keeps_runtime_fenced_and_future_startup_fails_open(
    unit_settings_kwargs,
):
    settings = Settings(_env_file=None, **unit_settings_kwargs, monitoring_enabled=True)
    entered = Event()

    class IncompleteRuntime:
        def shutdown(self):
            entered.set()
            return False

    manager = telemetry.TelemetryLifecycle()
    runtime = IncompleteRuntime()
    manager.runtime = runtime
    manager.owners = 1
    complete = manager.release(runtime)
    assert entered.wait(1)
    assert not complete.is_set()
    assert manager.acquire(settings) is None
    assert manager.retiring is runtime
