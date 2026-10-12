"""Public transactional event append interface for business producers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_id import get_request_id, new_request_id

from app.modules.events.domain.contracts import (
    EventEnvelope,
    EventType,
    deserialize_event,
    serialize_event,
)
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


@dataclass(frozen=True, slots=True)
class CommandEvents:
    """One command's correlation, including trusted calls outside HTTP requests."""

    correlation_id: str = field(
        default_factory=lambda: get_request_id() or new_request_id()
    )
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    async def append(
        self,
        session: AsyncSession,
        *,
        event_type: EventType,
        organization_id: UUID,
        restaurant_id: int,
        aggregate_type: str,
        aggregate_id: int,
        aggregate_revision: int,
        payload: dict[str, object],
    ) -> OutboxEvent:
        envelope = deserialize_event(
            {
                "event_id": new_request_id(),
                "event_type": event_type,
                "schema_version": 1,
                "organization_id": organization_id,
                "restaurant_id": restaurant_id,
                "aggregate_type": aggregate_type,
                "aggregate_id": str(aggregate_id),
                "aggregate_revision": aggregate_revision,
                "occurred_at": self.occurred_at,
                "correlation_id": self.correlation_id,
                "payload": payload,
            }
        )
        return await append_event(session, envelope)


async def next_catalog_revision(
    session: AsyncSession,
    organization_id: UUID,
    restaurant_id: int,
    aggregate_type: Literal["menu", "menu_item"],
    aggregate_id: int,
) -> int:
    """Allocate from retained facts while the caller holds the restaurant lock.

    Catalog revisions cover emitted changes only. The shared restaurant write
    lock serializes allocation and append, including deletion tombstones.
    """
    if not session.in_transaction():
        raise EventTransactionRequired("catalog revision requires a caller transaction")
    return await EventRepository(session).next_catalog_revision(
        organization_id, restaurant_id, aggregate_type, str(aggregate_id)
    )
