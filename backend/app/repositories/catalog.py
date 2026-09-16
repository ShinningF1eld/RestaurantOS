"""Focused persistence operations for menus and menu items."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.menu import Menu
from app.db.models.menu_items import MenuItem
from app.db.models.order import OrderItem


class CatalogRepository:
    """Access catalog records through one caller-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_menu(self, menu: Menu) -> None:
        """Stage a menu for insertion without committing it."""
        self._session.add(menu)

    async def get_menu_by_id(self, menu_id: int) -> Menu | None:
        """Return a menu by primary key when it exists."""
        result = await self._session.execute(
            select(Menu).where(Menu.menu_id == menu_id)
        )
        return result.scalar_one_or_none()

    async def list_menus_for_restaurant(self, restaurant_id: int) -> Sequence[Menu]:
        """Return all menus belonging to a restaurant."""
        result = await self._session.execute(
            select(Menu).where(Menu.restaurant_id == restaurant_id)
        )
        return result.scalars().all()

    async def delete_menu(self, menu: Menu) -> None:
        """Stage a menu for deletion without committing it."""
        await self._session.delete(menu)

    async def refresh_menu(self, menu: Menu) -> None:
        """Refresh a menu using the current transaction."""
        await self._session.refresh(menu)

    async def add_menu_item(self, menu_item: MenuItem) -> None:
        """Stage a menu item for insertion without committing it."""
        self._session.add(menu_item)

    async def get_menu_item_by_id(self, menu_item_id: int) -> MenuItem | None:
        """Return a menu item by primary key when it exists."""
        result = await self._session.execute(
            select(MenuItem).where(MenuItem.menu_item_id == menu_item_id)
        )
        return result.scalar_one_or_none()

    async def list_menu_items_for_menu(self, menu_id: int) -> Sequence[MenuItem]:
        """Return all menu items belonging to a menu."""
        result = await self._session.execute(
            select(MenuItem).where(MenuItem.menu_id == menu_id)
        )
        return result.scalars().all()

    async def menu_item_has_order_history(self, menu_item_id: int) -> bool:
        """Return whether an item is referenced by a historical order item."""
        result = await self._session.scalar(
            select(OrderItem.order_item_id)
            .where(OrderItem.menu_item_id == menu_item_id)
            .limit(1)
        )
        return result is not None

    async def delete_menu_item(self, menu_item: MenuItem) -> None:
        """Stage a menu item for deletion without committing it."""
        await self._session.delete(menu_item)

    async def flush(self) -> None:
        """Flush staged changes so generated fields are available."""
        await self._session.flush()

    async def refresh_menu_item(self, menu_item: MenuItem) -> None:
        """Refresh a menu item using the current transaction."""
        await self._session.refresh(menu_item)
