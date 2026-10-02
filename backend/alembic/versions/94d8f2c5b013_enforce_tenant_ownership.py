"""Require restaurant tenancy and enforce one organization per user."""

from alembic import op
import sqlalchemy as sa

revision = "94d8f2c5b013"  # pragma: allowlist secret
down_revision = "83c7e1b4a902"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT user_id FROM memberships GROUP BY user_id "
            "HAVING count(*) > 1) duplicate_users"
        )
    ):
        raise RuntimeError("Resolve users with multiple memberships before upgrading")
    op.execute(
        sa.text(
            "UPDATE restaurants SET organization_id = "
            "(SELECT id FROM organizations WHERE slug='restaurantos-development') "
            "WHERE organization_id IS NULL"
        )
    )
    if connection.scalar(
        sa.text("SELECT count(*) FROM restaurants WHERE organization_id IS NULL")
    ):
        raise RuntimeError("Backfill every restaurant before enforcing tenancy")
    # Keep UUID storage IDs and expose a stable, human-readable organization number.
    op.add_column("organizations", sa.Column("number", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "WITH numbered AS (SELECT id, row_number() OVER "
            "(ORDER BY (slug='restaurantos-development') DESC, created_at, id) AS n "
            "FROM organizations) UPDATE organizations g SET number=n.n "
            "FROM numbered n WHERE g.id=n.id"
        )
    )
    op.alter_column(
        "organizations",
        "number",
        nullable=False,
        server_default=sa.Identity(),
        existing_server_default=None,
    )
    op.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence('organizations','number'), "
            "coalesce((SELECT max(number) FROM organizations),1), "
            "EXISTS(SELECT 1 FROM organizations))"
        )
    )
    op.create_unique_constraint("organizations_number_key", "organizations", ["number"])
    op.drop_constraint("uq_memberships_user_org", "memberships", type_="unique")
    op.create_unique_constraint("uq_memberships_user", "memberships", ["user_id"])
    op.alter_column("restaurants", "organization_id", nullable=False)


def downgrade() -> None:
    op.alter_column("restaurants", "organization_id", nullable=True)
    op.drop_constraint("uq_memberships_user", "memberships", type_="unique")
    op.create_unique_constraint(
        "uq_memberships_user_org", "memberships", ["user_id", "organization_id"]
    )
    op.drop_column("organizations", "number")
