"""Audit storage; application writers must allowlist safe change summaries."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_audit_entries_restaurant_org",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(action)) > 0", name="ck_audit_entries_action"),
        CheckConstraint(
            "length(trim(resource_type)) > 0 AND length(trim(resource_id)) > 0",
            name="ck_audit_entries_resource",
        ),
        CheckConstraint(
            "jsonb_typeof(changes) = 'object'", name="ck_audit_entries_changes_object"
        ),
        Index("ix_audit_entries_org_occurred", "organization_id", "occurred_at"),
        Index("ix_audit_entries_restaurant_id", "restaurant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    restaurant_id: Mapped[int | None] = mapped_column()
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(80))
    # Snapshot identifiers survive deletion of the resource being audited.
    resource_id: Mapped[str] = mapped_column(String(100))
    changes: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    request_id: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
