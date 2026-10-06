"""Focused persistence operations for orders and their catalog lookups."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.catalog.repo.models import Menu
from app.modules.catalog.repo.models import MenuItem
from app.modules.inventory.repo.models import Ingredient, InventoryBalance
from app.modules.orders.repo.models import Order
from app.modules.orders.repo.models import OrderSubmission
from app.modules.restaurants.repo.models import Restaurant
from app.modules.tenancy.access import restaurant_scope
from app.modules.tenancy.domain.policies import AccessContext


class OrderRepository:
    """Access order data through one caller-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession, scope: AccessContext) -> None:
        self._session = session
        self._scope = scope

    async def restaurant_exists(self, restaurant_id: int) -> bool:
        """Return whether a restaurant exists."""
        result = await self._session.scalar(
            select(Restaurant.id).where(
                Restaurant.id == restaurant_id, restaurant_scope(self._scope)
            )
        )
        return result is not None

    async def get_by_id(self, order_id: int, *, lock: bool = False) -> Order | None:
        """Load one order with all API-visible item relationships."""
        statement = (
            select(Order)
            .join(Restaurant)
            .options(selectinload(Order.items))
            .where(Order.order_id == order_id, restaurant_scope(self._scope))
        )
        if lock:
            statement = statement.with_for_update(of=Order).execution_options(
                populate_existing=True
            )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_restaurant(
        self, restaurant_id: int, limit: int, offset: int
    ) -> Sequence[Order]:
        """Load a restaurant's page of orders with their items."""
        result = await self._session.execute(
            select(Order)
            .join(Restaurant)
            .options(selectinload(Order.items))
            .where(Order.restaurant_id == restaurant_id, restaurant_scope(self._scope))
            .order_by(Order.created_at.desc(), Order.order_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_for_restaurant(self, restaurant_id: int) -> int:
        """Count all orders belonging to a restaurant."""
        total = await self._session.scalar(
            select(func.count(Order.order_id))
            .join(Restaurant)
            .where(Order.restaurant_id == restaurant_id, restaurant_scope(self._scope))
        )
        return int(total or 0)

    async def menu_items_for_restaurant(
        self, restaurant_id: int, menu_item_ids: Sequence[int]
    ) -> Sequence[MenuItem]:
        """Load requested catalog items only when they belong to the restaurant."""
        result = await self._session.execute(
            select(MenuItem)
            .join(Menu)
            .join(Restaurant)
            .where(
                Menu.restaurant_id == restaurant_id,
                MenuItem.menu_item_id.in_(menu_item_ids),
                restaurant_scope(self._scope),
            )
        )
        return result.scalars().all()

    async def submission(self, restaurant_id: int, key: str) -> OrderSubmission | None:
        result = await self._session.execute(
            select(OrderSubmission)
            .join(Restaurant, OrderSubmission.restaurant_id == Restaurant.id)
            .where(
                OrderSubmission.restaurant_id == restaurant_id,
                OrderSubmission.idempotency_key == key,
                restaurant_scope(self._scope),
            )
        )
        return result.scalar_one_or_none()

    async def add_submission(self, submission: OrderSubmission) -> None:
        self._session.add(submission)

    async def lock_inventory_balances(
        self, restaurant_id: int, ingredient_ids: Sequence[int]
    ) -> list[tuple[Ingredient, InventoryBalance]]:
        if not ingredient_ids:
            return []
        # Lock in a stable ingredient order after the shared restaurant lock.
        result = await self._session.execute(
            select(Ingredient, InventoryBalance)
            .join(InventoryBalance, InventoryBalance.ingredient_id == Ingredient.id)
            .join(Restaurant, Restaurant.id == Ingredient.restaurant_id)
            .where(
                Ingredient.restaurant_id == restaurant_id,
                Ingredient.id.in_(ingredient_ids),
                restaurant_scope(self._scope),
            )
            .order_by(Ingredient.id)
            .with_for_update(of=(Ingredient, InventoryBalance))
            .execution_options(populate_existing=True)
        )
        return [(ingredient, balance) for ingredient, balance in result]

    async def inventory_balances(
        self, restaurant_id: int, ingredient_ids: Sequence[int]
    ) -> list[tuple[Ingredient, InventoryBalance]]:
        if not ingredient_ids:
            return []
        result = await self._session.execute(
            select(Ingredient, InventoryBalance)
            .join(InventoryBalance, InventoryBalance.ingredient_id == Ingredient.id)
            .join(Restaurant, Restaurant.id == Ingredient.restaurant_id)
            .where(
                Ingredient.restaurant_id == restaurant_id,
                Ingredient.id.in_(ingredient_ids),
                restaurant_scope(self._scope),
            )
            .order_by(Ingredient.id)
        )
        return [(ingredient, balance) for ingredient, balance in result]

    async def has_order_history(self, order_id: int) -> bool:
        from app.modules.inventory.repo.models import InventoryMovement

        return (
            await self._session.scalar(
                select(InventoryMovement.id)
                .where(InventoryMovement.order_id == order_id)
                .limit(1)
            )
            is not None
        )

    async def add(self, order: Order) -> None:
        """Stage an order for insertion without committing it."""
        self._session.add(order)

    async def delete(self, order: Order) -> None:
        """Stage an order for deletion without committing it."""
        await self._session.delete(order)

    async def flush(self) -> None:
        """Flush staged changes while keeping transaction ownership with the caller."""
        await self._session.flush()
