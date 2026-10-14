"""Retained order contribution revisions and daily sales projection.

Revision ID: a936d8e4c021
Revises: b8f34c2a91de
"""

from alembic import op
import sqlalchemy as sa

revision = "a936d8e4c021"  # pragma: allowlist secret - public Alembic revision ID
down_revision = "b8f34c2a91de"  # pragma: allowlist secret - public Alembic revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_order_contributions",
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("creation_date", sa.Date(), nullable=False),
        sa.Column("total", sa.Numeric(10, 2), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.PrimaryKeyConstraint("restaurant_id", "order_id"),
        sa.ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            ondelete="RESTRICT",
            name="fk_analytics_contribution_scope",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_analytics_contribution_revision"),
        sa.CheckConstraint("order_id > 0", name="ck_analytics_contribution_order"),
        sa.CheckConstraint("total >= 0", name="ck_analytics_contribution_total"),
        sa.CheckConstraint(
            "state IN ('completed','inactive','deleted')",
            name="ck_analytics_contribution_state",
        ),
        sa.CheckConstraint(
            "state = 'completed' OR total = 0",
            name="ck_analytics_contribution_inactive_total",
        ),
    )
    op.create_table(
        "analytics_daily_sales",
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("creation_date", sa.Date(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("order_count", sa.Integer(), nullable=False),
        sa.Column("sales", sa.Numeric(20, 2), nullable=False),
        sa.PrimaryKeyConstraint("restaurant_id", "creation_date"),
        sa.ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            ondelete="RESTRICT",
            name="fk_analytics_daily_scope",
        ),
        sa.CheckConstraint("order_count >= 0", name="ck_analytics_daily_count"),
        sa.CheckConstraint("sales >= 0", name="ck_analytics_daily_sales"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM analytics_order_contributions) OR EXISTS (SELECT 1 FROM analytics_daily_sales)"
        )
    ):
        raise RuntimeError(
            "Cannot downgrade while retained analytics projection data exists"
        )
    op.drop_table("analytics_daily_sales")
    op.drop_table("analytics_order_contributions")
