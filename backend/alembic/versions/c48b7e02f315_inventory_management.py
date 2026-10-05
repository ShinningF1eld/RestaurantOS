"""Restaurant inventory ingredients, balances and stock ledger."""

from alembic import op
import sqlalchemy as sa

revision = "c48b7e02f315"  # pragma: allowlist secret
down_revision = "b37a6d91e204"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_ingredients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(765), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("reorder_threshold", sa.Numeric(12, 3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "restaurant_id", "normalized_name", name="uq_inventory_ingredient_name"
        ),
        sa.CheckConstraint("unit IN ('g', 'ml', 'piece')", name="ck_inventory_unit"),
        sa.CheckConstraint(
            "reorder_threshold >= 0 AND reorder_threshold <= 999999999.999",
            name="ck_inventory_threshold",
        ),
    )
    op.create_index(
        "ix_inventory_ingredients_restaurant_id",
        "inventory_ingredients",
        ["restaurant_id"],
    )
    op.create_table(
        "inventory_balances",
        sa.Column(
            "ingredient_id",
            sa.Integer(),
            sa.ForeignKey("inventory_ingredients.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_inventory_balance_version"),
        sa.CheckConstraint(
            "quantity >= 0 AND quantity <= 999999999.999", name="ck_inventory_balance"
        ),
    )
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ingredient_id",
            sa.Integer(),
            sa.ForeignKey("inventory_ingredients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(12, 3), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 3), nullable=False),
        sa.Column("version_after", sa.Integer(), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_delta >= -999999999.999 AND quantity_delta <= 999999999.999",
            name="ck_inventory_delta",
        ),
        sa.CheckConstraint("version_after >= 1", name="ck_inventory_movement_version"),
        sa.CheckConstraint(
            "(kind IN ('opening', 'receipt') AND quantity_delta >= 0) OR (kind = 'waste' AND quantity_delta < 0) OR kind = 'count'",
            name="ck_inventory_movement_sign",
        ),
        sa.UniqueConstraint(
            "ingredient_id", "idempotency_key", name="uq_inventory_movement_key"
        ),
        sa.CheckConstraint(
            "kind IN ('opening', 'receipt', 'waste', 'count')",
            name="ck_inventory_movement_kind",
        ),
        sa.CheckConstraint(
            "balance_after >= 0 AND balance_after <= 999999999.999",
            name="ck_inventory_movement_balance",
        ),
    )
    op.create_index(
        "ix_inventory_movements_ingredient_id", "inventory_movements", ["ingredient_id"]
    )


def downgrade() -> None:
    op.drop_table("inventory_movements")
    op.drop_table("inventory_balances")
    op.drop_table("inventory_ingredients")
