"""Bounded Redis cache for the authorized restaurant menu-list response."""

from __future__ import annotations

import logging
import math
import os
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Annotated
from threading import Lock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.catalog.domain.policies import MAX_MENU_PRICE
from app.redis.adapter import FailureKind, RedisFailure


MENU_LIST_MAX_AGE_SECONDS = 10
MENU_LIST_MAX_AGE_MS = MENU_LIST_MAX_AGE_SECONDS * 1000
MENU_CACHE_RECOVERY_COOLDOWN_SECONDS = 5

logger = logging.getLogger(__name__)


class RedisCommands(Protocol):
    def namespace(self, use_case: str, version: int) -> str: ...

    async def execute(self, *arguments: object) -> object: ...


class CachedMenu(BaseModel):
    """Only the stable menu fields included in the existing response."""

    menu_id: int
    restaurant_id: int
    name: str
    description: str | None

    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")


class MenuListPayload(BaseModel):
    schema_version: int
    restaurant_id: int
    source_started_at: float
    menus: list[CachedMenu]

    model_config = ConfigDict(frozen=True, extra="forbid")


class CachedMenuItem(BaseModel):
    """Stable menu-item fields; stock availability is always read live."""

    menu_item_id: int
    menu_id: int
    restaurant_id: int
    name: str
    description: str | None
    price: Annotated[
        Decimal,
        Field(ge=0, le=MAX_MENU_PRICE, max_digits=10, decimal_places=2),
    ]
    is_available: bool

    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")


class MenuItemListPayload(BaseModel):
    schema_version: int
    menu_id: int
    restaurant_id: int
    source_started_at: float
    items: list[CachedMenuItem]

    model_config = ConfigDict(frozen=True, extra="forbid")


class MenuListLookup(BaseModel):
    menus: list[CachedMenu] | None
    redis_available: bool


