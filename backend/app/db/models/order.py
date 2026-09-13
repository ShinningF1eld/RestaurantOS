from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(Integer, primary_key=True, index=True)

    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id"),
        nullable=False,
    )

    table_number = Column(String(50), nullable=True)

    customer_name = Column(String(255), nullable=True)

    status = Column(String(50), nullable=False, default="pending")

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
        ForeignKey("menu_items.menu_item_id"),
        nullable=False,
    )

    quantity = Column(Integer, nullable=False)

    unit_price = Column(Numeric(10, 2), nullable=False)

    line_total = Column(Numeric(10, 2), nullable=False)

    notes = Column(String, nullable=True)

    order = relationship(
        "Order",
        back_populates="items",
    )

    menu_item = relationship("MenuItem")

    @property
    def menu_item_name(self) -> str:
        return self.menu_item.name
