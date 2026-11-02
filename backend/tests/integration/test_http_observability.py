"""Real SDK HTTP exporters and real PostgreSQL order/audit invariants."""

import json
import asyncio
import logging
import os
import re
from pathlib import Path
import time
from contextlib import contextmanager
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

import app.main as main
from app.core.logging import JsonFormatter
from app.core.telemetry import lifecycle
from app.http.observability import route_patterns
from integration.test_order_inventory import (
    balance,
    create_ingredient,
    create_menu_item,
    create_order,
    create_restaurant,
    movement_rows,
    set_recipe,
    update_order,
)

CANARY = "CANARY59_PRIVATE_password_jwt_cookie_body_sql"  # pragma: allowlist secret
MESSAGES = {
    "/v1/traces": ExportTraceServiceRequest,
    "/v1/logs": ExportLogsServiceRequest,
    "/v1/metrics": ExportMetricsServiceRequest,
}


@contextmanager
def collector(mode):
    entered, release = Event(), Event()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            message = MESSAGES[self.path]()
            message.ParseFromString(payload)
            decoded = MessageToDict(message)
            decoded["test_transport_headers"] = {
                key: self.headers.get(key) for key in ("Authorization", "Cookie")
            }
            decoded["test_encoded_bytes"] = len(payload)
            received.append(decoded)
            entered.set()
            if mode == "slow":
                release.wait(10)
            self.send_response(
                503
                if mode == "reject" or (mode == "outage" and release.is_set())
                else 200
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received, entered, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@contextmanager
def instrumented_client(monkeypatch, auth_user, endpoint, *, timeout=0.2):
    assert lifecycle.retired.wait(10)
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_HEADERS", "authorization=" + CANARY + ",cookie=" + CANARY
    )
    monkeypatch.setattr(
        main,
        "settings",
        main.settings.model_copy(
            update={
                "monitoring_enabled": True,
                "monitoring_endpoint": endpoint,
                "monitoring_queue_size": 16,
                "monitoring_export_timeout_seconds": timeout,
                "monitoring_export_interval_ms": 1000,
                "monitoring_shutdown_seconds": 0.2,
                "monitoring_trusted_upstream_ips": ["127.0.0.1"],
            }
        ),
    )
    trace_id = uuid4().hex
    with TestClient(
        main.app, raise_server_exceptions=False, client=("127.0.0.1", 1)
    ) as client:
        assert lifecycle.runtime is not None
        client.headers.update(
            {
                "Origin": "http://localhost:3000",
                "X-CSRF-Protection": "1",
                "traceparent": f"00-{trace_id}-1234567890abcdef-01",
                "baggage": CANARY,
                "tracestate": CANARY,
            }
        )
        response = client.post(
            "/auth/login",
            json={"email": auth_user["email"], "password": auth_user["password"]},
        )
        assert response.status_code == 200
        yield client, trace_id
        shutdown_started = time.monotonic()
    assert time.monotonic() - shutdown_started < 1.5
    assert lifecycle.retired.wait(10)


