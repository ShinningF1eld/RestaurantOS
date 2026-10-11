"""Add durable event contracts, per-consumer delivery history, and order revisions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c61a0f3d9e42"  # pragma: allowlist secret
down_revision = "e68d9a24b537"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
    )
    op.create_check_constraint("ck_orders_revision", "orders", "revision >= 1")

    op.create_table(
        "outbox_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=40), nullable=False),
        sa.Column("aggregate_id", sa.String(length=100), nullable=False),
        sa.Column("aggregate_revision", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'order.submitted.v1','order.accepted.v1','order.completed.v1',"
            "'order.cancelled.v1','order.deleted.v1','menu.updated.v1',"
            "'inventory.state_changed.v1','inventory.low.v1')",
            name="ck_outbox_events_type",
        ),
        sa.CheckConstraint("schema_version = 1", name="ck_outbox_events_version"),
        sa.CheckConstraint(
            "aggregate_type IN ('order','menu','menu_item','ingredient')",
            name="ck_outbox_events_aggregate_type",
        ),
        sa.CheckConstraint("aggregate_revision >= 1", name="ck_outbox_events_revision"),
        sa.CheckConstraint("restaurant_id > 0", name="ck_outbox_events_restaurant_id"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_outbox_events_payload_object"
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_outbox_events_restaurant_org",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_outbox_events"),
    )
    op.create_index(
        "ix_outbox_events_restaurant_occurred",
        "outbox_events",
        ["restaurant_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_events_organization_occurred",
        "outbox_events",
        ["organization_id", "occurred_at"],
        unique=False,
    )
    op.execute(
        "CREATE FUNCTION reject_outbox_event_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
        "'outbox event facts are immutable' USING ERRCODE = 'integrity_constraint_violation'; "
        "RETURN NULL; END; $$"
    )
    op.execute(
        "CREATE TRIGGER trg_outbox_events_immutable "
        "BEFORE UPDATE OR DELETE ON outbox_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_outbox_event_mutation()"
    )
    op.execute(
        "CREATE FUNCTION reject_retained_event_history_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
        "'retained event history cannot be changed or deleted' USING "
        "ERRCODE = 'integrity_constraint_violation'; RETURN NULL; END; $$"
    )

    op.create_table(
        "event_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consumer_name", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "retry_cycle", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim_owner", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "consumer_name IN ('analytics','alerts','notification_sink')",
            name="ck_event_deliveries_consumer",
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','succeeded','failed')",
            name="ck_event_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_event_deliveries_attempt_count"
        ),
        sa.CheckConstraint("retry_cycle >= 0", name="ck_event_deliveries_retry_cycle"),
        sa.CheckConstraint(
            "(claim_token IS NULL AND claim_owner IS NULL AND claim_expires_at IS NULL) OR "
            "(claim_token IS NOT NULL AND claim_owner IS NOT NULL AND claim_expires_at IS NOT NULL)",
            name="ck_event_deliveries_claim_fields",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["outbox_events.event_id"],
            name="fk_event_deliveries_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_deliveries"),
        sa.UniqueConstraint(
            "consumer_name", "event_id", name="uq_event_delivery_consumer_event"
        ),
    )
    op.create_index(
        "ix_event_deliveries_due",
        "event_deliveries",
        ["consumer_name", "status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_event_deliveries_expired_claim",
        "event_deliveries",
        ["claim_expires_at"],
        unique=False,
        postgresql_where=sa.text("claim_expires_at IS NOT NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_event_deliveries_no_delete BEFORE DELETE ON event_deliveries "
        "FOR EACH ROW EXECUTE FUNCTION reject_retained_event_history_mutation()"
    )

    op.create_table(
        "event_receipts",
        sa.Column("consumer_name", sa.String(length=40), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('processed','skipped')", name="ck_event_receipts_outcome"
        ),
        sa.ForeignKeyConstraint(
            ["consumer_name", "event_id"],
            ["event_deliveries.consumer_name", "event_deliveries.event_id"],
            name="fk_event_receipts_delivery",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("consumer_name", "event_id", name="pk_event_receipts"),
    )
    op.create_index(
        "ix_event_receipts_processed_at", "event_receipts", ["processed_at"]
    )
    op.execute(
        "CREATE TRIGGER trg_event_receipts_immutable BEFORE UPDATE OR DELETE ON event_receipts "
        "FOR EACH ROW EXECUTE FUNCTION reject_retained_event_history_mutation()"
    )

    op.create_table(
        "event_delivery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retry_cycle", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.CheckConstraint("retry_cycle >= 0", name="ck_event_attempts_retry_cycle"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_event_attempts_number"),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','skipped')",
            name="ck_event_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["event_deliveries.id"],
            name="fk_event_attempts_delivery",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_delivery_attempts"),
        sa.UniqueConstraint(
            "delivery_id",
            "retry_cycle",
            "attempt_number",
            name="uq_event_attempt_cycle_number",
        ),
    )
    op.create_index(
        "ix_event_attempts_delivery_started",
        "event_delivery_attempts",
        ["delivery_id", "started_at"],
        unique=False,
    )
    op.execute(
        "CREATE TRIGGER trg_event_attempts_no_delete BEFORE DELETE ON event_delivery_attempts "
        "FOR EACH ROW EXECUTE FUNCTION reject_retained_event_history_mutation()"
    )

    op.create_table(
        "event_delivery_replays",
        sa.Column("replay_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_cycle", sa.Integer(), nullable=False),
        sa.Column("to_cycle", sa.Integer(), nullable=False),
        sa.Column("operator", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("from_cycle >= 0", name="ck_event_replays_from_cycle"),
        sa.CheckConstraint(
            "to_cycle = from_cycle + 1", name="ck_event_replays_to_cycle"
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_event_replays_reason"),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["event_deliveries.id"],
            name="fk_event_replays_delivery",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("replay_id", name="pk_event_delivery_replays"),
        sa.UniqueConstraint("delivery_id", "to_cycle", name="uq_event_replay_cycle"),
    )
    op.create_index(
        "ix_event_replays_requested_at", "event_delivery_replays", ["requested_at"]
    )
    op.execute(
        "CREATE TRIGGER trg_event_replays_immutable BEFORE UPDATE OR DELETE ON event_delivery_replays "
        "FOR EACH ROW EXECUTE FUNCTION reject_retained_event_history_mutation()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    retained = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM outbox_events) "
            "OR EXISTS (SELECT 1 FROM event_deliveries) "
            "OR EXISTS (SELECT 1 FROM event_receipts) "
            "OR EXISTS (SELECT 1 FROM event_delivery_attempts) "
            "OR EXISTS (SELECT 1 FROM event_delivery_replays)"
        )
    )
    advanced_orders = bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM orders WHERE revision <> 1)")
    )
    if retained or advanced_orders:
        raise RuntimeError(
            "Cannot downgrade c61a0f3d9e42 while retained event/delivery history "
            "or advanced order revisions exist. Preserve these facts or restore a "
            "pre-migration backup only when discarding them is intended."
        )

    op.execute("DROP TRIGGER trg_outbox_events_immutable ON outbox_events")
    op.execute("DROP FUNCTION reject_outbox_event_mutation()")
    op.execute("DROP TRIGGER trg_event_replays_immutable ON event_delivery_replays")
    op.execute("DROP TRIGGER trg_event_attempts_no_delete ON event_delivery_attempts")
    op.execute("DROP TRIGGER trg_event_receipts_immutable ON event_receipts")
    op.execute("DROP TRIGGER trg_event_deliveries_no_delete ON event_deliveries")
    op.execute("DROP FUNCTION reject_retained_event_history_mutation()")
    op.drop_index("ix_event_replays_requested_at", table_name="event_delivery_replays")
    op.drop_table("event_delivery_replays")
    op.drop_index(
        "ix_event_attempts_delivery_started", table_name="event_delivery_attempts"
    )
    op.drop_table("event_delivery_attempts")
    op.drop_index("ix_event_receipts_processed_at", table_name="event_receipts")
    op.drop_table("event_receipts")
    op.drop_index("ix_event_deliveries_expired_claim", table_name="event_deliveries")
    op.drop_index("ix_event_deliveries_due", table_name="event_deliveries")
    op.drop_table("event_deliveries")
    op.drop_index("ix_outbox_events_organization_occurred", table_name="outbox_events")
    op.drop_index("ix_outbox_events_restaurant_occurred", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_constraint("ck_orders_revision", "orders", type_="check")
    op.drop_column("orders", "revision")
