"""Focused persistence operations for restaurants."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.restaurant import Restaurant


class RestaurantRepository:
    """Access restaurants through one caller-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, restaurant: Restaurant) -> None:
        """Stage a restaurant for insertion without committing it."""
        self._session.add(restaurant)

    async def get_by_id(self, restaurant_id: int) -> Restaurant | None:
        """Return a restaurant by primary key when it exists."""
        result = await self._session.execute(
            select(Restaurant).where(Restaurant.id == restaurant_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Restaurant]:
        """Return all restaurants in the database's natural order."""
        result = await self._session.execute(select(Restaurant))
        return result.scalars().all()

    async def delete(self, restaurant: Restaurant) -> None:
        """Stage a restaurant for deletion without committing it."""
        await self._session.delete(restaurant)

    async def flush(self) -> None:
        """Flush staged changes so generated fields are available."""
        await self._session.flush()

    async def refresh(self, restaurant: Restaurant) -> None:
        """Refresh a restaurant using the current transaction."""
        await self._session.refresh(restaurant)
