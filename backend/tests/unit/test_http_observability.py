"""SDK-backed HTTP privacy, accounting and lifecycle tests without network IO."""

import asyncio
import json
import logging
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import telemetry
from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.core.request_id import get_request_id
from app.http.observability import category, route_patterns
from app.http.request_middleware import RequestIdMiddleware

CANARY = "CANARY_SECRET_59_password_cookie_body_sql"
PARENT = "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"
CREDENTIAL_URL = "http://user:password@localhost:4318"  # pragma: allowlist secret


@pytest.fixture
def sdk(monkeypatch, unit_settings_kwargs):
    settings = Settings(
        _env_file=None,
        **unit_settings_kwargs,
        monitoring_enabled=True,
        monitoring_trusted_upstream_ips=["127.0.0.1"],
    )
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    reader = InMemoryMetricReader()
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda **kw: spans)
    monkeypatch.setattr(telemetry, "OTLPLogExporter", lambda **kw: logs)
    monkeypatch.setattr(telemetry, "BudgetedMetricExporter", lambda **kw: None)
    monkeypatch.setattr(
        telemetry, "PeriodicExportingMetricReader", lambda *a, **kw: reader
    )
    runtime = telemetry.Telemetry(settings)
    monkeypatch.setattr(telemetry.lifecycle, "runtime", runtime)
    yield SimpleNamespace(runtime=runtime, spans=spans, logs=logs, reader=reader)
    runtime.shutdown()
    route_patterns.cache_clear()


def metrics(sdk):
    return {
        m.name: m
        for r in sdk.reader.get_metrics_data().resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
    }


def test_requests_export_bounded_metrics_safe_traces_and_correlated_logs(sdk, caplog):
    local = []

    class Capture(logging.Handler):
        def emit(self, record):
            local.append(json.loads(JsonFormatter().format(record)))

    capture = Capture()
    request_logger = logging.getLogger("restaurantos.request")
    request_logger.addHandler(capture)
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    router = APIRouter(prefix="/api")

    @router.get("/items/{item_id}")
    async def item(item_id: int):
        return {"id": item_id}

    @router.get("/error")
    async def error():
        raise RuntimeError(CANARY)

    @router.get("/status/{status}")
    async def status(status: int):
        raise HTTPException(status, detail=CANARY)

    app.include_router(router)
    with caplog.at_level(logging.INFO, logger="restaurantos.request"):
        with TestClient(
            app, raise_server_exceptions=False, client=("127.0.0.1", 1234)
        ) as client:
            headers = {
                "X-Request-ID": "issue59-correlation",
                "traceparent": PARENT,
                "tracestate": CANARY,
                "baggage": CANARY,
                "Authorization": "Bearer " + CANARY,
                "Cookie": "ros_access=" + CANARY,
            }
            response = client.get("/api/items/12?password=" + CANARY, headers=headers)
            assert response.headers["X-Request-ID"] == "issue59-correlation"
            assert client.get("/api/items/13").status_code == 200
            assert client.get("/api/items/" + CANARY).status_code == 422
            assert client.get("/unknown/" + CANARY).status_code == 404
            assert client.get("/api/error").status_code == 500
            for status in (401, 403, 409, 429):
                assert client.get(f"/api/status/{status}").status_code == status
    sdk.runtime.traces.force_flush()
    sdk.runtime.logs.force_flush()
    spans = sdk.spans.get_finished_spans()
    assert len(spans) == 9
    first = spans[0]
    assert first.context.trace_id == int(PARENT.split("-")[1], 16)
    assert first.parent.span_id == int(PARENT.split("-")[2], 16)
    assert first.attributes["request_id"] == "issue59-correlation"
    assert first.context.trace_state.to_header() == ""
    assert all(not span.events and not span.links for span in spans)
    assert {s.attributes["outcome"] for s in spans} == {
        "success",
        "validation",
        "not_found",
        "server_error",
        "authentication",
        "forbidden",
        "conflict",
        "rate_limit",
    }
    data = metrics(sdk)
    assert (
        sum(p.value for p in data["restaurantos.http.requests"].data.data_points) == 9
    )
    points = data["restaurantos.http.duration"].data.data_points
    assert sum(p.count for p in points) == 9
    assert all(
        tuple(p.explicit_bounds) == telemetry.BUCKETS and not p.exemplars
        for p in points
    )
    assert all(
        p.value == 0 for p in data["restaurantos.http.inflight"].data.data_points
    )
    labels = {p.attributes["http.route"] for p in points}
    assert labels == {
        "/api/items/{item_id}",
        "/api/error",
        "/api/status/{status}",
        "<unmatched>",
    }
    records = sdk.logs.get_finished_logs()
    assert len(records) == 9
    assert records[0].log_record.trace_id == first.context.trace_id
    assert records[0].log_record.span_id == first.context.span_id
    request_logger.removeHandler(capture)
    assert local[0]["request_id"] == "issue59-correlation"
    assert local[0]["trace_id"] == f"{first.context.trace_id:032x}"
    assert local[0]["span_id"] == f"{first.context.span_id:016x}"
    # Raw records carry no exception details or paths; exported payloads are inspected too.
    serialized = (
        str(local)
        + str([dict(s.attributes) for s in spans])
        + str([r.to_json() for r in records])
        + str(points)
    )
    assert CANARY not in serialized


