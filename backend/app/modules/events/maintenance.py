"""Trusted offline maintenance. Stop workers and quiesce writes before use."""

from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.analytics.service import rebuild_analytics_projection
from app.modules.alerts.service import AlertProjectionService
from app.modules.events.domain.diagnostics import safe_identifier
from app.modules.events.repo import delivery_queries
from app.modules.events.repo.maintenance import (
    MaintenanceOperation,
    initialization,
    retained_counts,
)
from app.modules.inventory.service import (
    load_inventory_restaurant_states,
    record_baseline_inventory_episode,
)
from app.modules.notifications.service import inspect_notification_sink


class EventMaintenanceService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def run(
        self,
        organization_id: UUID,
        restaurant_id: int,
        *,
        kind: Literal["initialize", "analytics_rebuild"],
        reason: str,
        maintenance_confirmed: bool,
    ) -> dict[str, object]:
        if not maintenance_confirmed:
            raise ValueError("Stop workers and quiesce writes before maintenance")
        if not reason.strip() or len(reason) > 1000 or any(ord(c) < 32 for c in reason):
            raise ValueError("A safe maintenance reason is required")
        if kind not in {"initialize", "analytics_rebuild"}:
            raise ValueError("Unknown maintenance operation")
        async with self.sessions() as session, session.begin():
            # Public inventory interface validates organization/branch and takes
            # the restaurant lock before the scoped marker or any derived writes.
            states = await load_inventory_restaurant_states(
                session, organization_id, restaurant_id, lock=True
            )
            marker = await initialization(session, organization_id, restaurant_id)
            if kind == "initialize" and marker is not None:
                operation = marker
                outcome = "already_initialized"
            else:
                if kind == "analytics_rebuild" and marker is None:
                    raise ValueError("Initialize this scope before rebuilding")
                observed_at = await delivery_queries.clock(session)
                await rebuild_analytics_projection(
                    session, organization_id, restaurant_id
                )
                if kind == "initialize":
                    for state in states:
                        if state.is_low and state.episode_id is None:
                            await record_baseline_inventory_episode(
                                session,
                                organization_id,
                                restaurant_id,
                                state.ingredient_id,
                                observed_at=observed_at,
                            )
                    await AlertProjectionService().rebuild(
                        session, organization_id, restaurant_id
                    )
                operation = MaintenanceOperation(
                    organization_id=organization_id,
                    restaurant_id=restaurant_id,
                    kind=kind,
                    reason=reason.strip(),
                    observed_at=observed_at,
                    operator=await delivery_queries.operator_identity(session),
                )
                session.add(operation)
                await session.flush()
                outcome = "completed"
            counts = await retained_counts(session, organization_id, restaurant_id)
            alerts = await AlertProjectionService().inspect(
                session, organization_id, restaurant_id
            )
            sink = await inspect_notification_sink(
                session, organization_id, restaurant_id
            )
            for name, rows in (alerts | sink).items():
                if isinstance(rows, list):
                    counts[name] = len(rows)
            return {
                "organization_id": str(organization_id),
                "restaurant_id": restaurant_id,
                "operation_id": str(operation.operation_id),
                "kind": operation.kind,
                "outcome": outcome,
                "observed_at": operation.observed_at.isoformat(),
                "operator": safe_identifier(operation.operator),
                "reason_recorded": True,
                "retained_counts": counts,
            }
