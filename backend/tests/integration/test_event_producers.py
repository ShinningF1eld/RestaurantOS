"""T3 producer integration: real transactions, genuine changes and command facts."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError

from app.modules.events.domain.subscriptions import consumers_for
from conftest import engine
from integration.test_inventory_episodes import (
    change_stock,
    create_ingredient,
    update_ingredient,
)
from integration.test_order_inventory import (
    create_menu_item,
    create_order,
    create_restaurant,
    set_recipe,
    update_order,
    add_role_clients,
)


def rows(table):
    with engine.connect() as db:
        ordering = " ORDER BY occurred_at, event_id" if table == "outbox_events" else ""
        return [
            dict(row)
            for row in db.execute(text(f"SELECT * FROM {table}{ordering}")).mappings()
        ]


def events(kind=None):
    result = rows("outbox_events")
    return [e for e in result if kind is None or e["event_type"] == kind]


def assert_fanout():
    deliveries = rows("event_deliveries")
    for e in events():
        actual = [
            d["consumer_name"] for d in deliveries if d["event_id"] == e["event_id"]
        ]
        assert sorted(actual) == sorted(consumers_for(e["event_type"]))


def tracked_order(client):
    restaurant = create_restaurant(client)
    item = create_menu_item(client, restaurant)
    ingredient = create_ingredient(client, restaurant, quantity="10", threshold="5")
    assert (
        set_recipe(
            client, item, [{"ingredient_id": ingredient["id"], "quantity": "6"}]
        ).status_code
        == 200
    )
    created = create_order(client, restaurant, item, key="original-order")
    assert created.status_code == 201, created.text
    order = created.json()["order_id"]
    assert update_order(client, order, "SUBMITTED").status_code == 200
    return restaurant, item, ingredient, order


def test_order_lifecycle_authoritative_snapshots_correlation_and_retries(
    authenticated_client,
):
    client = authenticated_client
    restaurant, item, ingredient, order = tracked_order(client)
    before = len(events())
    client.headers["X-Request-ID"] = "accept-command"
    assert update_order(client, order, "ACCEPTED").status_code == 200
    new = events()[before:]
    assert {e["event_type"] for e in new} == {
        "order.accepted.v1",
        "inventory.state_changed.v1",
        "inventory.low.v1",
    }
    assert {e["correlation_id"] for e in new} == {"accept-command"}
    assert update_order(client, order, "ACCEPTED").status_code == 200
    # Creation replay remains the original draft snapshot and emits nothing.
    replay = create_order(client, restaurant, item, key="original-order")
    assert replay.status_code == 201 and replay.json()["status"] == "DRAFT"
    assert (
        create_order(
            client, restaurant, item, quantity=2, key="original-order"
        ).status_code
        == 409
    )
    assert len(events()) == before + 3
    # A later catalog price cannot rewrite the order's authoritative snapshot.
    assert client.put(f"/menu-items/{item}", json={"price": "99.00"}).status_code == 200
    for status in ("PREPARING", "READY", "COMPLETED"):
        assert update_order(client, order, status).status_code == 200
    completion = events("order.completed.v1")[0]
    stored = rows("orders")[0]
    assert completion["payload"]["total"] == "12.00"
    assert (
        completion["payload"]["created_at"].rstrip("Z")
        == stored["created_at"].isoformat()
    )
    assert completion["aggregate_revision"] == stored["revision"] == 6
    assert "customer_name" not in completion["payload"]
    before = len(events())
    assert update_order(client, order, "COMPLETED").status_code == 200
    assert client.get(f"/api/orders/{order}").status_code == 200
    assert client.get(f"/api/restaurants/{restaurant}/orders").status_code == 200
    assert len(events()) == before
    assert rows("orders")[0]["revision"] == 6
    assert_fanout()


def test_cancellation_has_no_inventory_event_or_restock(authenticated_client):
    client = authenticated_client
    _, _, _, order = tracked_order(client)
    assert update_order(client, order, "ACCEPTED").status_code == 200
    stock = rows("inventory_balances")
    movements = rows("inventory_movements")
    before = len(events())
    assert update_order(client, order, "CANCELLED").status_code == 200
    assert update_order(client, order, "CANCELLED").status_code == 200
    assert rows("inventory_balances") == stock
    assert rows("inventory_movements") == movements
    assert len(events()) == before + 1
    assert events("order.cancelled.v1")[0]["aggregate_revision"] == 4


def test_deletion_tombstone_survives_order_and_completion(authenticated_client):
    client = authenticated_client
    restaurant = create_restaurant(client)
    # Seed a representative legacy order without protected stock/replay history.
    with engine.begin() as db:
        order = db.scalar(
            text(
                "INSERT INTO orders (restaurant_id,status,payment_status,subtotal,total,created_at,updated_at,revision) VALUES (:r,'READY','PAID',17.25,17.25,'2026-10-01 23:59:00','2026-10-01',7) RETURNING order_id"
            ),
            {"r": restaurant},
        )
    assert update_order(client, order, "COMPLETED").status_code == 200
    assert client.delete(f"/api/orders/{order}").status_code == 204
    assert rows("orders") == []
    deleted = events("order.deleted.v1")[0]
    assert deleted["aggregate_revision"] == 9
    assert deleted["aggregate_id"] == str(order)
    assert deleted["payload"] == {
        "order_id": order,
        "prior_status": "COMPLETED",
        "total": "17.25",
        "created_at": "2026-10-01T23:59:00Z",
    }
    assert events("order.completed.v1")[0]["aggregate_revision"] == 8
    assert_fanout()


def test_catalog_operations_noops_and_monotonic_revisions(authenticated_client):
    client = authenticated_client
    restaurant = create_restaurant(client)
    item = create_menu_item(client, restaurant)
    menu = rows("menus")[0]["menu_id"]
    before = len(events())
    assert client.put(f"/menus/{menu}", json={"name": "Main"}).status_code == 200
    assert (
        client.put(
            f"/menu-items/{item}",
            json={"name": "Tracked dish", "price": "12.00", "is_available": True},
        ).status_code
        == 200
    )
    assert client.get(f"/restaurants/{restaurant}/menus").status_code == 200
    assert client.get(f"/menus/{menu}/items").status_code == 200
    assert len(events()) == before
    assert client.put(f"/menus/{menu}", json={"name": "Dinner"}).status_code == 200
    assert client.put(f"/menu-items/{item}", json={"price": "13.00"}).status_code == 200
    assert client.delete(f"/menu-items/{item}").status_code == 200
    assert client.delete(f"/menus/{menu}").status_code == 200
    menu_events = [e for e in events() if e["aggregate_type"] == "menu"]
    item_events = [e for e in events() if e["aggregate_type"] == "menu_item"]
    for sequence in (menu_events, item_events):
        sequence.sort(key=lambda e: e["aggregate_revision"])
        assert [e["aggregate_revision"] for e in sequence] == [1, 2, 3]
        assert [e["payload"]["operation"] for e in sequence] == [
            "created",
            "edited",
            "deleted",
        ]
    assert all(e["payload"]["affected_menu_item_ids"] == [item] for e in item_events)
    assert_fanout()


def test_repeated_deactivation_has_one_event(authenticated_client):
    client = authenticated_client
    restaurant = create_restaurant(client)
    item = create_menu_item(client, restaurant)
    assert create_order(client, restaurant, item).status_code == 201
    before = len(events())
    for _ in range(2):
        assert client.delete(f"/menu-items/{item}").status_code == 200
    assert len(events()) == before + 1
    assert events()[-1]["payload"]["operation"] == "deactivated"


def test_inventory_episodes_noop_count_replay_threshold_archive_restore(
    authenticated_client,
):
    client = authenticated_client
    restaurant = create_restaurant(client)
    ingredient = create_ingredient(client, restaurant, quantity="4", threshold="5")
    iid = ingredient["id"]
    assert len(events("inventory.low.v1")) == 1
    before = len(events())
    assert update_ingredient(client, restaurant, iid).status_code == 200
    assert (
        change_stock(client, restaurant, iid, "no-effect", "count", "4", 1).status_code
        == 201
    )
    assert len(events()) == before
    for _ in range(2):
        assert (
            change_stock(client, restaurant, iid, "waste", "waste", "1").status_code
            == 201
        )
    assert len(events("inventory.low.v1")) == 1
    assert update_ingredient(client, restaurant, iid, threshold="2").status_code == 200
    assert (
        events("inventory.state_changed.v1")[-1]["payload"]["resolution_reason"]
        == "threshold_changed"
    )
    assert update_ingredient(client, restaurant, iid, threshold="3").status_code == 200
    assert len(events("inventory.low.v1")) == 2
    assert (
        change_stock(client, restaurant, iid, "zero", "count", "0", 3).status_code
        == 201
    )
    assert (
        update_ingredient(
            client, restaurant, iid, threshold="3", active=False
        ).status_code
        == 200
    )
    assert (
        events("inventory.state_changed.v1")[-1]["payload"]["resolution_reason"]
        == "archived"
    )
    assert (
        update_ingredient(
            client, restaurant, iid, threshold="3", active=True
        ).status_code
        == 200
    )
    assert len(events("inventory.low.v1")) == 3
    assert len({e["payload"]["episode_id"] for e in events("inventory.low.v1")}) == 3
    assert (
        change_stock(client, restaurant, iid, "recover", "receipt", "4").status_code
        == 201
    )
    assert (
        events("inventory.state_changed.v1")[-1]["payload"]["resolution_reason"]
        == "stock_recovered"
    )
    assert len(events("inventory.low.v1")) == 3
    assert_fanout()


def test_legacy_low_state_change_does_not_invent_episode(authenticated_client):
    client = authenticated_client
    restaurant = create_restaurant(client)
    # Legacy initialization belongs to T8, not an ordinary business command.
    with engine.begin() as db:
        iid = db.scalar(
            text(
                "INSERT INTO inventory_ingredients (restaurant_id,name,normalized_name,unit,reorder_threshold,is_active,created_at,updated_at) VALUES (:r,'Rice','rice','g',5,true,now(),now()) RETURNING id"
            ),
            {"r": restaurant},
        )
        db.execute(
            text(
                "INSERT INTO inventory_balances (ingredient_id,quantity,version) VALUES (:i,3,1)"
            ),
            {"i": iid},
        )
    assert (
        change_stock(client, restaurant, iid, "legacy", "waste", "1").status_code == 201
    )
    state = events("inventory.state_changed.v1")[0]
    assert state["payload"]["is_low"] is True
    assert state["payload"]["episode_id"] is None
    assert events("inventory.low.v1") == []
    assert rows("inventory_low_stock_episodes") == []


@pytest.mark.parametrize("operation", ["accept", "catalog", "stock"])
@pytest.mark.parametrize("failure", ["audit", "event", "delivery", "flush"])
def test_failures_roll_back_complete_business_command(
    authenticated_client, monkeypatch, operation, failure
):
    client = authenticated_client
    restaurant, item, ingredient, order = tracked_order(client)
    tables = (
        "orders",
        "order_items",
        "menus",
        "menu_items",
        "inventory_ingredients",
        "inventory_balances",
        "inventory_movements",
        "inventory_low_stock_episodes",
        "audit_entries",
        "outbox_events",
        "event_deliveries",
    )
    before = {table: rows(table) for table in tables}
    if failure == "flush":
        original = AsyncSession.flush

        async def fail_flush(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            # Fail after event and fan-out were actually flushed.
            if await self.scalar(text("SELECT count(*) FROM event_deliveries")) > len(
                before["event_deliveries"]
            ):
                # A separate connection cannot see the business mutation or
                # even the partially flushed events/fan-out before commit.
                for table in tables:
                    assert rows(table) == before[table], table
                raise RuntimeError("injected flush failure")

        monkeypatch.setattr(AsyncSession, "flush", fail_flush)
    else:
        rejected_table = {
            "audit": "audit_entries",
            "event": "outbox_events",
            "delivery": "event_deliveries",
        }[failure]
        # Accept stock state fan-out first; reject notification fan-out later.
        condition = (
            "IF NEW.consumer_name <> 'notification_sink' THEN RETURN NEW; END IF;"
            if failure == "delivery"
            else ""
        )
        with engine.begin() as db:
            db.execute(
                text(
                    f"CREATE FUNCTION t3_reject() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {condition} RAISE EXCEPTION 'injected {failure} failure'; END $$"
                )
            )
            db.execute(
                text(
                    f"CREATE TRIGGER t3_reject BEFORE INSERT ON {rejected_table} FOR EACH ROW EXECUTE FUNCTION t3_reject()"
                )
            )
    try:
        with pytest.raises((DBAPIError, RuntimeError), match="injected"):
            if operation == "accept":
                update_order(client, order, "ACCEPTED")
            elif operation == "catalog":
                client.put(f"/menu-items/{item}", json={"price": "99.00"})
            else:
                change_stock(
                    client, restaurant, ingredient["id"], "failed-waste", "waste", "6"
                )
        for table in tables:
            assert rows(table) == before[table], table
    finally:
        if failure != "flush":
            with engine.begin() as db:
                db.execute(text(f"DROP TRIGGER t3_reject ON {rejected_table}"))
                db.execute(text("DROP FUNCTION t3_reject()"))


@pytest.mark.parametrize("second_name,expected_events", [("Evening", 1), ("Late", 2)])
def test_overlapping_catalog_updates_use_locked_state_and_unique_revisions(
    authenticated_client,
    auth_user,
    monkeypatch,
    second_name,
    expected_events,
):
    client = authenticated_client
    restaurant = create_restaurant(client)
    create_menu_item(client, restaurant)
    menu = rows("menus")[0]["menu_id"]
    ((manager, _),) = add_role_clients(auth_user, restaurant, ("MANAGER",))
    # Model one real API event loop, including its lifespan-owned Redis pool.
    monkeypatch.setattr(manager, "portal", client.portal)
    from app.modules.inventory.repo.queries import InventoryRepository

    original_lock = InventoryRepository.lock_restaurant
    first_locked, second_entered, release_first = Event(), Event(), Event()
    calls = 0

    async def controlled_lock(self, restaurant_id):
        nonlocal calls
        calls += 1
        ordinal = calls
        if ordinal == 1:
            await original_lock(self, restaurant_id)
            first_locked.set()
            if not await asyncio.to_thread(release_first.wait, 15):
                raise TimeoutError("Second command did not reach held restaurant lock")
        else:
            second_entered.set()
            await original_lock(self, restaurant_id)

    monkeypatch.setattr(InventoryRepository, "lock_restaurant", controlled_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.put, f"/menus/{menu}", json={"name": "Evening"})
            try:
                assert first_locked.wait(15)
                second = pool.submit(
                    manager.put, f"/menus/{menu}", json={"name": second_name}
                )
                assert second_entered.wait(15)
                assert not second.done(), "Second command passed held restaurant lock"
            finally:
                release_first.set()
            first, second = first.result(30), second.result(30)
        assert first.status_code == second.status_code == 200
        changes = [e for e in events() if e["aggregate_type"] == "menu"]
        assert [e["aggregate_revision"] for e in changes] == list(
            range(1, expected_events + 2)
        )
        assert rows("menus")[0]["name"] == second_name
        assert_fanout()
    finally:
        manager.close()


def test_ingredient_creation_replay_and_mismatch_emit_nothing(authenticated_client):
    client = authenticated_client
    restaurant = create_restaurant(client)
    path = f"/api/restaurants/{restaurant}/inventory/ingredients"
    data = {
        "name": "Rice",
        "unit": "g",
        "opening_quantity": "0",
        "reorder_threshold": "0",
        "idempotency_key": "ingredient-retry",
    }
    first = client.post(path, json=data)
    assert first.status_code == 201
    original = events()
    assert len(original) == 2
    assert len({e["correlation_id"] for e in original}) == 1
    assert client.post(path, json=data).status_code == 201
    assert client.post(path, json={**data, "opening_quantity": "1"}).status_code == 409
    assert client.get(path).status_code == 200
    assert events() == original
    assert_fanout()
