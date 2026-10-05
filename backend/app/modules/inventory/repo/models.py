from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Ingredient(Base):
    __tablename__ = "inventory_ingredients"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "normalized_name", name="uq_inventory_ingredient_name"
        ),
        CheckConstraint("unit IN ('g', 'ml', 'piece')", name="ck_inventory_unit"),
        CheckConstraint(
            "reorder_threshold >= 0 AND reorder_threshold <= 999999999.999",
            name="ck_inventory_threshold",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(765))
    unit: Mapped[str] = mapped_column(String(10))
    reorder_threshold: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        CheckConstraint(
            "quantity >= 0 AND quantity <= 999999999.999", name="ck_inventory_balance"
        ),
        CheckConstraint("version >= 1", name="ck_inventory_balance_version"),
    )
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_ingredients.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    version: Mapped[int] = mapped_column(Integer, default=1)


class InventoryMovement(Base):
    __allow_unmapped__ = True
    actor_name: str | None = None
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "quantity_delta >= -999999999.999 AND quantity_delta <= 999999999.999",
            name="ck_inventory_delta",
        ),
        CheckConstraint("version_after >= 1", name="ck_inventory_movement_version"),
        CheckConstraint(
            "(kind IN ('opening', 'receipt') AND quantity_delta >= 0) OR "
            "(kind IN ('waste', 'consumption') AND quantity_delta < 0) OR kind = 'count'",
            name="ck_inventory_movement_sign",
        ),
        UniqueConstraint(
            "ingredient_id", "idempotency_key", name="uq_inventory_movement_key"
        ),
        CheckConstraint(
            "kind IN ('opening', 'receipt', 'waste', 'count', 'consumption')",
            name="ck_inventory_movement_kind",
        ),
        UniqueConstraint(
            "order_id", "ingredient_id", name="uq_inventory_movement_order_ingredient"
        ),
        CheckConstraint(
            "(kind = 'consumption' AND order_id IS NOT NULL AND idempotency_key IS NULL) OR "
            "(kind <> 'consumption' AND order_id IS NULL AND idempotency_key IS NOT NULL)",
            name="ck_inventory_movement_order_link",
        ),
        CheckConstraint(
            "balance_after >= 0 AND balance_after <= 999999999.999",
            name="ck_inventory_movement_balance",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_ingredients.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    version_after: Mapped[int] = mapped_column(Integer)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "orders.order_id",
            ondelete="RESTRICT",
            name="fk_inventory_movements_order_id",
        ),
        nullable=True,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(500))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
