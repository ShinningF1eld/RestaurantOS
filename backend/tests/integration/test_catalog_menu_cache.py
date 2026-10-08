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

        count = client.post(
            f"/api/restaurants/{restaurant_id}/inventory/ingredients/"
            f"{ingredient.json()['id']}/movements",
            json={
                "kind": "count",
                "quantity": "2",
                "reason": "Live stock check",
                "expected_version": 1,
                "idempotency_key": "item-cache-count",
            },
        )
        assert count.status_code == 201, count.text
        second = client.get(f"/menus/{menu_id}/items")
        assert second.status_code == 200, second.text
        assert second.json()[0]["available_portions"] == 0
        assert second.json()[0]["out_of_stock"] is True
        assert source_reads == 1

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE memberships SET status = 'revoked' WHERE user_id = :user"),
                {"user": auth_user["id"]},
            )
        denied = client.get(f"/menus/{menu_id}/items")
        assert denied.status_code == 403
        assert source_reads == 1
    finally:
        client.portal.call(redis.execute, "DEL", key)


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
