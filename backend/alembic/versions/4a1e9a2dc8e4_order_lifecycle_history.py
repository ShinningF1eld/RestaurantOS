"""Add order lifecycle, payment state, and historical item snapshots.

Revision ID: 4a1e9a2dc8e4
Revises: 2d7747d9f5b1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4a1e9a2dc8e4"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "2d7747d9f5b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("payment_status", sa.String(length=20), nullable=False, server_default="UNPAID"))
    op.add_column("order_items", sa.Column("item_name", sa.String(), nullable=True))
    op.execute("UPDATE order_items SET item_name = menu_items.name FROM menu_items WHERE order_items.menu_item_id = menu_items.menu_item_id")
    op.alter_column("order_items", "item_name", nullable=False)
    op.drop_constraint("order_items_menu_item_id_fkey", "order_items", type_="foreignkey")
    op.create_foreign_key("order_items_menu_item_id_fkey", "order_items", "menu_items", ["menu_item_id"], ["menu_item_id"], ondelete="SET NULL")
    op.alter_column("order_items", "menu_item_id", nullable=True)
    op.execute("UPDATE orders SET status = CASE lower(status) WHEN 'pending' THEN 'DRAFT' WHEN 'complete' THEN 'COMPLETED' WHEN 'cancelled' THEN 'CANCELLED' ELSE upper(status) END")
    op.create_index("ix_orders_restaurant_created_at", "orders", ["restaurant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_orders_restaurant_created_at", table_name="orders")
    op.alter_column("order_items", "menu_item_id", nullable=False)
    op.drop_constraint("order_items_menu_item_id_fkey", "order_items", type_="foreignkey")
    op.create_foreign_key("order_items_menu_item_id_fkey", "order_items", "menu_items", ["menu_item_id"], ["menu_item_id"])
    op.drop_column("order_items", "item_name")
    op.drop_column("orders", "payment_status")
