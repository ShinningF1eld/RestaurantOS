"""Add identities, revocable sessions, refresh history and persistent rate limits."""

from alembic import op
import sqlalchemy as sa

revision = "72bd03a1f901"  # pragma: allowlist secret
down_revision = "4a1e9a2dc8e4"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
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
        sa.UniqueConstraint("email"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        sa.CheckConstraint(
            "email = lower(trim(email))", name="ck_users_email_normalized"
        ),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(32)),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "successor_id",
            sa.UUID(),
            sa.ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint("digest"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_auth_refresh_expiry"),
    )
    op.create_index(
        "ix_auth_refresh_tokens_session_id", "auth_refresh_tokens", ["session_id"]
    )
    op.create_index(
        "uq_auth_refresh_current",
        "auth_refresh_tokens",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )
    op.create_table(
        "auth_rate_limit_buckets",
        sa.Column("key_digest", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count > 0", name="ck_auth_rate_count"),
    )
    op.create_index(
        "ix_auth_rate_limit_buckets_expires_at",
        "auth_rate_limit_buckets",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("auth_rate_limit_buckets")
    op.drop_table("auth_refresh_tokens")
    op.drop_table("auth_sessions")
    op.drop_table("users")
