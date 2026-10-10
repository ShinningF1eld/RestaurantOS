"""Catalog application service and framework-independent command inputs."""

import time
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.catalog.domain.policies import validate_menu_price
from app.modules.catalog.repo.models import Menu
from app.modules.catalog.repo.models import MenuItem
from app.modules.catalog.repo.queries import CatalogRepository
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.inventory.repo.queries import InventoryRepository
from app.modules.recipes.service import RecipeAvailabilityService
from app.modules.tenancy.access import AccessService
from app.modules.tenancy.domain.policies import AccessContext
from app.modules.audit.service import record
from app.modules.catalog.menu_cache import (
    CachedMenu,
    CachedMenuItem,
    CatalogMenuCache,
)
from app.redis.adapter import RedisAdapter


from app.modules.catalog.domain.commands import (
    CreateMenu as CreateMenu,
    UpdateMenu as UpdateMenu,
    CreateMenuItem as CreateMenuItem,
    UpdateMenuItem as UpdateMenuItem,
    DeleteMenuItemOutcome as DeleteMenuItemOutcome,
)


class CatalogService:
    """Coordinates catalog use cases and owns write transactions."""

    def __init__(
        self,
        session: AsyncSession,
        principal: AuthenticatedPrincipal,
        *,
        menu_cache: CatalogMenuCache | None = None,
        redis: RedisAdapter | None = None,
    ) -> None:
        self._session = session
        self._access = AccessService(session, principal)
        self._menu_cache = menu_cache
        self._redis = redis

    async def _prepare(self, *, lock: bool = False) -> AccessContext:
        context = await self._access.current(lock=lock)
        self._catalog = CatalogRepository(self._session, context)
        return context

    async def _invalidate_menu_list(
        self, context: AccessContext, restaurant_id: int
    ) -> None:
        if self._menu_cache is None or self._redis is None:
            return
        key = self._menu_cache.key(
            self._redis,
            organization_id=str(context.organization_id),
            restaurant_id=restaurant_id,
        )
        await self._menu_cache.invalidate(self._redis, key)

    async def _invalidate_menu_items(
        self, context: AccessContext, menu_id: int
    ) -> None:
        if self._menu_cache is None or self._redis is None:
            return
        key = self._menu_cache.menu_items_key(
            self._redis,
            organization_id=str(context.organization_id),
            menu_id=menu_id,
        )
        await self._menu_cache.invalidate(self._redis, key)

    async def _invalidate_deleted_menu(
        self, context: AccessContext, restaurant_id: int, menu_id: int
    ) -> None:
        if self._menu_cache is None or self._redis is None:
            return
        menu_list_key = self._menu_cache.key(
            self._redis,
            organization_id=str(context.organization_id),
            restaurant_id=restaurant_id,
        )
        item_list_key = self._menu_cache.menu_items_key(
            self._redis,
            organization_id=str(context.organization_id),
            menu_id=menu_id,
        )
        await self._menu_cache.invalidate(self._redis, menu_list_key, item_list_key)

    async def _attach_menu_item_availability(
        self,
        menu_items: list[MenuItem],
        *,
        expected_menu_id: int | None = None,
        missing_is_cache_miss: bool = False,
    ) -> list[MenuItem] | None:
        availability = await RecipeAvailabilityService(self._session).for_menu_items(
            menu_items, expected_menu_id=expected_menu_id
        )
        for menu_item in menu_items:
            status = availability.get(menu_item.menu_item_id)
            if status is None:
                if missing_is_cache_miss:
                    return None
                raise NotFoundError("Menu item not found")
            # These response-only attributes keep the ORM model focused on stored
            # catalog state while exposing current stock beside menu items.
            menu_item.restaurant_id = status.restaurant_id
            menu_item.inventory_tracking = status.inventory_tracking
            menu_item.out_of_stock = status.out_of_stock
            menu_item.available_portions = status.available_portions
        return menu_items

    async def create_menu(self, restaurant_id: int, command: CreateMenu) -> Menu:
        """Create a menu only for an existing restaurant."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            await self._access.restaurant(context, restaurant_id, "menu.manage")
            menu = Menu(
                restaurant_id=restaurant_id,
                name=command.name,
                description=command.description,
            )
            await self._catalog.add_menu(menu)
            await self._catalog.flush()
            await self._catalog.refresh_menu(menu)
            record(
                self._session,
                context,
                "menu.created",
                "menu",
                menu.menu_id,
                restaurant_id=menu.restaurant_id,
            )
        await self._invalidate_menu_list(context, restaurant_id)
        return menu

    async def list_menus(self, restaurant_id: int) -> Sequence[Menu | CachedMenu]:
        """List menus only within an accessible restaurant."""
        context = await self._prepare()
        # This live check must precede all cache access: cached data never grants
        # membership, branch assignment, resource scope, or capability.
        await self._access.restaurant(context, restaurant_id, "menu.read")
        cache_key: str | None = None
        redis_available = False
        if self._menu_cache is not None and self._redis is not None:
            cache_key = self._menu_cache.key(
                self._redis,
                organization_id=str(context.organization_id),
                restaurant_id=restaurant_id,
            )
            cached = await self._menu_cache.lookup(
                self._redis, cache_key, restaurant_id=restaurant_id
            )
            if cached.menus is not None:
                return cached.menus
            redis_available = cached.redis_available

        source_started_at = time.time()
        source_started_monotonic = time.monotonic()
        menus = list(await self._catalog.list_menus_for_restaurant(restaurant_id))
        if (
            cache_key is not None
            and redis_available
            and self._menu_cache is not None
            and self._redis is not None
        ):
            await self._menu_cache.store(
                self._redis,
                cache_key,
                restaurant_id=restaurant_id,
                menus=[CachedMenu.model_validate(menu) for menu in menus],
                source_started_at=source_started_at,
                source_started_monotonic=source_started_monotonic,
            )
        return menus

    async def get_menu(self, menu_id: int) -> Menu:
        """Get a menu or raise the public not-found domain error."""
        context = await self._prepare()
        menu = await self._catalog.get_menu_by_id(menu_id)
        if menu is None:
            raise NotFoundError("Menu not found")
        context.require("menu.read")
        return menu

    async def update_menu(self, menu_id: int, command: UpdateMenu) -> Menu:
        """Apply supplied menu fields atomically."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            menu = await self._catalog.get_menu_by_id(menu_id)
            if menu is None:
                raise NotFoundError("Menu not found")
            context.require("menu.manage")
            if command.name is not None:
                menu.name = command.name
            if command.description is not None:
                menu.description = command.description
            await self._catalog.flush()
            await self._catalog.refresh_menu(menu)
            record(
                self._session,
                context,
                "menu.updated",
                "menu",
                menu.menu_id,
                restaurant_id=menu.restaurant_id,
            )
            restaurant_id = menu.restaurant_id
        await self._invalidate_menu_list(context, restaurant_id)
        return menu

    async def delete_menu(self, menu_id: int) -> None:
        """Delete a menu atomically."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            menu = await self._catalog.get_menu_by_id(menu_id)
            if menu is None:
                raise NotFoundError("Menu not found")
            context.require("menu.manage")
            if await self._catalog.menu_has_items(menu_id):
                raise ConflictError("Remove menu items before deleting the menu")
            record(
                self._session,
                context,
                "menu.deleted",
                "menu",
                menu_id,
                restaurant_id=menu.restaurant_id,
            )
            await self._catalog.delete_menu(menu)
            restaurant_id = menu.restaurant_id
        await self._invalidate_deleted_menu(context, restaurant_id, menu_id)

    async def create_menu_item(self, menu_id: int, command: CreateMenuItem) -> MenuItem:
        """Create a menu item only for an existing menu."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            menu = await self._catalog.get_menu_by_id(menu_id)
            if menu is None:
                raise NotFoundError("Menu not found")
            context.require("menu.manage")
            menu_item = MenuItem(
                menu_id=menu_id,
                name=command.name,
                description=command.description,
                price=validate_menu_price(command.price),
                is_available=command.is_available,
            )
            await self._catalog.add_menu_item(menu_item)
            await self._catalog.flush()
            await self._catalog.refresh_menu_item(menu_item)
            menu = await self._catalog.get_menu_by_id(menu_item.menu_id)
            assert menu is not None
            record(
                self._session,
                context,
                "menu_item.created",
                "menu_item",
                menu_item.menu_item_id,
                restaurant_id=menu.restaurant_id,
                changes={
                    "price": str(menu_item.price),
                    "is_available": menu_item.is_available,
                },
            )
            await self._attach_menu_item_availability([menu_item])
        await self._invalidate_menu_items(context, menu_id)
        return menu_item

    async def list_menu_items(self, menu_id: int) -> list[MenuItem]:
        """List items only within an accessible menu."""
        context = await self._prepare()
        menu = await self._catalog.get_menu_by_id(menu_id)
        if menu is None:
            raise NotFoundError("Menu not found")
        context.require("menu.read")
        cache_key: str | None = None
        redis_available = False
        if self._menu_cache is not None and self._redis is not None:
            cache_key = self._menu_cache.menu_items_key(
                self._redis,
                organization_id=str(context.organization_id),
                menu_id=menu_id,
            )
            cached_items, redis_available = await self._menu_cache.lookup_menu_items(
                self._redis,
                cache_key,
                menu_id=menu_id,
                restaurant_id=menu.restaurant_id,
            )
            if cached_items is not None:
                cached_models = [
                    MenuItem(
                        menu_item_id=item.menu_item_id,
                        menu_id=item.menu_id,
                        name=item.name,
                        description=item.description,
                        price=item.price,
                        is_available=item.is_available,
                    )
                    for item in cached_items
                ]
                cached_response = await self._attach_menu_item_availability(
                    cached_models,
                    expected_menu_id=menu_id,
                    missing_is_cache_miss=True,
                )
                if cached_response is not None:
                    return cached_response

        source_started_at = time.time()
        source_started_monotonic = time.monotonic()
        menu_items = list(await self._catalog.list_menu_items_for_menu(menu_id))
        response_items = await self._attach_menu_item_availability(
            menu_items, expected_menu_id=menu_id
        )
        assert response_items is not None
        if (
            cache_key is not None
            and redis_available
            and self._menu_cache is not None
            and self._redis is not None
        ):
            await self._menu_cache.store_menu_items(
                self._redis,
                cache_key,
                menu_id=menu_id,
                restaurant_id=menu.restaurant_id,
                items=[CachedMenuItem.model_validate(item) for item in menu_items],
                source_started_at=source_started_at,
                source_started_monotonic=source_started_monotonic,
            )
        return response_items

    async def get_menu_item(self, menu_item_id: int) -> MenuItem:
        """Get a menu item or raise the public not-found domain error."""
        context = await self._prepare()
        menu_item = await self._catalog.get_menu_item_by_id(menu_item_id)
        if menu_item is None:
            raise NotFoundError("Menu item not found")
        context.require("menu.read")
        await self._attach_menu_item_availability([menu_item])
        return menu_item

    async def update_menu_item(
        self, menu_item_id: int, command: UpdateMenuItem
    ) -> MenuItem:
        """Apply supplied menu-item fields atomically."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            menu_item = await self._catalog.get_menu_item_by_id(menu_item_id)
            if menu_item is None:
                raise NotFoundError("Menu item not found")
            context.require("menu.manage")
            menu = await self._catalog.get_menu_by_id(menu_item.menu_id)
            assert menu is not None
            await InventoryRepository(self._session, context).lock_restaurant(
                menu.restaurant_id
            )
            menu_item = await self._catalog.get_menu_item_by_id(menu_item_id, lock=True)
            if menu_item is None:
                raise NotFoundError("Menu item not found")
            if command.name is not None:
                menu_item.name = command.name
            if command.description is not None:
                menu_item.description = command.description
            if command.price is not None:
                menu_item.price = validate_menu_price(command.price)
            if command.is_available is not None:
                menu_item.is_available = command.is_available
            await self._catalog.flush()
            await self._catalog.refresh_menu_item(menu_item)
            menu = await self._catalog.get_menu_by_id(menu_item.menu_id)
            assert menu is not None
            record(
                self._session,
                context,
                "menu_item.updated",
                "menu_item",
                menu_item.menu_item_id,
                restaurant_id=menu.restaurant_id,
                changes={
                    "price": str(menu_item.price),
                    "is_available": menu_item.is_available,
                },
            )
            await self._attach_menu_item_availability([menu_item])
            menu_id = menu_item.menu_id
        await self._invalidate_menu_items(context, menu_id)
        return menu_item

    async def delete_menu_item(self, menu_item_id: int) -> DeleteMenuItemOutcome:
        """Delete unused items, preserving historical sales by deactivating used ones."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            menu_item = await self._catalog.get_menu_item_by_id(menu_item_id)
            if menu_item is None:
                raise NotFoundError("Menu item not found")
            context.require("menu.manage")
            menu = await self._catalog.get_menu_by_id(menu_item.menu_id)
            assert menu is not None
            await InventoryRepository(self._session, context).lock_restaurant(
                menu.restaurant_id
            )
            menu_item = await self._catalog.get_menu_item_by_id(menu_item_id, lock=True)
            if menu_item is None:
                raise NotFoundError("Menu item not found")
            if await self._catalog.menu_item_has_order_history(menu_item_id):
                menu_item.is_available = False
                record(
                    self._session,
                    context,
                    "menu_item.deactivated",
                    "menu_item",
                    menu_item_id,
                    restaurant_id=menu.restaurant_id,
                    changes={"is_available": False},
                )
                outcome: DeleteMenuItemOutcome = "deactivated"
            else:
                record(
                    self._session,
                    context,
                    "menu_item.deleted",
                    "menu_item",
                    menu_item_id,
                    restaurant_id=menu.restaurant_id,
                )
                await self._catalog.delete_menu_item(menu_item)
                outcome = "deleted"
            menu_id = menu_item.menu_id
        await self._invalidate_menu_items(context, menu_id)
        return outcome
