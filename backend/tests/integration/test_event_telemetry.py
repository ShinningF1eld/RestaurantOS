"""Real PostgreSQL context and actual OTLP worker export, including restarts."""

import asyncio
import base64
import json
import subprocess
import sys

import pytest
from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.telemetry import worker_lifecycle
from app.db.database import AsyncSessionLocal
from app.modules.events.repo.models import OutboxEvent
from app.modules.events.worker.service import EventWorkerService
from app.modules.events.execution import EventTransientFailure
from test_event_execution import service, execute, effect, effect_count
from test_event_worker import (
    BACKEND,
    append_event_for_test,
    create_scope,
    worker_settings,
    wait_for,
    process_environment,
    delete_owned_stream,
    delivery_rows,
    start_process,
    process_phase,
    kill_process,
)
from test_http_observability import collector
from conftest import engine

CANARY = "CANARY62_PRIVATE_password_cookie_payload"


def traced_event(*, completed=False):
    provider = TracerProvider(shutdown_on_exit=False)
    try:
        with provider.get_tracer("test").start_as_current_span("origin") as origin:
            event = append_event_for_test(create_scope(), completed=completed)
            context = origin.get_span_context()
        return event, context
    finally:
        provider.shutdown()


def spans(received):
    return [
        span
        for item in received
        for resource in item.get("resourceSpans", [])
        for scope in resource.get("scopeSpans", [])
        for span in scope["spans"]
    ]


def attrs(span):
    return {
        item["key"]: next(iter(item["value"].values()))
        for item in span.get("attributes", [])
    }


def references_drained(settings):
    from app.modules.events.worker.redis import WorkerRedisTransport

    async def inspect():
        redis = WorkerRedisTransport(settings)
        await redis.open()
        try:
            latest = await redis.execute(
                "XREVRANGE", redis.stream_key(), "+", "-", "COUNT", 1
            )
            groups = await redis.execute("XINFO", "GROUPS", redis.stream_key())

            def identity(value):
                return tuple(int(part) for part in value.split("-"))

            return (
                len(groups) == 3
                and bool(latest)
                and all(
                    group["pending"] == 0
                    and identity(group["last-delivered-id"]) >= identity(latest[0][0])
                    for group in groups
                )
            )
        finally:
            await redis.close()

    return asyncio.run(inspect())


def assert_origin_link(span, origin):
    assert not span.get("parentSpanId")
    assert len(span["links"]) == 1
    link = span["links"][0]
    assert (
        link["traceId"]
        == base64.b64encode(origin.trace_id.to_bytes(16, "big")).decode()
    )
    assert (
        link["spanId"] == base64.b64encode(origin.span_id.to_bytes(8, "big")).decode()
    )
    # Pinned OTLP encoder serializes remote-context bits, not low W3C flags.
    # Full W3C flags are asserted in persistence and SDK Link construction tests.
    assert link.get("flags", 0) & 0x300 == 0x300
    assert not link.get("traceState") and not link.get("attributes")


def test_atomic_context_persistence_claim_and_rollback():
    event, origin = traced_event()
    with Session(engine) as session:
        stored = session.get(OutboxEvent, event.event_id)
        assert (
            stored.traceparent
            == f"00-{origin.trace_id:032x}-{origin.span_id:016x}-{int(origin.trace_flags):02x}"
        )
        assert "traceparent" not in stored.payload
        assert stored.schema_version == 1

    async def run():
        claims = await EventWorkerService(AsyncSessionLocal).claim_due_deliveries(
            owner="telemetry", limit=10, lease_seconds=30, republish_after_seconds=60
        )
        assert claims[0].traceparent == stored.traceparent
        from app.modules.events.service import append_event
        from test_events_storage import completed_envelope

        envelope = completed_envelope(event.organization_id, event.restaurant_id)
        provider = TracerProvider(shutdown_on_exit=False)
        try:
            with provider.get_tracer("rollback").start_as_current_span(
                "rollback origin"
            ):
                with pytest.raises(RuntimeError):
                    async with AsyncSessionLocal() as session, session.begin():
                        staged = await append_event(session, envelope)
                        assert staged.traceparent is not None
                        raise RuntimeError("rollback")
        finally:
            provider.shutdown()
        async with AsyncSessionLocal() as session:
            assert await session.get(OutboxEvent, envelope.event_id) is None

    asyncio.run(run())


