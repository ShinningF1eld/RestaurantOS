"""PostgreSQL coverage for revisioned inventory and durable episode facts."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.database import AsyncSessionLocal
from app.modules.inventory.repo.queries import InventoryTransitionRepository
from app.modules.inventory.service import record_baseline_inventory_episode
from conftest import engine


def create_restaurant(client) -> int:
    response = client.post("/api/restaurants", json={"name": "Episode branch"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_ingredient(
    client,
    restaurant_id: int,
    *,
    name: str = "Rice",
    quantity: str = "10",
    threshold: str = "5",
) -> dict:
    response = client.post(
        f"/api/restaurants/{restaurant_id}/inventory/ingredients",
        json={
            "name": name,
            "unit": "g",
            "reorder_threshold": threshold,
            "opening_quantity": quantity,
            "idempotency_key": uuid4().hex,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def change_stock(
    client,
    restaurant_id: int,
    ingredient_id: int,
    key: str,
    kind: str,
    quantity: str,
    expected_version: int | None = None,
):
    return client.post(
        f"/api/restaurants/{restaurant_id}/inventory/ingredients/"
        f"{ingredient_id}/movements",
        json={
            "kind": kind,
            "quantity": quantity,
            "reason": "Episode lifecycle verification",
            "expected_version": expected_version,
            "idempotency_key": key,
        },
    )


def update_ingredient(
    client,
    restaurant_id: int,
    ingredient_id: int,
    *,
    name: str = "Rice",
    unit: str = "g",
    threshold: str = "5",
    active: bool = True,
):
    return client.put(
        f"/api/restaurants/{restaurant_id}/inventory/ingredients/{ingredient_id}",
        json={
            "name": name,
            "unit": unit,
            "reorder_threshold": threshold,
            "is_active": active,
        },
    )


def revision_for(ingredient_id: int) -> int:
    with engine.connect() as connection:
        return connection.scalar(
            text(
                "SELECT state_revision FROM inventory_ingredients WHERE id=:ingredient"
            ),
            {"ingredient": ingredient_id},
        )


def episodes_for(ingredient_id: int) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT episode_id,organization_id,restaurant_id,ingredient_id,"
                "ingredient_name,unit,opening_quantity,opening_reorder_threshold,"
                "opened_at,opening_revision,opening_source,opening_actor_user_id,"
                "opening_order_id,notification_suppressed,resolved_at,"
                "resolution_reason,closing_quantity,closing_reorder_threshold,"
                "closing_is_active,resolution_revision,resolution_source,"
                "resolution_actor_user_id,resolution_order_id "
                "FROM inventory_low_stock_episodes WHERE ingredient_id=:ingredient "
                "ORDER BY opening_revision"
            ),
            {"ingredient": ingredient_id},
        ).mappings()
        return [dict(row) for row in rows]


def test_episode_lifecycle_revisions_snapshots_and_noops(authenticated_client):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    base = f"/api/restaurants/{restaurant_id}/inventory/ingredients"
    ingredient = create_ingredient(client, restaurant_id)
    ingredient_id = ingredient["id"]
    assert revision_for(ingredient_id) == 1
    assert episodes_for(ingredient_id) == []

    opened = change_stock(client, restaurant_id, ingredient_id, "open", "waste", "5")
    assert opened.status_code == 201, opened.text
    first_episode = episodes_for(ingredient_id)[0]
    first_episode_id = first_episode["episode_id"]
    assert revision_for(ingredient_id) == 2
    assert first_episode["opening_quantity"] == Decimal("5.000")
    assert first_episode["opening_reorder_threshold"] == Decimal("5.000")
    assert first_episode["opening_revision"] == 2
    assert first_episode["opening_source"] == "stock_command"
    assert first_episode["notification_suppressed"] is False
    assert first_episode["resolved_at"] is None

    # A successful retry returns the original movement and leaves transition
    # facts and their revision unchanged.
    replay = change_stock(client, restaurant_id, ingredient_id, "open", "waste", "5")
    assert replay.status_code == 201
    assert replay.json()["id"] == opened.json()["id"]
    assert revision_for(ingredient_id) == 2
    assert len(episodes_for(ingredient_id)) == 1

    lower = change_stock(
        client, restaurant_id, ingredient_id, "deduct-low", "waste", "1"
    )
    assert lower.status_code == 201
    assert revision_for(ingredient_id) == 3
    assert [row["episode_id"] for row in episodes_for(ingredient_id)] == [
        first_episode_id
    ]

    # Physical counts keep their own version token; a zero-delta count advances
    # the count version and ledger but not the state revision.
    count = change_stock(
        client,
        restaurant_id,
        ingredient_id,
        "same-count",
        "count",
        "4",
        expected_version=3,
    )
    assert count.status_code == 201, count.text
    assert count.json()["version_after"] == 4
    assert revision_for(ingredient_id) == 3

    recovered = change_stock(
        client, restaurant_id, ingredient_id, "recover", "receipt", "5"
    )
    assert recovered.status_code == 201
    first_episode = episodes_for(ingredient_id)[0]
    assert first_episode["resolution_reason"] == "stock_recovered"
    assert first_episode["closing_quantity"] == Decimal("9.000")
    assert first_episode["resolution_revision"] == 4
    assert revision_for(ingredient_id) == 4

    entered_again = change_stock(
        client, restaurant_id, ingredient_id, "low-again", "waste", "4"
    )
    assert entered_again.status_code == 201
    rows = episodes_for(ingredient_id)
    assert len(rows) == 2 and rows[1]["episode_id"] != first_episode_id
    assert rows[1]["opening_revision"] == 5

    threshold_recovery = update_ingredient(
        client, restaurant_id, ingredient_id, threshold="3"
    )
    assert threshold_recovery.status_code == 200
    rows = episodes_for(ingredient_id)
    assert rows[1]["resolution_reason"] == "threshold_changed"
    assert rows[1]["closing_reorder_threshold"] == Decimal("3.000")
    assert revision_for(ingredient_id) == 6

    threshold_low = update_ingredient(
        client, restaurant_id, ingredient_id, threshold="6"
    )
    assert threshold_low.status_code == 200
    rows = episodes_for(ingredient_id)
    third_episode_id = rows[2]["episode_id"]
    assert rows[2]["opening_revision"] == 7
    threshold_still_low = update_ingredient(
        client, restaurant_id, ingredient_id, threshold="7"
    )
    assert threshold_still_low.status_code == 200
    assert revision_for(ingredient_id) == 8
    assert [row["episode_id"] for row in episodes_for(ingredient_id)] == [
        first_episode_id,
        rows[1]["episode_id"],
        third_episode_id,
    ]

    # Name-only and same-value updates do not advance the state revision, and
    # historical opening snapshots remain independent of the mutable ingredient.
    renamed = update_ingredient(
        client, restaurant_id, ingredient_id, name="Long grain rice", threshold="7"
    )
    assert renamed.status_code == 200
    same_values = update_ingredient(
        client, restaurant_id, ingredient_id, name="Long grain rice", threshold="7"
    )
    assert same_values.status_code == 200
    assert revision_for(ingredient_id) == 8
    assert episodes_for(ingredient_id)[2]["ingredient_name"] == "Rice"
    assert episodes_for(ingredient_id)[2]["unit"] == "g"
    assert (
        update_ingredient(
            client,
            restaurant_id,
            ingredient_id,
            name="Long grain rice",
            unit="piece",
            threshold="7",
        ).status_code
        == 409
    )

    zeroed = change_stock(client, restaurant_id, ingredient_id, "empty", "waste", "5")
    assert zeroed.status_code == 201
    assert revision_for(ingredient_id) == 9
    archived = update_ingredient(
        client,
        restaurant_id,
        ingredient_id,
        name="Long grain rice",
        threshold="7",
        active=False,
    )
    assert archived.status_code == 200
    rows = episodes_for(ingredient_id)
    assert rows[2]["resolution_reason"] == "archived"
    assert rows[2]["closing_is_active"] is False
    assert revision_for(ingredient_id) == 10

    restored = update_ingredient(
        client,
        restaurant_id,
        ingredient_id,
        name="Long grain rice",
        threshold="7",
        active=True,
    )
    assert restored.status_code == 200
    rows = episodes_for(ingredient_id)
    assert len(rows) == 4
    assert rows[3]["episode_id"] != third_episode_id
    assert rows[3]["opening_revision"] == 11
    assert rows[3]["opening_source"] == "ingredient_update"
    assert revision_for(ingredient_id) == 11
    assert client.get(base).json()[0]["low_stock"] is True


def test_creation_at_zero_with_zero_threshold_opens_episode(authenticated_client):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(
        client, restaurant_id, name="Zero threshold", quantity="0", threshold="0"
    )
    assert ingredient["low_stock"] is True
    rows = episodes_for(ingredient["id"])
    assert len(rows) == 1
    assert rows[0]["opening_quantity"] == Decimal("0.000")
    assert rows[0]["opening_reorder_threshold"] == Decimal("0.000")
    assert rows[0]["opening_revision"] == 1
    assert rows[0]["opening_source"] == "ingredient_creation"
    assert revision_for(ingredient["id"]) == 1


def test_opening_facts_are_immutable_and_survive_ingredient_deletion(
    authenticated_client,
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(
        client, restaurant_id, name="Historical rice", quantity="0", threshold="0"
    )
    ingredient_id = ingredient["id"]
    episode_id = episodes_for(ingredient_id)[0]["episode_id"]

    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE inventory_low_stock_episodes SET ingredient_name='Changed' "
                    "WHERE episode_id=:episode"
                ),
                {"episode": episode_id},
            )
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM inventory_low_stock_episodes WHERE episode_id=:episode"
                ),
                {"episode": episode_id},
            )

    # The episode keeps its opening snapshot without a cascading ingredient FK.
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM inventory_movements WHERE ingredient_id=:ingredient"),
            {"ingredient": ingredient_id},
        )
        connection.execute(
            text("DELETE FROM inventory_balances WHERE ingredient_id=:ingredient"),
            {"ingredient": ingredient_id},
        )
        connection.execute(
            text("DELETE FROM inventory_ingredients WHERE id=:ingredient"),
            {"ingredient": ingredient_id},
        )
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT ingredient_name,opening_quantity,opening_reorder_threshold "
                "FROM inventory_low_stock_episodes WHERE episode_id=:episode"
            ),
            {"episode": episode_id},
        ).one()
    assert row == ("Historical rice", Decimal("0.000"), Decimal("0.000"))


def test_baseline_episode_records_observation_and_suppression_without_revision(
    authenticated_client, auth_user
):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(client, restaurant_id)
    ingredient_id = ingredient["id"]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE inventory_balances SET quantity=5 WHERE ingredient_id=:ingredient"
            ),
            {"ingredient": ingredient_id},
        )
    observed_at = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    organization_id = UUID(auth_user["organization_id"])

    async def initialize():
        async with AsyncSessionLocal() as session:
            async with session.begin():
                first = await record_baseline_inventory_episode(
                    session,
                    organization_id,
                    restaurant_id,
                    ingredient_id,
                    observed_at=observed_at,
                )
        async with AsyncSessionLocal() as session:
            async with session.begin():
                second = await record_baseline_inventory_episode(
                    session,
                    organization_id,
                    restaurant_id,
                    ingredient_id,
                    observed_at=datetime(2026, 10, 11, 9, 0, tzinfo=UTC),
                )
        return first, second

    first, second = asyncio.run(initialize())
    assert first.is_low and second.is_low
    assert first.state_revision == second.state_revision == 1
    assert first.episode_id == second.episode_id
    assert first.episode_facts is not None
    assert first.episode_facts.opened_at == observed_at
    assert first.episode_facts.opening_source == "maintenance_initialization"
    assert first.episode_facts.notification_suppressed is True
    assert revision_for(ingredient_id) == 1
    assert len(episodes_for(ingredient_id)) == 1


@pytest.mark.parametrize("failure_point", ["episode_insert", "audit"])
def test_episode_and_stock_roll_back_on_required_persistence_failure(
    authenticated_client, monkeypatch, failure_point
):
    import app.modules.inventory.service as inventory_service

    client = authenticated_client
    restaurant_id = create_restaurant(client)
    ingredient = create_ingredient(client, restaurant_id)
    ingredient_id = ingredient["id"]
    audit_before = client.get("/api/audit?limit=100").json()

    def fail(*args, **kwargs):
        raise RuntimeError("Injected inventory persistence failure")

    if failure_point == "episode_insert":
        monkeypatch.setattr(InventoryTransitionRepository, "add_episode", fail)
    else:
        monkeypatch.setattr(inventory_service, "record", fail)

    with pytest.raises(RuntimeError, match="Injected inventory persistence failure"):
        change_stock(client, restaurant_id, ingredient_id, "rollback", "waste", "5")

    assert revision_for(ingredient_id) == 1
    assert episodes_for(ingredient_id) == []
    assert (
        client.get(f"/api/restaurants/{restaurant_id}/inventory/ingredients").json()[0][
            "quantity"
        ]
        == "10.000"
    )
    assert (
        len(
            client.get(
                f"/api/restaurants/{restaurant_id}/inventory/ingredients/"
                f"{ingredient_id}/movements"
            ).json()
        )
        == 1
    )
    assert client.get("/api/audit?limit=100").json() == audit_before
