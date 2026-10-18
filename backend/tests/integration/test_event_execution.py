"""Atomic effects, duplicate overlap, retries, operator recovery and real crashes."""

import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.database import AsyncSessionLocal
from app.modules.events.domain.retries import RetryPolicy
from app.modules.events.execution import (
    ConsumerExecutionService,
    DependencyUnavailable,
    EventTransientFailure,
    ExecutionHooks,
)
from app.modules.events.operator import EventOperatorService
from app.modules.events.repo.models import (
    EventDeliveryAttempt,
    EventDeliveryReplay,
    EventReceipt,
)
from app.modules.events.worker.redis import WorkerRedisTransport
from app.modules.events.worker.streams import EventStreams
from app.modules.tenancy.repo.models import Organization
from conftest import engine
from test_event_worker import (
    BACKEND,
    append_event_for_test,
    create_scope,
    delete_owned_stream,
    delivery_rows,
    kill_process,
    process_environment,
    process_phase,
    start_process,
    wait_for,
    worker_settings,
)


REDACTION_URL = "redis://user:secret@host"  # pragma: allowlist secret


def reference(event):
    return {
        key: str(getattr(event, key))
        for key in ("event_id", "event_type", "schema_version", "correlation_id")
    }


async def effect(session, event):
    # A real, uniquely keyed durable DB effect, exclusively in test wiring.
    session.add(
        Organization(name="T5 test effect", slug="effect-" + str(event.event_id))
    )
    await session.flush()
    return "processed"


def service(handler=effect, **kwargs):
    return ConsumerExecutionService(
        AsyncSessionLocal,
        registry={
            "analytics": handler,
            "alerts": None,
            "notification_sink": handler,
        },
        **kwargs,
    )


async def execute(execution, event, consumer="notification_sink", **kwargs):
    return await execution.execute(
        event_id=event.event_id,
        consumer=consumer,
        reference=reference(event),
        worker_id="test-worker",
        **kwargs,
    )


def count(model):
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(model))


def effect_count(event):
    with engine.connect() as connection:
        return connection.scalar(
            select(func.count())
            .select_from(Organization)
            .where(Organization.slug == "effect-" + str(event.event_id))
        )


def test_duplicate_overlap_serializes_and_commits_effect_receipt_together():
    event = append_event_for_test(create_scope())

    async def scenario():
        inside = asyncio.Event()
        release = asyncio.Event()

        async def hold(claim):
            inside.set()
            await release.wait()

        execution = service(hooks=ExecutionHooks(before_commit=hold))
        first = asyncio.create_task(execute(execution, event))
        await asyncio.wait_for(inside.wait(), 5)
        # The effect, receipt and delivery success are flushed but uncommitted.
        assert effect_count(event) == 0
        assert count(EventReceipt) == 0
        # Actual competing SELECT FOR UPDATE SKIP LOCKED while first holds lock.
        second = await asyncio.wait_for(execute(service(), event), 5)
        assert second.outcome == "delivery_missing_or_busy"
        release.set()
        assert (await first).acknowledge
        assert (
            await execute(service(), event)
        ).outcome == "durable_receipt_acknowledged"

    asyncio.run(scenario())
    assert (
        effect_count(event) == count(EventReceipt) == count(EventDeliveryAttempt) == 1
    )


def test_failure_rolls_back_effect_and_skip_has_durable_receipt():
    event = append_event_for_test(create_scope())

    async def fail(session, event):
        await effect(session, event)
        raise EventTransientFailure("sensitive customer payload")

    assert not asyncio.run(execute(service(fail), event)).acknowledge
    assert effect_count(event) == count(EventReceipt) == 0
    with engine.begin() as connection:
        connection.execute(text("UPDATE event_deliveries SET next_attempt_at=now()"))

    async def skip(session, event):
        return "skipped"

    assert asyncio.run(execute(service(skip), event)).acknowledge
    with engine.connect() as connection:
        assert connection.scalar(select(EventReceipt.outcome)) == "skipped"
    assert effect_count(event) == 0


