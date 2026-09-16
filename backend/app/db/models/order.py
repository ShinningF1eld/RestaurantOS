from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_restaurant_created_at", "restaurant_id", "created_at"),)

    order_id = Column(Integer, primary_key=True, index=True)

    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id"),
        nullable=False,
    )

    table_number = Column(String(50), nullable=True)

    customer_name = Column(String(255), nullable=True)

    # Values are controlled by the order state machine in routers.order.
    status = Column(String(50), nullable=False, default="DRAFT")

    # This deliberately stays local to the order until a payment provider is
    # introduced.  It gives the operational UI an honest payment state without
    # pretending that a charge was processed.
    payment_status = Column(
        String(20), nullable=False, default="UNPAID", server_default="UNPAID"
    )

    notes = Column(String, nullable=True)

    subtotal = Column(Numeric(10, 2), nullable=False, default=0)

    total = Column(Numeric(10, 2), nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    restaurant = relationship(
        "Restaurant",
        back_populates="orders",
    )

    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    order_item_id = Column(Integer, primary_key=True, index=True)

    order_id = Column(
        Integer,
        ForeignKey("orders.order_id"),
        nullable=False,
    )

    menu_item_id = Column(
        Integer,
        ForeignKey("menu_items.menu_item_id", ondelete="SET NULL"),
        nullable=True,
    )

    quantity = Column(Integer, nullable=False)

    unit_price = Column(Numeric(10, 2), nullable=False)

    item_name = Column(String, nullable=False)

    line_total = Column(Numeric(10, 2), nullable=False)

    notes = Column(String, nullable=True)

    order = relationship(
        "Order",
        back_populates="items",
    )

    menu_item = relationship("MenuItem")

    @property
    def menu_item_name(self) -> str:
        """Compatibility name used by the existing API contract."""
        return self.item_name
