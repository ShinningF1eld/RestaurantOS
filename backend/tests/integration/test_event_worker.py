"""Real PostgreSQL/Redis and worker-process recovery acceptance evidence."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.db.models import Restaurant
from app.modules.events.domain.contracts import (
    OrderCompletedEvent,
    OrderCompletedPayload,
    OrderSubmittedEvent,
    OrderSubmittedPayload,
)
from app.modules.events.repo.models import EventDelivery
from app.modules.events.repo.models import EventReceipt
from app.modules.events.repo.worker_queries import (
    claim_due_deliveries as claim_delivery_rows,
)
from app.modules.events.service import append_event
from app.modules.events.worker.service import EventWorkerService
from app.modules.events.worker.redis import (
    WorkerFailureKind,
    WorkerRedisFailure,
    WorkerRedisTransport,
)
from app.modules.events.worker.runtime import EventWorker
from app.modules.events.worker.streams import EventStreams, GROUPS
from app.modules.tenancy.repo.models import Organization
from support.owned_redis import docker, owned_redis
from conftest import engine


BACKEND = Path(__file__).resolve().parents[2]


def worker_settings(**updates):
    return get_settings().model_copy(
        update={
            "redis_test_namespace": "event-worker-" + uuid4().hex,
            "event_worker_redis_operation_budget_ms": 500,
            "event_worker_redis_block_ms": 100,
            "event_worker_claim_batch_size": 1,
            "event_worker_relay_concurrency": 1,
            "event_worker_claim_lease_seconds": 2,
            "event_worker_recovery_scan_interval_ms": 100,
            "event_worker_recovery_batch_size": 10,
            "event_worker_republish_stall_seconds": 60,
            "event_worker_pending_idle_ms": 500,
            "event_worker_infra_backoff_initial_ms": 100,
            "event_worker_infra_backoff_max_ms": 500,
            "event_worker_shutdown_grace_seconds": 3,
            **updates,
        }
    )


def process_environment(settings, *, pause_at=None, redis_url=None):
    values = {
        "event_worker_redis_operation_budget_ms": "EVENT_WORKER_REDIS_OPERATION_BUDGET_MS",
        "event_worker_redis_block_ms": "EVENT_WORKER_REDIS_BLOCK_MS",
        "event_worker_redis_max_connections": "EVENT_WORKER_REDIS_MAX_CONNECTIONS",
        "event_worker_claim_batch_size": "EVENT_WORKER_CLAIM_BATCH_SIZE",
        "event_worker_relay_concurrency": "EVENT_WORKER_RELAY_CONCURRENCY",
        "event_worker_claim_lease_seconds": "EVENT_WORKER_CLAIM_LEASE_SECONDS",
        "event_worker_recovery_scan_interval_ms": "EVENT_WORKER_RECOVERY_SCAN_INTERVAL_MS",
        "event_worker_recovery_batch_size": "EVENT_WORKER_RECOVERY_BATCH_SIZE",
        "event_worker_republish_stall_seconds": "EVENT_WORKER_REPUBLISH_STALL_SECONDS",
        "event_worker_pending_idle_ms": "EVENT_WORKER_PENDING_IDLE_MS",
        "event_worker_infra_backoff_initial_ms": "EVENT_WORKER_INFRA_BACKOFF_INITIAL_MS",
        "event_worker_infra_backoff_max_ms": "EVENT_WORKER_INFRA_BACKOFF_MAX_MS",
        "event_worker_shutdown_grace_seconds": "EVENT_WORKER_SHUTDOWN_GRACE_SECONDS",
    }
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "REDIS_TEST_NAMESPACE": settings.redis_test_namespace,
        **{
            env_name: str(getattr(settings, field))
            for field, env_name in values.items()
        },
    }
    if redis_url:
        env["REDIS_URL"] = redis_url
    if pause_at:
        env["EVENT_WORKER_TEST_PAUSE_AT"] = pause_at
    else:
        env.pop("EVENT_WORKER_TEST_PAUSE_AT", None)
    return env


def create_scope():
    with Session(engine, expire_on_commit=False) as db, db.begin():
        organization = Organization(name="Worker tests", slug=f"worker-{uuid4().hex}")
        db.add(organization)
        db.flush()
        restaurant = Restaurant(name="Worker branch", organization_id=organization.id)
        db.add(restaurant)
        db.flush()
        return organization.id, restaurant.id


def append_event_for_test(scope, *, completed=False):
    organization_id, restaurant_id = scope
    order_id = uuid4().int % 2_000_000_000 + 1
    correlation_id = "worker-" + uuid4().hex
    if completed:
        event = OrderCompletedEvent(
            organization_id=organization_id,
            restaurant_id=restaurant_id,
            aggregate_id=str(order_id),
            aggregate_revision=1,
            occurred_at=datetime.now(UTC),
            correlation_id=correlation_id,
            payload=OrderCompletedPayload(
                order_id=order_id,
                total="12.50",
                created_at=datetime(2026, 10, 12, 5, 0),
            ),
        )
    else:
        event = OrderSubmittedEvent(
            organization_id=organization_id,
            restaurant_id=restaurant_id,
            aggregate_id=str(order_id),
            aggregate_revision=1,
            occurred_at=datetime.now(UTC),
            correlation_id=correlation_id,
            payload=OrderSubmittedPayload(order_id=order_id),
        )

    async def append():
        async with AsyncSessionLocal() as session, session.begin():
            await append_event(session, event)

    asyncio.run(append())
    return event


def delivery_rows(event_id: UUID):
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT id,consumer_name,status,attempt_count,published_at,"
                    "claim_token,claim_owner,claim_expires_at,next_attempt_at,"
                    "last_error_category FROM event_deliveries WHERE event_id=:event_id "
                    "ORDER BY consumer_name"
                ),
                {"event_id": event_id},
            )
            .mappings()
            .all()
        )


def wait_for(predicate, *, timeout=15, interval=0.025):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError("Timed out waiting for worker state")


def start_process(tmp_path, settings, *, pause_at=None, redis_url=None, module=False):
    command = (
        [sys.executable, "-m", "app.worker"]
        if module
        else [sys.executable, str(BACKEND / "tests/support/event_worker_process.py")]
    )
    stdout = subprocess.PIPE if pause_at else subprocess.DEVNULL
    stderr_file = (tmp_path / f"worker-{uuid4().hex}.log").open("w", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        command,
        cwd=BACKEND,
        env=process_environment(settings, pause_at=pause_at, redis_url=redis_url),
        stdout=stdout,
        stderr=stderr_file,
        text=True,
        creationflags=creationflags,
    )
    messages = queue.Queue()
    reader = None
    if pause_at:

        def read_messages():
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
            messages.put(None)

        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
    return process, messages, reader, stderr_file


def process_phase(process_state, phase, timeout=15):
    process, messages, *_ = process_state
    message = messages.get(timeout=timeout)
    if message is None:
        raise AssertionError(f"Worker process exited before {phase}")
    assert message["phase"] == phase
    return message


def kill_process(process_state):
    process = process_state[0]
    if process.poll() is None:
        process.kill()
        process.wait(timeout=10)
    _close_process_state(process_state)


def stop_gracefully(process_state):
    process = process_state[0]
    if process.poll() is None:
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=15)
        assert process.returncode == 0
    _close_process_state(process_state)


def _close_process_state(process_state):
    process, _messages, reader, stderr_file = process_state
    if process.stdout is not None:
        process.stdout.close()
    if reader is not None:
        reader.join(timeout=2)
    stderr_file.close()


def claim_expired(event_id: UUID):
    with engine.connect() as connection:
        return connection.scalar(
            text(
                "SELECT bool_and(claim_expires_at IS NULL OR claim_expires_at <= now()) "
                "FROM event_deliveries WHERE event_id=:event_id"
            ),
            {"event_id": event_id},
        )


def stream_entries(settings):
    async def read():
        redis = WorkerRedisTransport(settings)
        await redis.open()
        streams = EventStreams(redis)
        try:
            return await redis.execute("XRANGE", streams.stream, "-", "+")
        finally:
            await redis.close()

    return asyncio.run(read())


def delete_owned_stream(settings):
    async def delete():
        redis = WorkerRedisTransport(settings)
        await redis.open()
        try:
            await redis.execute("DEL", redis.stream_key())
        finally:
            await redis.close()

    asyncio.run(delete())


def test_real_worker_entrypoint_relays_reference_and_shuts_down_gracefully(
    tmp_path,
):
    scope = create_scope()
    event = append_event_for_test(scope)
    settings = worker_settings()
    process_state = start_process(tmp_path, settings, module=True)

    try:
        entries = wait_for(lambda: stream_entries(settings) or None)
        assert len(entries) == 1
        row = wait_for(
            lambda: (
                delivery
                if (delivery := delivery_rows(event.event_id)[0])["published_at"]
                is not None
                else None
            )
        )
        message_id, fields = entries[0]
        assert fields == {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "schema_version": "1",
            "correlation_id": event.correlation_id,
        }
        assert not {"payload", "organization_id", "restaurant_id"}.intersection(fields)
        stop_gracefully(process_state)
        rows = delivery_rows(event.event_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "pending"
        assert rows[0]["attempt_count"] == 0
        assert row["published_at"] is not None
    finally:
        kill_process(process_state)
        delete_owned_stream(settings)


def test_worker_process_crash_after_claim_recovers_expired_delivery(tmp_path):
    event = append_event_for_test(create_scope())
    settings = worker_settings()
    paused = start_process(tmp_path, settings, pause_at="after_claim")
    try:
        process_phase(paused, "after_claim")
        before = delivery_rows(event.event_id)[0]
        assert before["claim_token"] is not None
        assert before["published_at"] is None
        kill_process(paused)
        wait_for(lambda: claim_expired(event.event_id))

        restarted = start_process(tmp_path, settings, module=True)
        try:
            entries = wait_for(lambda: stream_entries(settings) or None)
            assert len(entries) == 1
            assert entries[0][1]["event_id"] == str(event.event_id)
            after = wait_for(
                lambda: (
                    row
                    if (row := delivery_rows(event.event_id)[0])["published_at"]
                    is not None
                    else None
                )
            )
            assert after["published_at"] is not None
            assert after["attempt_count"] == 0
            stop_gracefully(restarted)
        finally:
            kill_process(restarted)
    finally:
        kill_process(paused)
        delete_owned_stream(settings)


def test_worker_process_crash_after_xadd_republishes_original_event_id(tmp_path):
    event = append_event_for_test(create_scope())
    settings = worker_settings()
    paused = start_process(tmp_path, settings, pause_at="after_publish")
    try:
        process_phase(paused, "after_publish")
        before = delivery_rows(event.event_id)[0]
        first = stream_entries(settings)
        assert before["published_at"] is None
        assert len(first) == 1
        assert first[0][1]["event_id"] == str(event.event_id)
        kill_process(paused)
        wait_for(lambda: claim_expired(event.event_id))

        restarted = start_process(tmp_path, settings, module=True)
        try:
            entries = wait_for(
                lambda: (
                    stream_entries(settings)
                    if len(stream_entries(settings)) >= 2
                    else None
                )
            )
            assert len(entries) == 2
            assert len({entry[0] for entry in entries}) == 2
            assert {entry[1]["event_id"] for entry in entries} == {str(event.event_id)}
            after = wait_for(
                lambda: (
                    row
                    if (row := delivery_rows(event.event_id)[0])["published_at"]
                    is not None
                    else None
                )
            )
            assert after["published_at"] is not None
            assert after["attempt_count"] == 0
            stop_gracefully(restarted)
        finally:
            kill_process(restarted)
    finally:
        kill_process(paused)
        delete_owned_stream(settings)


def test_consumer_groups_route_independently_reclaim_own_pel_and_rebuild_stream(
    tmp_path,
):
    event = append_event_for_test(create_scope(), completed=True)
    settings = worker_settings()
    first = start_process(tmp_path, settings, module=True)
    try:
        # Either subscribed delivery's reference can complete analytics before
        # its own relay turn, so one or two initial transport entries are valid.
        wait_for(lambda: len(stream_entries(settings)) >= 1)

        async def group_state():
            redis = WorkerRedisTransport(settings)
            await redis.open()
            streams = EventStreams(redis)
            try:
                counts = {group: await streams.pending_count(group) for group in GROUPS}
                owners = {
                    group: await streams.pending_page(group, cursor="-", count=10)
                    for group in GROUPS
                }
                groups = await redis.execute("XINFO", "GROUPS", streams.stream)
                latest = await redis.execute(
                    "XREVRANGE", streams.stream, "+", "-", "COUNT", 1
                )
                progress = {row["name"]: row["last-delivered-id"] for row in groups}
                latest_id = latest[0][0] if latest else None
                return counts, owners, progress, latest_id
            finally:
                await redis.close()

        def all_groups_read():
            state = asyncio.run(group_state())
            return (
                state
                if state[0]["analytics"] == 0
                and state[0]["notification_sink"] >= 1
                and state[0]["alerts"] == 0
                and all(state[2][group] == state[3] for group in GROUPS)
                else None
            )

        counts, owners, _, _ = wait_for(all_groups_read)
        assert counts["alerts"] == 0
        assert all(
            pending.owner
            for group in ("notification_sink",)
            for pending in owners[group]
        )
        # T6 analytics is complete/ACKed; the unimplemented sink still needs
        # pending recovery. Redis loss must not rerun the completed consumer.
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(EventReceipt)
                    .where(
                        EventReceipt.event_id == event.event_id,
                        EventReceipt.consumer_name == "analytics",
                    )
                )
                == 1
            )
        old_owner = owners["notification_sink"][0].owner
        kill_process(first)
        published_count = len(stream_entries(settings))
        assert published_count in (1, 2)

        second = start_process(tmp_path, settings, module=True)
        try:

            def changed_owner():
                latest_counts, latest_owners, _, _ = asyncio.run(group_state())
                pending = latest_owners["notification_sink"]
                return (
                    (
                        latest_counts,
                        latest_owners,
                    )
                    if pending
                    and latest_counts["notification_sink"] == published_count
                    and all(entry.owner != old_owner for entry in pending)
                    else None
                )

            counts, owners = wait_for(changed_owner)
            assert counts["analytics"] == 0
            assert counts["notification_sink"] == published_count
            assert owners["notification_sink"][0].owner != old_owner
            assert len(stream_entries(settings)) == published_count
            kill_process(second)

            # Deleting this one test-owned stream models Redis content/group loss.
            delete_owned_stream(settings)
            third = start_process(tmp_path, settings, module=True)
            try:
                rebuilt = wait_for(
                    lambda: (
                        stream_entries(settings)
                        if len(stream_entries(settings)) >= 1
                        else None
                    )
                )
                assert len(rebuilt) == 1
                assert {entry[1]["event_id"] for entry in rebuilt} == {
                    str(event.event_id)
                }
                with engine.connect() as connection:
                    assert (
                        connection.scalar(
                            select(func.count())
                            .select_from(EventReceipt)
                            .where(
                                EventReceipt.event_id == event.event_id,
                                EventReceipt.consumer_name == "analytics",
                            )
                        )
                        == 1
                    )
                stop_gracefully(third)
            finally:
                kill_process(third)
        finally:
            kill_process(second)
    finally:
        kill_process(first)
        delete_owned_stream(settings)


@pytest.mark.parametrize(
    "failure_point,expected_ack_calls",
    [
        ("postgres_read", 1),
        ("xack_before_execution", 2),
        ("xack_after_execution", 1),
    ],
)
def test_same_consumer_retries_transient_pending_reference_failures(
    failure_point, expected_ack_calls, monkeypatch
):
    event = append_event_for_test(create_scope())
    settings = worker_settings(event_worker_infra_backoff_initial_ms=500)

    async def consume_until_recovered():
        worker = EventWorker(settings, AsyncSessionLocal, worker_id="same-consumer")
        stop = asyncio.Event()
        first_failure = asyncio.Event()
        recovered = asyncio.Event()
        load_calls = 0
        ack_calls = 0
        original_load = worker.execution.execute
        original_ack = worker.streams.acknowledge
        original_pending_reference = worker.streams.pending_reference

        async def fail_postgres_read_once(**arguments):
            nonlocal load_calls
            load_calls += 1
            if failure_point == "postgres_read" and load_calls == 1:
                first_failure.set()
                raise SQLAlchemyError("injected transient database failure")
            return await original_load(**arguments)

        async def fail_ack_once(group, message_id):
            nonlocal ack_calls
            ack_calls += 1
            if failure_point == "xack_before_execution" and ack_calls == 1:
                first_failure.set()
                raise WorkerRedisFailure(WorkerFailureKind.CONNECTION)
            if failure_point == "xack_after_execution" and ack_calls == 1:
                acknowledged = await original_ack(group, message_id)
                assert acknowledged
                first_failure.set()
                raise WorkerRedisFailure(WorkerFailureKind.CONNECTION)
            acknowledged = await original_ack(group, message_id)
            if acknowledged:
                recovered.set()
            return acknowledged

        async def observe_ambiguous_ack(group, consumer, message_id):
            pending = await original_pending_reference(group, consumer, message_id)
            if failure_point == "xack_after_execution" and pending is None:
                recovered.set()
            return pending

        monkeypatch.setattr(worker.execution, "execute", fail_postgres_read_once)
        monkeypatch.setattr(worker.streams, "acknowledge", fail_ack_once)
        monkeypatch.setattr(worker.streams, "pending_reference", observe_ambiguous_ack)
        task = None
        try:
            await worker.redis.open()
            await worker.streams.ensure_groups()
            original_message_id = await worker.redis.execute(
                "XADD",
                worker.streams.stream,
                "*",
                "event_id",
                str(event.event_id),
                "event_type",
                event.event_type,
                "schema_version",
                str(event.schema_version),
                "correlation_id",
                event.correlation_id,
            )
            task = asyncio.create_task(worker._consumer_loop("alerts", stop))
            await asyncio.wait_for(first_failure.wait(), timeout=5)
            pending_after_failure = await worker.streams.pending_page(
                "alerts", cursor="-", count=10
            )
            if failure_point == "xack_after_execution":
                assert pending_after_failure == []
            else:
                assert len(pending_after_failure) == 1
                assert pending_after_failure[0].owner == "same-consumer.alerts"

            await asyncio.wait_for(recovered.wait(), timeout=5)
            assert await worker.streams.pending_count("alerts") == 0
            entries = await worker.redis.execute(
                "XRANGE", worker.streams.stream, "-", "+"
            )
            assert len(entries) == 1
            assert entries[0][0] == original_message_id
            assert ack_calls == expected_ack_calls
            if failure_point == "postgres_read":
                assert load_calls == 2
        finally:
            stop.set()
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await worker.redis.close()

    try:
        asyncio.run(consume_until_recovered())
    finally:
        delete_owned_stream(settings)


def test_physical_redis_restart_recreates_groups_from_postgres(tmp_path):
    event = append_event_for_test(create_scope())
    with owned_redis() as (container, port):
        redis_url = f"redis://127.0.0.1:{port}/0"
        settings = worker_settings(redis_url=SecretStr(redis_url))
        first = start_process(tmp_path, settings, module=True, redis_url=redis_url)
        try:
            before = wait_for(lambda: stream_entries(settings) or None)
            assert len(before) == 1
            assert before[0][1]["event_id"] == str(event.event_id)

            async def sink_pending():
                redis = WorkerRedisTransport(settings)
                await redis.open()
                try:
                    return await EventStreams(redis).pending_count("notification_sink")
                finally:
                    await redis.close()

            wait_for(lambda: asyncio.run(sink_pending()) >= 1)
            published = wait_for(
                lambda: (
                    row
                    if (row := delivery_rows(event.event_id)[0])["published_at"]
                    is not None
                    else None
                )
            )
            assert published["attempt_count"] == 0
            kill_process(first)

            docker("restart", container)
            wait_for(
                lambda: docker("exec", container, "redis-cli", "ping") == "PONG",
                timeout=20,
            )

            restarted = start_process(
                tmp_path, settings, module=True, redis_url=redis_url
            )
            try:
                after = wait_for(lambda: stream_entries(settings) or None)
                assert len(after) == 1
                assert after[0][1]["event_id"] == str(event.event_id)
                observed = wait_for(
                    lambda: (
                        row
                        if (row := delivery_rows(event.event_id)[0])["published_at"]
                        is not None
                        else None
                    )
                )
                assert observed["published_at"] is not None

                async def rebuilt_groups():
                    redis = WorkerRedisTransport(settings)
                    await redis.open()
                    streams = EventStreams(redis)
                    try:
                        await streams.ensure_groups()
                        return await redis.execute("XINFO", "GROUPS", streams.stream)
                    finally:
                        await redis.close()

                group_rows = wait_for(lambda: asyncio.run(rebuilt_groups()) or None)
                assert {row["name"] for row in group_rows} == set(GROUPS)
                stop_gracefully(restarted)
            finally:
                kill_process(restarted)
        finally:
            kill_process(first)


def test_worker_repository_stages_claim_inside_caller_transaction():
    event = append_event_for_test(create_scope())

    async def claim_inside_transaction():
        async with AsyncSessionLocal() as session:
            with pytest.raises(RuntimeError, match="caller transaction"):
                await claim_delivery_rows(
                    session,
                    owner="transaction-contract-worker",
                    limit=1,
                    lease_seconds=5,
                    republish_after_seconds=60,
                )

            async with session.begin():
                claims = await claim_delivery_rows(
                    session,
                    owner="transaction-contract-worker",
                    limit=1,
                    lease_seconds=5,
                    republish_after_seconds=60,
                )
                assert session.in_transaction()
                assert len(claims) == 1
                with engine.connect() as connection:
                    uncommitted_token = connection.scalar(
                        text(
                            "SELECT claim_token FROM event_deliveries "
                            "WHERE event_id=:event_id AND consumer_name=:consumer"
                        ),
                        {
                            "event_id": event.event_id,
                            "consumer": claims[0].consumer_name,
                        },
                    )
                assert uncommitted_token is None
                return claims[0]

    claim = asyncio.run(claim_inside_transaction())
    rows = delivery_rows(event.event_id)
    owned = next(row for row in rows if row["consumer_name"] == claim.consumer_name)
    assert owned["claim_token"] == claim.claim_token
    assert owned["claim_owner"] == "transaction-contract-worker"


def test_two_claimants_expiry_and_old_claim_fencing():
    event = append_event_for_test(create_scope())
    event_service = EventWorkerService(AsyncSessionLocal)

    async def race_claimants():
        barrier = asyncio.Barrier(2)

        async def claim(owner):
            await barrier.wait()
            return await event_service.claim_due_deliveries(
                owner=owner,
                limit=1,
                lease_seconds=5,
                republish_after_seconds=60,
            )

        return await asyncio.gather(claim("relay-a"), claim("relay-b"))

    first, second = asyncio.run(race_claimants())
    assert len(first) + len(second) == 1
    old_claim = (first or second)[0]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE event_deliveries SET claim_expires_at=now()-interval '1 second' "
                "WHERE id=:id"
            ),
            {"id": old_claim.delivery_id},
        )

    async def reclaim():
        return await event_service.claim_due_deliveries(
            owner="relay-new",
            limit=1,
            lease_seconds=5,
            republish_after_seconds=60,
        )

    newer = asyncio.run(reclaim())[0]
    assert newer.event_id == event.event_id
    assert newer.claim_token != old_claim.claim_token
    assert asyncio.run(event_service.observe_publication(old_claim)) is False
    assert asyncio.run(event_service.observe_publication(newer)) is True
    rows = delivery_rows(event.event_id)
    assert rows[0]["published_at"] is not None
    assert rows[0]["claim_token"] is None


def test_early_stream_reference_respects_persisted_next_attempt_time():
    event = append_event_for_test(create_scope(), completed=True)
    settings = worker_settings()

    async def route_early_reference():
        redis = WorkerRedisTransport(settings)
        await redis.open()
        streams = EventStreams(redis)
        worker = EventWorker(settings, AsyncSessionLocal, worker_id="early-reader")
        worker.redis = redis
        worker.streams = streams
        try:
            await streams.ensure_groups()
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE event_deliveries SET next_attempt_at=now()+interval '1 hour' "
                        "WHERE event_id=:event_id AND consumer_name='analytics'"
                    ),
                    {"event_id": event.event_id},
                )
            await redis.execute(
                "XADD",
                streams.stream,
                "*",
                "event_id",
                str(event.event_id),
                "event_type",
                event.event_type,
                "schema_version",
                "1",
                "correlation_id",
                event.correlation_id,
            )
            analytics = (
                await streams.read_new(
                    "analytics", "early-analytics", count=10, block_ms=100
                )
            )[0]
            alerts = (
                await streams.read_new("alerts", "early-alerts", count=10, block_ms=100)
            )[0]
            await worker._route_message(analytics, "analytics")
            await worker._route_message(alerts, "alerts")
            return (
                await streams.pending_count("analytics"),
                await streams.pending_count("alerts"),
            )
        finally:
            await redis.close()

    try:
        analytics_pending, alerts_pending = asyncio.run(route_early_reference())
        assert analytics_pending == 1
        assert alerts_pending == 0
        analytics_row = next(
            row
            for row in delivery_rows(event.event_id)
            if row["consumer_name"] == "analytics"
        )
        assert analytics_row["status"] == "pending"
        assert analytics_row["attempt_count"] == 0
    finally:
        delete_owned_stream(settings)


def test_worker_redis_outage_recovers_without_spending_delivery_attempts(tmp_path):
    event = append_event_for_test(create_scope())
    settings = worker_settings()
    unavailable = start_process(
        tmp_path,
        settings,
        redis_url="redis://127.0.0.1:1/0",
    )
    try:
        wait_for(
            lambda: (
                delivery_rows(event.event_id)[0]["last_error_category"]
                in {"redis_connection", "redis_timeout"}
            )
        )
        row = delivery_rows(event.event_id)[0]
        assert row["status"] == "pending"
        assert row["attempt_count"] == 0
        kill_process(unavailable)
        wait_for(lambda: claim_expired(event.event_id))

        recovered = start_process(tmp_path, settings, module=True)
        try:
            entries = wait_for(lambda: stream_entries(settings) or None)
            assert len(entries) == 1
            assert entries[0][1]["event_id"] == str(event.event_id)
            recovered_row = wait_for(
                lambda: (
                    row
                    if (row := delivery_rows(event.event_id)[0])["published_at"]
                    is not None
                    else None
                )
            )
            assert recovered_row["attempt_count"] == 0
            assert get_settings().redis_operation_budget_ms == 100
            stop_gracefully(recovered)
        finally:
            kill_process(recovered)
    finally:
        kill_process(unavailable)
        delete_owned_stream(settings)


def test_relay_claim_batch_stays_bounded_with_significant_backlog():
    scope = create_scope()
    events = [append_event_for_test(scope) for _ in range(25)]
    event_service = EventWorkerService(AsyncSessionLocal)

    async def claim_batch():
        return await event_service.claim_due_deliveries(
            owner="bounded-backlog-worker",
            limit=10,
            lease_seconds=30,
            republish_after_seconds=60,
        )

    claims = asyncio.run(claim_batch())
    assert len(claims) == 10
    assert {claim.event_id for claim in claims}.issubset(
        {event.event_id for event in events}
    )
    with engine.connect() as connection:
        claimed = connection.scalar(
            select(func.count())
            .select_from(EventDelivery)
            .where(EventDelivery.claim_owner == "bounded-backlog-worker")
        )
    assert claimed == 10
