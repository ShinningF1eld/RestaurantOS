"""Pure worker transport/configuration contracts; no service connections."""

import pytest
from pydantic import ValidationError
from redis.exceptions import ResponseError

from app.core.config import Settings
from app.modules.events.domain.subscriptions import SUBSCRIPTIONS
from app.modules.events.worker.redis import (
    WorkerFailureKind,
    WorkerRedisFailure,
    _safe_server_code,
    create_worker_client,
)
from app.modules.events.worker.streams import (
    GROUPS,
    _group_names,
    _group_pending_counts,
    _pending_messages,
    _stream_messages,
)
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
