from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.menu import Menu


class MenuItem(Base):
    __tablename__ = "menu_items"

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
