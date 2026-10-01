"""Tenant roots and branch assignments using the shared SQLAlchemy metadata."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base
from app.modules.tenancy.domain.roles import MembershipRole


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_organizations_name"),
        CheckConstraint(
            "slug = lower(trim(slug)) AND length(slug) > 0",
            name="ck_organizations_slug",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')", name="ck_organizations_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_memberships_user_org"),
        UniqueConstraint("id", "organization_id", name="uq_memberships_id_org"),
        CheckConstraint(
            "role IN ('OWNER', 'MANAGER', 'EMPLOYEE')", name="ck_memberships_role"
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')", name="ck_memberships_status"
        ),
        Index("ix_memberships_org_status_role", "organization_id", "status", "role"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(
            MembershipRole,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            length=20,
        )
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )


class RestaurantAssignment(Base):
    __tablename__ = "restaurant_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_assignments_membership_org",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_assignments_restaurant_org",
            ondelete="RESTRICT",
        ),
        Index("ix_assignments_org_restaurant", "organization_id", "restaurant_id"),
    )

    membership_id: Mapped[UUID] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
