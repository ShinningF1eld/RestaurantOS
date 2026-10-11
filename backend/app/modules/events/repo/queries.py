"""Focused outbox persistence operations using the caller-owned session."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.repo.models import EventDelivery, OutboxEvent
from app.modules.restaurants.repo.models import Restaurant


class EventRepository:
    """Stage event facts and required deliveries without transaction ownership."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def restaurant_matches_organization(
        self, restaurant_id: int, organization_id: UUID
    ) -> bool:
        result = await self._session.scalar(
            select(Restaurant.id).where(
                Restaurant.id == restaurant_id,
                Restaurant.organization_id == organization_id,
            )
        )
        return result is not None

    def add_event(self, event: OutboxEvent) -> None:
        self._session.add(event)

    def add_deliveries(self, deliveries: list[EventDelivery]) -> None:
        self._session.add_all(deliveries)

    async def flush(self) -> None:
        """Flush fan-out with the caller's transaction; never commits or rolls back."""
        await self._session.flush()
