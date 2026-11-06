"""Optional outbox trace metadata, without changing retained event facts.

Revision ID: d4e9f2a63b85
Revises: c3d8e1f52a74
"""

from alembic import op
import sqlalchemy as sa

revision = "d4e9f2a63b85"  # pragma: allowlist secret - public revision
down_revision = "c3d8e1f52a74"  # pragma: allowlist secret - public revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_events", sa.Column("traceparent", sa.String(55), nullable=True)
    )

    op.create_index(
        "ix_event_deliveries_observability",
        "event_deliveries",
        ["consumer_name", "status", "created_at"],
        postgresql_include=["next_attempt_at", "claim_expires_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing', 'failed')"),
    )


def downgrade() -> None:
    # Deploy compatible code first. Only trace metadata is discarded.
    op.drop_index("ix_event_deliveries_observability", table_name="event_deliveries")
    op.drop_column("outbox_events", "traceparent")
