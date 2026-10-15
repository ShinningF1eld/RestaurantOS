"""Retained alert episode snapshots and revisioned current inventory state."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlertEpisode(Base):
    __tablename__ = "alert_episodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_alert_episode_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ingredient_id > 0", name="ck_alert_episode_ingredient"),
        CheckConstraint("opening_revision >= 1", name="ck_alert_episode_open_revision"),
        CheckConstraint(
            "opening_quantity IS NULL OR (opening_quantity >= 0 AND opening_quantity <= 999999999.999)",
            name="ck_alert_episode_open_quantity",
        ),
        CheckConstraint(
            "opening_threshold IS NULL OR (opening_threshold >= 0 AND opening_threshold <= 999999999.999)",
            name="ck_alert_episode_open_threshold",
        ),
        CheckConstraint(
            "resolution_revision IS NULL OR resolution_revision >= opening_revision",
            name="ck_alert_episode_resolution_revision",
        ),
        Index(
            "ix_alert_episodes_scope_opened",
            "organization_id",
            "restaurant_id",
            "opened_at",
        ),
        Index(
            "ix_alert_episodes_ingredient",
            "restaurant_id",
            "ingredient_id",
            "opened_at",
        ),
    )

    episode_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_name: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(10))
    opening_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    opening_threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opening_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_source: Mapped[str | None] = mapped_column(String(40))
    opening_actor_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    opening_order_id: Mapped[int | None] = mapped_column(Integer)
    notification_suppressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_reason: Mapped[str | None] = mapped_column(String(32))
    closing_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    closing_threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    closing_is_active: Mapped[bool | None] = mapped_column(Boolean)
    resolution_revision: Mapped[int | None] = mapped_column(Integer)
    resolution_source: Mapped[str | None] = mapped_column(String(40))
    resolution_actor_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    resolution_order_id: Mapped[int | None] = mapped_column(Integer)


class AlertIngredientState(Base):
    __tablename__ = "alert_ingredient_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_alert_state_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ingredient_id > 0", name="ck_alert_state_ingredient"),
        CheckConstraint("revision >= 1", name="ck_alert_state_revision"),
        CheckConstraint(
            "quantity >= 0 AND reorder_threshold >= 0", name="ck_alert_state_quantities"
        ),
        CheckConstraint(
            "is_low = (is_active AND quantity <= reorder_threshold)",
            name="ck_alert_state_low_rule",
        ),
        Index("ix_alert_state_scope_low", "organization_id", "restaurant_id", "is_low"),
    )

    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    reorder_threshold: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_low: Mapped[bool] = mapped_column(Boolean, nullable=False)
    episode_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
