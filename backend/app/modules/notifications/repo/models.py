"""Retained low-stock outcomes and safe operator diagnostics."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationStub(Base):
    __tablename__ = "notification_stubs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_notification_stub_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "outcome IN ('created','skipped','suppressed')",
            name="ck_notification_stub_outcome",
        ),
        CheckConstraint("ingredient_id > 0", name="ck_notification_stub_ingredient"),
        UniqueConstraint("episode_id", name="uq_notification_stub_episode"),
        Index(
            "ix_notification_stubs_scope_created",
            "organization_id",
            "restaurant_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    episode_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    opening_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    reorder_threshold: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(40))
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class EventDiagnostic(Base):
    __tablename__ = "event_diagnostics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_event_diagnostic_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_type IN ('order.submitted.v1','order.accepted.v1','order.completed.v1','order.cancelled.v1','order.deleted.v1','menu.updated.v1')",
            name="ck_event_diagnostic_type",
        ),
        Index(
            "ix_event_diagnostics_scope_created",
            "organization_id",
            "restaurant_id",
            "created_at",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    facts: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
