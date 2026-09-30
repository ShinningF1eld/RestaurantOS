"""Catalog application service and framework-independent command inputs."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models.menu import Menu
from app.db.models.menu_items import MenuItem
from app.repositories.catalog import CatalogRepository
from app.repositories.restaurant import RestaurantRepository


@dataclass(frozen=True, slots=True)
class CreateMenu:
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class UpdateMenu:
    name: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class CreateMenuItem:
    name: str
    description: str | None
    price: Decimal
    is_available: bool


@dataclass(frozen=True, slots=True)
class UpdateMenuItem:
    name: str | None
    description: str | None
    price: Decimal | None
    is_available: bool | None


DeleteMenuItemOutcome = Literal["deleted", "deactivated"]


class CatalogService:
    """Coordinates catalog use cases and owns write transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._catalog = CatalogRepository(session)
        self._restaurants = RestaurantRepository(session)

    async def create_menu(
        self, restaurant_id: int, command: CreateMenu
    ) -> Menu:
        """Create a menu only for an existing restaurant."""
        async with self._session.begin():
            if await self._restaurants.get_by_id(restaurant_id) is None:
                raise NotFoundError("Restaurant not found")
            menu = Menu(
                restaurant_id=restaurant_id,
                name=command.name,
                description=command.description,
            )
            await self._catalog.add_menu(menu)
            await self._catalog.flush()
            await self._catalog.refresh_menu(menu)
        return menu

    async def list_menus(self, restaurant_id: int) -> list[Menu]:
        """List menus for a restaurant without changing legacy empty-list behavior."""
        return list(await self._catalog.list_menus_for_restaurant(restaurant_id))

    async def get_menu(self, menu_id: int) -> Menu:
        """Get a menu or raise the public not-found domain error."""
        menu = await self._catalog.get_menu_by_id(menu_id)
        if menu is None:
            raise NotFoundError("Menu not found")
        return menu

    async def update_menu(self, menu_id: int, command: UpdateMenu) -> Menu:
        """Apply supplied menu fields atomically."""
        async with self._session.begin():
            menu = await self._catalog.get_menu_by_id(menu_id)
            if menu is None:
                raise NotFoundError("Menu not found")
            if command.name is not None:
                menu.name = command.name
            if command.description is not None:
                menu.description = command.description
            await self._catalog.flush()
            await self._catalog.refresh_menu(menu)
        return menu

    async def delete_menu(self, menu_id: int) -> None:
        """Delete a menu atomically."""
        async with self._session.begin():
            menu = await self._catalog.get_menu_by_id(menu_id)
            if menu is None:
                raise NotFoundError("Menu not found")
            await self._catalog.delete_menu(menu)

    async def create_menu_item(
        self, menu_id: int, command: CreateMenuItem
    ) -> MenuItem:
        """Create a menu item only for an existing menu."""
        async with self._session.begin():
            if await self._catalog.get_menu_by_id(menu_id) is None:
                raise NotFoundError("Menu not found")
            menu_item = MenuItem(
                menu_id=menu_id,
                name=command.name,
                description=command.description,
                price=command.price,
                is_available=command.is_available,
            )
            await self._catalog.add_menu_item(menu_item)
            await self._catalog.flush()
            await self._catalog.refresh_menu_item(menu_item)
        return menu_item

    async def list_menu_items(self, menu_id: int) -> list[MenuItem]:
        """List items for a menu without changing legacy empty-list behavior."""
        return list(await self._catalog.list_menu_items_for_menu(menu_id))

    async def get_menu_item(self, menu_item_id: int) -> MenuItem:
        """Get a menu item or raise the public not-found domain error."""
        menu_item = await self._catalog.get_menu_item_by_id(menu_item_id)
        if menu_item is None:
            raise NotFoundError("Menu item not found")
        return menu_item

    async def update_menu_item(
        self, menu_item_id: int, command: UpdateMenuItem
    ) -> MenuItem:
        """Apply supplied menu-item fields atomically."""
        async with self._session.begin():
            menu_item = await self._catalog.get_menu_item_by_id(menu_item_id)
            if menu_item is None:
                raise NotFoundError("Menu item not found")
            if command.name is not None:
                menu_item.name = command.name
            if command.description is not None:
                menu_item.description = command.description
            if command.price is not None:
                menu_item.price = command.price
            if command.is_available is not None:
                menu_item.is_available = command.is_available
            await self._catalog.flush()
            await self._catalog.refresh_menu_item(menu_item)
        return menu_item

    async def delete_menu_item(self, menu_item_id: int) -> DeleteMenuItemOutcome:
        """Delete unused items, preserving historical sales by deactivating used ones."""
        async with self._session.begin():
            menu_item = await self._catalog.get_menu_item_by_id(menu_item_id)
            if menu_item is None:
                raise NotFoundError("Menu item not found")
            if await self._catalog.menu_item_has_order_history(menu_item_id):
                menu_item.is_available = False
                return "deactivated"
            await self._catalog.delete_menu_item(menu_item)
            return "deleted"
