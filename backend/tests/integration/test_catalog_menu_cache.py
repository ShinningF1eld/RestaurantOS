import json

from sqlalchemy import text

from conftest import engine


def test_menu_list_warm_hit_keeps_membership_authorization_fresh(
    authenticated_client, auth_user, monkeypatch
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache
    from app.modules.catalog.repo.queries import CatalogRepository

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Cache test"})
    assert restaurant.status_code == 201, restaurant.text
    restaurant_id = restaurant.json()["id"]
    redis = app.state.redis
    key = CatalogMenuCache.key(
        redis,
        organization_id=auth_user["organization_id"],
        restaurant_id=restaurant_id,
    )
    created = client.post(
        f"/restaurants/{restaurant_id}/menus",
        json={"name": "Lunch", "description": "Menu description"},
    )
    assert created.status_code == 200, created.text

    source_reads = 0
    original = CatalogRepository.list_menus_for_restaurant

    async def count_source_reads(self, requested_restaurant_id):
        nonlocal source_reads
        source_reads += 1
        return await original(self, requested_restaurant_id)

    monkeypatch.setattr(
        CatalogRepository, "list_menus_for_restaurant", count_source_reads
    )
    try:
        client.portal.call(
            redis.execute,
            "SET",
            key,
            '{"schema_version":99,"restaurant_id":'
            f'{restaurant_id},"source_started_at":1.0,"menus":[]}}',
            "PX",
            10_000,
        )
        first = client.get(f"/restaurants/{restaurant_id}/menus")
        second = client.get(f"/restaurants/{restaurant_id}/menus")

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json() == [created.json()]
        assert source_reads == 1

        # Revoke membership after warming. The next request must fail during
        # fresh access resolution before it can return the cached response.
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE memberships SET status = 'revoked' WHERE user_id = :user"),
                {"user": auth_user["id"]},
            )
        denied = client.get(f"/restaurants/{restaurant_id}/menus")
        assert denied.status_code == 403
        assert source_reads == 1
    finally:
        client.portal.call(redis.execute, "DEL", key)


