"""Pure worker transport/configuration contracts; no service connections."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from redis.exceptions import ResponseError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.modules.events.domain.subscriptions import SUBSCRIPTIONS
from app.modules.events.worker.redis import (
    WorkerFailureKind,
    WorkerRedisFailure,
    _safe_server_code,
    create_worker_client,
)
from app.modules.events.worker.streams import (
    EventStreams,
    StreamMessage,
    GROUPS,
    _group_names,
    _group_pending_counts,
    _pending_messages,
    _stream_messages,
)
from app.modules.events.worker.runtime import EventWorker, _ReferenceRetry
from app.redis.adapter import create_client


def test_worker_defaults_are_bounded_and_isolated_from_api(unit_settings):
    settings = unit_settings
    assert settings.redis_operation_budget_ms == 100
    assert settings.redis_max_connections == 20
    assert settings.event_worker_redis_operation_budget_ms == 2000
    assert settings.event_worker_redis_block_ms == 1000
    assert settings.event_worker_redis_max_connections == 8
    assert settings.event_worker_claim_batch_size == 10
    assert settings.event_worker_relay_concurrency == 2
    assert settings.event_worker_claim_lease_seconds == 30
    assert settings.event_worker_recovery_scan_interval_ms == 1500
    assert settings.event_worker_republish_stall_seconds == 60
    assert settings.event_worker_pending_idle_ms == 60000
    assert settings.event_worker_shutdown_grace_seconds == 10


def test_worker_redis_pool_does_not_change_api_pool(unit_settings):
    api_client = create_client(unit_settings)
    worker_client = create_worker_client(unit_settings)
    api_options = api_client.connection_pool.connection_kwargs
    worker_options = worker_client.connection_pool.connection_kwargs

    assert api_options["socket_timeout"] == api_options["socket_connect_timeout"] == 0.1
    assert (
        worker_options["socket_timeout"]
        == worker_options["socket_connect_timeout"]
        == 2
    )
    assert api_client.connection_pool.max_connections == 20
    assert worker_client.connection_pool.max_connections == 8
    assert api_options["decode_responses"] is False
    assert worker_options["decode_responses"] is True


@pytest.mark.parametrize(
    "updates",
    [
        {"event_worker_redis_block_ms": 2000},
        {
            "event_worker_infra_backoff_initial_ms": 2500,
            "event_worker_infra_backoff_max_ms": 1000,
        },
        {"event_worker_claim_lease_seconds": 4},
        {"event_worker_claim_batch_size": 101},
    ],
)
def test_worker_settings_reject_unsafe_budget_relationships(
    unit_settings_kwargs, updates
):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **unit_settings_kwargs, **updates)


def test_worker_redis_failure_keeps_only_allowlisted_server_code():
    code = _safe_server_code(ResponseError("BUSYGROUP private server detail"))
    assert code == "BUSYGROUP"
    failure = WorkerRedisFailure(WorkerFailureKind.COMMAND, server_code=code)
    assert "private server detail" not in str(failure)


def test_subscription_groups_are_fixed_and_stream_parser_is_bounded():
    assert set(GROUPS) == {
        consumer for consumers in SUBSCRIPTIONS.values() for consumer in consumers
    }
    parsed = _stream_messages(
        [["restaurantos:test:events:v1:stream", [["1-0", {"event_id": "abc"}]]]]
    )
    assert len(parsed) == 1
    assert parsed[0].message_id == "1-0"
    assert parsed[0].fields == {"event_id": "abc"}

    groups = _group_names([{"name": "analytics", "consumers": 1}, {"name": "alerts"}])
    assert groups == {"analytics", "alerts"}
    assert _group_pending_counts(
        [
            {"name": "analytics", "pending": 7},
            {"name": "alerts", "pending": 0},
        ]
    ) == {"analytics": 7, "alerts": 0}

    pending = _pending_messages(
        [["1-0", "worker-old", 90000, 2], ["2-0", "worker-new", 3, 1]]
    )
    assert [
        (message.message_id, message.owner, message.idle_ms) for message in pending
    ] == [
        ("1-0", "worker-old", 90000),
        ("2-0", "worker-new", 3),
    ]


@pytest.mark.parametrize("full_queue", [False, True])
def test_busy_revisits_are_bounded_and_interleave_new_reads(
    unit_settings, monkeypatch, full_queue
):
    async def scenario():
        worker = EventWorker(
            unit_settings.model_copy(update={"event_worker_recovery_batch_size": 2}),
            None,
        )
        stop = asyncio.Event()
        busy = StreamMessage("1-0", {})
        fresh = StreamMessage("2-0", {})
        other_busy = StreamMessage("3-0", {})
        overflow = StreamMessage("4-0", {})
        tracked = [busy, other_busy] if full_queue else [busy]
        routed = []
        delays = []
        reads = 0

        def ready_immediately(count, ready_at):
            delays.append(round((ready_at - asyncio.get_running_loop().time()) * 1000))
            return _ReferenceRetry(count, 0)

        monkeypatch.setattr(
            "app.modules.events.worker.runtime._ReferenceRetry", ready_immediately
        )

        async def route(message, group):
            routed.append(message.message_id)
            return message is not fresh

        async def read_new(group, consumer, *, count, block_ms):
            nonlocal reads
            reads += 1
            if reads == 1:
                assert count == 2
                return tracked
            if reads == 2:
                assert count == 2
                assert block_ms == 0
                return [overflow, fresh] if full_queue else [fresh]
            if all(routed.count(message.message_id) == 21 for message in tracked):
                assert count == 2
                stop.set()
            return []

        async def pending(group, consumer, message_id):
            return next(
                message for message in tracked if message.message_id == message_id
            )

        pending_reference = AsyncMock(side_effect=pending)
        worker.streams = SimpleNamespace(
            ensure_groups=AsyncMock(),
            pending_page=AsyncMock(return_value=[]),
            pending_reference=pending_reference,
            read_new=read_new,
        )
        monkeypatch.setattr(worker, "_route_message", route)
        await asyncio.wait_for(worker._consumer_loop("notification_sink", stop), 5)
        assert routed.count("1-0") == 21
        assert routed.index("2-0") < len(routed) - 1
        assert pending_reference.await_count == 20 * len(tracked)
        assert sorted(delays) == sorted(([50, 100, 200] + [250] * 17) * len(tracked))
        if full_queue:
            assert routed.count("3-0") == 21
            assert routed.count("4-0") == 1

    asyncio.run(scenario())


def test_zero_block_reads_omit_redis_block_instead_of_waiting_forever():
    async def scenario():
        transport = SimpleNamespace(
            stream_key=lambda: "test:events", execute=AsyncMock(return_value=[])
        )
        streams = EventStreams(transport)
        await streams.read_new("alerts", "owner", count=1, block_ms=0)
        assert "BLOCK" not in transport.execute.call_args.args
        await streams.read_new("alerts", "owner", count=1, block_ms=50)
        assert transport.execute.call_args.args[6:8] == ("BLOCK", 50)

    asyncio.run(scenario())


def test_relay_drains_full_and_partial_batches_before_idle_wait(
    unit_settings, monkeypatch
):
    async def scenario():
        worker = EventWorker(
            unit_settings.model_copy(update={"event_worker_claim_batch_size": 2}), None
        )
        stop = asyncio.Event()
        published = []
        batches = iter([["first", "second"], ["third"], []])

        async def claim(**arguments):
            assert arguments["limit"] == 2
            assert (
                arguments["lease_seconds"]
                == unit_settings.event_worker_claim_lease_seconds
            )
            assert (
                arguments["republish_after_seconds"]
                == unit_settings.event_worker_republish_stall_seconds
            )
            return next(batches)

        async def publish(claim, semaphore):
            published.append(claim)
            return False

        async def wait(stop_event, delay_ms):
            # Any old unconditional batch sleep would stop before publishing all
            # three deliveries and fail this observable drain assertion.
            assert published == ["first", "second", "third"]
            assert delay_ms == unit_settings.event_worker_recovery_scan_interval_ms
            stop_event.set()

        worker.event_service = SimpleNamespace(claim_due_deliveries=claim)
        worker.execution = SimpleNamespace(recover_expired=AsyncMock())
        monkeypatch.setattr(worker, "_publish_claim", publish)
        monkeypatch.setattr(worker, "_wait", wait)
        await asyncio.wait_for(worker._relay_loop(stop), 5)
        assert worker.execution.recover_expired.await_count == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("condition", ["empty", "transport", "postgres", "internal"])
def test_relay_preserves_idle_wait_and_failure_backoff(
    unit_settings, monkeypatch, condition
):
    async def scenario():
        worker = EventWorker(unit_settings, None)
        stop = asyncio.Event()
        claims = 0
        delays = []

        async def claim(**arguments):
            nonlocal claims
            claims += 1
            if claims <= 2:
                if condition == "postgres":
                    raise SQLAlchemyError("injected")
                if condition == "internal":
                    raise RuntimeError("injected")
                if condition == "transport":
                    return ["failed-publication"]
            return []

        async def wait(stop_event, delay_ms):
            delays.append(delay_ms)
            if len(delays) == 3:
                stop_event.set()

        worker.event_service = SimpleNamespace(claim_due_deliveries=claim)
        worker.execution = SimpleNamespace(recover_expired=AsyncMock())
        publish = AsyncMock(return_value=True)
        monkeypatch.setattr(worker, "_publish_claim", publish)
        monkeypatch.setattr(worker, "_wait", wait)
        await asyncio.wait_for(worker._relay_loop(stop), 5)
        idle = unit_settings.event_worker_recovery_scan_interval_ms
        initial = unit_settings.event_worker_infra_backoff_initial_ms
        assert delays == (
            [idle] * 3 if condition == "empty" else [initial, initial * 2, idle]
        )
        assert claims == 3
        assert publish.await_count == (2 if condition == "transport" else 0)

    asyncio.run(scenario())


def test_relay_stops_between_successful_batches(unit_settings, monkeypatch):
    async def scenario():
        worker = EventWorker(unit_settings, None)
        stop = asyncio.Event()
        claim = AsyncMock(return_value=["last-publication"])

        async def publish(claim, semaphore):
            stop.set()
            return False

        worker.event_service = SimpleNamespace(claim_due_deliveries=claim)
        worker.execution = SimpleNamespace(recover_expired=AsyncMock())
        wait = AsyncMock()
        monkeypatch.setattr(worker, "_publish_claim", publish)
        monkeypatch.setattr(worker, "_wait", wait)
        await asyncio.wait_for(worker._relay_loop(stop), 5)
        assert claim.await_count == 1
        wait.assert_not_awaited()

    asyncio.run(scenario())
