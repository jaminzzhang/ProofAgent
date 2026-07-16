"""Add versioned exact-origin egress policy authority."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_egress_policy"
down_revision: str | None = "0004_oidc_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_JSON = postgresql.JSONB(astext_type=sa.Text())
_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "egress_policy_versions",
        sa.Column("version_id", _UUID, primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False, unique=True),
        sa.Column("policy_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.CheckConstraint("revision > 0", name="egress_policy_revision_positive"),
    )
    op.create_table(
        "active_egress_policy",
        sa.Column("singleton", sa.Boolean(), primary_key=True),
        sa.Column(
            "version_id",
            _UUID,
            sa.ForeignKey("egress_policy_versions.version_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("activated_at", _UTC, nullable=False, server_default=_NOW),
        sa.CheckConstraint("singleton", name="active_egress_policy_singleton_true"),
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
