from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from conftest import engine
from app.main import app


@pytest.fixture
def stock(authenticated_client):
    client = authenticated_client
    restaurant = client.post(
        "/api/restaurants", json={"name": "Inventory branch"}
    ).json()["id"]
    base = f"/api/restaurants/{restaurant}/inventory/ingredients"
    payload = {
        "name": "Chicken",
        "unit": "g",
        "reorder_threshold": "5",
        "opening_quantity": "10",
        "idempotency_key": "opening",
    }
    result = client.post(base, json=payload)
    assert result.status_code == 201, result.text
    return client, restaurant, base, result.json(), payload


def change(client, base, ingredient, key, kind="receipt", amount="2", version=None):
    return client.post(
        f"{base}/{ingredient}/movements",
        json={
            "kind": kind,
            "quantity": amount,
            "reason": "Daily stock handling",
            "expected_version": version,
            "idempotency_key": key,
        },
    )


def test_lifecycle_retries_ledger_and_deletion(stock):
    client, restaurant, base, item, payload = stock
    ident = item["id"]
    assert client.post(base, json=payload).json()["id"] == ident
    assert (
        client.post(base, json={**payload, "opening_quantity": "11"}).status_code == 409
    )
    assert (
        client.post(
            base, json={**payload, "name": " chicken ", "idempotency_key": "duplicate"}
        ).status_code
        == 409
    )
    first = change(client, base, ident, "receipt")
    assert first.status_code == 201
    assert change(client, base, ident, "receipt").json()["id"] == first.json()["id"]
    assert change(client, base, ident, "receipt", amount="3").status_code == 409
    assert change(client, base, ident, "waste", "waste", "100").status_code == 409
    assert (
        change(client, base, ident, "stale", "count", "9", item["version"]).status_code
        == 409
    )
    assert change(client, base, ident, "count", "count", "9", 2).status_code == 201
    assert change(client, base, ident, "same-count", "count", "9", 3).status_code == 201
    row = client.get(base).json()[0]
    assert Decimal(row["quantity"]) == 9 and row["version"] == 4
    fields = {
        "name": row["name"],
        "unit": row["unit"],
        "reorder_threshold": "12",
        "is_active": False,
    }
    assert client.put(f"{base}/{ident}", json=fields).status_code == 409
    assert (
        client.put(
            f"{base}/{ident}", json={**fields, "unit": "piece", "is_active": True}
        ).status_code
        == 409
    )
    assert change(client, base, ident, "zero", "count", "0", 4).status_code == 201
    assert client.put(f"{base}/{ident}", json=fields).status_code == 200
    assert change(client, base, ident, "archived").status_code == 409
    assert (
        client.put(f"{base}/{ident}", json={**fields, "is_active": True}).status_code
        == 200
    )
    history = client.get(f"{base}/{ident}/movements").json()
    assert sum(Decimal(row["quantity_delta"]) for row in history) == 0
    assert all(row["actor_name"] == "operator@example.test" for row in history)
    assert (
        client.get(f"{base}/{ident}/movements?limit=2&offset=1").json() == history[1:3]
    )
    assert client.delete(f"/api/restaurants/{restaurant}").status_code == 409
    with engine.connect() as db:
        assert (
            db.scalar(
            text(
                "SELECT count(*) FROM audit_entries WHERE action LIKE 'inventory.%'"
            )
            )
            == 7
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0.0001", "1000000000"])
def test_http_rejects_invalid_quantities_without_writes(stock, value):
    client, _, base, item, _ = stock
    assert change(client, base, item["id"], "invalid", amount=value).status_code == 422
    assert Decimal(client.get(base).json()[0]["quantity"]) == 10
    assert len(client.get(f"{base}/{item['id']}/movements").json()) == 1


def test_nested_ids_and_pagination(stock):
    client, _, base, item, payload = stock
    other = client.post("/api/restaurants", json={"name": "Other inventory"}).json()[
        "id"
    ]
    foreign = f"/api/restaurants/{other}/inventory/ingredients"
    assert change(client, foreign, item["id"], "wrong-parent").status_code == 404
    assert client.get(f"{foreign}/{item['id']}/movements").status_code == 404
    for index in range(3):
        assert (
            client.post(
                base,
                json={
                    **payload,
                    "name": f"Ingredient {index}",
                    "idempotency_key": f"new-{index}",
                },
            ).status_code
            == 201
        )
    assert len(client.get(f"{base}?limit=2&offset=1").json()) == 2
    assert client.get(f"{base}?limit=101").status_code == 422


@pytest.fixture
def inventory_roles(stock, auth_user):
    owner, restaurant, base, item, payload = stock
    clients = []
    with engine.begin() as db:
        encoded = db.scalar(
            text("SELECT password_hash FROM users WHERE id=:id"),
            {"id": auth_user["id"]},
        )
        other_org = uuid4()
        db.execute(
            text(
                "INSERT INTO organizations (id,name,slug) VALUES (:id,'Foreign','inventory-foreign')"
            ),
            {"id": other_org},
        )
        for index, role in enumerate(["MANAGER", "MANAGER", "EMPLOYEE", "OWNER"]):
            uid, mid = uuid4(), uuid4()
            email = f"stock-{index}@example.test"
            org = other_org if index == 3 else auth_user["organization_id"]
            db.execute(
                text(
                    "INSERT INTO users (id,email,password_hash) VALUES (:id,:email,:hash)"
                ),
                {"id": uid, "email": email, "hash": encoded},
            )
            db.execute(
                text(
                    "INSERT INTO memberships (id,user_id,organization_id,role) VALUES (:id,:user,:org,:role)"
                ),
                {"id": mid, "user": uid, "org": org, "role": role},
            )
            if index < 3:
                db.execute(
                    text(
                        "INSERT INTO restaurant_assignments (membership_id,organization_id,restaurant_id) VALUES (:id,:org,:restaurant)"
                    ),
                    {"id": mid, "org": org, "restaurant": restaurant},
                )
    try:
        for index in range(4):
            client = TestClient(app)
            client.headers.update(
                {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
            )
            assert (
                client.post(
                    "/auth/login",
                    json={
                        "email": f"stock-{index}@example.test",
                        "password": auth_user["password"],
                    },
                ).status_code
                == 200
            )
            clients.append(client)
        yield clients
    finally:
        for client in clients:
            client.close()


def test_role_and_tenant_scope(stock, inventory_roles):
    owner, _, base, item, payload = stock
    manager, _, employee, foreign = inventory_roles

    def exercise(client, prefix):
        return [
            client.get(base).status_code,
            client.post(
                base,
                json={
                    **payload,
                    "name": f"{prefix} Rice",
                    "idempotency_key": f"{prefix}-create",
                },
            ).status_code,
            client.put(
                f"{base}/{item['id']}",
                json={
                    "name": item["name"],
                    "unit": item["unit"],
                    "reorder_threshold": "5",
                    "is_active": True,
                },
            ).status_code,
            change(client, base, item["id"], f"{prefix}-stock").status_code,
            client.get(f"{base}/{item['id']}/movements").status_code,
        ]

    assert exercise(manager, "manager") == [200, 201, 200, 201, 200]
    assert exercise(employee, "employee") == [403, 403, 403, 403, 403]
    assert exercise(foreign, "foreign") == [404, 404, 404, 404, 404]
    unassigned = owner.post("/api/restaurants", json={"name": "Unassigned"}).json()[
        "id"
    ]
    assert (
        manager.get(f"/api/restaurants/{unassigned}/inventory/ingredients").status_code
        == 404
    )


def test_role_and_assignment_revocation_are_immediate(stock, inventory_roles):
    _, _, base, item, payload = stock
    manager, second_manager, _, _ = inventory_roles
    assert manager.get(base).status_code == 200
    with engine.begin() as db:
        db.execute(
            text(
                "UPDATE memberships SET role='EMPLOYEE' "
                "WHERE user_id=(SELECT id FROM users WHERE email='stock-0@example.test')"
            )
        )
    assert manager.get(base).status_code == 403
    assert change(manager, base, item["id"], "revoked-role").status_code == 403

    assert second_manager.get(base).status_code == 200
    with engine.begin() as db:
        db.execute(
            text(
                "DELETE FROM restaurant_assignments WHERE membership_id=("
                "SELECT id FROM memberships WHERE user_id=("
                "SELECT id FROM users WHERE email='stock-1@example.test'))"
            )
        )
    assert second_manager.get(base).status_code == 404
    assert (
        second_manager.post(
            base, json={**payload, "idempotency_key": "revoked-assignment"}
        ).status_code
        == 404
    )


def overlap_inventory_requests_after_lock(monkeypatch, first_request, second_request):
    """Hold the first transaction's restaurant lock while the second enters."""
    from threading import Event, Lock

    from app.modules.inventory.repo.queries import InventoryRepository

    original = InventoryRepository.lock_restaurant
    first_locked = Event()
    second_entered = Event()
    release_first = Event()
    calls = 0
    calls_lock = Lock()

    async def controlled_lock(self, restaurant_id):
        nonlocal calls
        with calls_lock:
            calls += 1
            ordinal = calls
        if ordinal == 1:
            await original(self, restaurant_id)
            first_locked.set()
            if not release_first.wait(timeout=10):
                raise TimeoutError("Concurrent request did not reach the inventory lock")
            return
        if ordinal == 2:
            second_entered.set()
        await original(self, restaurant_id)

    monkeypatch.setattr(InventoryRepository, "lock_restaurant", controlled_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_request)
        try:
            assert first_locked.wait(timeout=10)
            second = pool.submit(second_request)
            assert second_entered.wait(timeout=10)
            assert not second.done(), "second write completed while first held the restaurant lock"
        finally:
            release_first.set()
        return first.result(timeout=20), second.result(timeout=20)


def test_two_managers_cannot_overdraw_and_count_cannot_overwrite_receipt(
    stock, inventory_roles, monkeypatch
):
    client, _, base, item, _ = stock
    managers = inventory_roles[:2]
    first, second = overlap_inventory_requests_after_lock(
        monkeypatch,
        lambda: change(managers[0], base, item["id"], "concurrent-0", "waste", "7"),
        lambda: change(managers[1], base, item["id"], "concurrent-1", "waste", "7"),
    )
    results = [first, second]
    assert sorted(row.status_code for row in results) == [201, 409]
    current = client.get(base).json()[0]
    assert Decimal(current["quantity"]) == 3
    receipt, count = overlap_inventory_requests_after_lock(
        monkeypatch,
        lambda: change(managers[0], base, item["id"], "race-receipt", "receipt", "2"),
        lambda: change(
            managers[1],
            base,
            item["id"],
            "race-count",
            "count",
            "3",
            current["version"],
        ),
    )
    assert receipt.status_code == 201
    assert count.status_code == 409
    current = client.get(base).json()[0]
    assert Decimal(current["quantity"]) == 5
    history = client.get(f"{base}/{item['id']}/movements").json()
    assert sum(Decimal(row["quantity_delta"]) for row in history) == 5


def test_concurrent_identical_keys_create_and_record_stock_once(stock, inventory_roles, monkeypatch):
    client, restaurant, base, item, _ = stock
    managers = inventory_roles[:2]
    create_payload = {
        "name": "Concurrent Rice",
        "unit": "g",
        "reorder_threshold": "1",
        "opening_quantity": "4",
        "idempotency_key": "shared-create-key",
    }
    first, second = overlap_inventory_requests_after_lock(
        monkeypatch,
        lambda: managers[0].post(base, json=create_payload),
        lambda: managers[1].post(base, json=create_payload),
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    listed = client.get(base).json()
    assert len([row for row in listed if row["name"] == "Concurrent Rice"]) == 1
    ingredient_id = first.json()["id"]

    stock_body = {
        "kind": "receipt",
        "quantity": "1.250",
        "reason": "Concurrent retry",
        "expected_version": None,
        "idempotency_key": "shared-stock-key",
    }
    first_move, second_move = overlap_inventory_requests_after_lock(
        monkeypatch,
        lambda: managers[0].post(f"{base}/{ingredient_id}/movements", json=stock_body),
        lambda: managers[1].post(f"{base}/{ingredient_id}/movements", json=stock_body),
    )
    assert first_move.status_code == second_move.status_code == 201
    assert first_move.json()["id"] == second_move.json()["id"]
    assert Decimal(client.get(base).json()[0]["quantity"]) == 10
    history = client.get(f"{base}/{ingredient_id}/movements").json()
    assert len([row for row in history if row["id"] == first_move.json()["id"]]) == 1
    assert len(history) == 2


def test_audit_failure_rolls_back_balance_and_movement(stock, monkeypatch):
    import app.modules.inventory.service as module

    client, _, base, item, _ = stock

    def fail(*args, **kwargs):
        raise RuntimeError("Audit storage failed")

    monkeypatch.setattr(module, "record", fail)
    with pytest.raises(RuntimeError, match="Audit storage failed"):
        change(client, base, item["id"], "fail-audit")
    assert Decimal(client.get(base).json()[0]["quantity"]) == 10
    assert len(client.get(f"{base}/{item['id']}/movements").json()) == 1