def business_and_privacy_requests(client, monkeypatch, after_creation=lambda: None):
    restaurant = create_restaurant(client, CANARY)
    item = create_menu_item(client, restaurant, CANARY)
    ingredient = create_ingredient(client, restaurant, name=CANARY, quantity="10")
    assert (
        set_recipe(
            client, item, [{"ingredient_id": ingredient["id"], "quantity": "2"}]
        ).status_code
        == 200
    )
    key = uuid4().hex
    created = create_order(client, restaurant, item, 2, key=key)
    assert created.status_code == 201
    order = created.json()["order_id"]
    after_creation()
    assert update_order(client, order, "SUBMITTED").status_code == 200
    assert update_order(client, order, "ACCEPTED").status_code == 200
    audit_before_noop = client.get("/api/audit?limit=100").json()
    assert update_order(client, order, "ACCEPTED").status_code == 200
    # Existing status updates audit even a same-status request. Idempotent create
    # replay/mismatch below adds no write; monitoring must preserve both rules.
    audit_before = client.get("/api/audit?limit=100").json()
    assert len(audit_before) == len(audit_before_noop) + 1
    assert audit_before[0]["action"] == "order.updated"
    assert create_order(client, restaurant, item, 2, key=key).status_code == 201
    assert create_order(client, restaurant, item, 3, key=key).status_code == 409
    assert balance(client, restaurant, ingredient["id"]) == Decimal("6")
    assert len(movement_rows(order)) == 1
    assert client.get("/api/audit?limit=100").json() == audit_before
    assert client.get(f"/api/orders/{order}").json()["status"] == "ACCEPTED"
    assert (
        client.get(
            "/health?secret=" + CANARY,
            headers={
                "Authorization": "Bearer " + CANARY,
                "X-Request-ID": "issue59-business",
            },
        ).status_code
        == 200
    )
    assert client.get("/health", headers={"traceparent": CANARY}).status_code == 200
    assert client.get("/unknown/" + CANARY).status_code == 404
    assert client.post("/auth/login", json={"password": CANARY}).status_code == 422
    assert (
        client.post(
            "/auth/login", json={}, headers={"X-CSRF-Protection": "0"}
        ).status_code
        == 403
    )
    assert client.get("/ready").status_code == 200

    async def cancel_request():
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked_readiness(*args):
            entered.set()
            await release.wait()

        async def receive():
            await release.wait()

        async def send(message):
            pass

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ready",
            "raw_path": b"/ready",
            "query_string": b"secret=" + CANARY.encode(),
            "root_path": "",
            "scheme": "http",
            "http_version": "1.1",
            "server": ("localhost", 80),
            "client": ("127.0.0.1", 1),
            "headers": [
                (b"traceparent", client.headers["traceparent"].encode()),
                (b"x-request-id", b"issue59-cancelled"),
            ],
        }
        with monkeypatch.context() as fault:
            fault.setattr(main, "database_ready", blocked_readiness)
            task = asyncio.create_task(main.app(scope, receive, send))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(cancel_request())
    subject = main.app.state.auth_limiter

    async def server_seconds():
        return int((await subject._redis().execute("TIME"))[0])

    window_end = client.portal.call(server_seconds) + 600
    # Like auth's admission tests, keep real Redis TIME/Lua and real limits but
    # hold this counting fixture in one fixed window. Crossing a minute boundary
    # legitimately expires prior failures; it is not a telemetry failure.
    with monkeypatch.context() as admission_fixture:
        admission_fixture.setattr(
            subject,
            "settings",
            subject.settings.model_copy(
                update={"auth_login_window_seconds": window_end},
            ),
        )
        attempts = [
            client.post(
                "/auth/login",
                json={"email": CANARY + "@example.test", "password": CANARY},
            ).status_code
            for _ in range(6)
        ]
        assert attempts[0] == 401
        assert attempts[-1] == 429
        assert client.portal.call(server_seconds) < window_end

    async def fail(*args):
        raise RuntimeError(CANARY)

    with monkeypatch.context() as fault:
        fault.setattr(main, "database_ready", fail)
        assert client.get("/ready").status_code == 500
    assert client.get("/ready").status_code == 200
    return order


@pytest.mark.parametrize("mode", ["unavailable", "outage", "slow", "reject", "success"])
def test_real_export_failures_never_change_order_stock_audit_or_shutdown(
    monkeypatch, auth_user, caplog, mode
):
    with collector(mode) as (endpoint, received, entered, release):
        if mode == "unavailable":
            # A closed local port: unavailable before startup and throughout commands.
            from socket import socket

            with socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                endpoint = f"http://127.0.0.1:{reservation.getsockname()[1]}"
        with caplog.at_level(logging.INFO):
            with instrumented_client(
                monkeypatch, auth_user, endpoint, timeout=2 if mode == "slow" else 0.2
            ) as (client, _):
                runtime = lifecycle.runtime

                def outage():
                    if mode == "outage":
                        runtime.traces.force_flush()
                        assert entered.wait(3)
                        release.set()

                business_and_privacy_requests(client, monkeypatch, outage)
                if mode != "unavailable":
                    assert entered.wait(3)
                if mode == "slow":
                    for _ in range(100):
                        assert client.get("/health").status_code == 200
                    assert any(
                        str(r.msg).startswith("Queue full,") for r in caplog.records
                    )
                assert client.get("/health").status_code == 200
                # Explicit flush is test-only, after all business transactions.
                if mode == "success":
                    runtime.traces.force_flush()
                    runtime.logs.force_flush()
                    runtime.metrics.force_flush()
                if mode != "slow":
                    release.set()
                started = time.monotonic()
            assert time.monotonic() - started < 10
        assert CANARY not in json.dumps(received)
        assert CANARY not in "".join(JsonFormatter().format(r) for r in caplog.records)
        if mode == "success":
            assert {next(iter(record)) for record in received} >= {
                "resourceSpans",
                "resourceLogs",
                "resourceMetrics",
            }


