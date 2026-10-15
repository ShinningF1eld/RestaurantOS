"""Transaction-bound low-stock stubs and durable diagnostic effects."""

from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.repo.models import EventDiagnostic, NotificationStub
from app.modules.notifications.repo.queries import NotificationRepository
from app.modules.events.domain.contracts import (
    EventEnvelope,
    InventoryLowEvent,
    MenuUpdatedEvent,
    OrderAcceptedEvent,
    OrderCancelledEvent,
    OrderCompletedEvent,
    OrderDeletedEvent,
    OrderSubmittedEvent,
)
from app.modules.inventory.service import (
    load_inventory_episode_facts,
    load_inventory_state,
)


async def apply_notification_event(
    session: AsyncSession, event: EventEnvelope
) -> Literal["processed", "skipped"]:
    """Create one durable low-stock stub or a durable skip outcome per episode."""
    if not session.in_transaction():
        raise RuntimeError("Notification effects require a caller transaction")
    if isinstance(event, InventoryLowEvent):
        payload = event.payload
        current = await load_inventory_state(
            session,
            event.organization_id,
            event.restaurant_id,
            payload.ingredient_id,
            lock=True,
        )
        existing = await NotificationRepository(session).stub(payload.episode_id)
        if existing is not None:
            return "skipped"
        producer_facts = await load_inventory_episode_facts(session, payload.episode_id)
        outcome = "created"
        reason = None
        if producer_facts is not None and producer_facts.notification_suppressed:
            outcome, reason = "suppressed", "initialization_baseline"
        elif not current.is_low or current.episode_id != payload.episode_id:
            outcome, reason = "skipped", "resolved_or_superseded"
        session.add(
            NotificationStub(
                episode_id=payload.episode_id,
                event_id=event.event_id,
                organization_id=event.organization_id,
                restaurant_id=event.restaurant_id,
                ingredient_id=payload.ingredient_id,
                ingredient_name=payload.ingredient_name,
                unit=payload.unit,
                opening_quantity=payload.opening_quantity,
                reorder_threshold=payload.reorder_threshold,
                opened_at=payload.opened_at,
                outcome=outcome,
                reason=reason,
                correlation_id=event.correlation_id,
            )
        )
        await session.flush()
        return "processed" if outcome == "created" else "skipped"

    elif isinstance(event, OrderSubmittedEvent):
        diagnostic_facts: dict[str, object] = {
            "order_id": event.payload.order_id,
            "status": event.payload.status,
        }
    elif isinstance(event, OrderAcceptedEvent):
        diagnostic_facts = {
            "order_id": event.payload.order_id,
            "status": event.payload.status,
        }
    elif isinstance(event, OrderCancelledEvent):
        diagnostic_facts = {
            "order_id": event.payload.order_id,
            "status": event.payload.status,
        }
    elif isinstance(event, OrderCompletedEvent):
        diagnostic_facts = {
            "order_id": event.payload.order_id,
            "total": str(event.payload.total),
            "created_at": event.payload.created_at.isoformat(),
        }
    elif isinstance(event, OrderDeletedEvent):
        diagnostic_facts = {
            "order_id": event.payload.order_id,
            "total": str(event.payload.total),
            "created_at": event.payload.created_at.isoformat(),
            "prior_status": event.payload.prior_status,
        }
    elif isinstance(event, MenuUpdatedEvent):
        diagnostic_facts = {
            "operation": event.payload.operation,
            "target_type": event.payload.target_type,
            "target_id": event.payload.target_id,
            "menu_id": event.payload.menu_id,
            "affected_menu_item_ids": list(event.payload.affected_menu_item_ids),
        }
    else:
        raise ValueError("Unsupported notification sink event")
    if isinstance(
        event,
        (
            OrderSubmittedEvent,
            OrderAcceptedEvent,
            OrderCompletedEvent,
            OrderCancelledEvent,
            OrderDeletedEvent,
            MenuUpdatedEvent,
        ),
    ):
        session.add(
            EventDiagnostic(
                event_id=event.event_id,
                organization_id=event.organization_id,
                restaurant_id=event.restaurant_id,
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                aggregate_revision=event.aggregate_revision,
                correlation_id=event.correlation_id,
                facts=diagnostic_facts,
            )
        )
        await session.flush()
        return "processed"


async def inspect_notification_sink(
    session: AsyncSession, organization_id: UUID, restaurant_id: int
) -> dict[str, object]:
    """Trusted scoped read hook for maintenance/operator callers."""
    repo = NotificationRepository(session)
    return {
        "notification_stubs": await repo.stubs(organization_id, restaurant_id),
        "diagnostics": await repo.diagnostics(organization_id, restaurant_id),
    }