def test_retry_terminal_replay_duplicate_and_backlog_export():
    from app.modules.events.operator import EventOperatorService
    from app.modules.events.domain.retries import RetryPolicy

    event, origin = traced_event()
    calls = 0

    async def flaky(session, envelope):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise EventTransientFailure(CANARY)
        return await effect(session, envelope)

    with collector("success") as (endpoint, received, _, _):
        settings = worker_settings(
            monitoring_enabled=True,
            monitoring_endpoint=endpoint,
            monitoring_export_timeout_seconds=0.2,
        )
        assert worker_lifecycle.retired.wait(10)
        runtime = worker_lifecycle.acquire(settings)
        try:

            async def run():
                execution = service(
                    flaky, policy=RetryPolicy(max_attempts=2), jitter=lambda: 0
                )
                assert (
                    await execute(execution, event)
                ).outcome == "consumer_retry_scheduled"
                backlog = await EventWorkerService(AsyncSessionLocal).backlog()
                assert [(r.state, r.depth) for r in backlog] == [("retry_delayed", 1)]
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE event_deliveries SET next_attempt_at=now() WHERE event_id=:id"
                        ),
                        {"id": event.event_id},
                    )
                assert (await execute(execution, event)).outcome == "consumer_failed"
                backlog = await EventWorkerService(AsyncSessionLocal).backlog()
                assert backlog[0].state == "terminal"
                operator = EventOperatorService(AsyncSessionLocal)
                # Use the same trusted, scoped replay path as the existing execution tests.
                await operator.replay(
                    delivery_rows(event.event_id)[0]["id"], reason="controlled repair"
                )
                assert (await execute(execution, event)).outcome == "consumer_committed"
                assert (
                    await execute(execution, event)
                ).outcome == "durable_receipt_acknowledged"
                assert effect_count(event) == 1
                runtime.worker_metrics.snapshot(
                    await EventWorkerService(AsyncSessionLocal).backlog()
                )
                runtime.worker_metrics.progress_snapshot(
                    await EventWorkerService(AsyncSessionLocal).progress()
                )

            asyncio.run(run())
            runtime.traces.force_flush()
            runtime.metrics.force_flush()
        finally:
            worker_lifecycle.release(runtime).wait(10)
        exported = spans(received)
        assert len(exported) == 3
        assert {attrs(s)["outcome"] for s in exported} == {
            "consumer_retry_scheduled",
            "consumer_failed",
            "consumer_committed",
        }
        assert all(
            s["links"][0]["traceId"]
            == base64.b64encode(origin.trace_id.to_bytes(16, "big")).decode()
            for s in exported
        )
        for span in exported:
            assert_origin_link(span, origin)
        assert len({attrs(s)["attempt_id"] for s in exported}) == 3
        assert any("replay_id" in attrs(s) for s in exported)
        assert CANARY not in json.dumps(received)
        metrics = [
            metric
            for item in received
            for resource in item.get("resourceMetrics", [])
            for scope in resource.get("scopeMetrics", [])
            for metric in scope["metrics"]
        ]
        assert {metric["name"] for metric in metrics} >= {
            "restaurantos.worker.operations",
            "restaurantos.worker.duration",
            "restaurantos.worker.deliveries",
            "restaurantos.worker.oldest",
            "restaurantos.worker.receipts.window",
            "restaurantos.worker.collected",
        }
        for metric in metrics:
            if not metric["name"].startswith("restaurantos.worker."):
                continue
            for instrument in ("gauge", "sum", "histogram"):
                for point in metric.get(instrument, {}).get("dataPoints", []):
                    assert {a["key"] for a in point.get("attributes", [])} <= {
                        "consumer",
                        "state",
                        "operation",
                        "outcome",
                        "event_type",
                        "worker_slot",
                    }


