"""Retained analytics revisions and derived daily completed sales."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrderContribution(Base):
    __tablename__ = "analytics_order_contributions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            ondelete="RESTRICT",
            name="fk_analytics_contribution_scope",
        ),
        CheckConstraint("revision >= 1", name="ck_analytics_contribution_revision"),
        CheckConstraint("order_id > 0", name="ck_analytics_contribution_order"),
        CheckConstraint("total >= 0", name="ck_analytics_contribution_total"),
        CheckConstraint(
            "state IN ('completed','inactive','deleted')",
            name="ck_analytics_contribution_state",
        ),
        CheckConstraint(
            "state = 'completed' OR total = 0",
            name="ck_analytics_contribution_inactive_total",
        ),
    )

    # No order FK: deletion must preserve the revision tombstone.
    restaurant_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False)
    creation_date: Mapped[date] = mapped_column(Date, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)


class DailySales(Base):
    __tablename__ = "analytics_daily_sales"
    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            ondelete="RESTRICT",
            name="fk_analytics_daily_scope",
        ),
        CheckConstraint("order_count >= 0", name="ck_analytics_daily_count"),
        CheckConstraint("sales >= 0", name="ck_analytics_daily_sales"),
    )

    restaurant_id: Mapped[int] = mapped_column(primary_key=True)
    creation_date: Mapped[date] = mapped_column(Date, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    order_count: Mapped[int] = mapped_column(nullable=False)
    # Daily sums must exceed the precision of any individual order.
    sales: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