class CatalogMenuCache:
    """Owns catalog-only outage state; it does not control auth Redis health."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
        cooldown_seconds: float = MENU_CACHE_RECOVERY_COOLDOWN_SECONDS,
    ) -> None:
        self._monotonic = monotonic
        self._wall_time = wall_time
        self._cooldown_seconds = cooldown_seconds
        self._open_until: float | None = None
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._state_lock = Lock()

    async def invalidate(self, redis: RedisCommands, *keys: str) -> None:
        """Best-effort targeted invalidation; committed writes never depend on it."""
        if not keys:
            return
        try:
            await redis.execute("DEL", *keys)
        except RedisFailure as error:
            # Do not open the read circuit here: failed invalidation is bounded by
            # the source-age TTL and is independent of cache lookup health.
            logger.warning(
                "Catalog cache invalidation failed",
                extra={
                    "event": "catalog_cache_invalidation_failed",
                    "failure_kind": error.kind.value,
                },
            )

    @staticmethod
    def key(
        redis: RedisCommands,
        *,
        organization_id: str,
        restaurant_id: int,
    ) -> str:
        return (
            f"{redis.namespace('catalog', 1)}org:{organization_id}:"
            f"restaurant:{restaurant_id}:menus"
        )

    @staticmethod
    def menu_items_key(
        redis: RedisCommands,
        *,
        organization_id: str,
        menu_id: int,
    ) -> str:
        return (
            f"{redis.namespace('catalog', 1)}org:{organization_id}:menu:{menu_id}:items"
        )

    async def _begin_lookup(self) -> tuple[bool, bool]:
        """Return whether Redis may be used and whether this request is its probe."""
        now = self._monotonic()
        with self._state_lock:
            if self._open_until is None:
                return True, False
            if now < self._open_until or self._probe_in_flight:
                return False, False
            self._probe_in_flight = True
            return True, True

    async def _finish_probe(self, *, success: bool) -> None:
        with self._state_lock:
            self._probe_in_flight = False
            if success and self._open_until is not None:
                opened_at = self._opened_at
                duration = (
                    max(0.0, self._monotonic() - opened_at)
                    if opened_at is not None
                    else 0.0
                )
                self._open_until = None
                self._opened_at = None
                logger.info(
                    "Catalog Redis cache circuit recovered",
                    extra={"process_id": os.getpid(), "duration_seconds": duration},
                )

    async def _open_circuit(self, reason: FailureKind) -> None:
        now = self._monotonic()
        with self._state_lock:
            newly_open = self._open_until is None
            self._open_until = now + self._cooldown_seconds
            if newly_open:
                self._opened_at = now
                logger.warning(
                    "Catalog Redis cache circuit opened",
                    extra={"process_id": os.getpid(), "reason": reason.value},
                )

    def _valid_payload(
        self, raw: object, *, restaurant_id: int
    ) -> list[CachedMenu] | None:
        if not isinstance(raw, (bytes, str)):
            return None
        try:
            payload = MenuListPayload.model_validate_json(raw)
        except (ValidationError, ValueError, UnicodeDecodeError):
            return None
        age = self._wall_time() - payload.source_started_at
        if (
            payload.schema_version != 1
            or payload.restaurant_id != restaurant_id
            or not math.isfinite(payload.source_started_at)
            or age < 0
            or age >= MENU_LIST_MAX_AGE_SECONDS
            or any(menu.restaurant_id != restaurant_id for menu in payload.menus)
        ):
            return None
        return payload.menus

    def _valid_item_payload(
        self,
        raw: object,
        *,
        menu_id: int,
        restaurant_id: int,
    ) -> list[CachedMenuItem] | None:
        if not isinstance(raw, (bytes, str)):
            return None
        try:
            payload = MenuItemListPayload.model_validate_json(raw)
        except (ValidationError, ValueError, UnicodeDecodeError):
            return None
        age = self._wall_time() - payload.source_started_at
        item_ids = [item.menu_item_id for item in payload.items]
        if (
            payload.schema_version != 1
            or payload.menu_id != menu_id
            or payload.restaurant_id != restaurant_id
            or not math.isfinite(payload.source_started_at)
            or age < 0
            or age >= MENU_LIST_MAX_AGE_SECONDS
            or len(item_ids) != len(set(item_ids))
            or any(
                item.menu_id != menu_id or item.restaurant_id != restaurant_id
                for item in payload.items
            )
        ):
            return None
        return payload.items

    async def lookup(
        self,
        redis: RedisCommands,
        key: str,
        *,
        restaurant_id: int,
    ) -> MenuListLookup:
        allowed, is_probe = await self._begin_lookup()
        if not allowed:
            return MenuListLookup(menus=None, redis_available=False)

        try:
            raw = await redis.execute("GET", key)
        except RedisFailure as error:
            if error.kind in {
                FailureKind.TIMEOUT,
                FailureKind.CONNECTION,
                FailureKind.CLOSED,
            }:
                await self._open_circuit(error.kind)
            if is_probe:
                await self._finish_probe(success=False)
            return MenuListLookup(menus=None, redis_available=False)
        except BaseException:
            if is_probe:
                await self._finish_probe(success=False)
            raise

        if is_probe:
            await self._finish_probe(success=True)
        return MenuListLookup(
            menus=self._valid_payload(raw, restaurant_id=restaurant_id)
            if raw is not None
            else None,
            redis_available=True,
        )

    async def lookup_menu_items(
        self,
        redis: RedisCommands,
        key: str,
        *,
        menu_id: int,
        restaurant_id: int,
    ) -> tuple[list[CachedMenuItem] | None, bool]:
        allowed, is_probe = await self._begin_lookup()
        if not allowed:
            return None, False

        try:
            raw = await redis.execute("GET", key)
        except RedisFailure as error:
            if error.kind in {
                FailureKind.TIMEOUT,
                FailureKind.CONNECTION,
                FailureKind.CLOSED,
            }:
                await self._open_circuit(error.kind)
            if is_probe:
                await self._finish_probe(success=False)
            return None, False
        except BaseException:
            if is_probe:
                await self._finish_probe(success=False)
            raise

        if is_probe:
            await self._finish_probe(success=True)
        return (
            self._valid_item_payload(raw, menu_id=menu_id, restaurant_id=restaurant_id)
            if raw is not None
            else None,
            True,
        )

    async def store(
        self,
        redis: RedisCommands,
        key: str,
        *,
        restaurant_id: int,
        menus: list[CachedMenu],
        source_started_at: float,
        source_started_monotonic: float,
    ) -> None:
        payload = MenuListPayload(
            schema_version=1,
            restaurant_id=restaurant_id,
            source_started_at=source_started_at,
            menus=menus,
        )
        serialized_payload = payload.model_dump_json()
        # Include query, DTO construction, and serialization in the absolute age.
        elapsed_ms = math.ceil(
            max(0.0, self._monotonic() - source_started_monotonic) * 1000
        )
        remaining_ms = MENU_LIST_MAX_AGE_MS - elapsed_ms
        if remaining_ms <= 0:
            return
        try:
            await redis.execute("SET", key, serialized_payload, "PX", remaining_ms)
        except RedisFailure as error:
            if error.kind in {
                FailureKind.TIMEOUT,
                FailureKind.CONNECTION,
                FailureKind.CLOSED,
            }:
                await self._open_circuit(error.kind)

    async def store_menu_items(
        self,
        redis: RedisCommands,
        key: str,
        *,
        menu_id: int,
        restaurant_id: int,
        items: list[CachedMenuItem],
        source_started_at: float,
        source_started_monotonic: float,
    ) -> None:
        payload = MenuItemListPayload(
            schema_version=1,
            menu_id=menu_id,
            restaurant_id=restaurant_id,
            source_started_at=source_started_at,
            items=items,
        )
        serialized_payload = payload.model_dump_json()
        elapsed_ms = math.ceil(
            max(0.0, self._monotonic() - source_started_monotonic) * 1000
        )
        remaining_ms = MENU_LIST_MAX_AGE_MS - elapsed_ms
        if remaining_ms <= 0:
            return
        try:
            await redis.execute("SET", key, serialized_payload, "PX", remaining_ms)
        except RedisFailure as error:
            if error.kind in {
                FailureKind.TIMEOUT,
                FailureKind.CONNECTION,
                FailureKind.CLOSED,
            }:
                await self._open_circuit(error.kind)


__all__ = ["CachedMenu", "CachedMenuItem", "CatalogMenuCache"]