def test_eight_attempts_restart_due_times_isolation_and_replay_provenance():
    event = append_event_for_test(create_scope(), completed=True)
    now = datetime.now(UTC) + timedelta(seconds=1)

    async def fail(session, event):
        raise EventTransientFailure(REDACTION_URL + " customer payload")

    async def scenario():
        nonlocal now
        assert (
            await execute(service(clock=lambda: now), event, "analytics")
        ).acknowledge
        for number in range(1, 9):
            execution = service(fail, clock=lambda: now, jitter=lambda: 0)
            result = await execute(execution, event)
            row = delivery_rows(event.event_id)[1]
            assert row["attempt_count"] == number
            assert result.acknowledge is (number == 8)
            if number < 8:
                assert row["next_attempt_at"] == now + timedelta(
                    seconds=RetryPolicy().delay_seconds(number, 0)
                )
                # New service instance proves persisted scheduling survives restart.
                assert (
                    await execute(service(fail, clock=lambda: now), event)
                ).outcome == "subscribed_delivery_not_due"
                now = row["next_attempt_at"]
        operator = EventOperatorService(AsyncSessionLocal)
        failed_id = delivery_rows(event.event_id)[1]["id"]
        inspected = await operator.inspect(failed_id)
        assert len(inspected["attempts"]) == 8
        assert "secret" not in json.dumps(inspected)
        status = await operator.status()
        sink = next(
            row for row in status["consumers"] if row["consumer"] == "notification_sink"
        )
        assert sink["failed"] == 1 and sink["retained_attempts"] == 8
        replay_id = await operator.replay(failed_id, reason="Fixed handler")
        with engine.connect() as connection:
            replay = (
                connection.execute(select(EventDeliveryReplay.__table__))
                .mappings()
                .one()
            )
            assert replay["operator"] == connection.scalar(text("SELECT session_user"))
            assert replay["replay_id"] == replay_id
            assert replay["correlation_id"] == event.correlation_id
            assert replay["reason"] == "Fixed handler"
        with pytest.raises(ValueError):
            await operator.replay(failed_id, reason="Duplicate request")

        # A skip represents repaired handling with a durable intentional outcome.
        async def skip(session, event):
            return "skipped"

        assert (await execute(service(skip, clock=lambda: now), event)).acknowledge
        with pytest.raises(ValueError):
            await operator.replay(failed_id, reason="Already succeeded")
        with pytest.raises(ValueError):
            await operator.replay(uuid4(), reason="Missing target")
        with pytest.raises(ValueError):
            await operator.replay(failed_id, reason="  ")
        assert (await execute(service(), event, "analytics")).acknowledge
        assert effect_count(event) == 1
        assert count(EventReceipt) == 2
        assert count(EventDeliveryAttempt) == 10

    asyncio.run(scenario())


def test_shared_outages_refund_allowance_and_constraints_do_not_pause_group():
    event = append_event_for_test(create_scope())
    now = datetime.now(UTC) + timedelta(seconds=1)

    async def outage(session, event):
        await effect(session, event)
        raise DependencyUnavailable("secret")

    async def scenario():
        nonlocal now
        for _ in range(10):
            with pytest.raises(DependencyUnavailable):
                await execute(service(outage, clock=lambda: now), event)
            assert delivery_rows(event.event_id)[0]["attempt_count"] == 0
            assert effect_count(event) == 0
            now += timedelta(seconds=2)
        assert count(EventDeliveryAttempt) == 10

        async def constraint(session, event):
            # Real PostgreSQL event-caused NOT NULL violation.
            session.add(Organization(name=None, slug="invalid"))
            await session.flush()
            return "processed"

        assert (
            await execute(service(constraint, clock=lambda: now), event)
        ).acknowledge
        assert (
            delivery_rows(event.event_id)[0]["last_error_category"]
            == "event_constraint"
        )
        assert (await execute(service(clock=lambda: now), good_event)).acknowledge

    good_event = append_event_for_test(create_scope())
    asyncio.run(scenario())
    assert effect_count(good_event) == 1


def test_missing_handler_and_conflicting_references_do_not_spend_attempts():
    event = append_event_for_test(create_scope())

    async def scenario():
        execution = ConsumerExecutionService(
            AsyncSessionLocal,
            registry={"analytics": None, "alerts": None, "notification_sink": None},
        )
        assert (await execute(execution, event)).outcome == "handler_unavailable"
        conflicting = {**reference(event), "correlation_id": "forged"}
        assert (
            await service().execute(
                event_id=event.event_id,
                consumer="notification_sink",
                reference=conflicting,
                worker_id="test",
            )
        ).outcome == "reference_conflict"
        assert (
            await service().execute(
                event_id=uuid4(),
                consumer="notification_sink",
                reference={},
                worker_id="test",
            )
        ).outcome == "event_not_found"

    asyncio.run(scenario())
    assert count(EventDeliveryAttempt) == count(EventReceipt) == 0


