"""Add inventory state revisions and durable low-stock episode facts."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8f34c2a91de"
down_revision: Union[str, None] = "c61a0f3d9e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows receive a baseline watermark only. This does not assert that
    # any historical low-stock episode began at the migration time.
    op.add_column(
        "inventory_ingredients",
        sa.Column(
            "state_revision",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_inventory_state_revision",
        "inventory_ingredients",
        "state_revision >= 1",
    )

    op.create_table(
        "inventory_low_stock_episodes",
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Scope and source IDs are immutable snapshots, deliberately without
        # cascading foreign keys so ingredient deletion cannot erase history.
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=10), nullable=False),
        sa.Column("opening_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("opening_reorder_threshold", sa.Numeric(12, 3), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opening_revision", sa.Integer(), nullable=False),
        sa.Column("opening_source", sa.String(length=40), nullable=False),
        sa.Column("opening_actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("opening_order_id", sa.Integer()),
        sa.Column(
            "notification_suppressed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_reason", sa.String(length=32)),
        sa.Column("closing_quantity", sa.Numeric(12, 3)),
        sa.Column("closing_reorder_threshold", sa.Numeric(12, 3)),
        sa.Column("closing_is_active", sa.Boolean()),
        sa.Column("resolution_revision", sa.Integer()),
        sa.Column("resolution_source", sa.String(length=40)),
        sa.Column("resolution_actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("resolution_order_id", sa.Integer()),
        sa.CheckConstraint(
            "restaurant_id > 0", name="ck_inventory_episode_restaurant"
        ),
        sa.CheckConstraint(
            "ingredient_id > 0", name="ck_inventory_episode_ingredient"
        ),
        sa.CheckConstraint(
            "unit IN ('g', 'ml', 'piece')", name="ck_inventory_episode_unit"
        ),
        sa.CheckConstraint(
            "length(trim(ingredient_name)) > 0", name="ck_inventory_episode_name"
        ),
        sa.CheckConstraint(
            "opening_quantity >= 0 AND opening_quantity <= 999999999.999",
            name="ck_inventory_episode_opening_quantity",
        ),
        sa.CheckConstraint(
            "opening_reorder_threshold >= 0 AND "
            "opening_reorder_threshold <= 999999999.999",
            name="ck_inventory_episode_opening_threshold",
        ),
        sa.CheckConstraint(
            "opening_quantity <= opening_reorder_threshold",
            name="ck_inventory_episode_opening_low",
        ),
        sa.CheckConstraint(
            "opening_revision >= 1", name="ck_inventory_episode_revision"
        ),
        sa.CheckConstraint(
            "opening_source IN ('ingredient_creation','ingredient_update',"
            "'stock_command','order_acceptance','maintenance_initialization')",
            name="ck_inventory_episode_opening_source",
        ),
        sa.CheckConstraint(
            "(opening_source = 'order_acceptance' AND opening_order_id IS NOT NULL) OR "
            "(opening_source <> 'order_acceptance' AND opening_order_id IS NULL)",
            name="ck_inventory_episode_opening_order",
        ),
        sa.CheckConstraint(
            "NOT notification_suppressed OR "
            "opening_source = 'maintenance_initialization'",
            name="ck_inventory_episode_suppression_source",
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL AND resolution_reason IS NULL AND "
            "closing_quantity IS NULL AND closing_reorder_threshold IS NULL AND "
            "closing_is_active IS NULL AND resolution_revision IS NULL AND "
            "resolution_source IS NULL AND resolution_actor_user_id IS NULL AND "
            "resolution_order_id IS NULL) OR "
            "(resolved_at IS NOT NULL AND resolution_reason IS NOT NULL AND "
            "closing_quantity IS NOT NULL AND closing_reorder_threshold IS NOT NULL AND "
            "closing_is_active IS NOT NULL AND resolution_revision IS NOT NULL AND "
            "resolution_source IS NOT NULL)",
            name="ck_inventory_episode_resolution_complete",
        ),
        sa.CheckConstraint(
            "resolution_reason IS NULL OR resolution_reason IN "
            "('stock_recovered','threshold_changed','archived')",
            name="ck_inventory_episode_resolution_reason",
        ),
        sa.CheckConstraint(
            "resolution_source IS NULL OR resolution_source IN "
            "('ingredient_creation','ingredient_update','stock_command',"
            "'order_acceptance','maintenance_initialization')",
            name="ck_inventory_episode_resolution_source",
        ),
        sa.CheckConstraint(
            "(resolution_source = 'order_acceptance' AND resolution_order_id IS NOT NULL) OR "
            "(resolution_source IS NULL AND resolution_order_id IS NULL) OR "
            "(resolution_source <> 'order_acceptance' AND resolution_order_id IS NULL)",
            name="ck_inventory_episode_resolution_order",
        ),
        sa.CheckConstraint(
            "resolution_revision IS NULL OR resolution_revision > opening_revision",
            name="ck_inventory_episode_resolution_revision",
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR NOT closing_is_active OR "
            "closing_quantity > closing_reorder_threshold",
            name="ck_inventory_episode_closing_not_low",
        ),
        sa.PrimaryKeyConstraint("episode_id", name="pk_inventory_low_stock_episodes"),
    )
    op.create_index(
        "uq_inventory_open_episode_per_ingredient",
        "inventory_low_stock_episodes",
        ["ingredient_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "ix_inventory_episode_org_restaurant_opened",
        "inventory_low_stock_episodes",
        ["organization_id", "restaurant_id", "opened_at"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_episode_ingredient_opened",
        "inventory_low_stock_episodes",
        ["ingredient_id", "opened_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION guard_inventory_low_stock_episode_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Inventory low-stock episode facts are retained';
            END IF;
            IF ROW(
                NEW.episode_id, NEW.organization_id, NEW.restaurant_id,
                NEW.ingredient_id, NEW.ingredient_name, NEW.unit,
                NEW.opening_quantity, NEW.opening_reorder_threshold,
                NEW.opened_at, NEW.opening_revision, NEW.opening_source,
                NEW.opening_actor_user_id, NEW.opening_order_id,
                NEW.notification_suppressed
            ) IS DISTINCT FROM ROW(
                OLD.episode_id, OLD.organization_id, OLD.restaurant_id,
                OLD.ingredient_id, OLD.ingredient_name, OLD.unit,
                OLD.opening_quantity, OLD.opening_reorder_threshold,
                OLD.opened_at, OLD.opening_revision, OLD.opening_source,
                OLD.opening_actor_user_id, OLD.opening_order_id,
                OLD.notification_suppressed
            ) THEN
                RAISE EXCEPTION 'Inventory low-stock episode opening facts are immutable';
            END IF;
            IF OLD.resolved_at IS NOT NULL THEN
                RAISE EXCEPTION 'Resolved inventory low-stock episode facts are immutable';
            END IF;
            IF NEW.resolved_at IS NULL THEN
                RAISE EXCEPTION 'Episode updates must record its resolution';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER tr_inventory_low_stock_episode_facts
        BEFORE UPDATE OR DELETE ON inventory_low_stock_episodes
        FOR EACH ROW EXECUTE FUNCTION guard_inventory_low_stock_episode_facts()
        """
    )


def downgrade() -> None:
    retained = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM inventory_low_stock_episodes)")
    )
    if retained:
        raise RuntimeError(
            "Cannot downgrade inventory episode facts while retained episodes exist"
        )

    op.execute(
        "DROP TRIGGER tr_inventory_low_stock_episode_facts "
        "ON inventory_low_stock_episodes"
    )
    op.execute("DROP FUNCTION guard_inventory_low_stock_episode_facts()")
    op.drop_index(
        "ix_inventory_episode_ingredient_opened",
        table_name="inventory_low_stock_episodes",
    )
    op.drop_index(
        "ix_inventory_episode_org_restaurant_opened",
        table_name="inventory_low_stock_episodes",
    )
    op.drop_index(
        "uq_inventory_open_episode_per_ingredient",
        table_name="inventory_low_stock_episodes",
    )
    op.drop_table("inventory_low_stock_episodes")
    op.drop_constraint(
        "ck_inventory_state_revision", "inventory_ingredients", type_="check"
    )
    op.drop_column("inventory_ingredients", "state_revision")
