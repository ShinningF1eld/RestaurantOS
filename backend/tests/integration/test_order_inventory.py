"""PostgreSQL tests for recipe stock checks and atomic order consumption."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event, Lock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from conftest import engine


def create_restaurant(client: TestClient, name: str = "Order inventory") -> int:
    response = client.post("/api/restaurants", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_menu_item(
    client: TestClient, restaurant_id: int, name: str = "Tracked dish"
) -> int:
    menu = client.post(f"/restaurants/{restaurant_id}/menus", json={"name": "Main"})
    assert menu.status_code == 200, menu.text
    item = client.post(
        f"/menus/{menu.json()['menu_id']}/items",
        json={"name": name, "price": "12.00", "is_available": True},
    )
    assert item.status_code == 200, item.text
    return item.json()["menu_item_id"]


def create_ingredient(
    client: TestClient,
    restaurant_id: int,
    *,
    name: str,
    quantity: str,
    unit: str = "g",
) -> dict:
    response = client.post(
        f"/api/restaurants/{restaurant_id}/inventory/ingredients",
        json={
            "name": name,
            "unit": unit,
            "reorder_threshold": "0",
            "opening_quantity": quantity,
            "idempotency_key": uuid4().hex,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def set_recipe(
    client: TestClient,
    menu_item_id: int,
    components: list[dict],
    *,
    tracked: bool = True,
):
    return client.put(
        f"/menu-items/{menu_item_id}/recipe",
        json={"inventory_tracking": tracked, "components": components},
    )


def create_order(
    client: TestClient,
    restaurant_id: int,
    menu_item_id: int,
    quantity: int = 1,
    *,
    key: str | None = None,
    **fields,
):
    return client.post(
        f"/api/restaurants/{restaurant_id}/orders",
        json={
            "idempotency_key": key or uuid4().hex,
            "items": [{"menu_item_id": menu_item_id, "quantity": quantity}],
            **fields,
        },
    )


def update_order(client: TestClient, order_id: int, status: str):
    return client.put(f"/api/orders/{order_id}", json={"status": status})


def balance(client: TestClient, restaurant_id: int, ingredient_id: int) -> Decimal:
    response = client.get(f"/api/restaurants/{restaurant_id}/inventory/ingredients")
    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["id"] == ingredient_id)
    return Decimal(item["quantity"])


def movement_rows(order_id: int) -> list[dict]:
    with engine.connect() as db:
        rows = db.execute(
            text(
                "SELECT ingredient_id, kind, quantity_delta, balance_after, "
                "version_after, order_id, actor_user_id, reason "
                "FROM inventory_movements WHERE order_id=:order_id "
                "ORDER BY ingredient_id"
            ),
            {"order_id": order_id},
        ).mappings()
        return [dict(row) for row in rows]


def add_role_clients(auth_user, restaurant_id: int, roles: tuple[str, ...]):
    """Provision distinct, assigned staff sessions for real concurrent requests."""
    accounts = []
    with engine.begin() as db:
        password_hash = db.scalar(
            text("SELECT password_hash FROM users WHERE id=:id"),
            {"id": auth_user["id"]},
        )
        for role in roles:
            user_id, membership_id = uuid4(), uuid4()
            email = f"m5-{role.lower()}-{uuid4().hex[:10]}@example.test"
            db.execute(
                text(
                    "INSERT INTO users (id,email,password_hash) "
                    "VALUES (:id,:email,:hash)"
                ),
                {"id": user_id, "email": email, "hash": password_hash},
            )
            db.execute(
                text(
                    "INSERT INTO memberships (id,user_id,organization_id,role) "
                    "VALUES (:id,:user,:org,:role)"
                ),
                {
                    "id": membership_id,
                    "user": user_id,
                    "org": auth_user["organization_id"],
                    "role": role,
                },
            )
            db.execute(
                text(
                    "INSERT INTO restaurant_assignments "
                    "(membership_id,organization_id,restaurant_id) "
                    "VALUES (:membership,:org,:restaurant)"
                ),
                {
                    "membership": membership_id,
                    "org": auth_user["organization_id"],
                    "restaurant": restaurant_id,
                },
            )
            accounts.append((str(user_id), email))

    clients = []
    try:
        for user_id, email in accounts:
            client = TestClient(app)
            client.headers.update(
                {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
            )
            login = client.post(
                "/auth/login",
                json={"email": email, "password": auth_user["password"]},
            )
            assert login.status_code == 200, login.text
            clients.append((client, user_id))
        return clients
    except BaseException:
        for client, _ in clients:
            client.close()
        raise


def overlap_after_restaurant_lock(monkeypatch, first_request, second_request):
    """Make the second HTTP request reach the shared restaurant lock while held."""
    from app.modules.inventory.repo.queries import InventoryRepository

    original = InventoryRepository.lock_restaurant
    first_locked = Event()
    second_entered = Event()
    release_first = Event()
    call_lock = Lock()
    calls = 0

    async def controlled_lock(self, restaurant_id):
        nonlocal calls
        with call_lock:
            calls += 1
            ordinal = calls
        if ordinal == 1:
            await original(self, restaurant_id)
            first_locked.set()
            if not release_first.wait(timeout=15):
                raise TimeoutError(
                    "Concurrent request did not reach the restaurant lock"
                )
            return
        if ordinal == 2:
            second_entered.set()
        await original(self, restaurant_id)

    monkeypatch.setattr(InventoryRepository, "lock_restaurant", controlled_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_request)
        try:
            assert first_locked.wait(timeout=15)
            second = pool.submit(second_request)
            assert second_entered.wait(timeout=15)
            assert not second.done(), "second write passed the held restaurant lock"
        finally:
            release_first.set()
        return first.result(timeout=30), second.result(timeout=30)


@pytest.fixture
def tracked_setup(authenticated_client):
    client = authenticated_client
    restaurant = create_restaurant(client)
    menu_item = create_menu_item(client, restaurant)
    return client, restaurant, menu_item


def test_acceptance_deducts_aggregated_recipe_once_and_later_states_do_not_deduct(
    tracked_setup,
):
    client, restaurant, item = tracked_setup
    flour = create_ingredient(client, restaurant, name="Flour", quantity="50")
    eggs = create_ingredient(
        client, restaurant, name="Eggs", quantity="20", unit="piece"
    )
    saved = set_recipe(
        client,
        item,
        [
            {"ingredient_id": flour["id"], "quantity": "1.250"},
            {"ingredient_id": eggs["id"], "quantity": "2"},
        ],
    )
    assert saved.status_code == 200, saved.text

    created = client.post(
        f"/api/restaurants/{restaurant}/orders",
        json={
            "idempotency_key": "aggregate-stock-order",
            "items": [
                {"menu_item_id": item, "quantity": 1},
                {"menu_item_id": item, "quantity": 2},
            ],
        },
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    assert balance(client, restaurant, flour["id"]) == Decimal("50")
    assert balance(client, restaurant, eggs["id"]) == Decimal("20")

    submitted = update_order(client, order_id, "SUBMITTED")
    assert submitted.status_code == 200, submitted.text
    assert balance(client, restaurant, flour["id"]) == Decimal("50")
    assert balance(client, restaurant, eggs["id"]) == Decimal("20")

    accepted = update_order(client, order_id, "ACCEPTED")
    assert accepted.status_code == 200, accepted.text
    assert balance(client, restaurant, flour["id"]) == Decimal("46.250")
    assert balance(client, restaurant, eggs["id"]) == Decimal("14")
    assert update_order(client, order_id, "ACCEPTED").status_code == 200
    for status in ("PREPARING", "READY", "COMPLETED"):
        response = update_order(client, order_id, status)
        assert response.status_code == 200, response.text

    assert balance(client, restaurant, flour["id"]) == Decimal("46.250")
    assert balance(client, restaurant, eggs["id"]) == Decimal("14")
    rows = movement_rows(order_id)
    assert len(rows) == 2
    assert [(row["ingredient_id"], row["kind"]) for row in rows] == [
        (flour["id"], "consumption"),
        (eggs["id"], "consumption"),
    ]
    assert [Decimal(row["quantity_delta"]) for row in rows] == [
        Decimal("-3.750"),
        Decimal("-6.000"),
    ]
    assert [Decimal(row["balance_after"]) for row in rows] == [
        Decimal("46.250"),
        Decimal("14.000"),
    ]
    assert [row["version_after"] for row in rows] == [2, 2]
    assert all(row["order_id"] == order_id for row in rows)
    assert all(row["actor_user_id"] is not None for row in rows)
    assert all(row["reason"] == f"Order {order_id} accepted" for row in rows)
    assert len({row["ingredient_id"] for row in rows}) == len(rows)
    with engine.connect() as db:
        processed = db.scalar(
            text("SELECT inventory_processed FROM orders WHERE order_id=:id"),
            {"id": order_id},
        )
    assert processed is True


def test_order_idempotency_replays_original_snapshot_after_updates(tracked_setup):
    client, restaurant, item = tracked_setup
    payload = {
        "idempotency_key": "replay-snapshot",
        "customer_name": "Initial customer",
        "items": [{"menu_item_id": item, "quantity": 1}],
    }
    created = client.post(f"/api/restaurants/{restaurant}/orders", json=payload)
    assert created.status_code == 201, created.text
    original = created.json()
    order_id = original["order_id"]
    update = client.put(
        f"/api/orders/{order_id}", json={"customer_name": "Updated customer"}
    )
    assert update.status_code == 200, update.text
    assert update.json()["customer_name"] == "Updated customer"

    replay = client.post(f"/api/restaurants/{restaurant}/orders", json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json() == original

    changed = client.post(
        f"/api/restaurants/{restaurant}/orders",
        json={**payload, "items": [{"menu_item_id": item, "quantity": 2}]},
    )
    assert changed.status_code == 409, changed.text
    with engine.connect() as db:
        submissions = db.scalar(
            text(
                "SELECT count(*) FROM order_submissions "
                "WHERE restaurant_id=:restaurant AND idempotency_key=:key"
            ),
            {"restaurant": restaurant, "key": payload["idempotency_key"]},
        )
    assert submissions == 1


def test_unconsumed_order_delete_keeps_its_idempotency_snapshot(tracked_setup):
    client, restaurant, item = tracked_setup
    key = "deleted-order-replay"
    created = create_order(client, restaurant, item, key=key)
    assert created.status_code == 201, created.text
    original = created.json()
    order_id = original["order_id"]

    deleted = client.delete(f"/api/orders/{order_id}")
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/orders/{order_id}").status_code == 404

    replay = create_order(client, restaurant, item, key=key)
    assert replay.status_code == 201, replay.text
    assert replay.json() == original
    assert client.get(f"/api/orders/{order_id}").status_code == 404
    with engine.connect() as db:
        orders = db.scalar(
            text("SELECT count(*) FROM orders WHERE order_id=:id"), {"id": order_id}
        )
        submissions = db.scalar(
            text("SELECT count(*) FROM order_submissions WHERE idempotency_key=:key"),
            {"key": key},
        )
    assert orders == 0
    assert submissions == 1


def test_insufficient_later_ingredient_rolls_back_prior_consumption_and_order_update(
    tracked_setup,
):
    client, restaurant, item = tracked_setup
    first = create_ingredient(client, restaurant, name="A flour", quantity="20")
    second = create_ingredient(client, restaurant, name="B eggs", quantity="10")
    assert (
        set_recipe(
            client,
            item,
            [
                {"ingredient_id": first["id"], "quantity": "2"},
                {"ingredient_id": second["id"], "quantity": "2"},
            ],
        ).status_code
        == 200
    )
    created = create_order(client, restaurant, item, 2)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    assert update_order(client, order_id, "SUBMITTED").status_code == 200

    waste = client.post(
        f"/api/restaurants/{restaurant}/inventory/ingredients/{second['id']}/movements",
        json={
            "kind": "waste",
            "quantity": "8",
            "reason": "Unexpected spoilage",
            "idempotency_key": "create-shortage",
        },
    )
    assert waste.status_code == 201, waste.text
    with engine.connect() as db:
        audit_before = db.scalar(
            text(
                "SELECT count(*) FROM audit_entries WHERE resource_type='order' "
                "AND resource_id=:id"
            ),
            {"id": str(order_id)},
        )

    accepted = update_order(client, order_id, "ACCEPTED")
    assert accepted.status_code == 409, accepted.text
    persisted = client.get(f"/api/orders/{order_id}")
    assert persisted.status_code == 200
    assert persisted.json()["status"] == "SUBMITTED"
    assert balance(client, restaurant, first["id"]) == Decimal("20")
    assert balance(client, restaurant, second["id"]) == Decimal("2")
    assert movement_rows(order_id) == []
    with engine.connect() as db:
        audit_after = db.scalar(
            text(
                "SELECT count(*) FROM audit_entries WHERE resource_type='order' "
                "AND resource_id=:id"
            ),
            {"id": str(order_id)},
        )
    assert audit_after == audit_before


def test_create_and_submit_check_stock_without_deducting_or_reserving(tracked_setup):
    client, restaurant, item = tracked_setup
    ingredient = create_ingredient(
        client, restaurant, name="Stock check rice", quantity="10"
    )
    assert (
        set_recipe(
            client, item, [{"ingredient_id": ingredient["id"], "quantity": "2"}]
        ).status_code
        == 200
    )

    too_large = create_order(client, restaurant, item, 6, key="too-large-order")
    assert too_large.status_code == 409, too_large.text
    first = create_order(client, restaurant, item, 2, key="first-draft")
    second = create_order(client, restaurant, item, 2, key="second-draft")
    assert first.status_code == second.status_code == 201
    assert balance(client, restaurant, ingredient["id"]) == Decimal("10")
    order_id = first.json()["order_id"]

    waste = client.post(
        f"/api/restaurants/{restaurant}/inventory/ingredients/{ingredient['id']}/movements",
        json={
            "kind": "waste",
            "quantity": "7",
            "reason": "Stock changed before submit",
            "idempotency_key": "waste-before-submit",
        },
    )
    assert waste.status_code == 201
    submitted = update_order(client, order_id, "SUBMITTED")
    assert submitted.status_code == 409, submitted.text
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "DRAFT"
    assert balance(client, restaurant, ingredient["id"]) == Decimal("3")
    assert movement_rows(order_id) == []

    after_waste = create_order(client, restaurant, item, 2, key="after-waste")
    assert after_waste.status_code == 409, after_waste.text
    assert movement_rows(second.json()["order_id"]) == []


@pytest.mark.parametrize("failure_point", ["balance", "movement", "order", "audit"])
def test_acceptance_flush_failures_roll_back_balance_movement_order_and_audit(
    tracked_setup, monkeypatch, failure_point
):
    from sqlalchemy.orm import Session

    from app.modules.audit.repo.models import AuditEntry
    from app.modules.inventory.repo.models import InventoryBalance, InventoryMovement
    from app.modules.orders.repo.models import Order

    client, restaurant, item = tracked_setup
    ingredient = create_ingredient(
        client, restaurant, name=f"Fail {failure_point}", quantity="10"
    )
    assert (
        set_recipe(
            client, item, [{"ingredient_id": ingredient["id"], "quantity": "3"}]
        ).status_code
        == 200
    )
    created = create_order(client, restaurant, item, 2)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    assert update_order(client, order_id, "SUBMITTED").status_code == 200
    audit_before = client.get("/api/audit?limit=100").json()
    original_flush = Session.flush

    def fail_target_flush(session, *args, **kwargs):
        if failure_point == "balance" and any(
            isinstance(row, InventoryBalance) and session.is_modified(row)
            for row in session.dirty
        ):
            raise RuntimeError("injected balance flush failure")
        if failure_point == "movement" and any(
            isinstance(row, InventoryMovement) and row.kind == "consumption"
            for row in session.new
        ):
            raise RuntimeError("injected movement flush failure")
        if failure_point == "order" and any(
            isinstance(row, Order)
            and row.order_id == order_id
            and row.status == "ACCEPTED"
            for row in session.dirty
        ):
            raise RuntimeError("injected order flush failure")
        if failure_point == "audit" and any(
            isinstance(row, AuditEntry)
            and row.resource_type == "order"
            and row.resource_id == str(order_id)
            and row.action == "order.updated"
            for row in session.new
        ):
            raise RuntimeError("injected audit flush failure")
        return original_flush(session, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", fail_target_flush)
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        failing_client.cookies.update(client.cookies)
        failing_client.headers.update(client.headers)
        response = update_order(failing_client, order_id, "ACCEPTED")
    assert response.status_code == 500, response.text

    current = client.get(f"/api/orders/{order_id}")
    assert current.status_code == 200
    assert current.json()["status"] == "SUBMITTED"
    assert balance(client, restaurant, ingredient["id"]) == Decimal("10")
    assert movement_rows(order_id) == []
    assert client.get("/api/audit?limit=100").json() == audit_before


def test_new_untracked_order_is_marked_processed_without_stock_movement(tracked_setup):
    client, restaurant, item = tracked_setup
    ingredient = create_ingredient(
        client, restaurant, name="Untracked stock", quantity="4"
    )
    # The default is untracked, matching rows from before recipes existed.
    assert client.get(f"/menu-items/{item}").json()["inventory_tracking"] is False
    created = create_order(client, restaurant, item)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    assert update_order(client, order_id, "SUBMITTED").status_code == 200
    assert update_order(client, order_id, "ACCEPTED").status_code == 200
    assert balance(client, restaurant, ingredient["id"]) == Decimal("4")
    assert movement_rows(order_id) == []
    with engine.connect() as db:
        processed = db.scalar(
            text("SELECT inventory_processed FROM orders WHERE order_id=:id"),
            {"id": order_id},
        )
    assert processed is True


def test_already_accepted_legacy_order_is_not_consumed_again(tracked_setup):
    client, restaurant, item = tracked_setup
    ingredient = create_ingredient(
        client, restaurant, name="Legacy rice", quantity="10"
    )
    # This order was created and accepted before its menu item had a recipe.
    created = create_order(client, restaurant, item)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    assert (
        set_recipe(
            client, item, [{"ingredient_id": ingredient["id"], "quantity": "4"}]
        ).status_code
        == 200
    )
    with engine.begin() as db:
        db.execute(
            text(
                "UPDATE orders SET status='ACCEPTED', inventory_processed=false "
                "WHERE order_id=:id"
            ),
            {"id": order_id},
        )

    retry = update_order(client, order_id, "ACCEPTED")
    assert retry.status_code == 200, retry.text
    assert balance(client, restaurant, ingredient["id"]) == Decimal("10")
    assert movement_rows(order_id) == []
    with engine.connect() as db:
        processed = db.scalar(
            text("SELECT inventory_processed FROM orders WHERE order_id=:id"),
            {"id": order_id},
        )
    assert processed is False


def test_cancellation_never_returns_stock_after_recipe_edit_and_history_is_retained(
    tracked_setup,
):
    client, restaurant, item = tracked_setup
    ingredient = create_ingredient(client, restaurant, name="Rice", quantity="10")
    assert (
        set_recipe(
            client, item, [{"ingredient_id": ingredient["id"], "quantity": "2"}]
        ).status_code
        == 200
    )
    created = create_order(client, restaurant, item, 2)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    assert update_order(client, order_id, "SUBMITTED").status_code == 200
    assert update_order(client, order_id, "ACCEPTED").status_code == 200
    assert balance(client, restaurant, ingredient["id"]) == Decimal("6")

    assert update_order(client, order_id, "CANCELLED").status_code == 200
    edited = set_recipe(
        client, item, [{"ingredient_id": ingredient["id"], "quantity": "4"}]
    )
    assert edited.status_code == 200, edited.text
    repeated_cancel = update_order(client, order_id, "CANCELLED")
    assert repeated_cancel.status_code == 200, repeated_cancel.text
    assert balance(client, restaurant, ingredient["id"]) == Decimal("6")
    rows = movement_rows(order_id)
    assert len(rows) == 1
    assert rows[0]["kind"] == "consumption"
    assert Decimal(rows[0]["quantity_delta"]) == Decimal("-4")

    deleted = client.delete(f"/api/orders/{order_id}")
    assert deleted.status_code == 409, deleted.text
    removed_menu_item = client.delete(f"/menu-items/{item}")
    assert removed_menu_item.status_code == 200, removed_menu_item.text
    assert (
        client.get(f"/api/orders/{order_id}").json()["items"][0]["menu_item_name"]
        == "Tracked dish"
    )
    assert len(movement_rows(order_id)) == 1


def test_employee_cannot_create_accept_or_cancel_but_assigned_manager_can(
    tracked_setup, auth_user
):
    owner, restaurant, item = tracked_setup
    employees = add_role_clients(auth_user, restaurant, ("MANAGER", "EMPLOYEE"))
    manager, employee = [entry[0] for entry in employees]
    try:
        ingredient = create_ingredient(
            owner, restaurant, name="Permission rice", quantity="10"
        )
        assert (
            set_recipe(
                owner, item, [{"ingredient_id": ingredient["id"], "quantity": "1"}]
            ).status_code
            == 200
        )
        denied_create = create_order(employee, restaurant, item, key="employee-create")
        assert denied_create.status_code == 403, denied_create.text
        manager_created = create_order(manager, restaurant, item, key="manager-create")
        assert manager_created.status_code == 201, manager_created.text

        created = create_order(owner, restaurant, item, key="manager-acceptance")
        assert created.status_code == 201, created.text
        order_id = created.json()["order_id"]
        assert update_order(owner, order_id, "SUBMITTED").status_code == 200
        assert update_order(employee, order_id, "ACCEPTED").status_code == 403
        accepted = update_order(manager, order_id, "ACCEPTED")
        assert accepted.status_code == 200, accepted.text
        assert update_order(employee, order_id, "CANCELLED").status_code == 403
        assert update_order(manager, order_id, "CANCELLED").status_code == 200
    finally:
        for client, _ in employees:
            client.close()


def test_two_distinct_managers_accepting_competing_orders_cannot_overdraw(
    tracked_setup, auth_user, monkeypatch
):
    owner, restaurant, item = tracked_setup
    users = add_role_clients(auth_user, restaurant, ("MANAGER", "MANAGER"))
    manager_a, manager_b = [entry[0] for entry in users]
    try:
        ingredient = create_ingredient(
            owner, restaurant, name="Limited rice", quantity="10"
        )
        assert (
            set_recipe(
                owner, item, [{"ingredient_id": ingredient["id"], "quantity": "7"}]
            ).status_code
            == 200
        )
        orders = [
            create_order(owner, restaurant, item),
            create_order(owner, restaurant, item),
        ]
        assert all(response.status_code == 201 for response in orders)
        order_ids = [response.json()["order_id"] for response in orders]
        for order_id in order_ids:
            assert update_order(owner, order_id, "SUBMITTED").status_code == 200

        first, second = overlap_after_restaurant_lock(
            monkeypatch,
            lambda: update_order(manager_a, order_ids[0], "ACCEPTED"),
            lambda: update_order(manager_b, order_ids[1], "ACCEPTED"),
        )
        assert sorted((first.status_code, second.status_code)) == [200, 409]
        winner_index = 0 if first.status_code == 200 else 1
        loser_index = 1 - winner_index
        assert balance(owner, restaurant, ingredient["id"]) == Decimal("3")
        assert len(movement_rows(order_ids[winner_index])) == 1
        assert movement_rows(order_ids[loser_index]) == []
        with engine.connect() as db:
            actor_id = db.scalar(
                text(
                    "SELECT inventory_movements.actor_user_id::text FROM inventory_movements "
                    "JOIN users ON users.id=inventory_movements.actor_user_id "
                    "WHERE order_id=:order"
                ),
                {"order": order_ids[winner_index]},
            )
        assert actor_id == users[winner_index][1]
        assert len({users[0][1], users[1][1]}) == 2
    finally:
        for client, _ in users:
            client.close()


@pytest.mark.parametrize(
    "kind,opening,amount,expected_manual_status,expected_balance",
    [
        ("receipt", "5", "5", 201, Decimal("5")),
        ("waste", "10", "7", 409, Decimal("5")),
        ("count", "10", "3", 409, Decimal("5")),
    ],
)
def test_manual_receipt_waste_and_count_serialize_with_acceptance(
    tracked_setup,
    auth_user,
    monkeypatch,
    kind,
    opening,
    amount,
    expected_manual_status,
    expected_balance,
):
    client, restaurant, item = tracked_setup
    managers = add_role_clients(auth_user, restaurant, ("MANAGER",))
    manager = managers[0][0]
    ingredient = create_ingredient(
        client, restaurant, name=f"Concurrent {kind}", quantity=opening
    )
    assert (
        set_recipe(
            client, item, [{"ingredient_id": ingredient["id"], "quantity": "5"}]
        ).status_code
        == 200
    )
    created = create_order(client, restaurant, item)
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    assert update_order(client, order_id, "SUBMITTED").status_code == 200

    def manual_change():
        return client.post(
            f"/api/restaurants/{restaurant}/inventory/ingredients/{ingredient['id']}/movements",
            json={
                "kind": kind,
                "quantity": amount,
                "reason": f"Concurrent {kind}",
                "expected_version": 1 if kind == "count" else None,
                "idempotency_key": f"concurrent-{kind}",
            },
        )

    accepted, manual = overlap_after_restaurant_lock(
        monkeypatch,
        lambda: update_order(manager, order_id, "ACCEPTED"),
        manual_change,
    )
    assert accepted.status_code == 200, accepted.text
    assert manual.status_code == expected_manual_status, manual.text
    assert balance(client, restaurant, ingredient["id"]) == expected_balance
    assert len(movement_rows(order_id)) == 1
    for role_client, _ in managers:
        role_client.close()


def test_recipe_edit_and_acceptance_use_one_consistent_recipe_snapshot(
    tracked_setup, auth_user, monkeypatch
):
    owner, restaurant, item = tracked_setup
    managers = add_role_clients(auth_user, restaurant, ("MANAGER",))
    manager = managers[0][0]
    try:
        flour = create_ingredient(
            owner, restaurant, name="Snapshot flour", quantity="12"
        )
        salt = create_ingredient(owner, restaurant, name="Snapshot salt", quantity="12")
        original_components = [
            {"ingredient_id": flour["id"], "quantity": "2"},
            {"ingredient_id": salt["id"], "quantity": "3"},
        ]
        edited_components = [
            {"ingredient_id": flour["id"], "quantity": "4"},
            {"ingredient_id": salt["id"], "quantity": "1"},
        ]
        assert set_recipe(owner, item, original_components).status_code == 200
        created = create_order(owner, restaurant, item, 2)
        assert created.status_code == 201, created.text
        order_id = created.json()["order_id"]
        assert update_order(owner, order_id, "SUBMITTED").status_code == 200

        accepted, edited = overlap_after_restaurant_lock(
            monkeypatch,
            lambda: update_order(owner, order_id, "ACCEPTED"),
            lambda: set_recipe(manager, item, edited_components),
        )
        assert accepted.status_code == 200, accepted.text
        assert edited.status_code == 200, edited.text
        client_recipe = owner.get(f"/menu-items/{item}/recipe")
        assert client_recipe.status_code == 200
        assert [row["quantity"] for row in client_recipe.json()["components"]] == [
            "4.000",
            "1.000",
        ]

        consumed = {
            row["ingredient_id"]: Decimal(row["quantity_delta"])
            for row in movement_rows(order_id)
        }
        assert consumed in (
            {flour["id"]: Decimal("-4"), salt["id"]: Decimal("-6")},
            {flour["id"]: Decimal("-8"), salt["id"]: Decimal("-2")},
        )
        assert (
            balance(owner, restaurant, flour["id"])
            == Decimal("12") + consumed[flour["id"]]
        )
        assert (
            balance(owner, restaurant, salt["id"])
            == Decimal("12") + consumed[salt["id"]]
        )
    finally:
        for client, _ in managers:
            client.close()
