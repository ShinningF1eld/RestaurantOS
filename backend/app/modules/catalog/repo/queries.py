"""Focused persistence operations for menus and menu items."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.tenancy.access import restaurant_scope
from app.modules.tenancy.domain.policies import AccessContext

from app.modules.catalog.repo.models import Menu
from app.modules.catalog.repo.models import MenuItem
from app.modules.orders.repo.models import OrderItem
from app.modules.orders.repo.models import Order
from app.modules.restaurants.repo.models import Restaurant


class CatalogRepository:
    """Access catalog records through one caller-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession, scope: AccessContext) -> None:
        self._session = session
        self._scope = scope

    async def add_menu(self, menu: Menu) -> None:
        """Stage a menu for insertion without committing it."""
        self._session.add(menu)

    async def get_menu_by_id(self, menu_id: int) -> Menu | None:
        """Return a menu by primary key when it exists."""
        result = await self._session.execute(
            select(Menu)
            .join(Restaurant)
            .where(Menu.menu_id == menu_id, restaurant_scope(self._scope))
        )
        return result.scalar_one_or_none()

    async def list_menus_for_restaurant(self, restaurant_id: int) -> Sequence[Menu]:
        """Return all menus belonging to a restaurant."""
        result = await self._session.execute(
            select(Menu)
            .join(Restaurant)
            .where(Menu.restaurant_id == restaurant_id, restaurant_scope(self._scope))
        )
        return result.scalars().all()

    async def delete_menu(self, menu: Menu) -> None:
        """Stage a menu for deletion without committing it."""
        await self._session.delete(menu)

    async def menu_has_items(self, menu_id: int) -> bool:
        return bool(await self.list_menu_items_for_menu(menu_id))

    async def refresh_menu(self, menu: Menu) -> None:
        """Refresh a menu using the current transaction."""
        await self._session.refresh(menu)

    async def add_menu_item(self, menu_item: MenuItem) -> None:
        """Stage a menu item for insertion without committing it."""
        self._session.add(menu_item)

    async def get_menu_item_by_id(
        self, menu_item_id: int, *, lock: bool = False
    ) -> MenuItem | None:
        """Return a menu item by primary key when it exists."""
        statement = (
            select(MenuItem)
            .join(Menu)
            .join(Restaurant)
            .where(MenuItem.menu_item_id == menu_item_id, restaurant_scope(self._scope))
        )
        if lock:
            statement = statement.execution_options(populate_existing=True).with_for_update(
                of=MenuItem
            )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_menu_items_for_menu(self, menu_id: int) -> Sequence[MenuItem]:
        """Return all menu items belonging to a menu."""
        result = await self._session.execute(
            select(MenuItem)
            .join(Menu)
            .join(Restaurant)
            .where(MenuItem.menu_id == menu_id, restaurant_scope(self._scope))
        )
        return result.scalars().all()

    async def menu_item_has_order_history(self, menu_item_id: int) -> bool:
        """Return whether an item is referenced by a historical order item."""
        result = await self._session.scalar(
            select(OrderItem.order_item_id)
            .join(Order)
            .join(Restaurant)
            .where(
                OrderItem.menu_item_id == menu_item_id, restaurant_scope(self._scope)
            )
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