@pytest.mark.parametrize(
    "header,trusted",
    [("bad-" + CANARY, True), (PARENT, False), (PARENT + CANARY, True)],
)
def test_invalid_or_untrusted_traceparent_restarts_without_rejecting(
    sdk, header, trusted
):
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.add_middleware(RequestIdMiddleware)
    with TestClient(app, client=("127.0.0.1" if trusted else "127.0.0.2", 1)) as client:
        assert client.get("/health", headers={"traceparent": header}).status_code == 200
    sdk.runtime.traces.force_flush()
    span = sdk.spans.get_finished_spans()[0]
    assert span.parent is None
    assert span.context.trace_id != int(PARENT.split("-")[1], 16)


@pytest.mark.asyncio
async def test_cancellation_releases_actual_inflight_and_request_context(sdk):
    entered = asyncio.Event()
    release = asyncio.Event()
    app = FastAPI()

    @app.get("/health")
    async def health():
        entered.set()
        await release.wait()

    app.add_middleware(RequestIdMiddleware)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "root_path": "",
        "server": ("localhost", 80),
        "client": ("127.0.0.1", 1),
        "http_version": "1.1",
    }

    async def receive():
        await release.wait()

    async def send(message):
        pass

    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(entered.wait(), 2)
    assert (
        sum(
            p.value for p in metrics(sdk)["restaurantos.http.inflight"].data.data_points
        )
        == 1
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (
        sum(
            p.value for p in metrics(sdk)["restaurantos.http.inflight"].data.data_points
        )
        == 0
    )
    assert get_request_id() is None
    sdk.runtime.traces.force_flush()
    assert sdk.spans.get_finished_spans()[0].attributes["outcome"] == "cancelled"


def test_exception_after_headers_keeps_status_and_releases_inflight(sdk):
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/stream")
    async def stream():
        async def body():
            yield b"safe"
            raise RuntimeError(CANARY)

        return StreamingResponse(body())

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/stream").status_code == 200
    sdk.runtime.traces.force_flush()
    span = sdk.spans.get_finished_spans()[0]
    assert span.attributes["http.response.status_code"] == 200
    assert span.attributes["outcome"] == "server_error"
    assert not span.events
    data = metrics(sdk)
    assert all(
        p.value == 0 for p in data["restaurantos.http.inflight"].data.data_points
    )


def test_local_formatter_does_not_render_messages_arguments_or_exceptions():
    try:
        raise ValueError(CANARY)
    except ValueError:
        import sys

        record = logging.LogRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "request %s",
            (CANARY,),
            sys.exc_info(),
        )
    formatted = JsonFormatter().format(record)
    assert CANARY not in formatted
    assert "suppressed" in formatted


def test_lifecycle_shares_overlapping_owners_and_fences_slow_shutdown(
    monkeypatch, unit_settings_kwargs
):
    settings = Settings(_env_file=None, **unit_settings_kwargs, monitoring_enabled=True)
    stop = Event()
    entered = Event()
    instances = []

    class Pipeline:
        def __init__(self, settings):
            instances.append(self)

        def shutdown(self):
            entered.set()
            assert stop.wait(3)
            return True

    monkeypatch.setattr(telemetry, "Telemetry", Pipeline)
    manager = telemetry.TelemetryLifecycle()
    first = manager.acquire(settings)
    assert manager.acquire(settings) is first
    assert manager.release(first).is_set()
    assert not manager.release(first).is_set()
    assert entered.wait(1)
    assert manager.acquire(settings) is None
    assert len(instances) == 1
    stop.set()
    assert manager.retired.wait(2)
    second = manager.acquire(settings)
    assert second is not first
    assert manager.release(second).wait(2)
    disabled = settings.model_copy(update={"monitoring_enabled": False})
    assert manager.acquire(disabled) is None


def test_pipeline_initialization_failure_is_safe_and_retryable(
    monkeypatch, unit_settings_kwargs, caplog
):
    settings = Settings(_env_file=None, **unit_settings_kwargs, monitoring_enabled=True)

    def unavailable(settings):
        raise RuntimeError(CANARY)

    monkeypatch.setattr(telemetry, "Telemetry", unavailable)
    manager = telemetry.TelemetryLifecycle()
    assert manager.acquire(settings) is None
    assert manager.acquire(settings) is None
    assert manager.runtime is None and manager.owners == 0 and manager.retired.is_set()
    assert CANARY not in "".join(
        JsonFormatter().format(record) for record in caplog.records
    )


@pytest.mark.parametrize(
    "change",
    [
        {"monitoring_queue_size": 0},
        {"monitoring_queue_size": 1025},
        {"monitoring_export_timeout_seconds": 10},
        {"monitoring_shutdown_seconds": 0},
        {"monitoring_endpoint": CREDENTIAL_URL},
        {"monitoring_endpoint": "http://localhost:4318/?secret=value"},
        {"monitoring_trusted_upstream_ips": ["*"]},
        {"monitoring_enabled": True, "database_echo": True},
    ],
)
def test_configuration_is_bounded(unit_settings_kwargs, change):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **unit_settings_kwargs, **change)


def test_instrument_failure_does_not_change_business_response(sdk, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError(CANARY)

    monkeypatch.setattr(sdk.runtime, "completed", fail)
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.add_middleware(RequestIdMiddleware)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, "success"),
        (307, "success"),
        (400, "client_error"),
        (415, "client_error"),
        (503, "server_error"),
    ],
)
def test_other_status_categories(status, expected):
    assert category(status, cancelled=False, failed=False) == expected
