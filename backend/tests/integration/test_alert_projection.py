"""T7 alert, notification and diagnostic effects using real PostgreSQL facts."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.database import AsyncSessionLocal
from app.modules.alerts.service import AlertProjectionService
from app.modules.events.domain.contracts import InventoryLowEvent, deserialize_event
from app.modules.events.execution import (
    CONSUMERS,
    ConsumerExecutionService,
    ExecutionHooks,
)
from app.modules.events.service import append_event
from app.modules.inventory.repo.queries import InventoryTransitionRepository
from app.modules.inventory.service import record_baseline_inventory_episode
from conftest import engine
from integration.test_inventory_episodes import (
    change_stock,
    create_ingredient,
    create_restaurant,
    update_ingredient,
)
from integration.test_order_inventory import (
    create_menu_item,
    create_order,
    update_order,
)
from test_event_worker import (
    start_process,
    kill_process,
    process_phase,
    worker_settings,
    wait_for,
)


def event_rows():
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT event_id,event_type,schema_version,organization_id,restaurant_id,"
                "aggregate_type,aggregate_id,aggregate_revision,occurred_at,correlation_id,payload "
                "FROM outbox_events ORDER BY recorded_at,event_id"
            )
        ).mappings()
        return [
            (
                UUID(str(row["event_id"])),
                deserialize_event({key: row[key] for key in row.keys()}),
            )
            for row in rows
        ]


def reference(event):
    return {
        key: str(getattr(event, key))
        for key in ("event_id", "event_type", "schema_version", "correlation_id")
    }


async def deliver(event, consumer):
    service = ConsumerExecutionService(AsyncSessionLocal, registry=CONSUMERS)
    return await service.execute(
        event_id=event.event_id,
        consumer=consumer,
        reference=reference(event),
        worker_id="t7-test-worker",
    )


async def wait_for_stock_lock_waiter(blocker_pid=None):
    """Observe a real PostgreSQL waiter at the shared restaurant lock."""

    async def observe():
        while True:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT pg_blocking_pids(pid) FROM pg_stat_activity "
                        "WHERE datname=current_database() AND wait_event_type='Lock' "
                        "AND query ILIKE '%restaurants%' AND pid<>pg_backend_pid()"
                    )
                ).scalars()
                if any(
                    pids and (blocker_pid is None or blocker_pid in pids)
                    for pids in rows
                ):
                    return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(observe(), timeout=10)


def test_out_of_order_events_preserve_closed_history_and_never_reopen_current_state(
    authenticated_client,
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(
        client, restaurant_id, name="Rice", quantity="5", threshold="5"
    )
    ingredient_id = ingredient["id"]
    opening_events = event_rows()
    low_event = next(
        event for _, event in opening_events if event.event_type == "inventory.low.v1"
    )
    opening_state = next(
        event
        for _, event in opening_events
        if event.event_type == "inventory.state_changed.v1"
    )

    # A later resolution is consumed first. Its producer-owned episode row
    # supplies opening and closing facts even though the low event is delayed.
    assert (
        change_stock(
            client, restaurant_id, ingredient_id, "replenish", "receipt", "1"
        ).status_code
        == 201
    )
    resolution = next(
        event
        for _, event in event_rows()
        if event.event_type == "inventory.state_changed.v1"
        and event.aggregate_revision > opening_state.aggregate_revision
    )
    assert asyncio.run(deliver(resolution, "alerts")).acknowledge
    assert asyncio.run(deliver(opening_state, "alerts")).acknowledge
    assert asyncio.run(deliver(low_event, "alerts")).acknowledge
    assert asyncio.run(deliver(low_event, "notification_sink")).acknowledge

    with engine.connect() as connection:
        episode = (
            connection.execute(
                text(
                    "SELECT ingredient_name,opening_quantity,opening_threshold,resolved_at,resolution_reason FROM alert_episodes WHERE episode_id=:id"
                ),
                {"id": low_event.payload.episode_id},
            )
            .mappings()
            .one()
        )
        state = (
            connection.execute(
                text(
                    "SELECT revision,is_low,episode_id,quantity FROM alert_ingredient_states WHERE ingredient_id=:id"
                ),
                {"id": ingredient_id},
            )
            .mappings()
            .one()
        )
        stub = (
            connection.execute(
                text(
                    "SELECT outcome,reason FROM notification_stubs WHERE episode_id=:id"
                ),
                {"id": low_event.payload.episode_id},
            )
            .mappings()
            .one()
        )
    assert episode["ingredient_name"] == "Rice"
    assert episode["opening_quantity"] == 5
    assert episode["opening_threshold"] == 5
    assert episode["resolved_at"] is not None
    assert episode["resolution_reason"] == "stock_recovered"
    assert state["revision"] == resolution.aggregate_revision
    assert state["is_low"] is False and state["episode_id"] is None
    assert stub["outcome"] == "skipped" and stub["reason"] == "resolved_or_superseded"


def test_created_stub_survives_later_replenishment_and_diagnostics_are_durable(
    authenticated_client,
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(
        client, restaurant_id, name="Beans", quantity="5", threshold="5"
    )
    events = [event for _, event in event_rows()]
    low_event = next(
        event for event in events if event.event_type == "inventory.low.v1"
    )
    # One sink event per committed order/menu business event, with a stable UUID.
    sink_events = [event for event in events if event.event_type == "inventory.low.v1"]
    assert asyncio.run(deliver(low_event, "notification_sink")).acknowledge
    assert (
        change_stock(
            client, restaurant_id, ingredient["id"], "replenish", "receipt", "1"
        ).status_code
        == 201
    )
    resolution = next(
        event
        for _, event in event_rows()
        if event.event_type == "inventory.state_changed.v1"
        and event.aggregate_revision > low_event.aggregate_revision
    )
    assert asyncio.run(deliver(resolution, "alerts")).acknowledge
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT outcome,ingredient_name FROM notification_stubs WHERE episode_id=:id"
                ),
                {"id": low_event.payload.episode_id},
            )
            .mappings()
            .one()
        )
        receipt = connection.execute(
            text(
                "SELECT outcome FROM event_receipts WHERE consumer_name='notification_sink' AND event_id=:id"
            ),
            {"id": low_event.event_id},
        ).scalar_one()
    assert row["outcome"] == "created" and row["ingredient_name"] == "Beans"
    assert receipt == "processed"
    assert len(sink_events) == 1


def test_diagnostic_sink_stores_only_safe_deduplicated_event_facts(
    authenticated_client,
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    menu_item_id = create_menu_item(client, restaurant_id, name="Lunch special")
    order = create_order(client, restaurant_id, menu_item_id)
    assert order.status_code == 201, order.text
    assert (
        update_order(client, order.json()["order_id"], "SUBMITTED").status_code == 200
    )
    for status in ("ACCEPTED", "PREPARING", "READY", "COMPLETED"):
        response = update_order(client, order.json()["order_id"], status)
        assert response.status_code == 200, response.text
    assert client.delete(f"/api/orders/{order.json()['order_id']}").status_code == 204
    cancelled = create_order(client, restaurant_id, menu_item_id)
    assert cancelled.status_code == 201
    assert (
        update_order(client, cancelled.json()["order_id"], "CANCELLED").status_code
        == 200
    )
    events = [event for _, event in event_rows()]
    diagnostic_events = [
        event for event in events if event.event_type.startswith(("menu.", "order."))
    ]
    assert diagnostic_events
    for event in diagnostic_events:
        assert asyncio.run(deliver(event, "notification_sink")).acknowledge
        assert (
            asyncio.run(deliver(event, "notification_sink")).outcome
            == "durable_receipt_acknowledged"
        )
    with engine.connect() as connection:
        count = connection.scalar(text("SELECT count(*) FROM event_diagnostics"))
        facts = connection.execute(
            text(
                "SELECT facts FROM event_diagnostics WHERE event_type='menu.updated.v1' LIMIT 1"
            )
        ).scalar_one()
        event_types = set(
            connection.scalars(text("SELECT event_type FROM event_diagnostics"))
        )
    assert count == len(diagnostic_events)
    assert event_types == {
        "menu.updated.v1",
        "order.submitted.v1",
        "order.accepted.v1",
        "order.completed.v1",
        "order.deleted.v1",
        "order.cancelled.v1",
    }
    assert facts["operation"] == "created"


def test_alert_rebuild_preserves_stubs_and_episode_facts(authenticated_client):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    create_ingredient(client, restaurant_id, quantity="5", threshold="5")
    low_event = next(
        event for _, event in event_rows() if event.event_type == "inventory.low.v1"
    )
    assert asyncio.run(deliver(low_event, "notification_sink")).acknowledge

    async def rebuild():
        async with AsyncSessionLocal() as session, session.begin():
            await AlertProjectionService().rebuild(
                session, low_event.organization_id, restaurant_id
            )

    asyncio.run(rebuild())
    assert asyncio.run(rebuild()) is None
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alert_episodes")) == 1
        assert (
            connection.scalar(text("SELECT count(*) FROM alert_ingredient_states")) == 1
        )
        assert connection.scalar(text("SELECT count(*) FROM notification_stubs")) == 1


def test_initialization_baseline_persists_suppressed_notification_outcome(
    authenticated_client,
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(client, restaurant_id, quantity="10", threshold="5")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE inventory_balances SET quantity=5 WHERE ingredient_id=:id"),
            {"id": ingredient["id"]},
        )

    # Resolve the verified organization scope from the restaurant row.
    with engine.connect() as connection:
        organization_id = connection.scalar(
            text("SELECT organization_id FROM restaurants WHERE id=:id"),
            {"id": restaurant_id},
        )

    async def baseline_with_scope():
        async with AsyncSessionLocal() as session, session.begin():
            return await record_baseline_inventory_episode(
                session, UUID(str(organization_id)), restaurant_id, ingredient["id"]
            )

    baseline = asyncio.run(baseline_with_scope())
    assert baseline.episode_facts is not None
    facts = baseline.episode_facts
    event = InventoryLowEvent(
        event_id=UUID(int=9001),
        event_type="inventory.low.v1",
        schema_version=1,
        organization_id=UUID(str(organization_id)),
        restaurant_id=restaurant_id,
        aggregate_type="ingredient",
        aggregate_id=str(ingredient["id"]),
        aggregate_revision=baseline.state_revision,
        occurred_at=facts.opened_at,
        correlation_id="baseline-test",
        payload={
            "ingredient_id": ingredient["id"],
            "episode_id": baseline.episode_id,
            "ingredient_name": facts.ingredient_name,
            "unit": facts.unit,
            "opening_quantity": "5",
            "reorder_threshold": "5",
            "opened_at": facts.opened_at,
        },
    )

    async def handle_baseline():
        async with AsyncSessionLocal() as session, session.begin():
            await append_event(session, event)
        return await deliver(event, "notification_sink")

    assert facts.notification_suppressed
    assert asyncio.run(handle_baseline()).acknowledge
    with engine.connect() as connection:
        outcome = connection.scalar(
            text("SELECT outcome FROM notification_stubs WHERE episode_id=:id"),
            {"id": baseline.episode_id},
        )
    assert outcome == "suppressed"

    async def rebuild():
        async with AsyncSessionLocal() as session, session.begin():
            await AlertProjectionService().rebuild(
                session, event.organization_id, restaurant_id
            )

    asyncio.run(rebuild())
    asyncio.run(rebuild())
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT notification_suppressed FROM alert_episodes")
        )
        assert (
            connection.scalar(text("SELECT opening_source FROM alert_episodes"))
            == "maintenance_initialization"
        )
        assert (
            connection.scalar(
                text("SELECT outcome FROM event_receipts WHERE event_id=:id"),
                {"id": event.event_id},
            )
            == "skipped"
        )


def test_resolution_holding_stock_lock_wins_against_waiting_stub_commit(
    authenticated_client,
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(client, restaurant_id, quantity="5", threshold="5")
    low_event = next(
        event for _, event in event_rows() if event.event_type == "inventory.low.v1"
    )

    async def scenario():
        started = asyncio.Event()
        execution = ConsumerExecutionService(
            AsyncSessionLocal,
            registry=CONSUMERS,
            hooks=ExecutionHooks(after_start=lambda _claim: _signal(started)),
        )
        async with AsyncSessionLocal() as writer, writer.begin():
            writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            repository = InventoryTransitionRepository(writer)
            await repository.lock_restaurant_for_organization(
                low_event.organization_id, restaurant_id
            )
            item, balance = await repository.ingredient_state(
                low_event.organization_id,
                restaurant_id,
                ingredient["id"],
                lock=True,
            )
            episode = await repository.open_episode(ingredient["id"], lock=True)
            assert episode is not None
            balance.quantity += 1
            item.state_revision += 1
            episode.resolved_at = datetime.now(UTC)
            episode.resolution_reason = "stock_recovered"
            episode.closing_quantity = balance.quantity
            episode.closing_reorder_threshold = item.reorder_threshold
            episode.closing_is_active = item.is_active
            episode.resolution_revision = item.state_revision
            episode.resolution_source = "stock_command"

            consumer = asyncio.create_task(
                execution.execute(
                    event_id=low_event.event_id,
                    consumer="notification_sink",
                    reference=reference(low_event),
                    worker_id="t7-lock-test",
                )
            )
            await asyncio.wait_for(started.wait(), timeout=5)
            await wait_for_stock_lock_waiter(writer_pid)
            # The consumer has durably started, but cannot pass the stock lock.
            with engine.connect() as connection:
                assert (
                    connection.scalar(text("SELECT count(*) FROM notification_stubs"))
                    == 0
                )
        result = await asyncio.wait_for(consumer, timeout=5)
        assert result.acknowledge
        return result.outcome

    async def _signal(event):
        event.set()

    assert asyncio.run(scenario()) == "consumer_committed"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM notification_stubs")) == 1
        assert (
            connection.scalar(text("SELECT outcome FROM notification_stubs"))
            == "skipped"
        )
        assert (
            connection.scalar(
                text("SELECT outcome FROM event_receipts WHERE event_id=:id"),
                {"id": low_event.event_id},
            )
            == "skipped"
        )


def test_stub_commit_holds_off_replenishment_and_duplicate_delivery(
    authenticated_client,
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(client, restaurant_id, quantity="5", threshold="5")
    low_event = next(
        event for _, event in event_rows() if event.event_type == "inventory.low.v1"
    )

    async def scenario():
        inside, release = asyncio.Event(), asyncio.Event()

        async def hold(_claim):
            inside.set()
            await release.wait()

        execution = ConsumerExecutionService(
            AsyncSessionLocal, hooks=ExecutionHooks(before_commit=hold)
        )
        consumer = asyncio.create_task(
            execution.execute(
                event_id=low_event.event_id,
                consumer="notification_sink",
                reference=reference(low_event),
                worker_id="stub-first",
            )
        )
        await asyncio.wait_for(inside.wait(), 10)
        stock = asyncio.create_task(
            asyncio.to_thread(
                change_stock,
                client,
                restaurant_id,
                ingredient["id"],
                "overlap-receipt",
                "receipt",
                "1",
            )
        )
        try:
            await wait_for_stock_lock_waiter()
            with engine.connect() as connection:
                assert (
                    connection.scalar(text("SELECT count(*) FROM notification_stubs"))
                    == 0
                )
                assert (
                    connection.scalar(text("SELECT count(*) FROM event_receipts")) == 0
                )
            duplicate = await deliver(low_event, "notification_sink")
            assert duplicate.outcome == "delivery_missing_or_busy"
        finally:
            release.set()
        assert (await asyncio.wait_for(consumer, 10)).acknowledge
        response = await asyncio.wait_for(stock, 10)
        assert response.status_code == 201, response.text
        assert (
            await deliver(low_event, "notification_sink")
        ).outcome == "durable_receipt_acknowledged"

    asyncio.run(scenario())
    for _, event in event_rows():
        if event.event_type == "inventory.state_changed.v1":
            assert asyncio.run(deliver(event, "alerts")).acknowledge
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM notification_stubs")) == 1
        assert (
            connection.scalar(text("SELECT outcome FROM notification_stubs"))
            == "created"
        )
        assert (
            connection.scalar(text("SELECT resolved_at FROM alert_episodes"))
            is not None
        )
        assert (
            connection.scalar(text("SELECT is_low FROM alert_ingredient_states"))
            is False
        )


def test_parallel_opening_events_share_lock_before_creating_history(
    authenticated_client,
):
    restaurant_id = create_restaurant(authenticated_client)
    create_ingredient(authenticated_client, restaurant_id, quantity="5", threshold="5")
    low = next(
        event for _, event in event_rows() if event.event_type == "inventory.low.v1"
    )
    state = next(
        event
        for _, event in event_rows()
        if event.event_type == "inventory.state_changed.v1"
    )

    async def scenario():
        inside, release = asyncio.Event(), asyncio.Event()

        async def hold(_claim):
            inside.set()
            await release.wait()

        execution = ConsumerExecutionService(
            AsyncSessionLocal, hooks=ExecutionHooks(before_commit=hold)
        )
        first = asyncio.create_task(
            execution.execute(
                event_id=low.event_id,
                consumer="alerts",
                reference=reference(low),
                worker_id="low-first",
            )
        )
        await asyncio.wait_for(inside.wait(), 10)
        second = asyncio.create_task(deliver(state, "alerts"))
        try:
            await wait_for_stock_lock_waiter()
        finally:
            release.set()
        assert (await asyncio.wait_for(first, 10)).outcome == "consumer_committed"
        assert (await asyncio.wait_for(second, 10)).outcome == "consumer_committed"

    asyncio.run(scenario())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alert_episodes")) == 1
        assert (
            connection.scalar(
                text("SELECT count(*) FROM event_receipts WHERE consumer_name='alerts'")
            )
            == 2
        )


def test_superseded_episode_snapshots_survive_rename_archive_and_rebuild(
    authenticated_client,
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(
        client, restaurant_id, name="Original rice", quantity="5", threshold="5"
    )
    ingredient_id = ingredient["id"]
    old_events = event_rows()
    old_low = next(
        event for _, event in old_events if event.event_type == "inventory.low.v1"
    )
    assert (
        change_stock(
            client, restaurant_id, ingredient_id, "still-low", "waste", "1"
        ).status_code
        == 201
    )
    assert (
        update_ingredient(
            client, restaurant_id, ingredient_id, name="Renamed rice"
        ).status_code
        == 200
    )
    assert (
        change_stock(
            client, restaurant_id, ingredient_id, "clear-stock", "waste", "4"
        ).status_code
        == 201
    )
    assert (
        update_ingredient(
            client, restaurant_id, ingredient_id, name="Renamed rice", active=False
        ).status_code
        == 200
    )
    assert (
        update_ingredient(
            client, restaurant_id, ingredient_id, name="Renamed rice", active=True
        ).status_code
        == 200
    )
    low_events = [
        event for _, event in event_rows() if event.event_type == "inventory.low.v1"
    ]
    assert (
        len(low_events) == 2
    )  # Repeated low deductions/rename never open another episode.
    for _, event in reversed(event_rows()):
        if event.event_type.startswith("inventory."):
            assert asyncio.run(deliver(event, "alerts")).acknowledge
    for event in low_events:
        assert asyncio.run(deliver(event, "notification_sink")).acknowledge

    async def rebuild():
        async with AsyncSessionLocal() as session, session.begin():
            await AlertProjectionService().rebuild(
                session, old_low.organization_id, restaurant_id
            )

    asyncio.run(rebuild())
    with engine.connect() as connection:
        episodes = (
            connection.execute(
                text("SELECT * FROM alert_episodes ORDER BY opening_revision")
            )
            .mappings()
            .all()
        )
        assert len(episodes) == 2
        assert episodes[0]["ingredient_name"] == "Original rice"
        assert episodes[0]["unit"] == "g"
        assert episodes[0]["opening_quantity"] == episodes[0]["opening_threshold"] == 5
        assert episodes[0]["resolution_reason"] == "archived"
        assert episodes[0]["opening_actor_user_id"] is not None
        assert episodes[0]["opening_source"] == "ingredient_creation"
        assert episodes[0]["resolution_source"] == "ingredient_update"
        assert episodes[1]["ingredient_name"] == "Renamed rice"
        assert episodes[1]["resolved_at"] is None
        assert (
            connection.scalar(text("SELECT episode_id FROM alert_ingredient_states"))
            == low_events[1].payload.episode_id
        )
        outcomes = dict(
            connection.execute(
                text("SELECT episode_id,outcome FROM notification_stubs")
            ).all()
        )
        assert outcomes[old_low.payload.episode_id] == "skipped"
        assert outcomes[low_events[1].payload.episode_id] == "created"


@pytest.mark.parametrize(
    "kind,consumer,table",
    [
        ("inventory.state_changed.v1", "alerts", "alert_episodes"),
        ("inventory.low.v1", "notification_sink", "notification_stubs"),
        ("menu.updated.v1", "notification_sink", "event_diagnostics"),
    ],
)
def test_actual_effects_roll_back_with_receipt_failure(
    authenticated_client, kind, consumer, table
):
    restaurant_id = create_restaurant(authenticated_client)
    create_ingredient(authenticated_client, restaurant_id, quantity="5", threshold="5")
    create_menu_item(authenticated_client, restaurant_id)
    event = next(event for _, event in event_rows() if event.event_type == kind)

    async def fail_before_commit(_claim):
        raise IntegrityError("injected receipt transaction failure", {}, Exception())

    async def scenario():
        service = ConsumerExecutionService(
            AsyncSessionLocal, hooks=ExecutionHooks(before_commit=fail_before_commit)
        )
        return await service.execute(
            event_id=event.event_id,
            consumer=consumer,
            reference=reference(event),
            worker_id="rollback-test",
        )

    assert asyncio.run(scenario()).outcome == "consumer_failed"
    with engine.connect() as connection:
        assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        assert connection.scalar(text("SELECT count(*) FROM event_receipts")) == 0
        assert (
            connection.scalar(text("SELECT count(*) FROM alert_ingredient_states")) == 0
        )


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
@pytest.mark.parametrize(
    "consumer,table",
    [("alerts", "alert_episodes"), ("notification_sink", "notification_stubs")],
)
def test_real_alert_and_sink_worker_crash_recovery(
    authenticated_client, tmp_path, monkeypatch, phase, consumer, table
):
    restaurant_id = create_restaurant(authenticated_client)
    create_ingredient(authenticated_client, restaurant_id, quantity="5", threshold="5")
    low = next(
        event for _, event in event_rows() if event.event_type == "inventory.low.v1"
    )
    settings = worker_settings()
    monkeypatch.setenv("EVENT_WORKER_TEST_REAL_CONSUMER", consumer)
    worker = start_process(tmp_path, settings, pause_at=phase)
    try:
        process_phase(worker, phase)
        with engine.connect() as connection:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == (
                0 if phase == "before_commit" else 1
            )
    finally:
        kill_process(worker)
    restarted = start_process(tmp_path, settings, module=True)
    try:

        def completed():
            with engine.connect() as connection:
                return (
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM event_receipts WHERE consumer_name=:consumer AND event_id=:id"
                        ),
                        {"consumer": consumer, "id": low.event_id},
                    )
                    == 1
                )

        wait_for(completed)
        with engine.connect() as connection:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 1
    finally:
        kill_process(restarted)