@pytest.mark.parametrize("outage", [False, True, "unavailable"])
def test_real_process_restart_and_collector_outage(tmp_path, monkeypatch, outage):
    import socket

    settings = worker_settings()
    with (
        socket.socket() as unavailable,
        collector("reject" if outage else "success") as (endpoint, received, _, _),
    ):
        if outage == "unavailable":
            unavailable.bind(("127.0.0.1", 0))
            endpoint = f"http://127.0.0.1:{unavailable.getsockname()[1]}"
        env = process_environment(settings)
        env.update(
            MONITORING_ENABLED="true",
            MONITORING_ENDPOINT=endpoint,
            MONITORING_EXPORT_TIMEOUT_SECONDS="0.1",
            MONITORING_SHUTDOWN_SECONDS="1",
        )
        for key in (
            "MONITORING_ENABLED",
            "MONITORING_ENDPOINT",
            "MONITORING_EXPORT_TIMEOUT_SECONDS",
            "MONITORING_SHUTDOWN_SECONDS",
        ):
            monkeypatch.setenv(key, env[key])
        event, origin = traced_event(completed=True)
        legacy = append_event_for_test(create_scope())
        first = start_process(tmp_path, settings, pause_at="after_claim")
        try:
            process_phase(first, "after_claim")
        finally:
            kill_process(first)
        # The originating request/provider and first worker are gone. PostgreSQL
        # context and fenced claims survive into the production worker process.
        process = subprocess.Popen(
            [sys.executable, "-m", "app.worker"],
            cwd=BACKEND,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for(
                lambda: all(
                    row["status"] == "succeeded"
                    for row in delivery_rows(event.event_id)
                ),
                timeout=25,
            )
            wait_for(
                lambda: all(
                    row["status"] == "succeeded"
                    for row in delivery_rows(legacy.event_id)
                ),
                timeout=25,
            )
            wait_for(lambda: references_drained(settings), timeout=10)
            # Graceful SIGTERM exercises bounded exporter shutdown as well as actual loops.
            process.terminate()
            process.wait(timeout=10)
            assert process.returncode == 0
            from decimal import Decimal
            from sqlalchemy import select, func
            from app.modules.analytics.repo.models import DailySales
            from app.modules.events.repo.models import EventReceipt

            with Session(engine) as session:
                sales = session.scalar(
                    select(DailySales).where(
                        DailySales.restaurant_id == event.restaurant_id
                    )
                )
                assert sales.sales == Decimal("12.50") and sales.order_count == 1
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(EventReceipt)
                        .where(EventReceipt.event_id == event.event_id)
                    )
                    == 2
                )
            exported = spans(received)
            if outage == "unavailable":
                assert not exported
                return
            event_spans = [
                s for s in exported if attrs(s).get("event_id") == str(event.event_id)
            ]
            assert {s["name"] for s in event_spans} == {
                "outbox publish",
                "consumer attempt",
            }
            assert all(
                s["links"][0]["traceId"]
                == base64.b64encode(origin.trace_id.to_bytes(16, "big")).decode()
                for s in event_spans
            )
            for span in event_spans:
                assert_origin_link(span, origin)
            assert {
                attrs(s)["consumer"]
                for s in event_spans
                if s["name"] == "consumer attempt"
            } == {"analytics", "notification_sink"}
            assert all(
                not s.get("links")
                for s in exported
                if attrs(s).get("event_id") == str(legacy.event_id)
            )
            assert CANARY not in json.dumps(received)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            delete_owned_stream(settings)


