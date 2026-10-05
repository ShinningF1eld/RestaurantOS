"""Track order inventory processing and creation idempotency."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e68d9a24b537"  # pragma: allowlist secret
down_revision = "d57c8f13a426"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "inventory_processed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_table(
        "order_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.order_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("response_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "restaurant_id", "idempotency_key", name="uq_order_submission_key"
        ),
    )

    op.alter_column(
        "inventory_movements",
        "idempotency_key",
        existing_type=sa.String(100),
        nullable=True,
    )
    op.alter_column(
        "inventory_movements",
        "request_fingerprint",
        existing_type=sa.String(64),
        nullable=True,
    )
    op.add_column(
        "inventory_movements", sa.Column("order_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_inventory_movements_order_id",
        "inventory_movements",
        "orders",
        ["order_id"],
        ["order_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_inventory_movements_order_id", "inventory_movements", ["order_id"]
    )

    op.drop_constraint(
        "ck_inventory_movement_sign", "inventory_movements", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_movement_sign",
        "inventory_movements",
        "(kind IN ('opening', 'receipt') AND quantity_delta >= 0) OR "
        "(kind IN ('waste', 'consumption') AND quantity_delta < 0) OR kind = 'count'",
    )
    op.drop_constraint(
        "ck_inventory_movement_kind", "inventory_movements", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_movement_kind",
        "inventory_movements",
        "kind IN ('opening', 'receipt', 'waste', 'count', 'consumption')",
    )
    op.create_check_constraint(
        "ck_inventory_movement_order_link",
        "inventory_movements",
        "(kind = 'consumption' AND order_id IS NOT NULL AND idempotency_key IS NULL) OR "
        "(kind <> 'consumption' AND order_id IS NULL AND idempotency_key IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_inventory_movement_order_ingredient",
        "inventory_movements",
        ["order_id", "ingredient_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    history = bind.execute(
        sa.text(
            "SELECT "
            "EXISTS (SELECT 1 FROM inventory_movements WHERE kind = 'consumption') "
            "AS has_consumption, "
            "EXISTS (SELECT 1 FROM order_submissions) AS has_submissions, "
            "EXISTS (SELECT 1 FROM orders WHERE inventory_processed IS TRUE) "
            "AS has_processed_orders"
        )
    ).mappings().one()
    if any(history.values()):
        raise RuntimeError(
            "Cannot downgrade e68d9a24b537 while order inventory history exists. "
            "This migration preserves stock and replay history; stay on this "
            "revision, or restore a pre-migration backup only if discarding that "
            "history is intended."
        )

    op.drop_constraint(
        "uq_inventory_movement_order_ingredient", "inventory_movements", type_="unique"
    )
    op.drop_constraint(
        "ck_inventory_movement_order_link", "inventory_movements", type_="check"
    )
    op.drop_constraint(
        "ck_inventory_movement_sign", "inventory_movements", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_movement_sign",
        "inventory_movements",
        "(kind IN ('opening', 'receipt') AND quantity_delta >= 0) OR "
        "(kind = 'waste' AND quantity_delta < 0) OR kind = 'count'",
    )
    op.drop_constraint(
        "ck_inventory_movement_kind", "inventory_movements", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_movement_kind",
        "inventory_movements",
        "kind IN ('opening', 'receipt', 'waste', 'count')",
    )
    op.drop_index("ix_inventory_movements_order_id", table_name="inventory_movements")
    op.drop_constraint(
        "fk_inventory_movements_order_id", "inventory_movements", type_="foreignkey"
    )
    op.drop_column("inventory_movements", "order_id")
    op.alter_column(
        "inventory_movements",
        "request_fingerprint",
        existing_type=sa.String(64),
        nullable=False,
    )
    op.alter_column(
        "inventory_movements",
        "idempotency_key",
        existing_type=sa.String(100),
        nullable=False,
    )
    op.drop_table("order_submissions")
    op.drop_column("orders", "inventory_processed")
