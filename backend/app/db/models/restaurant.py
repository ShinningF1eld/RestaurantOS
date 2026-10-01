from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.menu import Menu
    from app.db.models.order import Order


class Restaurant(Base):
    __tablename__ = "restaurants"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_restaurants_id_org"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Expansion phase: existing creation services do not supply tenant scope yet.
    # Remove nullability after owner bootstrap and scoped writes are implemented.
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "organizations.id", name="fk_restaurants_organization", ondelete="RESTRICT"
        ),
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
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

    menus: Mapped[list["Menu"]] = relationship(
        "Menu",
        back_populates="restaurant",
    )

    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="restaurant",
    )
