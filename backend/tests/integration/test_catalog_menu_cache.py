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
