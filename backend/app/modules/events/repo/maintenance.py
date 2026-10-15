"""Scoped maintenance provenance and queries; caller owns transactions."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Uuid,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.events.repo.models import (
    OutboxEvent,
    EventDelivery,
    EventReceipt,
    EventDeliveryAttempt,
    EventDeliveryReplay,
)


class MaintenanceOperation(Base):
    __tablename__ = "event_maintenance_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_event_maintenance_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "kind IN ('initialize','analytics_rebuild')",
            name="ck_event_maintenance_kind",
        ),
        CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 1000",
            name="ck_event_maintenance_reason",
        ),
        Index(
            "uq_event_maintenance_initialization",
            "restaurant_id",
            unique=True,
            postgresql_where=text("kind = 'initialize'"),
        ),
    )
    operation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    operator: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


async def initialization(
    session: AsyncSession, organization_id: UUID, restaurant_id: int
) -> MaintenanceOperation | None:
    return await session.scalar(
        select(MaintenanceOperation).where(
            MaintenanceOperation.organization_id == organization_id,
            MaintenanceOperation.restaurant_id == restaurant_id,
            MaintenanceOperation.kind == "initialize",
        )
    )


async def retained_counts(
    session: AsyncSession, organization_id: UUID, restaurant_id: int
) -> dict[str, int]:
    scope = (
        OutboxEvent.organization_id == organization_id,
        OutboxEvent.restaurant_id == restaurant_id,
    )
    counts = {
        "events": int(
            await session.scalar(
                select(func.count()).select_from(OutboxEvent).where(*scope)
            )
            or 0
        )
    }
    for name, model in (("deliveries", EventDelivery), ("receipts", EventReceipt)):
        counts[name] = int(
            await session.scalar(
                select(func.count())
                .select_from(model)
                .join(OutboxEvent, model.event_id == OutboxEvent.event_id)
                .where(*scope)
            )
            or 0
        )
    for name, history_model in (
        ("attempts", EventDeliveryAttempt),
        ("replays", EventDeliveryReplay),
    ):
        counts[name] = int(
            await session.scalar(
                select(func.count())
                .select_from(history_model)
                .join(EventDelivery, history_model.delivery_id == EventDelivery.id)
                .join(OutboxEvent, EventDelivery.event_id == OutboxEvent.event_id)
                .where(*scope)
            )
            or 0
        )
    counts["maintenance_operations"] = int(
        await session.scalar(
            select(func.count())
            .select_from(MaintenanceOperation)
            .where(
                MaintenanceOperation.organization_id == organization_id,
                MaintenanceOperation.restaurant_id == restaurant_id,
            )
        )
        or 0
    )
    return counts
