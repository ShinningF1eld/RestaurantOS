"""Focused persistence operations for restaurants."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.tenancy.access import restaurant_scope
from app.modules.tenancy.domain.policies import AccessContext

from app.modules.restaurants.repo.models import Restaurant
from app.modules.catalog.repo.models import Menu
from app.modules.orders.repo.models import Order
from app.modules.tenancy.repo.models import RestaurantAssignment
from app.modules.audit.repo.models import AuditEntry
from app.modules.inventory.repo.models import Ingredient


class RestaurantRepository:
    """Access restaurants through one caller-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession, scope: AccessContext) -> None:
        self._session = session
        self._scope = scope

    async def add(self, restaurant: Restaurant) -> None:
        """Stage a restaurant for insertion without committing it."""
        self._session.add(restaurant)

    async def get_by_id(self, restaurant_id: int) -> Restaurant | None:
        """Return a restaurant by primary key when it exists."""
        result = await self._session.execute(
            select(Restaurant).where(
                Restaurant.id == restaurant_id, restaurant_scope(self._scope)
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Restaurant]:
        """Return all restaurants in the database's natural order."""
        result = await self._session.execute(
            select(Restaurant)
            .where(restaurant_scope(self._scope))
            .order_by(Restaurant.id)
        )
        return result.scalars().all()

    async def delete(self, restaurant: Restaurant) -> None:
        """Stage a restaurant for deletion without committing it."""
        await self._session.delete(restaurant)

    async def has_dependents(self, restaurant_id: int) -> bool:
        for column in (
            Ingredient.restaurant_id,
            Menu.restaurant_id,
            Order.restaurant_id,
            RestaurantAssignment.restaurant_id,
            AuditEntry.restaurant_id,
        ):
            if (
                await self._session.scalar(
                    select(column)
                    .join(Restaurant, column == Restaurant.id)
                    .where(column == restaurant_id, restaurant_scope(self._scope))
                    .limit(1)
                )
                is not None
            ):
                return True
        return False

    async def flush(self) -> None:
        """Flush staged changes so generated fields are available."""
        await self._session.flush()

    async def refresh(self, restaurant: Restaurant) -> None:
        """Refresh a restaurant using the current transaction."""
        await self._session.refresh(restaurant)
