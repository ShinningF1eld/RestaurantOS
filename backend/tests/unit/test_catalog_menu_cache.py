from __future__ import annotations

import json

import pytest

from app.modules.catalog.menu_cache import (
    MENU_LIST_MAX_AGE_MS,
    CachedMenu,
    CatalogMenuCache,
)
from app.redis.adapter import FailureKind, RedisFailure


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.commands: list[tuple[object, ...]] = []
        self.failure: RedisFailure | None = None

    def namespace(self, use_case: str, version: int) -> str:
        return f"restaurantos:development:{use_case}:v{version}:"

    async def execute(self, *arguments: object) -> object:
        self.commands.append(arguments)
        if self.failure is not None:
            raise self.failure
        if arguments[0] == "GET":
            return self.values.get(str(arguments[1]))
        if arguments[0] == "SET":
            self.values[str(arguments[1])] = str(arguments[2]).encode()
            return b"OK"
        raise AssertionError(f"Unexpected command: {arguments[0]}")


def test_menu_list_key_uses_the_accepted_tenant_scoped_shape() -> None:
    redis = FakeRedis()

    key = CatalogMenuCache.key(redis, organization_id="org-uuid", restaurant_id=42)

    assert key == "restaurantos:development:catalog:v1:org:org-uuid:restaurant:42:menus"
    other_organization_key = CatalogMenuCache.key(
        redis, organization_id="other-org-uuid", restaurant_id=42
    )
    assert other_organization_key != key
    assert set(CachedMenu.model_fields) == {
        "menu_id",
        "restaurant_id",
        "name",
        "description",
    }


@pytest.mark.asyncio
async def test_store_uses_only_remaining_absolute_age_ttl() -> None:
    monotonic = [20.0]
    wall_time = [1_800_000_000.0]
    cache = CatalogMenuCache(
        monotonic=lambda: monotonic[0], wall_time=lambda: wall_time[0]
    )
    redis = FakeRedis()
    key = "menu-list"
    menus = [
        CachedMenu(
            menu_id=7,
            restaurant_id=42,
            name="Lunch",
            description=None,
        )
    ]

    monotonic[0] += 2.345
    await cache.store(
        redis,
        key,
        restaurant_id=42,
        menus=menus,
        source_started_at=wall_time[0],
        source_started_monotonic=20.0,
    )

    command = redis.commands[-1]
    assert command[:2] == ("SET", key)
    assert command[3] == "PX"
    assert command[4] == MENU_LIST_MAX_AGE_MS - 2345
    payload = json.loads(redis.values[key])
    assert payload["source_started_at"] == wall_time[0]
    assert payload["menus"][0]["name"] == "Lunch"


@pytest.mark.asyncio
async def test_slow_fill_is_discarded_after_absolute_age() -> None:
    monotonic = [20.0]
    cache = CatalogMenuCache(monotonic=lambda: monotonic[0])
    redis = FakeRedis()

    monotonic[0] = 30.001
    await cache.store(
        redis,
        "menu-list",
        restaurant_id=42,
        menus=[],
        source_started_at=1_800_000_000.0,
        source_started_monotonic=20.0,
    )

    assert redis.commands == []


@pytest.mark.asyncio
async def test_expired_payload_is_a_miss_without_opening_circuit() -> None:
    monotonic = [5.0]
    wall_time = [100.0]
    cache = CatalogMenuCache(
        monotonic=lambda: monotonic[0], wall_time=lambda: wall_time[0]
    )
    redis = FakeRedis()
    key = "menu-list"
    redis.values[key] = json.dumps(
        {
            "schema_version": 1,
            "restaurant_id": 42,
            "source_started_at": 90.0,
            "menus": [],
        }
    ).encode()

    lookup = await cache.lookup(redis, key, restaurant_id=42)
    next_lookup = await cache.lookup(redis, key, restaurant_id=42)

    assert lookup.menus is None
    assert lookup.redis_available is True
    assert next_lookup.redis_available is True
    assert [command[0] for command in redis.commands] == ["GET", "GET"]


@pytest.mark.asyncio
async def test_schema_mismatch_is_a_miss_without_opening_circuit() -> None:
    cache = CatalogMenuCache()
    redis = FakeRedis()
    redis.values["menu-list"] = json.dumps(
        {
            "schema_version": 2,
            "restaurant_id": 42,
            "source_started_at": 1_800_000_000.0,
            "menus": [],
        }
    ).encode()

    lookup = await cache.lookup(redis, "menu-list", restaurant_id=42)

    assert lookup.menus is None
    assert lookup.redis_available is True


@pytest.mark.asyncio
async def test_non_finite_source_age_is_rejected() -> None:
    cache = CatalogMenuCache()
    redis = FakeRedis()
    redis.values["menu-list"] = (
        b'{"schema_version":1,"restaurant_id":42,"source_started_at":NaN,"menus":[]}'
    )

    lookup = await cache.lookup(redis, "menu-list", restaurant_id=42)

    assert lookup.menus is None
    assert lookup.redis_available is True


@pytest.mark.asyncio
async def test_transport_failure_bypasses_redis_until_single_recovery_probe() -> None:
    monotonic = [5.0]
    cache = CatalogMenuCache(monotonic=lambda: monotonic[0], cooldown_seconds=5)
    redis = FakeRedis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)

    failed = await cache.lookup(redis, "menu-list", restaurant_id=42)
    during_cooldown = await cache.lookup(redis, "menu-list", restaurant_id=42)
    assert failed.redis_available is False
    assert during_cooldown.redis_available is False
    assert len(redis.commands) == 1

    monotonic[0] = 10.0
    redis.failure = None
    recovered = await cache.lookup(redis, "menu-list", restaurant_id=42)
    after_recovery = await cache.lookup(redis, "menu-list", restaurant_id=42)

    assert recovered.redis_available is True
    assert after_recovery.redis_available is True
    assert len(redis.commands) == 3
