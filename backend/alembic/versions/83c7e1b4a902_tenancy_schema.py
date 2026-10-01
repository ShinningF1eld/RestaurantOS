"""Expand tenancy schema and backfill legacy restaurants without enforcing access.

Organization ownership and the restaurant NOT NULL constraint are deferred until
services can supply verified tenant scope. No account is automatically promoted.
"""

from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "83c7e1b4a902"  # pragma: allowlist secret
down_revision = "72bd03a1f901"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        *_timestamps(),
        sa.UniqueConstraint("slug"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_organizations_name"),
        sa.CheckConstraint(
            "slug = lower(trim(slug)) AND length(slug) > 0",
            name="ck_organizations_slug",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name="ck_organizations_status"
        ),
    )
    op.add_column("restaurants", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_restaurants_organization",
        "restaurants",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_restaurants_organization_id", "restaurants", ["organization_id"]
    )
    op.create_unique_constraint(
        "uq_restaurants_id_org", "restaurants", ["id", "organization_id"]
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        *_timestamps(),
        sa.UniqueConstraint(
            "user_id", "organization_id", name="uq_memberships_user_org"
        ),
        sa.UniqueConstraint("id", "organization_id", name="uq_memberships_id_org"),
        sa.CheckConstraint(
            "role IN ('OWNER', 'MANAGER', 'EMPLOYEE')", name="ck_memberships_role"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')", name="ck_memberships_status"
        ),
    )
    op.create_index(
        "ix_memberships_org_status_role",
        "memberships",
        ["organization_id", "status", "role"],
    )
    op.create_table(
        "restaurant_assignments",
        sa.Column("membership_id", sa.UUID(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_assignments_membership_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_assignments_restaurant_org",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_assignments_org_restaurant",
        "restaurant_assignments",
        ["organization_id", "restaurant_id"],
    )
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column(
            "actor_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column(
            "changes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id", "organization_id"],
            ["restaurants.id", "restaurants.organization_id"],
            name="fk_audit_entries_restaurant_org",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("length(trim(action)) > 0", name="ck_audit_entries_action"),
        sa.CheckConstraint(
            "length(trim(resource_type)) > 0 AND length(trim(resource_id)) > 0",
            name="ck_audit_entries_resource",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(changes) = 'object'", name="ck_audit_entries_changes_object"
        ),
    )
    op.create_index(
        "ix_audit_entries_org_occurred",
        "audit_entries",
        ["organization_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_entries_restaurant_id", "audit_entries", ["restaurant_id"]
    )

    # Stable migration-owned development tenant; user ownership is explicit later.
    organizations = sa.table(
        "organizations",
        sa.column("id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
    )
    development_id = UUID("00000000-0000-4000-8000-000000000004")
    op.bulk_insert(
        organizations,
        [
            {
                "id": development_id,
                "name": "RestaurantOS Development Workspace",
                "slug": "restaurantos-development",
            }
        ],
    )
    restaurants = sa.table("restaurants", sa.column("organization_id", sa.UUID()))
    op.execute(
        restaurants.update()
        .where(restaurants.c.organization_id.is_(None))
        .values(organization_id=development_id)
    )


def downgrade() -> None:
    # This removes tenant assignments/audit data. Operational and auth rows survive.
    op.drop_table("audit_entries")
    op.drop_table("restaurant_assignments")
    op.drop_table("memberships")
    op.drop_constraint("uq_restaurants_id_org", "restaurants", type_="unique")
    op.drop_index("ix_restaurants_organization_id", table_name="restaurants")
    op.drop_constraint("fk_restaurants_organization", "restaurants", type_="foreignkey")
    op.drop_column("restaurants", "organization_id")
    op.drop_table("organizations")