@pytest.mark.parametrize("invalid", ["payload", "version"])
def test_invalid_stored_contracts_fail_immediately_and_remain_inspectable(invalid):
    event = append_event_for_test(create_scope())
    # Model old-version/invalid durable facts in the disposable DB only. Restore
    # all constraints and immutable trigger in the same transaction afterward.
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE outbox_events DISABLE TRIGGER trg_outbox_events_immutable"
            )
        )
        if invalid == "payload":
            connection.execute(text("UPDATE outbox_events SET payload='{}'::jsonb"))
        else:
            connection.execute(
                text(
                    "ALTER TABLE outbox_events DROP CONSTRAINT ck_outbox_events_version"
                )
            )
            connection.execute(text("UPDATE outbox_events SET schema_version=2"))
        connection.execute(
            text("ALTER TABLE outbox_events ENABLE TRIGGER trg_outbox_events_immutable")
        )
    try:
        ref = reference(event)
        if invalid == "version":
            ref["schema_version"] = "2"

        async def scenario():
            result = await service().execute(
                event_id=event.event_id,
                consumer="notification_sink",
                reference=ref,
                worker_id="test",
            )
            assert result.acknowledge
            assert result.outcome == (
                "invalid_payload" if invalid == "payload" else "unsupported_version"
            )
            assert (
                await EventOperatorService(AsyncSessionLocal).inspect(
                    delivery_rows(event.event_id)[0]["id"]
                )
            )["status"] == "failed"

        asyncio.run(scenario())
        assert count(EventDeliveryAttempt) == 1
        assert effect_count(event) == count(EventReceipt) == 0
    finally:
        if invalid == "version":
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE outbox_events DISABLE TRIGGER trg_outbox_events_immutable"
                    )
                )
                connection.execute(text("UPDATE outbox_events SET schema_version=1"))
                connection.execute(
                    text(
                        "ALTER TABLE outbox_events ADD CONSTRAINT ck_outbox_events_version CHECK (schema_version=1)"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE outbox_events ENABLE TRIGGER trg_outbox_events_immutable"
                    )
                )


def test_expired_claim_is_fenced_and_limit_survives_worker_restart():
    event = append_event_for_test(create_scope())
    now = datetime.now(UTC) + timedelta(seconds=1)

    async def scenario():
        nonlocal now
        execution = service(clock=lambda: now, lease_seconds=1, policy=RetryPolicy(2))
        first = await execution._start(
            event.event_id, "notification_sink", reference(event), "old-worker"
        )
        now += timedelta(seconds=2)
        assert await execution.recover_expired(limit=10) == 1
        second = await execution._start(
            event.event_id, "notification_sink", reference(event), "new-worker"
        )
        assert (await execution._effect(first)).outcome == "claim_superseded"
        now += timedelta(seconds=2)
        restarted = service(clock=lambda: now, policy=RetryPolicy(2))
        assert await restarted.recover_expired(limit=10) == 1
        assert (await restarted._effect(second)).outcome == "claim_superseded"
        assert delivery_rows(event.event_id)[0]["status"] == "failed"
        assert delivery_rows(event.event_id)[0]["attempt_count"] == 2

    asyncio.run(scenario())
    assert count(EventReceipt) == effect_count(event) == 0


@pytest.mark.parametrize(
    "phase,expected_before", [("before_commit", 0), ("after_commit", 1)]
)
def test_actual_worker_crash_before_commit_and_before_ack(
    tmp_path, monkeypatch, phase, expected_before
):
    event = append_event_for_test(create_scope())
    settings = worker_settings()
    monkeypatch.setenv("EVENT_WORKER_TEST_EFFECTS", "1")
    process = start_process(tmp_path, settings, pause_at=phase)
    try:
        process_phase(process, phase)
        assert effect_count(event) == count(EventReceipt) == expected_before
    finally:
        kill_process(process)
    restarted = start_process(tmp_path, settings)
    try:
        wait_for(lambda: delivery_rows(event.event_id)[0]["status"] == "succeeded")

        async def acknowledged():
            redis = WorkerRedisTransport(settings)
            await redis.open()
            try:
                streams = EventStreams(redis)
                return await streams.pending_count("notification_sink") == 0
            finally:
                await redis.close()

        wait_for(lambda: asyncio.run(acknowledged()))
        assert effect_count(event) == count(EventReceipt) == 1
        assert count(EventDeliveryAttempt) == (2 if phase == "before_commit" else 1)
    finally:
        kill_process(restarted)