def populate_metric_capacity(runtime):
    """Approved finite dimension coverage, not a request-throughput benchmark."""
    operations = [
        (path, method.upper())
        for path, item in main.app.openapi()["paths"].items()
        if not path.startswith("/auth")
        and path not in {"/health", "/ready", "/api/test"}
        for method in item
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    ]
    for path, method in operations:
        for status, outcome in (
            (200, "success"),
            (401, "authentication"),
            (403, "forbidden"),
            (404, "not_found"),
            (422, "validation"),
            (500, "server_error"),
        ):
            attributes = {
                "http.route": path,
                "http.request.method": method,
                "http.response.status_code": status,
                "outcome": outcome,
            }
            runtime.requests.add(1, attributes)
            runtime.duration.record(0.02, attributes)
        runtime.inflight.add(0, {"http.route": path, "http.request.method": method})
    runtime.observed.set(time.time())
    return {
        "groups": len(operations) * 6,
        "route": operations[0][0],
        "method": operations[0][1],
        "operations": operations,
    }


def test_large_metric_snapshot_and_idle_snapshot_reach_real_http_collector(
    monkeypatch, auth_user
):
    with collector("success") as (endpoint, received, _, _):
        with instrumented_client(monkeypatch, auth_user, endpoint, timeout=1):
            capacity = populate_metric_capacity(lifecycle.runtime)
            lifecycle.runtime.metrics.force_flush()
            first = [record for record in received if "resourceMetrics" in record]
            assert len(first) > 1
            assert sum(record["test_encoded_bytes"] for record in first) > 65536
            assert all(record["test_encoded_bytes"] <= 65536 for record in first)
            received.clear()
            lifecycle.runtime.metrics.force_flush()
            counters = [
                point
                for record in received
                for resource in record.get("resourceMetrics", [])
                for scope in resource["scopeMetrics"]
                for metric in scope["metrics"]
                if metric["name"] == "restaurantos.http.requests"
                for point in metric["sum"]["dataPoints"]
            ]
            assert len(counters) >= capacity["groups"]
            assert {int(point["asInt"]) for point in counters} == {1}
            unique = {
                tuple(
                    sorted(
                        (
                            a["key"],
                            a["value"].get("stringValue", a["value"].get("intValue")),
                        )
                        for a in point["attributes"]
                    )
                )
                for point in counters
            }
            assert len(unique) >= capacity["groups"]


@pytest.mark.skipif(
    not os.getenv("TEST_MONITORING_ENDPOINT"),
    reason="explicit isolated monitoring acceptance only",
)
def test_stored_api_signals_workload(monkeypatch, auth_user):
    # The companion runner inspects actual Prometheus/Loki/Tempo storage and owns
    # both disposable stacks. This fixture never reads the developer .env target.
    with instrumented_client(
        monkeypatch, auth_user, os.environ["TEST_MONITORING_ENDPOINT"], timeout=1
    ) as (client, trace_id):
        business_and_privacy_requests(client, monkeypatch)
        runtime = lifecycle.runtime
        capacity = populate_metric_capacity(runtime)
        runtime.traces.force_flush()
        runtime.logs.force_flush()
        runtime.metrics.force_flush()
        runtime.metrics.force_flush()  # Quiet cumulative re-export must still fit.
    print(
        "API_OBSERVABILITY_RESULT="
        + json.dumps({"trace_id": trace_id, "canary": CANARY, "capacity": capacity})
    )
    route_patterns.cache_clear()


def test_collector_route_admission_covers_every_current_api_template():
    config = yaml.safe_load(
        (
            Path(__file__).resolve().parents[3] / "monitoring/otel-collector.yaml"
        ).read_text()
    )
    conditions = config["processors"]["filter/api"]["trace_conditions"][1]["conditions"]
    prefix = 'not IsMatch(span.attributes["http.route"], '
    condition = next(c for c in conditions if c.startswith(prefix))
    pattern = json.loads(condition[len(prefix) : -1])
    route_patterns.cache_clear()
    assert all(re.fullmatch(pattern, path) for path, _ in route_patterns(main.app))


@pytest.mark.asyncio
async def test_actual_overlapping_and_sequential_lifespans_share_then_retire(
    monkeypatch,
):
    assert await asyncio.to_thread(lifecycle.retired.wait, 10)
    monkeypatch.setattr(
        main,
        "settings",
        main.settings.model_copy(
            update={
                "monitoring_enabled": True,
                "monitoring_endpoint": "http://127.0.0.1:1",
                "monitoring_export_timeout_seconds": 0.1,
            }
        ),
    )
    first, second = main.lifespan(main.app), main.lifespan(main.app)
    await first.__aenter__()
    runtime = lifecycle.runtime
    try:
        await second.__aenter__()
        assert lifecycle.runtime is runtime
        await first.__aexit__(None, None, None)
        assert lifecycle.runtime is runtime
    finally:
        await second.__aexit__(None, None, None)
    assert lifecycle.runtime is None
    assert await asyncio.to_thread(lifecycle.retired.wait, 5)
    async with main.lifespan(main.app):
        assert lifecycle.runtime is not None and lifecycle.runtime is not runtime
    assert await asyncio.to_thread(lifecycle.retired.wait, 5)
