from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Menu(Base):
    __tablename__ = "menus"

    menu_id = Column(Integer, primary_key=True, index=True)

    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id"),
        nullable=False,
    )

    name = Column(String, nullable=False)

    description = Column(String, nullable=True)

    restaurant = relationship(
        "Restaurant",
        back_populates="menus",
    )

    items = relationship(
    "MenuItem",
    back_populates="menu",
)