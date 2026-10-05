"""Recipe components associate menu portions with fixed-base-unit stock."""

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecipeComponent(Base):
    __tablename__ = "recipe_components"
    __table_args__ = (
        UniqueConstraint(
            "menu_item_id", "ingredient_id", name="uq_recipe_component_item_ingredient"
        ),
        CheckConstraint(
            "quantity > 0 AND quantity <= 999999999.999",
            name="ck_recipe_component_quantity",
        ),
        Index("ix_recipe_components_menu_item_id", "menu_item_id"),
        Index("ix_recipe_components_ingredient_id", "ingredient_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.menu_item_id", ondelete="CASCADE"),
        nullable=False,
    )
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_ingredients.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
