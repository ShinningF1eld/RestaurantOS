"""T9 user-facing scope, live stock fencing, and retained episode pagination."""
# ruff: noqa: F811 - imported pytest fixtures intentionally share parameter names

import asyncio

import pytest
from sqlalchemy import text

from conftest import engine
from integration.test_alert_projection import deliver, event_rows
from integration.test_inventory_management import (  # noqa: F401
    stock,
    inventory_roles,
    change,
)


def project_alerts():
    for _, event in event_rows():
        if event.event_type.startswith("inventory."):
            asyncio.run(deliver(event, "alerts"))


def test_active_reads_live_stock_and_excludes_delayed_closed_or_superseded(stock):
    client, restaurant, base, item, _ = stock
    alerts = f"/api/restaurants/{restaurant}/inventory/alerts"
    assert change(client, base, item["id"], "low", "waste", "7").status_code == 201
    assert client.get(alerts).json()["total"] == 0  # worker has not run
    assert client.get(base).json()[0]["low_stock"] is True
    project_alerts()
    row = client.get(alerts).json()["items"][0]
    assert row["quantity"] == "3.000"
    assert row["reorder_threshold"] == "5.000"
    assert change(client, base, item["id"], "lower", "waste", "1").status_code == 201
    assert client.get(alerts).json()["items"][0]["quantity"] == "2.000"
    assert (
        change(client, base, item["id"], "recover", "receipt", "10").status_code == 201
    )
    assert client.get(alerts).json()["total"] == 0
    assert change(client, base, item["id"], "new-low", "waste", "10").status_code == 201
    assert (
        client.get(alerts).json()["total"] == 0
    )  # old projected episode cannot return
    project_alerts()
    fresh = client.get(alerts).json()["items"][0]
    assert fresh["episode_id"] != row["episode_id"]
    assert client.get(alerts + "/history").json()["total"] == 2


def test_history_snapshots_baseline_order_pagination_and_validation(stock, auth_user):
    client, restaurant, base, item, _ = stock
    alerts = f"/api/restaurants/{restaurant}/inventory/alerts"
    assert change(client, base, item["id"], "low", "waste", "7").status_code == 201
    project_alerts()
    assert (
        client.put(
            f"{base}/{item['id']}",
            json={"name": "Renamed chicken", "unit": "g", "reorder_threshold": "5"},
        ).status_code
        == 200
    )
    assert client.get(alerts).json()["items"][0]["ingredient_name"] == "Renamed chicken"
    history = client.get(alerts + "/history").json()["items"][0]
    assert history["ingredient_name"] == "Chicken"
    assert history["opening_quantity"] == "3.000"
    assert history["resolved_at"] is None
    # Seed observed baseline facts through the production maintenance hook.
    from app.db.database import AsyncSessionLocal
    from app.modules.alerts.service import AlertProjectionService
    from app.modules.inventory.service import record_baseline_inventory_episode

    baseline = client.post(
        base,
        json={
            "name": "Legacy low",
            "unit": "g",
            "opening_quantity": "10",
            "reorder_threshold": "0",
            "idempotency_key": "legacy",
        },
    ).json()
    # Simulate a legacy ingredient with no producer episode/events before initialization.
    with engine.begin() as db:
        db.execute(
            text("UPDATE inventory_balances SET quantity=0 WHERE ingredient_id=:id"),
            {"id": baseline["id"]},
        )

    async def initialize():
        async with AsyncSessionLocal() as session, session.begin():
            await record_baseline_inventory_episode(
                session, auth_user["organization_id"], restaurant, baseline["id"]
            )
            await AlertProjectionService().rebuild(
                session, auth_user["organization_id"], restaurant
            )

    asyncio.run(initialize())
    # Equal timestamps exercise UUID tie breaking rather than relying on insertion order.
    with engine.begin() as db:
        db.execute(text("UPDATE alert_episodes SET opened_at='2026-10-15T00:00:00Z'"))
    all_rows = client.get(alerts + "/history").json()
    ids = [row["episode_id"] for row in all_rows["items"]]
    assert ids == sorted(ids, reverse=True)
    assert all_rows["limit"] == 20 and all_rows["offset"] == 0
    assert all_rows["total"] == 2
    assert any(
        row["opening_source"] == "maintenance_initialization"
        and row["notification_suppressed"]
        for row in all_rows["items"]
    )
    page = client.get(alerts + "/history?limit=1&offset=1").json()
    assert page["items"] == all_rows["items"][1:2] and page["total"] == 2
    assert client.get(alerts + "/history?offset=100").json()["items"] == []
    for suffix in ("", "/history"):
        assert client.get(alerts + suffix + "?limit=100").status_code == 200
        for query in ("limit=0", "limit=101", "offset=-1"):
            assert client.get(alerts + suffix + "?" + query).status_code == 422


