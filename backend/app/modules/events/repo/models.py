"""Durable outbox facts and per-consumer delivery history."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_outbox_events_restaurant_org",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_type IN ("
            "'order.submitted.v1','order.accepted.v1','order.completed.v1',"
            "'order.cancelled.v1','order.deleted.v1','menu.updated.v1',"
            "'inventory.state_changed.v1','inventory.low.v1')",
            name="ck_outbox_events_type",
        ),
        CheckConstraint("schema_version = 1", name="ck_outbox_events_version"),
        CheckConstraint(
            "aggregate_type IN ('order','menu','menu_item','ingredient')",
            name="ck_outbox_events_aggregate_type",
        ),
        CheckConstraint("aggregate_revision >= 1", name="ck_outbox_events_revision"),
        CheckConstraint("restaurant_id > 0", name="ck_outbox_events_restaurant_id"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_outbox_events_payload_object"
        ),
        Index("ix_outbox_events_restaurant_occurred", "restaurant_id", "occurred_at"),
        Index(
            "ix_outbox_events_organization_occurred", "organization_id", "occurred_at"
        ),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EventDelivery(Base):
    __tablename__ = "event_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id"],
            ["outbox_events.event_id"],
            name="fk_event_deliveries_event",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "consumer_name IN ('analytics','alerts','notification_sink')",
            name="ck_event_deliveries_consumer",
        ),
        CheckConstraint(
            "status IN ('pending','processing','succeeded','failed')",
            name="ck_event_deliveries_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_event_deliveries_attempt_count"),
        CheckConstraint("retry_cycle >= 0", name="ck_event_deliveries_retry_cycle"),
        CheckConstraint(
            "(claim_token IS NULL AND claim_owner IS NULL AND claim_expires_at IS NULL) OR "
            "(claim_token IS NOT NULL AND claim_owner IS NOT NULL AND claim_expires_at IS NOT NULL)",
            name="ck_event_deliveries_claim_fields",
        ),
        UniqueConstraint(
            "consumer_name", "event_id", name="uq_event_delivery_consumer_event"
        ),
        Index("ix_event_deliveries_due", "consumer_name", "status", "next_attempt_at"),
        Index(
            "ix_event_deliveries_expired_claim",
            "claim_expires_at",
            postgresql_where=text("claim_expires_at IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    consumer_name: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    retry_cycle: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    claim_owner: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EventReceipt(Base):
    __tablename__ = "event_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["consumer_name", "event_id"],
            ["event_deliveries.consumer_name", "event_deliveries.event_id"],
            name="fk_event_receipts_delivery",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "outcome IN ('processed','skipped')", name="ck_event_receipts_outcome"
        ),
        Index("ix_event_receipts_processed_at", "processed_at"),
    )

    consumer_name: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventDeliveryAttempt(Base):
    __tablename__ = "event_delivery_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["delivery_id"],
            ["event_deliveries.id"],
            name="fk_event_attempts_delivery",
            ondelete="RESTRICT",
        ),
        CheckConstraint("retry_cycle >= 0", name="ck_event_attempts_retry_cycle"),
        CheckConstraint("attempt_number >= 1", name="ck_event_attempts_number"),
        CheckConstraint(
            "status IN ('running','succeeded','failed','skipped')",
            name="ck_event_attempts_status",
        ),
        UniqueConstraint(
            "delivery_id",
            "retry_cycle",
            "attempt_number",
            name="uq_event_attempt_cycle_number",
        ),
        Index("ix_event_attempts_delivery_started", "delivery_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    delivery_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    retry_cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(80))


class EventDeliveryReplay(Base):
    __tablename__ = "event_delivery_replays"
    __table_args__ = (
        ForeignKeyConstraint(
            ["delivery_id"],
            ["event_deliveries.id"],
            name="fk_event_replays_delivery",
            ondelete="RESTRICT",
        ),
        CheckConstraint("from_cycle >= 0", name="ck_event_replays_from_cycle"),
        CheckConstraint("to_cycle = from_cycle + 1", name="ck_event_replays_to_cycle"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_event_replays_reason"),
        UniqueConstraint("delivery_id", "to_cycle", name="uq_event_replay_cycle"),
        Index("ix_event_replays_requested_at", "requested_at"),
    )

    replay_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    delivery_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    from_cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    to_cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    operator: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
