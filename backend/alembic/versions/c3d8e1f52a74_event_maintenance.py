"""Scoped maintenance initialization markers and operator provenance.

Revision ID: c3d8e1f52a74
Revises: b2c7d9a41e63
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d8e1f52a74"  # pragma: allowlist secret
down_revision = "b2c7d9a41e63"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_maintenance_operations",
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("operator", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_event_maintenance_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "kind IN ('initialize','analytics_rebuild')",
            name="ck_event_maintenance_kind",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 1000",
            name="ck_event_maintenance_reason",
        ),
    )
    op.create_index(
        "uq_event_maintenance_initialization",
        "event_maintenance_operations",
        ["restaurant_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'initialize'"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM event_maintenance_operations)")
    ):
        raise RuntimeError(
            "Cannot downgrade while retained maintenance provenance exists"
        )
    op.drop_table("event_maintenance_operations")