def test_real_process_failed_retry_repair_and_duplicate(tmp_path):
    """Test-only poison handler; repair uses the production handler and operator API."""
    from uuid import uuid4
    from app.modules.events.operator import EventOperatorService
    from app.modules.events.repo.worker_queries import DeliveryClaim
    from app.modules.events.worker.redis import WorkerRedisTransport
    from app.modules.events.worker.streams import EventStreams
    from app.modules.notifications.repo.models import EventDiagnostic
    from sqlalchemy import select, func

    settings = worker_settings(event_worker_max_attempts=2)
    event, origin = traced_event()
    with collector("success") as (endpoint, received, _, _):
        env = process_environment(settings)
        env.update(
            MONITORING_ENABLED="true",
            MONITORING_ENDPOINT=endpoint,
            MONITORING_EXPORT_TIMEOUT_SECONDS="0.1",
            MONITORING_SHUTDOWN_SECONDS="1",
            EVENT_WORKER_MAX_ATTEMPTS="2",
            EVENT_WORKER_TEST_POISON_SINK="1",
        )
        poison = subprocess.Popen(
            [sys.executable, str(BACKEND / "tests/support/event_worker_process.py")],
            cwd=BACKEND,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for(
                lambda: delivery_rows(event.event_id)[0]["status"] == "failed",
                timeout=20,
            )
            poison.terminate()
            poison.wait(timeout=10)
            row = delivery_rows(event.event_id)[0]
            assert row["attempt_count"] == 2
            asyncio.run(
                EventOperatorService(AsyncSessionLocal).replay(
                    row["id"], reason="synthetic worker repair"
                )
            )
        finally:
            if poison.poll() is None:
                poison.kill()
                poison.wait(timeout=10)
        env.pop("EVENT_WORKER_TEST_POISON_SINK")
        repaired = subprocess.Popen(
            [sys.executable, "-m", "app.worker"],
            cwd=BACKEND,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for(
                lambda: delivery_rows(event.event_id)[0]["status"] == "succeeded",
                timeout=20,
            )

            async def duplicate():
                redis = WorkerRedisTransport(settings)
                await redis.open()
                try:
                    streams = EventStreams(redis)
                    return await streams.publish(
                        DeliveryClaim(
                            row["id"],
                            event.event_id,
                            "notification_sink",
                            event.event_type,
                            1,
                            event.correlation_id,
                            uuid4(),
                            "test-duplicate",
                        )
                    )
                finally:
                    await redis.close()

            message_id = asyncio.run(duplicate())

            async def acknowledged():
                redis = WorkerRedisTransport(settings)
                await redis.open()
                try:
                    groups = await redis.execute("XINFO", "GROUPS", redis.stream_key())
                    return all(
                        group["last-delivered-id"] >= message_id
                        and group["pending"] == 0
                        for group in groups
                    )
                finally:
                    await redis.close()

            wait_for(lambda: asyncio.run(acknowledged()), timeout=15)
            repaired.terminate()
            repaired.wait(timeout=10)
            with Session(engine) as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(EventDiagnostic)
                        .where(EventDiagnostic.event_id == event.event_id)
                    )
                    == 1
                )
            actual = [s for s in spans(received) if s["name"] == "consumer attempt"]
            assert len(actual) == 3
            assert [attrs(s)["outcome"] for s in actual] == [
                "consumer_retry_scheduled",
                "consumer_failed",
                "consumer_committed",
            ]
            assert len({attrs(s)["attempt_id"] for s in actual}) == 3
            assert attrs(actual[-1])["replay_id"]
            for span in actual:
                assert_origin_link(span, origin)
            assert all(
                s["links"][0]["traceId"]
                == base64.b64encode(origin.trace_id.to_bytes(16, "big")).decode()
                for s in actual
            )
        finally:
            if repaired.poll() is None:
                repaired.kill()
                repaired.wait(timeout=10)
            delete_owned_stream(settings)


