from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.restaurants.repo.models import Restaurant


class Menu(Base):
    __tablename__ = "menus"

    menu_id: Mapped[int] = mapped_column(primary_key=True, index=True)

    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String, nullable=False)

    description: Mapped[str | None] = mapped_column(String, nullable=True)

    restaurant: Mapped["Restaurant"] = relationship(
        "Restaurant",
        back_populates="menus",
    )

    items: Mapped[list["MenuItem"]] = relationship(
        "MenuItem",
        back_populates="menu",
    )


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        CheckConstraint(
            "price >= 0 AND price <= 99999999.99", name="ck_menu_items_price_range"
        ),
    )

    menu_item_id: Mapped[int] = mapped_column(primary_key=True, index=True)

    menu_id: Mapped[int] = mapped_column(
        ForeignKey("menus.menu_id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String, nullable=False)

    description: Mapped[str | None] = mapped_column(String, nullable=True)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    is_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    menu: Mapped["Menu"] = relationship(
        "Menu",
        back_populates="items",
    )
