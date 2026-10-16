"""T8 maintenance uses real PostgreSQL, retained events and production consumers."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.db.database import AsyncSessionLocal
from app.core.errors import NotFoundError
from app.modules.events.maintenance import EventMaintenanceService
from app.modules.events.execution import CONSUMERS, ConsumerExecutionService
from app.modules.events.domain.retries import RetryPolicy
from app.modules.events.operator import EventOperatorService
from app.modules.analytics.service import AnalyticsProjectionService
from conftest import engine
from integration.test_inventory_episodes import (
    create_restaurant,
    create_ingredient,
    change_stock,
    update_ingredient,
)
from integration.test_alert_projection import (
    event_rows,
    deliver,
    wait_for_stock_lock_waiter,
)
from integration.test_analytics_projection import live_order, event, execute
from integration.test_order_inventory import create_menu_item
from test_event_execution import reference
from test_event_worker import (
    start_process,
    kill_process,
    stop_gracefully,
    worker_settings,
    wait_for,
    delete_owned_stream,
)


def scope_for(restaurant_id):
    with engine.connect() as connection:
        return UUID(
            str(
                connection.scalar(
                    text("SELECT organization_id FROM restaurants WHERE id=:id"),
                    {"id": restaurant_id},
                )
            )
        ), restaurant_id


def maintain(scope, kind="initialize", confirmed=True):
    return asyncio.run(
        EventMaintenanceService(AsyncSessionLocal).run(
            *scope,
            kind=kind,
            reason="T8 disposable rehearsal",
            maintenance_confirmed=confirmed,
        )
    )


def rows(table):
    with engine.connect() as connection:
        return list(
            connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")).mappings()
        )


def legacy_low(client, restaurant_id):
    ingredient = create_ingredient(client, restaurant_id, quantity="10", threshold="5")
    # Seed a pre-T2 low balance without inventing historical transitions.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE inventory_balances SET quantity=0 WHERE ingredient_id=:id"),
            {"id": ingredient["id"]},
        )
    return ingredient


def test_initialization_scoped_truthful_atomic_baseline_and_queued_watermarks(
    authenticated_client,
):
    client = authenticated_client
    branch = create_restaurant(client)
    scope = scope_for(branch)
    other = create_restaurant(client)
    legacy_low(client, other)
    ingredient = legacy_low(client, branch)
    genuine = create_ingredient(
        client, branch, name="New low", quantity="1", threshold="5"
    )
    live_order(scope, 900, total="12.34")
    live_order(scope, 901, status="SUBMITTED", revision=5)
    complete = event(scope, 900)
    deleted = event(scope, 902, 5, deleted=True)
    stale = event(scope, 902)
    inactive_old = event(scope, 901)
    events_before, deliveries_before = rows("outbox_events"), rows("event_deliveries")
    before = datetime.now(UTC)
    result = maintain(scope)
    assert result["outcome"] == "completed"
    assert rows("outbox_events") == events_before
    assert rows("event_deliveries") == deliveries_before
    baselines = [
        r for r in rows("inventory_low_stock_episodes") if r["notification_suppressed"]
    ]
    assert len(baselines) == 1
    baseline = baselines[0]
    assert baseline["ingredient_id"] == ingredient["id"]
    assert before <= baseline["opened_at"] <= datetime.now(UTC)
    assert baseline["opening_source"] == "maintenance_initialization"
    assert baseline["ingredient_name"] == "Rice" and baseline["unit"] == "g"
    assert (
        baseline["opening_quantity"] == 0 and baseline["opening_reorder_threshold"] == 5
    )
    assert len(rows("alert_ingredient_states")) == 2
    genuine_episode = next(
        r
        for r in rows("inventory_low_stock_episodes")
        if r["ingredient_id"] == genuine["id"]
    )
    assert not genuine_episode["notification_suppressed"]
    for value in (complete, deleted, stale, inactive_old):
        assert asyncio.run(execute(value)).acknowledge
    assert asyncio.run(AnalyticsProjectionService(AsyncSessionLocal).reconcile(*scope))[
        "matches"
    ]
    assert maintain(scope)["operation_id"] == result["operation_id"]
    assert len(rows("event_maintenance_operations")) == 1
    assert rows("event_maintenance_operations")[0]["operator"]
    assert len(rows("notification_stubs")) == 0


@pytest.mark.parametrize("recovery", ["stock", "threshold", "archive"])
def test_baseline_rerun_and_new_episode_notification(authenticated_client, recovery):
    client = authenticated_client
    branch = create_restaurant(client)
    scope = scope_for(branch)
    ingredient = legacy_low(client, branch)
    maintain(scope)
    baseline = rows("inventory_low_stock_episodes")[0]
    # Changes while still low keep the same suppressed episode.
    assert (
        update_ingredient(
            client, branch, ingredient["id"], name="Renamed", threshold="6"
        ).status_code
        == 200
    )
    maintain(scope)
    assert (
        rows("inventory_low_stock_episodes")[0]["episode_id"] == baseline["episode_id"]
    )
    assert rows("inventory_low_stock_episodes")[0]["ingredient_name"] == "Rice"
    if recovery == "stock":
        assert (
            change_stock(
                client, branch, ingredient["id"], uuid4().hex, "receipt", "10"
            ).status_code
            == 201
        )
    elif recovery == "threshold":
        # First put quantity above zero but still below the threshold, then lower it.
        assert (
            change_stock(
                client, branch, ingredient["id"], uuid4().hex, "receipt", "1"
            ).status_code
            == 201
        )
        assert (
            update_ingredient(
                client, branch, ingredient["id"], threshold="0"
            ).status_code
            == 200
        )
    else:
        assert (
            update_ingredient(
                client, branch, ingredient["id"], active=False
            ).status_code
            == 200
        )
    maintain(scope)
    assert len(rows("inventory_low_stock_episodes")) == 1
    assert rows("inventory_low_stock_episodes")[0]["resolved_at"] is not None
    if recovery == "stock":
        assert (
            change_stock(
                client, branch, ingredient["id"], uuid4().hex, "waste", "10"
            ).status_code
            == 201
        )
    else:
        assert (
            update_ingredient(
                client, branch, ingredient["id"], threshold="5", active=True
            ).status_code
            == 200
        )
    maintain(scope)
    new_low = next(e for _, e in event_rows() if e.event_type == "inventory.low.v1")
    assert asyncio.run(deliver(new_low, "notification_sink")).acknowledge
    assert rows("notification_stubs")[0]["outcome"] == "created"
    assert len(rows("inventory_low_stock_episodes")) == 2


def test_interruption_rolls_back_analytics_baselines_and_marker(
    authenticated_client, monkeypatch
):
    import app.modules.events.maintenance as module

    branch = create_restaurant(authenticated_client)
    scope = scope_for(branch)
    legacy_low(authenticated_client, branch)
    live_order(scope, 900)
    original = module.AlertProjectionService.rebuild

    async def interrupt(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("Interrupted before marker commit")

    monkeypatch.setattr(module.AlertProjectionService, "rebuild", interrupt)
    with pytest.raises(RuntimeError, match="Interrupted"):
        maintain(scope)
    for table in (
        "event_maintenance_operations",
        "inventory_low_stock_episodes",
        "analytics_daily_sales",
        "analytics_order_contributions",
        "alert_episodes",
        "alert_ingredient_states",
    ):
        assert rows(table) == []
    monkeypatch.setattr(module.AlertProjectionService, "rebuild", original)
    assert maintain(scope)["outcome"] == "completed"


def test_rebuild_preserves_receipts_events_attempts_history_and_stubs(
    authenticated_client,
):
    branch = create_restaurant(authenticated_client)
    scope = scope_for(branch)
    create_ingredient(authenticated_client, branch, quantity="1")
    live_order(scope, 900)
    live_order(scope, 901)
    create_menu_item(authenticated_client, branch)
    complete = event(scope, 900)
    assert asyncio.run(execute(complete)).acknowledge
    for _, value in event_rows():
        if value.event_type in {"inventory.low.v1", "menu.updated.v1"}:
            assert asyncio.run(deliver(value, "notification_sink")).acknowledge
    pending = event(scope, 901)

    async def fail_and_replay():
        async def fail(session, value):
            raise RuntimeError("Test event failure")

        await ConsumerExecutionService(
            AsyncSessionLocal,
            registry={**CONSUMERS, "analytics": fail},
            policy=RetryPolicy(max_attempts=1),
        ).execute(
            event_id=pending.event_id,
            consumer="analytics",
            reference=reference(pending),
            worker_id="maintenance-test",
        )
        delivery = next(
            r
            for r in rows("event_deliveries")
            if r["event_id"] == pending.event_id and r["consumer_name"] == "analytics"
        )
        await EventOperatorService(AsyncSessionLocal).replay(
            delivery["id"], reason="Repaired test handler"
        )

    asyncio.run(fail_and_replay())
    maintain(scope)
    tables = (
        "outbox_events",
        "event_deliveries",
        "event_delivery_attempts",
        "event_delivery_replays",
        "event_receipts",
        "alert_episodes",
        "inventory_low_stock_episodes",
        "notification_stubs",
        "event_diagnostics",
    )
    retained = {t: rows(t) for t in tables}
    with engine.begin() as connection:
        connection.execute(text("UPDATE analytics_daily_sales SET sales=99"))
    assert not asyncio.run(
        AnalyticsProjectionService(AsyncSessionLocal).reconcile(*scope)
    )["matches"]
    result = maintain(scope, "analytics_rebuild")
    assert result["retained_counts"]["receipts"] > 0
    assert result["retained_counts"]["replays"] == 1
    assert result["retained_counts"]["diagnostics"] > 0
    assert asyncio.run(AnalyticsProjectionService(AsyncSessionLocal).reconcile(*scope))[
        "matches"
    ]
    assert {t: rows(t) for t in tables} == retained
    assert asyncio.run(execute(complete)).outcome == "durable_receipt_acknowledged"
    assert asyncio.run(execute(pending)).acknowledge
    assert asyncio.run(AnalyticsProjectionService(AsyncSessionLocal).reconcile(*scope))[
        "matches"
    ]


def test_maintenance_requires_explicit_preconditions_and_matching_scope(
    authenticated_client,
):
    branch = create_restaurant(authenticated_client)
    scope = scope_for(branch)
    with pytest.raises(ValueError):
        maintain(scope, confirmed=False)
    with pytest.raises(NotFoundError):
        maintain((uuid4(), branch))
    with pytest.raises(ValueError):
        maintain(scope, "analytics_rebuild")
    assert rows("event_maintenance_operations") == []


def test_concurrent_initialization_serializes_at_restaurant_lock(authenticated_client):
    from app.modules.inventory.service import load_inventory_restaurant_states

    branch = create_restaurant(authenticated_client)
    scope = scope_for(branch)
    legacy_low(authenticated_client, branch)

    async def overlap():
        service = EventMaintenanceService(AsyncSessionLocal)
        async with AsyncSessionLocal() as blocker:
            async with blocker.begin():
                await load_inventory_restaurant_states(blocker, *scope, lock=True)
                pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
                tasks = [
                    asyncio.create_task(
                        service.run(
                            *scope,
                            kind="initialize",
                            reason="Concurrent rehearsal",
                            maintenance_confirmed=True,
                        )
                    )
                    for _ in range(2)
                ]
                await wait_for_stock_lock_waiter(pid)
            return await asyncio.gather(*tasks)

    results = asyncio.run(overlap())
    assert {r["outcome"] for r in results} == {"completed", "already_initialized"}
    assert results[0]["operation_id"] == results[1]["operation_id"]
    assert len(rows("inventory_low_stock_episodes")) == 1
    assert len(rows("event_maintenance_operations")) == 1


def test_start_real_worker_after_baseline_then_resume_business_writes(
    authenticated_client, tmp_path
):
    client = authenticated_client
    branch = create_restaurant(client)
    scope = scope_for(branch)
    ingredient = legacy_low(client, branch)
    live_order(scope, 900)
    event(scope, 900)
    maintain(scope)  # No worker and no in-flight business write during initialization.
    settings = worker_settings()
    process = start_process(tmp_path, settings, module=True)
    try:
        wait_for(
            lambda: all(r["status"] == "succeeded" for r in rows("event_deliveries"))
        )
        assert asyncio.run(
            AnalyticsProjectionService(AsyncSessionLocal).reconcile(*scope)
        )["matches"]
        assert rows("notification_stubs") == []
        assert (
            change_stock(
                client, branch, ingredient["id"], uuid4().hex, "receipt", "10"
            ).status_code
            == 201
        )
        assert (
            change_stock(
                client, branch, ingredient["id"], uuid4().hex, "waste", "10"
            ).status_code
            == 201
        )
        # The new episode and its notification can arrive before the separate
        # baseline-resolution delivery. Wait for all effects to commit before
        # asserting the final projection state.
        wait_for(
            lambda: all(r["status"] == "succeeded" for r in rows("event_deliveries"))
        )
        assert len(rows("notification_stubs")) == 1
        assert len(rows("alert_episodes")) == 2
        assert rows("notification_stubs")[0]["outcome"] == "created"
        baseline = next(
            r for r in rows("alert_episodes") if r["notification_suppressed"]
        )
        assert baseline["resolved_at"] is not None
        assert rows("notification_stubs")[0]["episode_id"] != baseline["episode_id"]
        stop_gracefully(process)
        assert maintain(scope)["outcome"] == "already_initialized"
    finally:
        kill_process(process)
        delete_owned_stream(settings)