def test_backlog_state_precedence_age_and_expired_leases():
    """All gauges derive from PostgreSQL time/state, independent of Redis length."""
    events = [append_event_for_test(create_scope()) for _ in range(6)]
    with engine.begin() as connection:
        for event in events:
            connection.execute(
                text(
                    "UPDATE event_deliveries SET created_at=now()-interval '120 seconds' WHERE event_id=:id"
                ),
                {"id": event.event_id},
            )
        # Pending relay ownership is in flight. Processing with an expired lease
        # requires recovery, and must not masquerade as an actively executing job.
        connection.execute(
            text(
                "UPDATE event_deliveries SET claim_token=gen_random_uuid(),claim_owner='test',claim_expires_at=now()+interval '30 seconds' WHERE event_id=:id"
            ),
            {"id": events[1].event_id},
        )
        connection.execute(
            text(
                "UPDATE event_deliveries SET next_attempt_at=now()+interval '30 seconds' WHERE event_id=:id"
            ),
            {"id": events[2].event_id},
        )
        connection.execute(
            text("UPDATE event_deliveries SET status='failed' WHERE event_id=:id"),
            {"id": events[3].event_id},
        )
        connection.execute(
            text(
                "UPDATE event_deliveries SET status='processing',claim_token=gen_random_uuid(),claim_owner='expired',claim_expires_at=now()-interval '1 second' WHERE event_id=:id"
            ),
            {"id": events[4].event_id},
        )
        connection.execute(
            text("UPDATE event_deliveries SET status='succeeded' WHERE event_id=:id"),
            {"id": events[5].event_id},
        )
    rows = asyncio.run(EventWorkerService(AsyncSessionLocal).backlog())
    assert {r.state: r.depth for r in rows} == {
        "queued": 1,
        "in_flight": 1,
        "retry_delayed": 1,
        "terminal": 1,
        "recovery_due": 1,
    }
    assert all(120 <= r.oldest_seconds < 130 for r in rows)


@pytest.mark.parametrize(
    "outcome", ["published", "claim_lost", "transport_failure", "observation_failure"]
)
def test_publication_branch_export_keeps_durable_claim_semantics(monkeypatch, outcome):
    import socket
    from pydantic import SecretStr
    from sqlalchemy.exc import SQLAlchemyError
    from app.modules.events.worker.runtime import EventWorker, WorkerHooks

    event, origin = traced_event()
    settings = worker_settings()
    with (
        socket.socket() as reservation,
        collector("success") as (endpoint, received, _, _),
    ):
        reservation.bind(
            ("127.0.0.1", 0)
        )  # Bound but not listening: deterministic refusal.
        if outcome == "transport_failure":
            settings = settings.model_copy(
                update={
                    "redis_url": SecretStr(
                        f"redis://127.0.0.1:{reservation.getsockname()[1]}/0"
                    )
                }
            )
        telemetry = worker_lifecycle.acquire(
            settings.model_copy(
                update={
                    "monitoring_enabled": True,
                    "monitoring_endpoint": endpoint,
                    "monitoring_export_timeout_seconds": 0.1,
                }
            )
        )

        async def run():
            async def lose(claim, message_id):
                async with AsyncSessionLocal() as session, session.begin():
                    await session.execute(
                        text(
                            "UPDATE event_deliveries SET claim_token=NULL,claim_owner=NULL,claimed_at=NULL,claim_expires_at=NULL WHERE id=:id"
                        ),
                        {"id": claim.delivery_id},
                    )

            worker = EventWorker(
                settings,
                AsyncSessionLocal,
                hooks=WorkerHooks(
                    after_publish=lose if outcome == "claim_lost" else None
                ),
            )
            if outcome == "observation_failure":

                async def broken(claim):
                    raise SQLAlchemyError(CANARY)

                monkeypatch.setattr(worker.event_service, "observe_publication", broken)
            claim = (
                await worker.event_service.claim_due_deliveries(
                    owner=worker.worker_id,
                    limit=1,
                    lease_seconds=30,
                    republish_after_seconds=60,
                )
            )[0]
            await worker.redis.open()
            try:
                assert await worker._publish_claim(claim, asyncio.Semaphore(1)) is (
                    outcome in {"transport_failure", "observation_failure"}
                )
            finally:
                await worker.redis.close()

        try:
            asyncio.run(run())
            telemetry.traces.force_flush()
        finally:
            worker_lifecycle.release(telemetry).wait(10)
            if outcome != "transport_failure":
                delete_owned_stream(settings)
        exported = spans(received)
        assert len(exported) == 1 and attrs(exported[0])["outcome"] == outcome
        assert_origin_link(exported[0], origin)
        assert CANARY not in json.dumps(received)
        row = delivery_rows(event.event_id)[0]
        assert row["status"] == "pending" and row["attempt_count"] == 0
        assert (row["published_at"] is not None) is (outcome == "published")


