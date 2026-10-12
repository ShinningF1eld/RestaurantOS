"""Transactional PostgreSQL operations owned by the event worker runtime."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.events.repo.worker_queries import (
    DeliveryClaim,
    RetainedWork,
    StoredDelivery,
    claim_due_deliveries as claim_delivery_rows,
    database_time as read_database_time,
    defer_claim_after_transport_failure as defer_delivery_claim,
    load_stored_delivery as read_stored_delivery,
    observe_publication as record_publication,
    reset_observations_before as reset_delivery_observations,
    retained_work_counts as read_retained_work_counts,
)


class EventWorkerService:
    """Own worker sessions and short write transactions around repository work."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim_due_deliveries(
        self,
        *,
        owner: str,
        limit: int,
        lease_seconds: int,
        republish_after_seconds: int,
    ) -> list[DeliveryClaim]:
        async with self._sessions() as session, session.begin():
            return await claim_delivery_rows(
                session,
                owner=owner,
                limit=limit,
                lease_seconds=lease_seconds,
                republish_after_seconds=republish_after_seconds,
            )

    async def observe_publication(self, claim: DeliveryClaim) -> bool:
        async with self._sessions() as session, session.begin():
            return await record_publication(session, claim)

    async def defer_claim_after_transport_failure(
        self,
        claim: DeliveryClaim,
        *,
        retry_after_ms: int,
        failure_category: str,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            return await defer_delivery_claim(
                session,
                claim,
                retry_after_ms=retry_after_ms,
                failure_category=failure_category,
            )

    async def database_time(self) -> datetime:
        async with self._sessions() as session:
            return await read_database_time(session)

    async def reset_observations_before(self, *, cutoff: datetime, limit: int) -> int:
        async with self._sessions() as session, session.begin():
            return await reset_delivery_observations(
                session, cutoff=cutoff, limit=limit
            )

    async def load_stored_delivery(
        self, *, event_id: UUID, consumer_name: str
    ) -> StoredDelivery | None:
        async with self._sessions() as session:
            return await read_stored_delivery(
                session, event_id=event_id, consumer_name=consumer_name
            )

    async def retained_work_counts(self) -> RetainedWork:
        async with self._sessions() as session:
            return await read_retained_work_counts(session)
