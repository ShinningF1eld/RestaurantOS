"""Short, fenced PostgreSQL operations used by the event transport worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.events.domain.contracts import EventEnvelope, deserialize_event
from app.modules.events.domain.subscriptions import SUBSCRIPTIONS
from app.modules.events.repo.models import (
    EventDelivery,
    EventDeliveryAttempt,
    EventReceipt,
    OutboxEvent,
)


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    delivery_id: UUID
    event_id: UUID
    consumer_name: str
    event_type: str
    schema_version: int
    correlation_id: str
    claim_token: UUID
    claim_owner: str


@dataclass(frozen=True, slots=True)
class StoredDelivery:
    event: EventEnvelope
    status: str | None
    next_attempt_at: datetime | None
    is_due: bool
    receipt_outcome: str | None


@dataclass(frozen=True, slots=True)
class RetainedWork:
    events: int
    deliveries: int
    receipts: int
    attempts: int
    unfinished: int


_SUBSCRIBED_ROUTE_PAIRS = tuple(
    (event_type, consumer)
    for event_type, consumers in SUBSCRIPTIONS.items()
    for consumer in consumers
)


async def claim_due_deliveries(
    sessions: async_sessionmaker[AsyncSession],
    *,
    owner: str,
    limit: int,
    lease_seconds: int,
    republish_after_seconds: int,
) -> list[DeliveryClaim]:
    """Claim a bounded batch and commit its short transaction before returning."""
    route_filter = or_(
        *(
            and_(
                OutboxEvent.event_type == event_type,
                EventDelivery.consumer_name == consumer,
            )
            for event_type, consumer in _SUBSCRIBED_ROUTE_PAIRS
        )
    )
    async with sessions() as session, session.begin():
        statement = (
            select(EventDelivery, OutboxEvent)
            .join(OutboxEvent, OutboxEvent.event_id == EventDelivery.event_id)
            .where(
                EventDelivery.status == "pending",
                EventDelivery.next_attempt_at <= func.now(),
                or_(
                    EventDelivery.claim_token.is_(None),
                    EventDelivery.claim_expires_at <= func.now(),
                ),
                or_(
                    EventDelivery.published_at.is_(None),
                    EventDelivery.published_at
                    <= func.now() - timedelta(seconds=republish_after_seconds),
                ),
                route_filter,
            )
            .order_by(
                EventDelivery.next_attempt_at,
                EventDelivery.created_at,
                EventDelivery.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True, of=EventDelivery)
        )
        rows = (await session.execute(statement)).all()
        claims: list[DeliveryClaim] = []
        for delivery, event in rows:
            token = uuid4()
            delivery.claim_token = token
            delivery.claim_owner = owner
            delivery.claimed_at = func.now()  # type: ignore[assignment]
            delivery.claim_expires_at = func.now() + timedelta(seconds=lease_seconds)  # type: ignore[assignment]
            claims.append(
                DeliveryClaim(
                    delivery_id=delivery.id,
                    event_id=event.event_id,
                    consumer_name=delivery.consumer_name,
                    event_type=event.event_type,
                    schema_version=event.schema_version,
                    correlation_id=event.correlation_id,
                    claim_token=token,
                    claim_owner=owner,
                )
            )
        await session.flush()
    return claims


async def observe_publication(
    sessions: async_sessionmaker[AsyncSession], claim: DeliveryClaim
) -> bool:
    """Fence the observation so an expired/old claimant cannot overwrite state."""
    async with sessions() as session, session.begin():
        result = await session.execute(
            update(EventDelivery)
            .where(
                EventDelivery.id == claim.delivery_id,
                EventDelivery.status == "pending",
                EventDelivery.claim_token == claim.claim_token,
                EventDelivery.claim_owner == claim.claim_owner,
                EventDelivery.claim_expires_at > func.now(),
            )
            .values(
                published_at=func.now(),
                claim_token=None,
                claim_owner=None,
                claimed_at=None,
                claim_expires_at=None,
                last_error_category=None,
            )
            .returning(EventDelivery.id)
        )
    return result.scalar_one_or_none() is not None


async def defer_claim_after_transport_failure(
    sessions: async_sessionmaker[AsyncSession],
    claim: DeliveryClaim,
    *,
    retry_after_ms: int,
    failure_category: str,
) -> bool:
    """Keep ownership fenced while a short infrastructure probe delay elapses."""
    async with sessions() as session, session.begin():
        result = await session.execute(
            update(EventDelivery)
            .where(
                EventDelivery.id == claim.delivery_id,
                EventDelivery.status == "pending",
                EventDelivery.claim_token == claim.claim_token,
                EventDelivery.claim_owner == claim.claim_owner,
                EventDelivery.claim_expires_at > func.now(),
            )
            .values(
                claim_expires_at=func.now() + timedelta(milliseconds=retry_after_ms),
                last_error_category=failure_category,
            )
            .returning(EventDelivery.id)
        )
    return result.scalar_one_or_none() is not None


async def database_time(
    sessions: async_sessionmaker[AsyncSession],
) -> datetime:
    """Read PostgreSQL's UTC transaction clock for recovery cutoffs."""
    async with sessions() as session:
        return await session.scalar(select(func.now()))  # type: ignore[return-value]