def test_cli_status_inspect_replay_and_redaction(tmp_path):
    event = append_event_for_test(create_scope())

    async def poison(session, event):
        raise IntegrityError(
            "secret statement",
            {},
            Exception(REDACTION_URL),
        )

    asyncio.run(execute(service(poison), event))
    delivery_id = str(delivery_rows(event.event_id)[0]["id"])
    env = process_environment(worker_settings())

    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "app.modules.events.cli", *args],
            cwd=BACKEND,
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
        )

    inspected = cli("inspect", delivery_id)
    assert inspected.returncode == 0, inspected.stderr
    assert "secret" not in inspected.stdout + inspected.stderr
    assert json.loads(inspected.stdout)["last_error_category"] == "event_constraint"
    status = cli("status")
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["stream_size"] == 0
    replayed = cli(
        "replay", delivery_id, "--reason", "Repaired secret-sensitive detail"
    )
    assert replayed.returncode == 0, replayed.stderr
    assert "secret" not in replayed.stdout + replayed.stderr
    assert cli("replay", delivery_id, "--reason", "again").returncode == 1
    invalid = cli("inspect", "redis://secret")
    assert invalid.returncode != 0 and "secret" not in invalid.stderr
    inspected = cli("inspect", delivery_id)
    assert "secret" not in inspected.stdout + inspected.stderr
    assert json.loads(inspected.stdout)["replays"][0]["reason_recorded"]


def test_worker_groups_isolate_shared_outage_and_ack_ambiguity(monkeypatch):
    event = append_event_for_test(create_scope(), completed=True)
    settings = worker_settings()

    async def scenario():
        from app.modules.events.worker.redis import (
            WorkerRedisFailure,
            WorkerFailureKind,
        )
        from app.modules.events.worker.runtime import EventWorker
        from app.modules.events.worker.streams import StreamMessage

        async def outage(session, event):
            raise DependencyUnavailable()

        execution = ConsumerExecutionService(
            AsyncSessionLocal,
            registry={
                "analytics": effect,
                "alerts": None,
                "notification_sink": outage,
            },
        )
        worker = EventWorker(settings, AsyncSessionLocal, execution=execution)
        await worker.redis.open()
        stop = asyncio.Event()
        tasks = []
        original_ack = worker.streams.acknowledge
        ack_calls = 0

        async def ambiguous_ack(group, message_id):
            nonlocal ack_calls
            ack_calls += 1
            if group == "analytics" and ack_calls == 1:
                raise WorkerRedisFailure(WorkerFailureKind.CONNECTION)
            return await original_ack(group, message_id)

        monkeypatch.setattr(worker.streams, "acknowledge", ambiguous_ack)
        try:
            await worker.streams.ensure_groups()
            fields = reference(event)
            message_id = await worker.redis.execute(
                "XADD",
                worker.streams.stream,
                "*",
                *(part for pair in fields.items() for part in pair),
            )
            # Both groups receive the same committed fact independently.
            tasks = [
                asyncio.create_task(worker._consumer_loop(group, stop))
                for group in ("analytics", "notification_sink")
            ]

            async def completed():
                while True:
                    rows = delivery_rows(event.event_id)
                    if (
                        rows[0]["status"] == "succeeded"
                        and rows[1]["last_error_category"] == "dependency_unavailable"
                        and ack_calls >= 2
                    ):
                        return
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(completed(), 10)
            assert delivery_rows(event.event_id)[0]["attempt_count"] == 1
            assert effect_count(event) == 1
            assert delivery_rows(event.event_id)[1]["attempt_count"] == 0
            # Receipt check precedes another ACK attempt; no duplicate effect.
            await worker._route_message(
                StreamMessage(str(message_id), fields), "analytics"
            )
            assert effect_count(event) == 1
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await worker.redis.close()

    asyncio.run(scenario())


