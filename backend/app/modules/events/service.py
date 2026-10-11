"""Public transactional event append interface for business producers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.domain.contracts import EventEnvelope, serialize_event
from app.modules.events.domain.subscriptions import consumers_for
from app.modules.events.repo.models import EventDelivery, OutboxEvent
from app.modules.events.repo.queries import EventRepository


class EventTransactionRequired(RuntimeError):
    """Raised when an event append is attempted without a caller transaction."""


class EventScopeMismatch(ValueError):
    """Raised when the envelope restaurant is outside its declared organization."""


async def append_event(session: AsyncSession, envelope: EventEnvelope) -> OutboxEvent:
    """Append one immutable event and its fixed consumer fan-out atomically.

    The caller owns the PostgreSQL transaction. This function only verifies the
    restaurant/organization pair, stages rows, and flushes them; it never begins,
    commits, or rolls back a transaction.
    """
    if not session.in_transaction():
        raise EventTransactionRequired(
            "append_event requires an active caller-owned transaction"
        )

    repository = EventRepository(session)
    if not await repository.restaurant_matches_organization(
        envelope.restaurant_id, envelope.organization_id
    ):
        raise EventScopeMismatch("event restaurant is not in its declared organization")

    serialized = serialize_event(envelope)
    event = OutboxEvent(
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        schema_version=envelope.schema_version,
        organization_id=envelope.organization_id,
        restaurant_id=envelope.restaurant_id,
        aggregate_type=envelope.aggregate_type,
        aggregate_id=envelope.aggregate_id,
        aggregate_revision=envelope.aggregate_revision,
        occurred_at=envelope.occurred_at,
        correlation_id=envelope.correlation_id,
        payload=serialized["payload"],
    )
    deliveries = [
        EventDelivery(event_id=envelope.event_id, consumer_name=consumer)
        for consumer in consumers_for(envelope.event_type)
    ]
    repository.add_event(event)
    await repository.flush()
    repository.add_deliveries(deliveries)
    await repository.flush()
    return event
