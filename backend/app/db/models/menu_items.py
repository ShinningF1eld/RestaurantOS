from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class MenuItem(Base):
    __tablename__ = "menu_items"

    menu_item_id = Column(Integer, primary_key=True, index=True)

    menu_id = Column(
        Integer,
        ForeignKey("menus.menu_id"),
        nullable=False,
    )

    name = Column(String, nullable=False)

    description = Column(String, nullable=True)

    price = Column(Numeric(10, 2), nullable=False)

    is_available = Column(Boolean, nullable=False, default=True)

    menu = relationship(
        "Menu",
        back_populates="items",
    )