def test_http_command_to_restarted_worker_all_consumers(
    tmp_path, monkeypatch, auth_user
):
    from test_http_observability import instrumented_client
    from test_order_inventory import (
        create_restaurant,
        create_ingredient,
        create_menu_item,
        create_order,
        update_order,
    )
    from app.core.trace_context import parse_traceparent
    from sqlalchemy import select

    with collector("success") as (endpoint, received, _, _):
        with instrumented_client(monkeypatch, auth_user, endpoint) as (
            client,
            trace_id,
        ):
            restaurant = create_restaurant(client)
            create_ingredient(client, restaurant, name=CANARY, quantity="0")
            item = create_menu_item(client, restaurant)
            created = create_order(client, restaurant, item)
            assert created.status_code == 201
            order = created.json()["order_id"]
            for status in ("SUBMITTED", "ACCEPTED", "PREPARING", "READY", "COMPLETED"):
                assert update_order(client, order, status).status_code == 200
        with Session(engine) as session:
            origins = {
                str(row.event_id): parse_traceparent(row.traceparent)
                for row in session.scalars(select(OutboxEvent))
            }
        assert origins and all(
            ctx is not None and ctx.trace_id == int(trace_id, 16)
            for ctx in origins.values()
        )
        settings = worker_settings()
        first = start_process(tmp_path, settings, pause_at="after_claim")
        try:
            process_phase(first, "after_claim")
        finally:
            kill_process(first)
        log_path = tmp_path / "http-worker.jsonl"
        env = process_environment(settings)
        env.update(
            MONITORING_ENABLED="true",
            MONITORING_ENDPOINT=endpoint,
            MONITORING_EXPORT_TIMEOUT_SECONDS="0.1",
            MONITORING_SHUTDOWN_SECONDS="1",
        )
        with log_path.open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "app.worker"],
                cwd=BACKEND,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=log,
            )
            try:
                wait_for(
                    lambda: all(
                        all(
                            row["status"] == "succeeded"
                            for row in delivery_rows(event_id)
                        )
                        for event_id in origins
                    ),
                    timeout=25,
                )
                process.terminate()
                process.wait(timeout=10)
                assert process.returncode == 0
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                delete_owned_stream(settings)
        exported = [
            span
            for span in spans(received)
            if span["name"] in {"outbox publish", "consumer attempt"}
        ]
        assert {
            attrs(span)["consumer"]
            for span in exported
            if span["name"] == "consumer attempt"
        } == {"analytics", "alerts", "notification_sink"}
        for span in exported:
            assert_origin_link(span, origins[attrs(span)["event_id"]])
        assert CANARY not in json.dumps(received)
        assert CANARY not in log_path.read_text()
        assert all(
            json.loads(line).get("message")
            for line in log_path.read_text().splitlines()
        )


def test_legacy_pre_column_event_upgrade_and_real_worker(tmp_path):
    import os
    from uuid import uuid4

    organization, restaurant = create_scope()
    event_id, delivery_id = uuid4(), uuid4()
    assert os.environ["TEST_DATABASE_URL"].endswith("_test")

    def migrate(*args):
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND,
            env=dict(os.environ),
            capture_output=True,
            check=True,
        )

    try:
        legacy_revision = "c3d8e1f52a74"  # pragma: allowlist secret - public revision
        migrate("downgrade", legacy_revision)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO outbox_events(event_id,event_type,schema_version,organization_id,restaurant_id,aggregate_type,aggregate_id,aggregate_revision,occurred_at,correlation_id,payload) VALUES(:id,'order.submitted.v1',1,:org,:restaurant,'order','17',1,now(),'legacy-upgrade',CAST(:payload AS jsonb))"
                ),
                {
                    "id": event_id,
                    "org": organization,
                    "restaurant": restaurant,
                    "payload": json.dumps({"order_id": 17, "status": "SUBMITTED"}),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO event_deliveries(id,event_id,consumer_name) VALUES(:id,:event,'notification_sink')"
                ),
                {"id": delivery_id, "event": event_id},
            )
    finally:
        migrate("upgrade", "head")
    with Session(engine) as session:
        assert session.get(OutboxEvent, event_id).traceparent is None
    settings = worker_settings()
    state = start_process(tmp_path, settings, module=True)
    try:
        wait_for(
            lambda: delivery_rows(event_id)[0]["status"] == "succeeded", timeout=20
        )
    finally:
        from test_event_worker import stop_gracefully

        stop_gracefully(state)
        delete_owned_stream(settings)


