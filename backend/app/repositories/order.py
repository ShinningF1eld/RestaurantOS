"""Focused persistence operations for orders and their catalog lookups."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.menu import Menu
from app.db.models.menu_items import MenuItem
from app.db.models.order import Order, OrderItem
from app.db.models.restaurant import Restaurant


class OrderRepository:
    """Access order data through one caller-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def restaurant_exists(self, restaurant_id: int) -> bool:
        """Return whether a restaurant exists."""
        result = await self._session.scalar(
            select(Restaurant.id).where(Restaurant.id == restaurant_id)
        )
        return result is not None

    async def get_by_id(self, order_id: int) -> Order | None:
        """Load one order with all API-visible item relationships."""
        result = await self._session.execute(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.menu_item))
            .where(Order.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def list_for_restaurant(
        self, restaurant_id: int, limit: int, offset: int
    ) -> Sequence[Order]:
        """Load a restaurant's page of orders with their items."""
        result = await self._session.execute(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.menu_item))
            .where(Order.restaurant_id == restaurant_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_for_restaurant(self, restaurant_id: int) -> int:
        """Count all orders belonging to a restaurant."""
        total = await self._session.scalar(
            select(func.count(Order.order_id)).where(Order.restaurant_id == restaurant_id)
        )
        return int(total or 0)

    async def menu_items_for_restaurant(
        self, restaurant_id: int, menu_item_ids: Sequence[int]
    ) -> Sequence[MenuItem]:
        """Load requested catalog items only when they belong to the restaurant."""
        result = await self._session.execute(
            select(MenuItem)
            .join(Menu)
            .where(
                Menu.restaurant_id == restaurant_id,
                MenuItem.menu_item_id.in_(menu_item_ids),
            )
        )
        return result.scalars().all()

    async def add(self, order: Order) -> None:
        """Stage an order for insertion without committing it."""
        self._session.add(order)

    async def delete(self, order: Order) -> None:
        """Stage an order for deletion without committing it."""
        await self._session.delete(order)

    async def flush(self) -> None:
        """Flush staged changes while keeping transaction ownership with the caller."""
        await self._session.flush()
