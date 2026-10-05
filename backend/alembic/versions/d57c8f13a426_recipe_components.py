"""Add menu item inventory tracking and recipe components."""

from alembic import op
import sqlalchemy as sa


revision = "d57c8f13a426"  # pragma: allowlist secret
down_revision = "c48b7e02f315"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column(
            "inventory_tracking",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "recipe_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "menu_item_id",
            sa.Integer(),
            sa.ForeignKey("menu_items.menu_item_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.Integer(),
            sa.ForeignKey("inventory_ingredients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.UniqueConstraint(
            "menu_item_id", "ingredient_id", name="uq_recipe_component_item_ingredient"
        ),
        sa.CheckConstraint(
            "quantity > 0 AND quantity <= 999999999.999",
            name="ck_recipe_component_quantity",
        ),
    )
    op.create_index(
        "ix_recipe_components_menu_item_id",
        "recipe_components",
        ["menu_item_id"],
    )
    op.create_index(
        "ix_recipe_components_ingredient_id",
        "recipe_components",
        ["ingredient_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_recipe_components_ingredient_id", table_name="recipe_components")
    op.drop_index("ix_recipe_components_menu_item_id", table_name="recipe_components")
    op.drop_table("recipe_components")
    op.drop_column("menu_items", "inventory_tracking")