def test_menu_list_redis_outage_falls_back_and_opens_catalog_circuit(
    authenticated_client, monkeypatch
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache
    from app.modules.catalog.repo.queries import CatalogRepository
    from app.redis.adapter import FailureKind, RedisFailure

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Fallback test"})
    assert restaurant.status_code == 201, restaurant.text
    restaurant_id = restaurant.json()["id"]
    menu = client.post(f"/restaurants/{restaurant_id}/menus", json={"name": "Menu"})
    assert menu.status_code == 200, menu.text

    source_reads = 0
    redis_gets = 0
    original_read = CatalogRepository.list_menus_for_restaurant
    original_execute = app.state.redis.execute

    async def count_source_reads(self, requested_restaurant_id):
        nonlocal source_reads
        source_reads += 1
        return await original_read(self, requested_restaurant_id)

    async def unavailable_get(*arguments):
        nonlocal redis_gets
        if arguments[0] == "GET":
            redis_gets += 1
            raise RedisFailure(FailureKind.CONNECTION)
        return await original_execute(*arguments)

    monkeypatch.setattr(
        CatalogRepository, "list_menus_for_restaurant", count_source_reads
    )
    monkeypatch.setattr(app.state.redis, "execute", unavailable_get)
    monkeypatch.setattr(
        app.state, "catalog_menu_cache", CatalogMenuCache(cooldown_seconds=60)
    )

    first = client.get(f"/restaurants/{restaurant_id}/menus")
    second = client.get(f"/restaurants/{restaurant_id}/menus")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == [menu.json()]
    assert source_reads == 2
    assert redis_gets == 1


def test_menu_item_list_cache_keeps_stock_live_and_rechecks_membership(
    authenticated_client, auth_user, monkeypatch
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache
    from app.modules.catalog.repo.queries import CatalogRepository

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Item cache"})
    assert restaurant.status_code == 201, restaurant.text
    restaurant_id = restaurant.json()["id"]
    menu = client.post(f"/restaurants/{restaurant_id}/menus", json={"name": "Dinner"})
    assert menu.status_code == 200, menu.text
    menu_id = menu.json()["menu_id"]
    created = client.post(
        f"/menus/{menu_id}/items",
        json={"name": "Noodle bowl", "price": "15.20"},
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["menu_item_id"]
    ingredient = client.post(
        f"/api/restaurants/{restaurant_id}/inventory/ingredients",
        json={
            "name": "Noodles",
            "unit": "g",
            "reorder_threshold": "0",
            "opening_quantity": "20",
            "idempotency_key": "item-cache-opening",
        },
    )
    assert ingredient.status_code == 201, ingredient.text
    recipe = client.put(
        f"/menu-items/{item_id}/recipe",
        json={
            "inventory_tracking": True,
            "components": [{"ingredient_id": ingredient.json()["id"], "quantity": "4"}],
        },
    )
    assert recipe.status_code == 200, recipe.text

    redis = app.state.redis
    key = CatalogMenuCache.menu_items_key(
        redis, organization_id=auth_user["organization_id"], menu_id=menu_id
    )
    source_reads = 0
    original = CatalogRepository.list_menu_items_for_menu

    async def count_source_reads(self, requested_menu_id):
        nonlocal source_reads
        source_reads += 1
        return await original(self, requested_menu_id)

    monkeypatch.setattr(
        CatalogRepository, "list_menu_items_for_menu", count_source_reads
    )
    try:
        first = client.get(f"/menus/{menu_id}/items")
        assert first.status_code == 200, first.text
        assert first.json()[0]["available_portions"] == 5
        raw_payload = client.portal.call(redis.execute, "GET", key)
        assert raw_payload is not None
        payload_item = json.loads(raw_payload)["items"][0]
        assert payload_item["price"] == "15.20"
        assert set(payload_item) == {
            "menu_item_id",
            "menu_id",
            "restaurant_id",
            "name",
            "description",
            "price",
            "is_available",
        }

        receipt = client.post(
            f"/api/restaurants/{restaurant_id}/inventory/ingredients/"
            f"{ingredient.json()['id']}/movements",
            json={
                "kind": "receipt",
                "quantity": "4",
                "reason": "Live stock receipt",
                "idempotency_key": "item-cache-receipt",
            },
        )
        assert receipt.status_code == 201, receipt.text
        after_receipt = client.get(f"/menus/{menu_id}/items")
        assert after_receipt.status_code == 200, after_receipt.text
        assert after_receipt.json()[0]["available_portions"] == 6

        waste = client.post(
            f"/api/restaurants/{restaurant_id}/inventory/ingredients/"
            f"{ingredient.json()['id']}/movements",
            json={
                "kind": "waste",
                "quantity": "4",
                "reason": "Live stock waste",
                "idempotency_key": "item-cache-waste",
            },
        )
        assert waste.status_code == 201, waste.text
        after_waste = client.get(f"/menus/{menu_id}/items")
        assert after_waste.status_code == 200, after_waste.text
        assert after_waste.json()[0]["available_portions"] == 5

        count = client.post(
            f"/api/restaurants/{restaurant_id}/inventory/ingredients/"
            f"{ingredient.json()['id']}/movements",
            json={
                "kind": "count",
                "quantity": "8",
                "reason": "Live stock count",
                "expected_version": 3,
                "idempotency_key": "item-cache-count",
            },
        )
        assert count.status_code == 201, count.text
        after_count = client.get(f"/menus/{menu_id}/items")
        assert after_count.status_code == 200, after_count.text
        assert after_count.json()[0]["available_portions"] == 2

        # The successful catalog write invalidates the item list, so the next
        # response reloads the new fixed-precision price from PostgreSQL.
        changed_price = client.put(f"/menu-items/{item_id}", json={"price": "18.99"})
        assert changed_price.status_code == 200, changed_price.text
        refreshed_price = client.get(f"/menus/{menu_id}/items")
        assert refreshed_price.status_code == 200, refreshed_price.text
        assert refreshed_price.json()[0]["price"] == "18.99"
        order = client.post(
            f"/api/restaurants/{restaurant_id}/orders",
            json={
                "idempotency_key": "item-cache-authoritative-price",
                "items": [{"menu_item_id": item_id, "quantity": 1}],
            },
        )
        assert order.status_code == 201, order.text
        order_id = order.json()["order_id"]
        order_detail = client.get(f"/api/orders/{order_id}")
        assert order_detail.status_code == 200, order_detail.text
        assert str(order_detail.json()["items"][0]["unit_price"]) == "18.99"
        submitted = client.put(f"/api/orders/{order_id}", json={"status": "SUBMITTED"})
        assert submitted.status_code == 200, submitted.text
        accepted = client.put(f"/api/orders/{order_id}", json={"status": "ACCEPTED"})
        assert accepted.status_code == 200, accepted.text
        after_consumption = client.get(f"/menus/{menu_id}/items")
        assert after_consumption.status_code == 200, after_consumption.text
        assert after_consumption.json()[0]["available_portions"] == 1

        changed_recipe = client.put(
            f"/menu-items/{item_id}/recipe",
            json={"inventory_tracking": False, "components": []},
        )
        assert changed_recipe.status_code == 200, changed_recipe.text
        after_recipe_change = client.get(f"/menus/{menu_id}/items")
        assert after_recipe_change.status_code == 200, after_recipe_change.text
        assert after_recipe_change.json()[0]["inventory_tracking"] is False
        assert after_recipe_change.json()[0]["out_of_stock"] is False
        assert after_recipe_change.json()[0]["available_portions"] is None
        assert source_reads == 2

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE memberships SET status = 'revoked' WHERE user_id = :user"),
                {"user": auth_user["id"]},
            )
        denied = client.get(f"/menus/{menu_id}/items")
        assert denied.status_code == 403
        assert source_reads == 2
    finally:
        client.portal.call(redis.execute, "DEL", key)


def test_corrupt_menu_item_cache_falls_back_to_scoped_database_payload(
    authenticated_client, auth_user, monkeypatch
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache
    from app.modules.catalog.repo.queries import CatalogRepository

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Corrupt item cache"})
    assert restaurant.status_code == 201, restaurant.text
    menu = client.post(
        f"/restaurants/{restaurant.json()['id']}/menus", json={"name": "Lunch"}
    )
    assert menu.status_code == 200, menu.text
    menu_id = menu.json()["menu_id"]
    item = client.post(
        f"/menus/{menu_id}/items", json={"name": "Soup", "price": "5.00"}
    )
    assert item.status_code == 200, item.text

    redis = app.state.redis
    key = CatalogMenuCache.menu_items_key(
        redis, organization_id=auth_user["organization_id"], menu_id=menu_id
    )
    source_reads = 0
    original = CatalogRepository.list_menu_items_for_menu

    async def count_source_reads(self, requested_menu_id):
        nonlocal source_reads
        source_reads += 1
        return await original(self, requested_menu_id)

    monkeypatch.setattr(
        CatalogRepository, "list_menu_items_for_menu", count_source_reads
    )
    try:
        client.portal.call(
            redis.execute,
            "SET",
            key,
            json.dumps(
                {
                    "schema_version": 99,
                    "menu_id": menu_id,
                    "restaurant_id": restaurant.json()["id"],
                    "source_started_at": 1_800_000_000.0,
                    "items": [],
                }
            ),
            "PX",
            10_000,
        )
        first = client.get(f"/menus/{menu_id}/items")
        second = client.get(f"/menus/{menu_id}/items")

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json() == [item.json()]
        assert source_reads == 1
    finally:
        client.portal.call(redis.execute, "DEL", key)


def test_deleted_menu_is_checked_before_cached_empty_item_list(
    authenticated_client, auth_user, monkeypatch
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Deleted menu cache"})
    assert restaurant.status_code == 201, restaurant.text
    menu = client.post(
        f"/restaurants/{restaurant.json()['id']}/menus", json={"name": "Empty"}
    )
    assert menu.status_code == 200, menu.text
    menu_id = menu.json()["menu_id"]
    redis = app.state.redis
    key = CatalogMenuCache.menu_items_key(
        redis, organization_id=auth_user["organization_id"], menu_id=menu_id
    )
    original_execute = redis.execute
    redis_gets = 0

    async def count_gets(*arguments):
        nonlocal redis_gets
        if arguments[0] == "GET" and arguments[1] == key:
            redis_gets += 1
        return await original_execute(*arguments)

    monkeypatch.setattr(redis, "execute", count_gets)
    try:
        warmed = client.get(f"/menus/{menu_id}/items")
        assert warmed.status_code == 200, warmed.text
        assert warmed.json() == []
        deleted = client.delete(f"/menus/{menu_id}")
        assert deleted.status_code == 200, deleted.text

        missing = client.get(f"/menus/{menu_id}/items")
        assert missing.status_code == 404
        assert redis_gets == 1
    finally:
        client.portal.call(original_execute, "DEL", key)


def test_menu_item_cache_entry_with_deleted_item_reloads_scoped_list(
    authenticated_client, auth_user, monkeypatch
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache
    from app.modules.catalog.repo.queries import CatalogRepository

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Deleted item cache"})
    assert restaurant.status_code == 201, restaurant.text
    menu = client.post(
        f"/restaurants/{restaurant.json()['id']}/menus", json={"name": "Lunch"}
    )
    assert menu.status_code == 200, menu.text
    menu_id = menu.json()["menu_id"]
    created = client.post(
        f"/menus/{menu_id}/items", json={"name": "Soup", "price": "5.00"}
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["menu_item_id"]

    redis = app.state.redis
    key = CatalogMenuCache.menu_items_key(
        redis, organization_id=auth_user["organization_id"], menu_id=menu_id
    )
    source_reads = 0
    original = CatalogRepository.list_menu_items_for_menu

    async def count_source_reads(self, requested_menu_id):
        nonlocal source_reads
        source_reads += 1
        return await original(self, requested_menu_id)

    monkeypatch.setattr(
        CatalogRepository, "list_menu_items_for_menu", count_source_reads
    )
    try:
        first = client.get(f"/menus/{menu_id}/items")
        assert first.status_code == 200, first.text
        assert first.json()[0]["menu_item_id"] == item_id
        deleted = client.delete(f"/menu-items/{item_id}")
        assert deleted.status_code == 200, deleted.text
        refreshed = client.get(f"/menus/{menu_id}/items")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json() == []
        assert source_reads == 2
    finally:
        client.portal.call(redis.execute, "DEL", key)


def test_committed_catalog_mutations_invalidate_only_their_list_keys(
    authenticated_client, auth_user
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Invalidate catalog"})
    assert restaurant.status_code == 201, restaurant.text
    restaurant_id = restaurant.json()["id"]
    redis = app.state.redis
    menu_key = CatalogMenuCache.key(
        redis, organization_id=auth_user["organization_id"], restaurant_id=restaurant_id
    )
    unrelated_key = "restaurantos:test:catalog:v1:org:unrelated:restaurant:999:menus"
    client.portal.call(redis.execute, "SET", unrelated_key, b"retained", "PX", 10_000)

    assert client.get(f"/restaurants/{restaurant_id}/menus").json() == []
    first_menu = client.post(
        f"/restaurants/{restaurant_id}/menus", json={"name": "Lunch"}
    )
    assert first_menu.status_code == 200, first_menu.text
    assert client.portal.call(redis.execute, "GET", menu_key) is None
    assert client.get(f"/restaurants/{restaurant_id}/menus").json() == [
        first_menu.json()
    ]

    menu_id = first_menu.json()["menu_id"]
    item_key = CatalogMenuCache.menu_items_key(
        redis, organization_id=auth_user["organization_id"], menu_id=menu_id
    )
    assert client.get(f"/menus/{menu_id}/items").json() == []
    item = client.post(
        f"/menus/{menu_id}/items", json={"name": "Soup", "price": "5.20"}
    )
    assert item.status_code == 200, item.text
    assert client.portal.call(redis.execute, "GET", item_key) is None
    assert client.get(f"/menus/{menu_id}/items").json() == [item.json()]

    changed_menu = client.put(
        f"/menus/{menu_id}", json={"name": "Dinner", "description": "Updated"}
    )
    assert changed_menu.status_code == 200, changed_menu.text
    assert client.portal.call(redis.execute, "GET", menu_key) is None
    assert client.get(f"/restaurants/{restaurant_id}/menus").json() == [
        changed_menu.json()
    ]

    changed_item = client.put(
        f"/menu-items/{item.json()['menu_item_id']}",
        json={"name": "Soup special", "price": "5.20"},
    )
    assert changed_item.status_code == 200, changed_item.text
    assert changed_item.json()["price"] == "5.20"
    assert client.portal.call(redis.execute, "GET", item_key) is None
    assert client.get(f"/menus/{menu_id}/items").json() == [changed_item.json()]

    deleted = client.delete(f"/menu-items/{item.json()['menu_item_id']}")
    assert deleted.status_code == 200, deleted.text
    assert client.portal.call(redis.execute, "GET", item_key) is None
    assert client.get(f"/menus/{menu_id}/items").json() == []

    historic_item = client.post(
        f"/menus/{menu_id}/items", json={"name": "Historic dish", "price": "7.40"}
    )
    assert historic_item.status_code == 200, historic_item.text
    historical_order = client.post(
        f"/api/restaurants/{restaurant_id}/orders",
        json={
            "idempotency_key": "catalog-deactivation-snapshot",
            "items": [
                {"menu_item_id": historic_item.json()["menu_item_id"], "quantity": 1}
            ],
        },
    )
    assert historical_order.status_code == 201, historical_order.text
    assert client.get(f"/menus/{menu_id}/items").status_code == 200
    deactivated = client.delete(f"/menu-items/{historic_item.json()['menu_item_id']}")
    assert deactivated.status_code == 200, deactivated.text
    assert "deactivated" in deactivated.json()["message"]
    assert client.portal.call(redis.execute, "GET", item_key) is None
    remaining_item = client.get(f"/menus/{menu_id}/items").json()[0]
    assert remaining_item["is_available"] is False
    historical_detail = client.get(f"/api/orders/{historical_order.json()['order_id']}")
    assert historical_detail.status_code == 200, historical_detail.text
    assert historical_detail.json()["items"][0]["menu_item_name"] == "Historic dish"
    assert str(historical_detail.json()["items"][0]["unit_price"]) == "7.40"

    empty_menu = client.post(
        f"/restaurants/{restaurant_id}/menus", json={"name": "Temporary"}
    )
    empty_menu_id = empty_menu.json()["menu_id"]
    deleted_item_list_key = CatalogMenuCache.menu_items_key(
        redis,
        organization_id=auth_user["organization_id"],
        menu_id=empty_menu_id,
    )
    assert client.get(f"/menus/{empty_menu_id}/items").json() == []
    assert client.get(f"/restaurants/{restaurant_id}/menus").status_code == 200
    assert client.delete(f"/menus/{empty_menu_id}").status_code == 200
    assert client.portal.call(redis.execute, "GET", menu_key) is None
    assert client.portal.call(redis.execute, "GET", deleted_item_list_key) is None
    assert client.portal.call(redis.execute, "GET", unrelated_key) == b"retained"
    client.portal.call(redis.execute, "DEL", unrelated_key)


def test_audit_failure_rolls_back_menu_update_without_invalidation(
    authenticated_client, auth_user, monkeypatch
) -> None:
    import pytest

    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Audit rollback"})
    menu = client.post(
        f"/restaurants/{restaurant.json()['id']}/menus", json={"name": "Original"}
    )
    menu_id = menu.json()["menu_id"]
    redis = app.state.redis
    key = CatalogMenuCache.key(
        redis,
        organization_id=auth_user["organization_id"],
        restaurant_id=restaurant.json()["id"],
    )
    client.get(f"/restaurants/{restaurant.json()['id']}/menus")
    original_execute = redis.execute
    delete_commands: list[tuple[object, ...]] = []

    async def observe_delete(*arguments: object) -> object:
        if arguments[0] == "DEL":
            delete_commands.append(arguments)
        return await original_execute(*arguments)

    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(redis, "execute", observe_delete)
    monkeypatch.setattr("app.modules.catalog.service.record", fail_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        client.put(f"/menus/{menu_id}", json={"name": "Should roll back"})

    monkeypatch.setattr("app.modules.catalog.service.record", lambda *_a, **_k: None)
    result = client.get(f"/menus/{menu_id}")
    assert result.status_code == 200
    assert result.json()["name"] == "Original"
    assert delete_commands == []
    assert client.portal.call(original_execute, "GET", key) is not None


def test_redis_invalidation_failure_does_not_fail_committed_menu_create(
    authenticated_client, auth_user, monkeypatch, caplog
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache
    from app.redis.adapter import FailureKind, RedisFailure

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Redis failure"})
    restaurant_id = restaurant.json()["id"]
    redis = app.state.redis
    key = CatalogMenuCache.key(
        redis,
        organization_id=auth_user["organization_id"],
        restaurant_id=restaurant_id,
    )
    client.get(f"/restaurants/{restaurant_id}/menus")
    original_execute = redis.execute

    async def fail_delete(*arguments: object) -> object:
        if arguments[0] == "DEL":
            raise RedisFailure(FailureKind.COMMAND)
        return await original_execute(*arguments)

    monkeypatch.setattr(redis, "execute", fail_delete)
    created = client.post(
        f"/restaurants/{restaurant_id}/menus", json={"name": "Committed"}
    )
    assert created.status_code == 200, created.text
    assert created.json()["name"] == "Committed"
    assert any(
        getattr(record, "event", None) == "catalog_cache_invalidation_failed"
        for record in caplog.records
    )
    monkeypatch.setattr(redis, "execute", original_execute)
    persisted = client.get(f"/menus/{created.json()['menu_id']}")
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["name"] == "Committed"
    assert client.portal.call(original_execute, "GET", key) is not None


def test_database_commit_failure_rolls_back_without_menu_invalidation(
    authenticated_client, auth_user, monkeypatch
) -> None:
    import pytest
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Commit rollback"})
    menu = client.post(
        f"/restaurants/{restaurant.json()['id']}/menus", json={"name": "Original"}
    )
    menu_id = menu.json()["menu_id"]
    redis = app.state.redis
    key = CatalogMenuCache.key(
        redis,
        organization_id=auth_user["organization_id"],
        restaurant_id=restaurant.json()["id"],
    )
    client.get(f"/restaurants/{restaurant.json()['id']}/menus")
    original_execute = redis.execute
    delete_commands: list[tuple[object, ...]] = []

    async def observe_delete(*arguments: object) -> object:
        if arguments[0] == "DEL":
            delete_commands.append(arguments)
        return await original_execute(*arguments)

    def fail_commit(_session: Session) -> None:
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(redis, "execute", observe_delete)
    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="injected commit failure"):
            client.put(f"/menus/{menu_id}", json={"name": "Should roll back"})
    finally:
        event.remove(Session, "before_commit", fail_commit)

    result = client.get(f"/menus/{menu_id}")
    assert result.status_code == 200
    assert result.json()["name"] == "Original"
    assert delete_commands == []
    assert client.portal.call(original_execute, "GET", key) is not None

    from app.modules.catalog.repo.queries import CatalogRepository

    async def fail_constraint_flush(_repository: CatalogRepository) -> None:
        raise IntegrityError("UPDATE menus", {}, RuntimeError("constraint failure"))

    monkeypatch.setattr(CatalogRepository, "flush", fail_constraint_flush)
    with pytest.raises(IntegrityError):
        client.put(f"/menus/{menu_id}", json={"name": "Constraint rollback"})
    monkeypatch.undo()

    result = client.get(f"/menus/{menu_id}")
    assert result.status_code == 200
    assert result.json()["name"] == "Original"
    assert delete_commands == []
    assert client.portal.call(original_execute, "GET", key) is not None


def test_menu_item_cache_redis_outage_falls_back_and_bypasses_during_cooldown(
    authenticated_client, monkeypatch
) -> None:
    from app.main import app
    from app.modules.catalog.menu_cache import CatalogMenuCache
    from app.modules.catalog.repo.queries import CatalogRepository
    from app.redis.adapter import FailureKind, RedisFailure

    client = authenticated_client
    restaurant = client.post("/api/restaurants", json={"name": "Item cache outage"})
    assert restaurant.status_code == 201, restaurant.text
    menu = client.post(
        f"/restaurants/{restaurant.json()['id']}/menus", json={"name": "Dinner"}
    )
    assert menu.status_code == 200, menu.text
    menu_id = menu.json()["menu_id"]
    item = client.post(
        f"/menus/{menu_id}/items", json={"name": "Rice", "price": "4.00"}
    )
    assert item.status_code == 200, item.text

    source_reads = 0
    redis_gets = 0
    original_read = CatalogRepository.list_menu_items_for_menu
    original_execute = app.state.redis.execute

    async def count_source_reads(self, requested_menu_id):
        nonlocal source_reads
        source_reads += 1
        return await original_read(self, requested_menu_id)

    async def unavailable_get(*arguments):
        nonlocal redis_gets
        if arguments[0] == "GET":
            redis_gets += 1
            raise RedisFailure(FailureKind.CONNECTION)
        return await original_execute(*arguments)

    monkeypatch.setattr(
        CatalogRepository, "list_menu_items_for_menu", count_source_reads
    )
    monkeypatch.setattr(app.state.redis, "execute", unavailable_get)
    monkeypatch.setattr(
        app.state, "catalog_menu_cache", CatalogMenuCache(cooldown_seconds=60)
    )

    first = client.get(f"/menus/{menu_id}/items")
    second = client.get(f"/menus/{menu_id}/items")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == [item.json()]
    assert source_reads == 2
    assert redis_gets == 1
