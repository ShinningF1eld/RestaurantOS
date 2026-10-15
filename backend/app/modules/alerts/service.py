"""Transaction-bound alert episode history and current inventory projection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.repo.models import (
    AlertEpisode,
    AlertIngredientState,
)
from app.modules.alerts.repo.queries import AlertProjectionRepository
from app.modules.events.domain.contracts import (
    EventEnvelope,
    InventoryLowEvent,
    InventoryStateChangedEvent,
)
from app.modules.inventory.service import (
    load_inventory_episode_facts,
    load_inventory_episode_history,
    load_inventory_restaurant_states,
    load_inventory_state,
)
from app.modules.inventory.domain.transitions import InventoryEpisodeFacts


def _require_transaction(session: AsyncSession) -> None:
    if not session.in_transaction():
        raise RuntimeError("Alert effects require a caller transaction")


async def _store_episode_facts(
    session: AsyncSession, facts: InventoryEpisodeFacts
) -> None:
    episode_id = facts.episode_id
    repo = AlertProjectionRepository(session)
    row = await repo.episode(episode_id, lock=True)
    if row is None:
        row = AlertEpisode(
            episode_id=episode_id,
            organization_id=facts.organization_id,
            restaurant_id=facts.restaurant_id,
            ingredient_id=facts.ingredient_id,
            opening_revision=facts.opening_revision,
        )
        session.add(row)
    row.organization_id = facts.organization_id
    row.restaurant_id = facts.restaurant_id
    row.ingredient_id = facts.ingredient_id
    row.ingredient_name = facts.ingredient_name
    row.unit = facts.unit
    row.opening_quantity = facts.opening_quantity
    row.opening_threshold = facts.opening_reorder_threshold
    row.opened_at = facts.opened_at
    row.opening_revision = facts.opening_revision
    row.opening_source = facts.opening_source
    row.opening_actor_user_id = facts.opening_actor_user_id
    row.opening_order_id = facts.opening_order_id
    row.notification_suppressed = facts.notification_suppressed
    row.resolved_at = facts.resolved_at
    row.resolution_reason = facts.resolution_reason
    row.closing_quantity = facts.closing_quantity
    row.closing_threshold = facts.closing_reorder_threshold
    row.closing_is_active = facts.closing_is_active
    row.resolution_revision = facts.resolution_revision
    row.resolution_source = facts.resolution_source
    row.resolution_actor_user_id = facts.resolution_actor_user_id
    row.resolution_order_id = facts.resolution_order_id


async def _sync_episode(session: AsyncSession, episode_id: UUID) -> None:
    facts = await load_inventory_episode_facts(session, episode_id)
    if facts is not None:
        await _store_episode_facts(session, facts)


async def apply_alert_event(
    session: AsyncSession, event: EventEnvelope
) -> Literal["processed", "skipped"]:
    """Project durable producer facts and revision-fence current inventory state."""
    _require_transaction(session)
    if not isinstance(event, InventoryStateChangedEvent):
        if isinstance(event, InventoryLowEvent):
            await load_inventory_state(
                session,
                event.organization_id,
                event.restaurant_id,
                event.payload.ingredient_id,
                lock=True,
            )
            await _sync_episode(session, event.payload.episode_id)
            await session.flush()
            return "processed"
        raise ValueError("Unsupported alert event")

    payload = event.payload
    current = await load_inventory_state(
        session,
        event.organization_id,
        event.restaurant_id,
        payload.ingredient_id,
        lock=True,
    )
    if payload.episode_id is not None and payload.episode_transition is not None:
        await _sync_episode(session, payload.episode_id)
    repo = AlertProjectionRepository(session)
    row = await repo.state(
        event.organization_id, event.restaurant_id, payload.ingredient_id, lock=True
    )
    if row is not None and row.revision >= current.state_revision:
        return "skipped"
    if row is None:
        row = AlertIngredientState(
            organization_id=event.organization_id,
            restaurant_id=event.restaurant_id,
            ingredient_id=payload.ingredient_id,
            revision=current.state_revision,
            ingredient_name=current.ingredient_name,
            unit=current.unit,
            quantity=current.quantity,
            reorder_threshold=current.reorder_threshold,
            is_active=current.is_active,
            is_low=current.is_low,
            episode_id=current.episode_id if current.is_low else None,
            occurred_at=event.occurred_at,
        )
        session.add(row)
    else:
        row.revision = current.state_revision
        row.ingredient_name = current.ingredient_name
        row.unit = current.unit
        row.quantity = current.quantity
        row.reorder_threshold = current.reorder_threshold
        row.is_active = current.is_active
        row.is_low = current.is_low
        row.episode_id = current.episode_id if current.is_low else None
        row.occurred_at = max(row.occurred_at, event.occurred_at)
    await session.flush()
    return "processed"


class AlertProjectionService:
    """Trusted maintenance hooks for T8; preserve history and notification outcomes."""

    async def inspect(
        self, session: AsyncSession, organization_id: UUID, restaurant_id: int
    ) -> dict[str, object]:
        repo = AlertProjectionRepository(session)
        episodes = await repo.all_episodes(organization_id, restaurant_id)
        states = await repo.states(organization_id, restaurant_id)
        return {"episodes": episodes, "states": states}

    async def rebuild(
        self, session: AsyncSession, organization_id: UUID, restaurant_id: int
    ) -> None:
        """Refresh history/current watermarks from retained producer and live inventory facts."""
        _require_transaction(session)
        # Establish the same restaurant serialization point as stock writes.
        states = await load_inventory_restaurant_states(
            session, organization_id, restaurant_id, lock=True
        )
        episode_facts = await load_inventory_episode_history(
            session, organization_id, restaurant_id
        )
        for facts in episode_facts:
            await _store_episode_facts(session, facts)
        repo = AlertProjectionRepository(session)
        for current in states:
            row = await repo.state(
                organization_id, restaurant_id, current.ingredient_id, lock=True
            )
            if row is not None and row.revision > current.state_revision:
                continue
            if row is None:
                row = AlertIngredientState(
                    organization_id=organization_id,
                    restaurant_id=restaurant_id,
                    ingredient_id=current.ingredient_id,
                    revision=current.state_revision,
                    ingredient_name=current.ingredient_name,
                    unit=current.unit,
                    quantity=current.quantity,
                    reorder_threshold=current.reorder_threshold,
                    is_active=current.is_active,
                    is_low=current.is_low,
                    episode_id=current.episode_id if current.is_low else None,
                    occurred_at=datetime.now(timezone.utc),
                )
                session.add(row)
            else:
                row.revision = current.state_revision
                row.ingredient_name = current.ingredient_name
                row.unit = current.unit
                row.quantity = current.quantity
                row.reorder_threshold = current.reorder_threshold
                row.is_active = current.is_active
                row.is_low = current.is_low
                row.episode_id = current.episode_id if current.is_low else None
                row.occurred_at = datetime.now(timezone.utc)
        await session.flush()
