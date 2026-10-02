"""Enforce the supported catalog price range without rewriting existing data."""

from alembic import op


revision = "b37a6d91e204"  # pragma: allowlist secret
down_revision = "94d8f2c5b013"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NUMERIC(10, 2) supplies storage precision. Application validation rejects
    # fractional cents before PostgreSQL can round them. Invalid existing rows
    # deliberately fail this migration rather than silently changing prices.
    op.create_check_constraint(
        "ck_menu_items_price_range", "menu_items", "price >= 0 AND price <= 99999999.99"
    )


def downgrade() -> None:
    op.drop_constraint("ck_menu_items_price_range", "menu_items", type_="check")
