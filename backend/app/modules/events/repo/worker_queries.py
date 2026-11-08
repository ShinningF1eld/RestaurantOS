"""Short, fenced PostgreSQL operations used by the event transport worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    traceparent: str | None = None


@dataclass(frozen=True, slots=True)
class StoredDelivery:
    event: EventEnvelope
    status: str | None
    next_attempt_at: datetime | None
    is_due: bool
    receipt_outcome: str | None
    traceparent: str | None = None


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


def _require_write_transaction(session: AsyncSession) -> None:
    if not session.in_transaction():
        raise RuntimeError(
            "event worker repository writes require a caller transaction"
        )


async def claim_due_deliveries(
    session: AsyncSession,
    *,
    owner: str,
    limit: int,
    lease_seconds: int,
    republish_after_seconds: int,
) -> list[DeliveryClaim]:
    """Stage a bounded claim in the caller-owned short transaction."""
    _require_write_transaction(session)
    route_filter = or_(
        *(
            and_(
                OutboxEvent.event_type == event_type,
                EventDelivery.consumer_name == consumer,
            )
            for event_type, consumer in _SUBSCRIBED_ROUTE_PAIRS
        )
    )
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
                traceparent=event.traceparent,
            )
        )
    await session.flush()
    return claims


async def observe_publication(session: AsyncSession, claim: DeliveryClaim) -> bool:
    """Stage an ownership-fenced observation in the caller transaction."""
    _require_write_transaction(session)
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
    session: AsyncSession,
    claim: DeliveryClaim,
    *,
    retry_after_ms: int,
    failure_category: str,
) -> bool:
    """Stage a short infrastructure delay without counting a consumer attempt."""
    _require_write_transaction(session)
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
    session: AsyncSession,
) -> datetime:
    """Read PostgreSQL's UTC transaction clock for recovery cutoffs."""
    return await session.scalar(select(func.now()))  # type: ignore[return-value]


async def reset_observations_before(
    session: AsyncSession,
    *,
    cutoff: datetime,
    limit: int,
) -> int:
    """Stage a bounded publication reset after stream loss in caller transaction."""
    _require_write_transaction(session)
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
    session: AsyncSession,
    *,
    event_id: UUID,
    consumer_name: str,
) -> StoredDelivery | None:
    """Load and validate the immutable PostgreSQL envelope and consumer state."""
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
        next_attempt_at=(delivery.next_attempt_at if delivery is not None else None),
        is_due=bool(is_due) if delivery is not None else False,
        receipt_outcome=receipt_outcome,
        traceparent=event.traceparent,
    )


async def retained_work_counts(
    session: AsyncSession,
) -> RetainedWork:
    """Return retained facts and unfinished delivery depth for safe operations."""
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


@dataclass(frozen=True, slots=True)
class BacklogSample:
    consumer: str
    state: str
    depth: int
    oldest_seconds: float


async def backlog_samples(
    session: AsyncSession, *, consumer: str | None = None
) -> list[BacklogSample]:
    """Only unfinished/terminal rows, using due/lease indexes; bounded statement time.

    Completed history is excluded. Expired processing claims require recovery,
    whereas an active relay claim is already in flight even while still pending.
    """
    from sqlalchemy import case, text

    await session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
    state = case(
        (EventDelivery.status == "failed", "terminal"),
        (EventDelivery.claim_expires_at > func.now(), "in_flight"),
        (EventDelivery.status == "processing", "recovery_due"),
        (EventDelivery.next_attempt_at > func.now(), "retry_delayed"),
        else_="queued",
    )
    query = (
        select(
            EventDelivery.consumer_name,
            state,
            func.count(),
            func.greatest(
                0,
                func.extract("epoch", func.now() - func.min(EventDelivery.created_at)),
            ),
        )
        .where(EventDelivery.status.in_(("pending", "processing", "failed")))
        .group_by(EventDelivery.consumer_name, state)
    )
    if consumer is not None:
        query = query.where(EventDelivery.consumer_name == consumer)
    rows = (await session.execute(query)).all()
    return [
        BacklogSample(consumer, state, depth, float(age))
        for consumer, state, depth, age in rows
    ]


async def progress_samples(session: AsyncSession) -> list[tuple[str, int, float]]:
    """Indexed receipt window, not a scan of complete business history."""
    from sqlalchemy import text

    await session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
    rows = (
        await session.execute(
            select(
                EventReceipt.consumer_name,
                func.count(),
                func.extract("epoch", func.max(EventReceipt.processed_at)),
            )
            .where(EventReceipt.processed_at >= func.now() - timedelta(minutes=5))
            .group_by(EventReceipt.consumer_name)
        )
    ).all()
    return [(consumer, count, float(latest)) for consumer, count, latest in rows]
