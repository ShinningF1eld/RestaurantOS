from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    UniqueConstraint,
    text,
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
        CheckConstraint("state_revision >= 1", name="ck_inventory_state_revision"),
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
    state_revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
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


class InventoryLowStockEpisode(Base):
    """Durable producer facts; scope identifiers intentionally survive deletion."""

    __tablename__ = "inventory_low_stock_episodes"
    __table_args__ = (
        CheckConstraint("restaurant_id > 0", name="ck_inventory_episode_restaurant"),
        CheckConstraint("ingredient_id > 0", name="ck_inventory_episode_ingredient"),
        CheckConstraint(
            "unit IN ('g', 'ml', 'piece')", name="ck_inventory_episode_unit"
        ),
        CheckConstraint(
            "length(trim(ingredient_name)) > 0", name="ck_inventory_episode_name"
        ),
        CheckConstraint(
            "opening_quantity >= 0 AND opening_quantity <= 999999999.999",
            name="ck_inventory_episode_opening_quantity",
        ),
        CheckConstraint(
            "opening_reorder_threshold >= 0 AND "
            "opening_reorder_threshold <= 999999999.999",
            name="ck_inventory_episode_opening_threshold",
        ),
        CheckConstraint(
            "opening_quantity <= opening_reorder_threshold",
            name="ck_inventory_episode_opening_low",
        ),
        CheckConstraint("opening_revision >= 1", name="ck_inventory_episode_revision"),
        CheckConstraint(
            "opening_source IN ('ingredient_creation','ingredient_update',"
            "'stock_command','order_acceptance','maintenance_initialization')",
            name="ck_inventory_episode_opening_source",
        ),
        CheckConstraint(
            "(opening_source = 'order_acceptance' AND opening_order_id IS NOT NULL) OR "
            "(opening_source <> 'order_acceptance' AND opening_order_id IS NULL)",
            name="ck_inventory_episode_opening_order",
        ),
        CheckConstraint(
            "NOT notification_suppressed OR "
            "opening_source = 'maintenance_initialization'",
            name="ck_inventory_episode_suppression_source",
        ),
        CheckConstraint(
            "(resolved_at IS NULL AND resolution_reason IS NULL AND "
            "closing_quantity IS NULL AND closing_reorder_threshold IS NULL AND "
            "closing_is_active IS NULL AND resolution_revision IS NULL AND "
            "resolution_source IS NULL AND resolution_actor_user_id IS NULL AND "
            "resolution_order_id IS NULL) OR "
            "(resolved_at IS NOT NULL AND resolution_reason IS NOT NULL AND "
            "closing_quantity IS NOT NULL AND closing_reorder_threshold IS NOT NULL AND "
            "closing_is_active IS NOT NULL AND resolution_revision IS NOT NULL AND "
            "resolution_source IS NOT NULL)",
            name="ck_inventory_episode_resolution_complete",
        ),
        CheckConstraint(
            "resolution_reason IS NULL OR resolution_reason IN "
            "('stock_recovered','threshold_changed','archived')",
            name="ck_inventory_episode_resolution_reason",
        ),
        CheckConstraint(
            "resolution_source IS NULL OR resolution_source IN "
            "('ingredient_creation','ingredient_update','stock_command',"
            "'order_acceptance','maintenance_initialization')",
            name="ck_inventory_episode_resolution_source",
        ),
        CheckConstraint(
            "(resolution_source = 'order_acceptance' AND resolution_order_id IS NOT NULL) OR "
            "(resolution_source IS NULL AND resolution_order_id IS NULL) OR "
            "(resolution_source <> 'order_acceptance' AND resolution_order_id IS NULL)",
            name="ck_inventory_episode_resolution_order",
        ),
        CheckConstraint(
            "resolution_revision IS NULL OR resolution_revision > opening_revision",
            name="ck_inventory_episode_resolution_revision",
        ),
        CheckConstraint(
            "resolved_at IS NULL OR NOT closing_is_active OR "
            "closing_quantity > closing_reorder_threshold",
            name="ck_inventory_episode_closing_not_low",
        ),
        Index(
            "uq_inventory_open_episode_per_ingredient",
            "ingredient_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index(
            "ix_inventory_episode_org_restaurant_opened",
            "organization_id",
            "restaurant_id",
            "opened_at",
        ),
        Index("ix_inventory_episode_ingredient_opened", "ingredient_id", "opened_at"),
    )

    episode_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    # These are immutable scope snapshots, not cascading business-object references.
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    opening_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    opening_reorder_threshold: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opening_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_source: Mapped[str] = mapped_column(String(40), nullable=False)
    opening_actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    opening_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notification_suppressed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    closing_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), nullable=True
    )
    closing_reorder_threshold: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), nullable=True
    )
    closing_is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resolution_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution_actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    resolution_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
