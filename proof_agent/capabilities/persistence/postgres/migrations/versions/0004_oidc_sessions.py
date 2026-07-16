"""Add one-time OIDC transactions and backend-managed operator sessions."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_oidc_sessions"
down_revision: str | None = "0003_identity_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_UUID = postgresql.UUID(as_uuid=True)
_JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "oidc_login_attempts",
        sa.Column("state_sha256", sa.String(64), primary_key=True),
        sa.Column("nonce_envelope", postgresql.BYTEA(), nullable=False),
        sa.Column("pkce_verifier_envelope", postgresql.BYTEA(), nullable=False),
        sa.Column("envelope_key_version", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
        sa.Column("expires_at", _UTC, nullable=False),
        sa.Column("consumed_at", _UTC),
        sa.CheckConstraint(
            "state_sha256 ~ '^[0-9a-f]{64}$'", name="oidc_login_state_digest_valid"
        ),
        sa.CheckConstraint("expires_at > created_at", name="oidc_login_expiry_after_create"),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="oidc_login_consumed_after_create",
        ),
    )
    op.create_index("oidc_login_expiry_idx", "oidc_login_attempts", ["expires_at"])
    op.create_table(
        "operator_sessions",
        sa.Column("session_id", _UUID, primary_key=True),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("session_token_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("principal_json", _JSON, nullable=False),
        sa.Column("provider_token_envelope", postgresql.BYTEA(), nullable=False),
        sa.Column("envelope_key_version", sa.Text(), nullable=False),
        sa.Column(
            "permission_mapping_version_id",
            _UUID,
            sa.ForeignKey("permission_mapping_versions.version_id", ondelete="RESTRICT"),
        ),
        sa.Column("permission_epoch", sa.BigInteger(), nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
        sa.Column("absolute_expires_at", _UTC, nullable=False),
        sa.Column("idle_expires_at", _UTC, nullable=False),
        sa.Column("claims_verified_at", _UTC, nullable=False),
        sa.Column("revoked_at", _UTC),
        sa.CheckConstraint("session_version > 0", name="operator_session_version_positive"),
        sa.CheckConstraint(
            "session_token_sha256 ~ '^[0-9a-f]{64}$'",
            name="operator_session_token_digest_valid",
        ),
        sa.CheckConstraint(
            "permission_epoch >= 0", name="operator_session_permission_epoch_nonnegative"
        ),
        sa.CheckConstraint(
            "absolute_expires_at > created_at", name="operator_session_absolute_expiry"
        ),
        sa.CheckConstraint("idle_expires_at > created_at", name="operator_session_idle_expiry"),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at", name="operator_session_idle_bounded"
        ),
    )
    op.create_index(
        "operator_sessions_active_expiry_idx",
        "operator_sessions",
        ["absolute_expires_at", "idle_expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
