from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.menu_items import MenuItem
    from app.db.models.restaurant import Restaurant


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
