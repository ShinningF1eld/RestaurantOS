"""Alert episode projection and durable notification/diagnostic sink.

Revision ID: b2c7d9a41e63
Revises: a936d8e4c021
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2c7d9a41e63"  # pragma: allowlist secret - public Alembic revision ID
down_revision = "a936d8e4c021"  # pragma: allowlist secret - public Alembic revision ID
branch_labels = None
depends_on = None


def _scope_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["restaurant_id", "organization_id"],
        ["restaurants.id", "restaurants.organization_id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "alert_episodes",
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_name", sa.String(255)),
        sa.Column("unit", sa.String(10)),
        sa.Column("opening_quantity", sa.Numeric(12, 3)),
        sa.Column("opening_threshold", sa.Numeric(12, 3)),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("opening_revision", sa.Integer(), nullable=False),
        sa.Column("opening_source", sa.String(40)),
        sa.Column("opening_actor_user_id", sa.Uuid()),
        sa.Column("opening_order_id", sa.Integer()),
        sa.Column(
            "notification_suppressed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_reason", sa.String(32)),
        sa.Column("closing_quantity", sa.Numeric(12, 3)),
        sa.Column("closing_threshold", sa.Numeric(12, 3)),
        sa.Column("closing_is_active", sa.Boolean()),
        sa.Column("resolution_revision", sa.Integer()),
        sa.Column("resolution_source", sa.String(40)),
        sa.Column("resolution_actor_user_id", sa.Uuid()),
        sa.Column("resolution_order_id", sa.Integer()),
        sa.PrimaryKeyConstraint("episode_id"),
        _scope_fk("fk_alert_episode_scope"),
        sa.CheckConstraint("ingredient_id > 0", name="ck_alert_episode_ingredient"),
        sa.CheckConstraint(
            "opening_revision >= 1", name="ck_alert_episode_open_revision"
        ),
        sa.CheckConstraint(
            "opening_quantity IS NULL OR (opening_quantity >= 0 AND opening_quantity <= 999999999.999)",
            name="ck_alert_episode_open_quantity",
        ),
        sa.CheckConstraint(
            "opening_threshold IS NULL OR (opening_threshold >= 0 AND opening_threshold <= 999999999.999)",
            name="ck_alert_episode_open_threshold",
        ),
        sa.CheckConstraint(
            "resolution_revision IS NULL OR resolution_revision >= opening_revision",
            name="ck_alert_episode_resolution_revision",
        ),
    )
    op.create_index(
        "ix_alert_episodes_scope_opened",
        "alert_episodes",
        ["organization_id", "restaurant_id", "opened_at"],
    )
    op.create_index(
        "ix_alert_episodes_ingredient",
        "alert_episodes",
        ["restaurant_id", "ingredient_id", "opened_at"],
    )

    op.create_table(
        "alert_ingredient_states",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ingredient_name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("reorder_threshold", sa.Numeric(12, 3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_low", sa.Boolean(), nullable=False),
        sa.Column("episode_id", sa.Uuid()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ingredient_id"),
        _scope_fk("fk_alert_state_scope"),
        sa.CheckConstraint("ingredient_id > 0", name="ck_alert_state_ingredient"),
        sa.CheckConstraint("revision >= 1", name="ck_alert_state_revision"),
        sa.CheckConstraint(
            "quantity >= 0 AND reorder_threshold >= 0", name="ck_alert_state_quantities"
        ),
        sa.CheckConstraint(
            "is_low = (is_active AND quantity <= reorder_threshold)",
            name="ck_alert_state_low_rule",
        ),
    )
    op.create_index(
        "ix_alert_state_scope_low",
        "alert_ingredient_states",
        ["organization_id", "restaurant_id", "is_low"],
    )

    op.create_table(
        "notification_stubs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("opening_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("reorder_threshold", sa.Numeric(12, 3), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(40)),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("episode_id", name="uq_notification_stub_episode"),
        _scope_fk("fk_notification_stub_scope"),
        sa.CheckConstraint(
            "outcome IN ('created','skipped','suppressed')",
            name="ck_notification_stub_outcome",
        ),
        sa.CheckConstraint("ingredient_id > 0", name="ck_notification_stub_ingredient"),
    )
    op.create_index(
        "ix_notification_stubs_scope_created",
        "notification_stubs",
        ["organization_id", "restaurant_id", "created_at"],
    )

    op.create_table(
        "event_diagnostics",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("aggregate_type", sa.String(40), nullable=False),
        sa.Column("aggregate_id", sa.String(100), nullable=False),
        sa.Column("aggregate_revision", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id"),
        _scope_fk("fk_event_diagnostic_scope"),
        sa.CheckConstraint(
            "event_type IN ('order.submitted.v1','order.accepted.v1','order.completed.v1','order.cancelled.v1','order.deleted.v1','menu.updated.v1')",
            name="ck_event_diagnostic_type",
        ),
    )
    op.create_index(
        "ix_event_diagnostics_scope_created",
        "event_diagnostics",
        ["organization_id", "restaurant_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    retained = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM alert_episodes) OR "
            "EXISTS (SELECT 1 FROM alert_ingredient_states) OR "
            "EXISTS (SELECT 1 FROM notification_stubs) OR "
            "EXISTS (SELECT 1 FROM event_diagnostics)"
        )
    )
    if retained:
        raise RuntimeError("Cannot downgrade while retained alert or sink data exists")
    op.drop_table("event_diagnostics")
    op.drop_table("notification_stubs")
    op.drop_table("alert_ingredient_states")
    op.drop_table("alert_episodes")
