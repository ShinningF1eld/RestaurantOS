"""Adversarial database constraints and races for Milestone 5 writes."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.main import app
from app.modules.audit.repo.models import AuditEntry
from app.modules.inventory.repo.models import InventoryBalance, InventoryMovement
from app.modules.orders.repo.models import Order
from conftest import engine
from test_order_inventory import (
    add_role_clients,
    balance,
    create_ingredient,
    create_menu_item,
    create_order,
    create_restaurant,
    movement_rows,
    overlap_after_restaurant_lock,
    set_recipe,
    update_order,
)


def ingredient_state(client: TestClient, restaurant_id: int, ingredient_id: int) -> tuple[Decimal, int]:
    response = client.get(
        f"/api/restaurants/{restaurant_id}/inventory/ingredients"
    )
    assert response.status_code == 200, response.text
    row = next(value for value in response.json() if value["id"] == ingredient_id)
    return Decimal(row["quantity"]), row["version"]


def tracked_order(client: TestClient, restaurant_id: int, menu_item_id: int):
    ingredient = create_ingredient(
        client, restaurant_id, name="Constraint stock", quantity="10"
    )
    recipe = set_recipe(
        client,
        menu_item_id,
        [{"ingredient_id": ingredient["id"], "quantity": "3"}],
    )
    assert recipe.status_code == 200, recipe.text
    created = create_order(client, restaurant_id, menu_item_id, 2)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    submitted = update_order(client, order_id, "SUBMITTED")
    assert submitted.status_code == 200, submitted.text
    return ingredient, order_id


def test_concurrent_same_key_order_creates_replay_one_original_snapshot(
    authenticated_client, auth_user, monkeypatch
):
    owner = authenticated_client
    restaurant = create_restaurant(owner, "Concurrent submission")
    item = create_menu_item(owner, restaurant, "Idempotent dish")
    managers = add_role_clients(auth_user, restaurant, ("MANAGER", "MANAGER"))
    first_client, second_client = managers[0][0], managers[1][0]
    try:
        payload = {
            "idempotency_key": "shared-order-key",
            "customer_name": "Same request",
            "items": [{"menu_item_id": item, "quantity": 1}],
        }
        first, second = overlap_after_restaurant_lock(
            monkeypatch,
            lambda: first_client.post(
                f"/api/restaurants/{restaurant}/orders", json=payload
            ),
            lambda: second_client.post(
                f"/api/restaurants/{restaurant}/orders", json=payload
            ),
        )
        assert first.status_code == second.status_code == 201
        assert first.json() == second.json()
        order_id = first.json()["order_id"]
        with engine.connect() as db:
            assert (
                db.scalar(
                    text("SELECT count(*) FROM orders WHERE restaurant_id=:id"),
                    {"id": restaurant},
                )
                == 1
            )
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM order_submissions "
                        "WHERE restaurant_id=:restaurant AND idempotency_key=:key"
                    ),
                    {"restaurant": restaurant, "key": payload["idempotency_key"]},
                )
                == 1
            )
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM audit_entries "
                        "WHERE action='order.created' AND resource_id=:id"
                    ),
                    {"id": str(order_id)},
                )
                == 1
            )
    finally:
        for client, _ in managers:
            client.close()


@pytest.mark.parametrize("failure_point", ["balance", "movement", "order", "audit"])
def test_database_constraint_failures_during_acceptance_roll_back_all_rows(
    authenticated_client, failure_point
):
    client = authenticated_client
    restaurant = create_restaurant(client, f"DB constraint {failure_point}")
    item = create_menu_item(client, restaurant)
    ingredient, order_id = tracked_order(client, restaurant, item)
    before_order = client.get(f"/api/orders/{order_id}").json()
    before_balance = ingredient_state(client, restaurant, ingredient["id"])
    before_audit = client.get("/api/audit?limit=100").json()
    assert movement_rows(order_id) == []

    def violate_database_constraint(session, flush_context, instances):
        if failure_point == "balance":
            for row in session.dirty:
                if (
                    isinstance(row, InventoryBalance)
                    and row.ingredient_id == ingredient["id"]
                ):
                    row.quantity = Decimal("-1")
        elif failure_point == "movement":
            for row in session.new:
                if isinstance(row, InventoryMovement) and row.order_id == order_id:
                    row.quantity_delta = Decimal("1")
        elif failure_point == "order":
            for row in session.dirty:
                if isinstance(row, Order) and row.order_id == order_id:
                    row.status = None
        elif failure_point == "audit":
            for row in session.new:
                if (
                    isinstance(row, AuditEntry)
                    and row.resource_type == "order"
                    and row.resource_id == str(order_id)
                    and row.action == "order.updated"
                ):
                    row.action = ""

    event.listen(Session, "before_flush", violate_database_constraint)
    try:
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            failing_client.cookies.update(client.cookies)
            failing_client.headers.update(client.headers)
            response = update_order(failing_client, order_id, "ACCEPTED")
    finally:
        event.remove(Session, "before_flush", violate_database_constraint)

    assert response.status_code == 500, response.text
    assert client.get(f"/api/orders/{order_id}").json() == before_order
    assert ingredient_state(client, restaurant, ingredient["id"]) == before_balance
    assert movement_rows(order_id) == []
    assert client.get("/api/audit?limit=100").json() == before_audit
    with engine.connect() as db:
        assert db.scalar(
            text("SELECT inventory_processed FROM orders WHERE order_id=:id"),
            {"id": order_id},
        ) is False


def test_duplicate_consumption_for_one_order_violates_database_unique_constraint(
    authenticated_client,
):
    client = authenticated_client
    restaurant = create_restaurant(client, "Consumption uniqueness")
    item = create_menu_item(client, restaurant)
    ingredient, order_id = tracked_order(client, restaurant, item)
    assert update_order(client, order_id, "ACCEPTED").status_code == 200
    existing = movement_rows(order_id)
    assert len(existing) == 1
    assert balance(client, restaurant, ingredient["id"]) == Decimal("4")

    with pytest.raises(IntegrityError) as failure:
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO inventory_movements "
                    "(ingredient_id, kind, quantity_delta, balance_after, "
                    "version_after, actor_user_id, order_id, reason, "
                    "idempotency_key, request_fingerprint, occurred_at) "
                    "VALUES (:ingredient, 'consumption', -1, 3, 3, NULL, :order, "
                    "'duplicate order consumption', NULL, NULL, CURRENT_TIMESTAMP)"
                ),
                {"ingredient": ingredient["id"], "order": order_id},
            )
    assert (
        failure.value.orig.diag.constraint_name
        == "uq_inventory_movement_order_ingredient"
    )
    assert len(movement_rows(order_id)) == 1
    assert balance(client, restaurant, ingredient["id"]) == Decimal("4")


def test_recipe_audit_failure_restores_previous_tracking_components_and_audit(
    authenticated_client, monkeypatch
):
    client = authenticated_client
    restaurant = create_restaurant(client, "Recipe audit rollback")
    item = create_menu_item(client, restaurant)
    first = create_ingredient(client, restaurant, name="Original ingredient", quantity="5")
    second = create_ingredient(client, restaurant, name="Replacement ingredient", quantity="5")
    original_recipe = set_recipe(
        client,
        item,
        [{"ingredient_id": first["id"], "quantity": "2"}],
    )
    assert original_recipe.status_code == 200, original_recipe.text
    before_recipe = client.get(f"/menu-items/{item}/recipe").json()
    before_audit = client.get("/api/audit?limit=100").json()

    import app.modules.recipes.service as recipe_service

    def fail_recipe_audit(session, context, action, *args, **kwargs):
        if action == "menu_item.recipe.updated":
            raise RuntimeError("injected recipe audit failure")

    monkeypatch.setattr(recipe_service, "record", fail_recipe_audit)
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        failing_client.cookies.update(client.cookies)
        failing_client.headers.update(client.headers)
        response = set_recipe(
            failing_client,
            item,
            [{"ingredient_id": second["id"], "quantity": "1"}],
            tracked=False,
        )
    assert response.status_code == 500, response.text
    assert client.get(f"/menu-items/{item}/recipe").json() == before_recipe
    assert client.get("/api/audit?limit=100").json() == before_audit
    assert client.get(f"/menu-items/{item}").json()["inventory_tracking"] is True


def test_deactivated_draft_item_cannot_be_submitted_without_stock_changes(
    authenticated_client,
):
    client = authenticated_client
    restaurant = create_restaurant(client, "Unavailable draft")
    item = create_menu_item(client, restaurant)
    ingredient = create_ingredient(client, restaurant, name="Unavailable dish stock", quantity="10")
    assert set_recipe(
        client, item, [{"ingredient_id": ingredient["id"], "quantity": "2"}]
    ).status_code == 200
    created = create_order(client, restaurant, item)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]

    unavailable = client.put(f"/menu-items/{item}", json={"is_available": False})
    assert unavailable.status_code == 200, unavailable.text
    submitted = update_order(client, order_id, "SUBMITTED")
    assert submitted.status_code == 409, submitted.text
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "DRAFT"
    assert balance(client, restaurant, ingredient["id"]) == Decimal("10")
    assert movement_rows(order_id) == []


def test_draft_item_replacement_checks_aggregated_portions_atomically(
    authenticated_client,
):
    client = authenticated_client
    restaurant = create_restaurant(client, "Draft aggregate")
    item = create_menu_item(client, restaurant)
    ingredient = create_ingredient(client, restaurant, name="Aggregate draft stock", quantity="10")
    assert set_recipe(
        client, item, [{"ingredient_id": ingredient["id"], "quantity": "2"}]
    ).status_code == 200
    created = create_order(client, restaurant, item)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]

    fits = client.put(
        f"/api/orders/{order_id}",
        json={"items": [{"menu_item_id": item, "quantity": 3}]},
    )
    assert fits.status_code == 200, fits.text
    assert [row["quantity"] for row in fits.json()["items"]] == [3]
    before = client.get(f"/api/orders/{order_id}").json()

    exceeds = client.put(
        f"/api/orders/{order_id}",
        json={
            "items": [
                {"menu_item_id": item, "quantity": 3},
                {"menu_item_id": item, "quantity": 3},
            ]
        },
    )
    assert exceeds.status_code == 409, exceeds.text
    assert client.get(f"/api/orders/{order_id}").json() == before
    assert balance(client, restaurant, ingredient["id"]) == Decimal("10")
    assert movement_rows(order_id) == []