def test_backlog_statement_timeout_recovers_without_stale_session():
    from sqlalchemy.exc import DBAPIError
    from time import monotonic

    event = append_event_for_test(create_scope())

    async def run():
        service = EventWorkerService(AsyncSessionLocal)
        with engine.begin() as lock:
            lock.execute(text("LOCK TABLE event_deliveries IN ACCESS EXCLUSIVE MODE"))
            started = monotonic()
            with pytest.raises(DBAPIError) as error:
                await service.backlog()
            assert getattr(error.value.orig, "sqlstate", None) == "57014"
            assert monotonic() - started < 3
        rows = await service.backlog()
        assert rows[0].depth == 1 and rows[0].state == "queued"

    asyncio.run(run())
    assert delivery_rows(event.event_id)[0]["status"] == "pending"


def test_worker_slow_collector_pressure_and_recovery(tmp_path):
    """Explicit pipe barrier fills the bounded SDK queue during blocked export."""
    from app.modules.notifications.repo.models import EventDiagnostic
    from sqlalchemy import select, func

    first, _ = traced_event()
    settings = worker_settings()
    log_path = tmp_path / "pressure.jsonl"
    with (
        collector("slow") as (endpoint, received, entered, release),
        log_path.open("w") as log,
    ):
        env = process_environment(settings)
        env.update(
            MONITORING_ENABLED="true",
            MONITORING_ENDPOINT=endpoint,
            MONITORING_QUEUE_SIZE="16",
            MONITORING_EXPORT_TIMEOUT_SECONDS="0.1",
            MONITORING_SHUTDOWN_SECONDS="1",
            EVENT_WORKER_TEST_REAL_CONSUMER="notification_sink",
            EVENT_WORKER_TEST_TELEMETRY_PRESSURE="1",
        )
        process = subprocess.Popen(
            [sys.executable, str(BACKEND / "tests/support/event_worker_process.py")],
            cwd=BACKEND,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        try:
            assert json.loads(process.stdout.readline())["phase"] == "pressure_ready"
            assert entered.wait(5)
            process.stdin.write("continue\n")
            process.stdin.flush()
            wait_for(
                lambda: delivery_rows(first.event_id)[0]["status"] == "succeeded",
                timeout=20,
            )
            wait_for(lambda: "telemetry_queue_full" in log_path.read_text(), timeout=5)
            release.set()
            second, origin = traced_event()
            wait_for(
                lambda: delivery_rows(second.event_id)[0]["status"] == "succeeded",
                timeout=20,
            )
            wait_for(
                lambda: any(
                    attrs(span).get("event_id") == str(second.event_id)
                    and attrs(span).get("outcome") == "consumer_committed"
                    for span in spans(received)
                ),
                timeout=10,
            )
            wait_for(lambda: references_drained(settings), timeout=10)
            process.terminate()
            process.wait(timeout=10)
            assert process.returncode == 0
            for span in spans(received):
                if attrs(span).get("event_id") == str(second.event_id):
                    assert_origin_link(span, origin)
            with Session(engine) as session:
                assert (
                    session.scalar(select(func.count()).select_from(EventDiagnostic))
                    == 2
                )
            assert CANARY not in log_path.read_text()
        finally:
            release.set()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()
            delete_owned_stream(settings)
