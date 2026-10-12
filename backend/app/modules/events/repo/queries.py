"""Focused outbox persistence operations using the caller-owned session."""

from uuid import UUID

from sqlalchemy import func, select
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

    async def next_catalog_revision(
        self,
        organization_id: UUID,
        restaurant_id: int,
        aggregate_type: str,
        aggregate_id: str,
    ) -> int:
        revision = await self._session.scalar(
            select(func.max(OutboxEvent.aggregate_revision)).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.restaurant_id == restaurant_id,
                OutboxEvent.aggregate_type == aggregate_type,
                OutboxEvent.aggregate_id == aggregate_id,
            )
        )
        return (revision or 0) + 1