@pytest.mark.parametrize("suffix", ["", "/history"])
def test_alert_scope_counts_and_immediate_revocation(stock, inventory_roles, suffix):
    owner, restaurant, base, item, _ = stock
    manager, second_manager, employee, foreign = inventory_roles
    alerts = f"/api/restaurants/{restaurant}/inventory/alerts{suffix}"
    assert (
        change(owner, base, item["id"], "scoped-low", "waste", "7").status_code == 201
    )
    project_alerts()
    assert owner.get(alerts).status_code == 200
    assert manager.get(alerts).json()["total"] == 1
    assert employee.get(alerts).status_code == 403
    assert foreign.get(alerts).status_code == 404
    other = owner.post("/api/restaurants", json={"name": "Unassigned"}).json()["id"]
    assert (
        manager.get(f"/api/restaurants/{other}/inventory/alerts{suffix}").status_code
        == 404
    )
    with engine.begin() as db:
        db.execute(
            text(
                "UPDATE memberships SET role='EMPLOYEE' WHERE user_id=(SELECT id FROM users WHERE email='stock-0@example.test')"
            )
        )
        db.execute(
            text(
                "DELETE FROM restaurant_assignments WHERE membership_id=(SELECT id FROM memberships WHERE user_id=(SELECT id FROM users WHERE email='stock-1@example.test'))"
            )
        )
    assert manager.get(alerts).status_code == 403
    assert second_manager.get(alerts).status_code == 404


def test_default_pages_and_counts_exclude_other_branches(stock):
    client, restaurant, base, _, payload = stock
    other = client.post("/api/restaurants", json={"name": "Other alerts"}).json()["id"]
    for index in range(22):
        target = (
            base if index < 21 else f"/api/restaurants/{other}/inventory/ingredients"
        )
        response = client.post(
            target,
            json={
                **payload,
                "name": f"Low {index}",
                "opening_quantity": "0",
                "idempotency_key": f"low-{index}",
            },
        )
        assert response.status_code == 201
    project_alerts()
    for suffix in ("", "/history"):
        url = f"/api/restaurants/{restaurant}/inventory/alerts{suffix}"
        first = client.get(url).json()
        second = client.get(url + "?offset=20").json()
        assert first["total"] == second["total"] == 21
        assert len(first["items"]) == 20 and len(second["items"]) == 1
        assert not (
            {row["episode_id"] for row in first["items"]}
            & {row["episode_id"] for row in second["items"]}
        )
        assert (
            client.get(f"/api/restaurants/{other}/inventory/alerts{suffix}").json()[
                "total"
            ]
            == 1
        )


def test_revoked_membership_cannot_read_lists_or_counts(stock):
    client, restaurant, _, _, _ = stock
    with engine.begin() as db:
        db.execute(text("UPDATE memberships SET status='revoked'"))
    for suffix in ("", "/history"):
        assert (
            client.get(
                f"/api/restaurants/{restaurant}/inventory/alerts{suffix}"
            ).status_code
            == 403
        )
