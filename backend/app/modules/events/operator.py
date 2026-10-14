"""Trusted local operator use cases. Database credentials authorize access."""

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.events.domain.diagnostics import safe_category, safe_identifier
from app.modules.events.repo import delivery_queries as queries
from app.modules.events.repo.models import (
    EventDelivery,
    EventDeliveryReplay,
    OutboxEvent,
)


logger = logging.getLogger("restaurantos.event_operator")


class EventOperatorService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def status(self) -> dict[str, object]:
        async with self.sessions() as session, session.begin():
            return {
                "consumers": await queries.status_rows(session),
                "retained_events": await session.scalar(
                    select(func.count()).select_from(OutboxEvent)
                ),
                "retained_replays": await session.scalar(
                    select(func.count()).select_from(EventDeliveryReplay)
                ),
            }

    async def inspect(self, delivery_id: UUID) -> dict[str, object]:
        async with self.sessions() as session, session.begin():
            delivery = await session.get(EventDelivery, delivery_id)
            if delivery is None:
                raise ValueError("Delivery not found")
            event = await session.get(OutboxEvent, delivery.event_id)
            if event is None:
                raise ValueError("Event not found")
            attempts, replays = await queries.history(session, delivery_id)
            receipt = await queries.receipt(
                session, delivery.event_id, delivery.consumer_name
            )
            return {
                "delivery_id": str(delivery.id),
                "event_id": str(event.event_id),
                "consumer": delivery.consumer_name,
                "status": delivery.status,
                "event_type": safe_identifier(event.event_type),
                "schema_version": event.schema_version,
                "organization_id": str(event.organization_id),
                "restaurant_id": event.restaurant_id,
                "aggregate_type": safe_identifier(event.aggregate_type),
                "aggregate_id": safe_identifier(event.aggregate_id),
                "aggregate_revision": event.aggregate_revision,
                "correlation_id": safe_identifier(event.correlation_id),
                "attempt_count": delivery.attempt_count,
                "retry_cycle": delivery.retry_cycle,
                "next_attempt_at": delivery.next_attempt_at.isoformat(),
                "last_error_category": safe_category(delivery.last_error_category),
                "receipt_outcome": receipt.outcome if receipt else None,
                "attempts": [
                    {
                        "attempt_id": str(a.id),
                        "retry_cycle": a.retry_cycle,
                        "attempt_number": a.attempt_number,
                        "status": a.status,
                        "started_at": a.started_at.isoformat(),
                        "finished_at": a.finished_at.isoformat()
                        if a.finished_at
                        else None,
                        "error_category": safe_category(a.error_category),
                    }
                    for a in attempts
                ],
                "replays": [
                    {
                        "replay_id": str(r.replay_id),
                        "from_cycle": r.from_cycle,
                        "to_cycle": r.to_cycle,
                        "operator": safe_identifier(r.operator),
                        "reason_recorded": bool(r.reason),
                        "requested_at": r.requested_at.isoformat(),
                    }
                    for r in replays
                ],
            }

    async def replay(self, delivery_id: UUID, *, reason: str) -> UUID:
        if not reason.strip() or len(reason) > 1000 or any(ord(c) < 32 for c in reason):
            raise ValueError(
                "Replay reason must be 1–1000 characters without control characters"
            )
        async with self.sessions() as session, session.begin():
            delivery = await session.scalar(
                select(EventDelivery)
                .where(EventDelivery.id == delivery_id)
                .with_for_update()
            )
            if delivery is None:
                raise ValueError("Delivery not found")
            if delivery.status != "failed" or await queries.receipt(
                session, delivery.event_id, delivery.consumer_name
            ):
                raise ValueError(
                    "Replay requires exactly one failed delivery without a receipt"
                )
            event = await session.get(OutboxEvent, delivery.event_id)
            if event is None:
                raise ValueError("Event not found")
            replay = EventDeliveryReplay(
                delivery_id=delivery.id,
                from_cycle=delivery.retry_cycle,
                to_cycle=delivery.retry_cycle + 1,
                operator=await queries.operator_identity(session),
                reason=reason.strip(),
                correlation_id=event.correlation_id,
            )
            session.add(replay)
            delivery.retry_cycle += 1
            delivery.attempt_count = 0
            delivery.status = "pending"
            delivery.next_attempt_at = await queries.clock(session)
            delivery.published_at = None
            delivery.claim_token = None
            delivery.claim_owner = None
            delivery.claim_expires_at = None
            delivery.claimed_at = None
            delivery.last_error_category = None
            await session.flush()
            replay_id = replay.replay_id
            context = {
                "event_id": str(event.event_id),
                "consumer_name": delivery.consumer_name,
                "correlation_id": safe_identifier(event.correlation_id),
                "replay_id": str(replay_id),
                "retry_cycle": delivery.retry_cycle,
            }
        logger.info(
            "event_delivery_replayed", extra={"event": "delivery_replayed", **context}
        )
        return replay_id
