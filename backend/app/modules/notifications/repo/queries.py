"""Queries for durable notification outcomes and operator diagnostics."""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.notifications.repo.models import EventDiagnostic, NotificationStub


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def stub(self, episode_id: UUID) -> NotificationStub | None:
        return await self.session.scalar(
            select(NotificationStub).where(NotificationStub.episode_id == episode_id)
        )

    async def stubs(
        self, organization_id: UUID, restaurant_id: int
    ) -> list[NotificationStub]:
        return list(
            await self.session.scalars(
                select(NotificationStub)
                .where(
                    NotificationStub.organization_id == organization_id,
                    NotificationStub.restaurant_id == restaurant_id,
                )
                .order_by(NotificationStub.created_at, NotificationStub.id)
            )
        )

    async def diagnostics(
        self, organization_id: UUID, restaurant_id: int
    ) -> list[EventDiagnostic]:
        return list(
            await self.session.scalars(
                select(EventDiagnostic)
                .where(
                    EventDiagnostic.organization_id == organization_id,
                    EventDiagnostic.restaurant_id == restaurant_id,
                )
                .order_by(EventDiagnostic.created_at, EventDiagnostic.event_id)
            )
        )