def test_postgres_disconnect_refunds_attempt_after_storage_recovers(monkeypatch):
    event = append_event_for_test(create_scope())

    async def scenario():
        from sqlalchemy.exc import OperationalError

        async def disconnect(session, event):
            # Terminate this real connection after staging an uncommitted effect.
            await effect(session, event)
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            with engine.begin() as connection:
                connection.execute(
                    text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                )
            await session.execute(text("SELECT 1"))
            return "processed"

        execution = service(disconnect)
        finish = execution._finish_failure
        calls = 0

        async def storage_unavailable_once(claim, failure):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OperationalError("", {}, Exception(), connection_invalidated=True)
            return await finish(claim, failure)

        monkeypatch.setattr(execution, "_finish_failure", storage_unavailable_once)
        with pytest.raises(OperationalError):
            await execute(execution, event)
        assert effect_count(event) == count(EventReceipt) == 0
        assert delivery_rows(event.event_id)[0]["attempt_count"] == 1
        await execution.settle_failures()
        assert delivery_rows(event.event_id)[0]["attempt_count"] == 0
        with engine.connect() as connection:
            assert (
                connection.scalar(select(EventDeliveryAttempt.error_category))
                == "postgres_unavailable"
            )

    asyncio.run(scenario())


def test_cli_driver_authentication_errors_are_redacted():
    from sqlalchemy.engine import make_url

    env = process_environment(worker_settings())
    bad_url = make_url(env["DATABASE_URL"]).set(
        username="redaction-probe-" + uuid4().hex
    )
    env["DATABASE_URL"] = bad_url.render_as_string(hide_password=False)
    result = subprocess.run(
        [sys.executable, "-m", "app.modules.events.cli", "status"],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "redaction-probe" not in result.stderr
    assert "asyncpg" not in result.stderr


def test_real_poison_worker_restart_preserves_eight_attempts_and_other_consumer(
    tmp_path, monkeypatch
):
    """Real time/backoff and process restart complement the controlled-clock cases."""
    event = append_event_for_test(create_scope(), completed=True)
    settings = worker_settings()
    monkeypatch.setenv("EVENT_WORKER_TEST_POISON_SINK", "1")
    first = start_process(tmp_path, settings)
    restarted = None
    repaired = None
    try:
        # Restart during the longer fourth delay. Earlier controlled-clock
        # tests check every due boundary; here the process owns the real clock.
        wait_for(
            lambda: (
                (row := delivery_rows(event.event_id)[1])["attempt_count"] == 4
                and row["claim_token"] is None
            ),
            timeout=35,
        )
        before = delivery_rows(event.event_id)[1]
        assert before["next_attempt_at"] > datetime.now(UTC)
        kill_process(first)
        restarted = start_process(tmp_path, settings)
        wait_for(
            lambda: delivery_rows(event.event_id)[1]["status"] == "failed",
            timeout=150,
        )
        kill_process(restarted)
        rows = delivery_rows(event.event_id)
        assert rows[0]["status"] == "succeeded" and rows[0]["attempt_count"] == 1
        assert rows[1]["attempt_count"] == 8
        with engine.connect() as db:
            attempts = (
                db.execute(
                    text(
                        "SELECT a.started_at,a.finished_at FROM event_delivery_attempts a "
                        "WHERE delivery_id=:delivery ORDER BY attempt_number"
                    ),
                    {"delivery": rows[1]["id"]},
                )
                .mappings()
                .all()
            )
            assert len(attempts) == 8
            for index, (previous, following) in enumerate(zip(attempts, attempts[1:])):
                assert following["started_at"] >= previous["finished_at"] + timedelta(
                    seconds=RetryPolicy().delay_seconds(index + 1, 0)
                )
            assert db.scalar(text("SELECT count(*) FROM event_receipts")) == 1
        assert asyncio.run(
            EventOperatorService(AsyncSessionLocal).replay(
                rows[1]["id"], reason="T10 repaired test handler"
            )
        )
        monkeypatch.delenv("EVENT_WORKER_TEST_POISON_SINK")
        repaired = start_process(tmp_path, settings, module=True)
        wait_for(
            lambda: all(
                r["status"] == "succeeded" for r in delivery_rows(event.event_id)
            )
        )
        with engine.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM event_receipts")) == 2
            assert db.scalar(text("SELECT count(*) FROM event_diagnostics")) == 1
            assert db.scalar(text("SELECT count(*) FROM event_delivery_replays")) == 1
            assert db.scalar(text("SELECT count(*) FROM event_delivery_attempts")) == 10
    finally:
        kill_process(first)
        if restarted is not None:
            kill_process(restarted)
        if repaired is not None:
            kill_process(repaired)
        delete_owned_stream(settings)