async def reset_observations_before(
    sessions: async_sessionmaker[AsyncSession],
    *,
    cutoff: datetime,
    limit: int,
) -> int:
    """Clear old publication observations in a bounded batch after stream loss."""
    async with sessions() as session, session.begin():
        statement = (
            select(EventDelivery)
            .where(
                EventDelivery.status == "pending",
                EventDelivery.next_attempt_at <= func.now(),
                EventDelivery.published_at <= cutoff,
                or_(
                    EventDelivery.claim_token.is_(None),
                    EventDelivery.claim_expires_at <= func.now(),
                ),
            )
            .order_by(EventDelivery.published_at, EventDelivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await session.scalars(statement)).all()
        for delivery in rows:
            delivery.published_at = None
            delivery.claim_token = None
            delivery.claim_owner = None
            delivery.claimed_at = None
            delivery.claim_expires_at = None
            delivery.last_error_category = "redis_stream_recovered"
        await session.flush()
        return len(rows)


async def load_stored_delivery(
    sessions: async_sessionmaker[AsyncSession],
    *,
    event_id: UUID,
    consumer_name: str,
) -> StoredDelivery | None:
    """Load and validate the immutable PostgreSQL envelope and consumer state."""
    async with sessions() as session:
        result = await session.execute(
            select(
                OutboxEvent,
                EventDelivery,
                EventReceipt.outcome,
                EventDelivery.next_attempt_at <= func.now(),
            )
            .outerjoin(
                EventDelivery,
                and_(
                    EventDelivery.event_id == OutboxEvent.event_id,
                    EventDelivery.consumer_name == consumer_name,
                ),
            )
            .outerjoin(
                EventReceipt,
                and_(
                    EventReceipt.event_id == OutboxEvent.event_id,
                    EventReceipt.consumer_name == consumer_name,
                ),
            )
            .where(OutboxEvent.event_id == event_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        event, delivery, receipt_outcome, is_due = row
        envelope = deserialize_event(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "schema_version": event.schema_version,
                "organization_id": event.organization_id,
                "restaurant_id": event.restaurant_id,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "aggregate_revision": event.aggregate_revision,
                "occurred_at": event.occurred_at,
                "correlation_id": event.correlation_id,
                "payload": event.payload,
            }
        )
        return StoredDelivery(
            event=envelope,
            status=delivery.status if delivery is not None else None,
            next_attempt_at=(
                delivery.next_attempt_at if delivery is not None else None
            ),
            is_due=bool(is_due) if delivery is not None else False,
            receipt_outcome=receipt_outcome,
        )


async def retained_work_counts(
    sessions: async_sessionmaker[AsyncSession],
) -> RetainedWork:
    """Return retained facts and unfinished delivery depth for safe operations."""
    async with sessions() as session:
        counts = (
            await session.execute(
                select(
                    select(func.count()).select_from(OutboxEvent).scalar_subquery(),
                    select(func.count()).select_from(EventDelivery).scalar_subquery(),
                    select(func.count()).select_from(EventReceipt).scalar_subquery(),
                    select(func.count())
                    .select_from(EventDeliveryAttempt)
                    .scalar_subquery(),
                    select(func.count())
                    .select_from(EventDelivery)
                    .where(EventDelivery.status.in_(("pending", "processing")))
                    .scalar_subquery(),
                )
            )
        ).one()
        events, deliveries, receipts, attempts, unfinished = counts
    return RetainedWork(
        events=events,
        deliveries=deliveries,
        receipts=receipts,
        attempts=attempts,
        unfinished=unfinished,
    )
