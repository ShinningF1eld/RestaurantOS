from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.menu_items import MenuItem
    from app.db.models.restaurant import Restaurant


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_restaurant_created_at", "restaurant_id", "created_at"),)

    order_id: Mapped[int] = mapped_column(primary_key=True, index=True)

    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"),
        nullable=False,
    )

    table_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Values are controlled by the order state machine in routers.order.
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")

    # This deliberately stays local to the order until a payment provider is
    # introduced.  It gives the operational UI an honest payment state without
    # pretending that a charge was processed.
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNPAID", server_default="UNPAID"
    )

    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
    )

    total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    restaurant: Mapped["Restaurant"] = relationship(
        "Restaurant",
        back_populates="orders",
    )

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    order_item_id: Mapped[int] = mapped_column(primary_key=True, index=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.order_id"),
        nullable=False,
    )

    menu_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("menu_items.menu_item_id", ondelete="SET NULL"),
        nullable=True,
    )

    quantity: Mapped[int] = mapped_column(nullable=False)

    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    item_name: Mapped[str] = mapped_column(String, nullable=False)

    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="items",
    )

    menu_item: Mapped["MenuItem | None"] = relationship("MenuItem")

    @property
    def menu_item_name(self) -> str:
        """Compatibility name used by the existing API contract."""
        return self.item_name
