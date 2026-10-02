"""Tenant-scoped, read-only audit inspection."""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.audit.repo.models import AuditEntry


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_entries(
        self, organization_id: UUID, limit: int, offset: int
    ) -> list[AuditEntry]:
        return list(
            (
                await self._session.scalars(
                    select(AuditEntry)
                    .where(AuditEntry.organization_id == organization_id)
                    .order_by(AuditEntry.occurred_at.desc(), AuditEntry.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
