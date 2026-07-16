"""Add tenant-global identity and security configuration authority."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_identity_security"
down_revision: str | None = "0002_hybrid_knowledge_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_JSON = postgresql.JSONB(astext_type=sa.Text())
_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "security_configuration_state",
        sa.Column("singleton", sa.Boolean(), primary_key=True),
        sa.Column(
            "permission_mapping_revision", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("egress_policy_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("permission_epoch", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", _UTC, nullable=False, server_default=_NOW),
        sa.CheckConstraint("singleton", name="security_configuration_singleton_true"),
        sa.CheckConstraint(
            "permission_mapping_revision >= 0",
            name="security_permission_mapping_revision_nonnegative",
        ),
        sa.CheckConstraint(
            "egress_policy_revision >= 0", name="security_egress_revision_nonnegative"
        ),
        sa.CheckConstraint(
            "permission_epoch >= 0", name="security_permission_epoch_nonnegative"
        ),
    )
    op.execute(
        "INSERT INTO security_configuration_state "
        "(singleton, permission_mapping_revision, egress_policy_revision, permission_epoch) "
        "VALUES (TRUE, 0, 0, 0)"
    )
    op.create_table(
        "permission_mapping_versions",
        sa.Column("version_id", _UUID, primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False, unique=True),
        sa.Column("mapping_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.CheckConstraint("revision > 0", name="permission_mapping_revision_positive"),
    )
    op.create_table(
        "active_permission_mapping",
        sa.Column("singleton", sa.Boolean(), primary_key=True),
        sa.Column(
            "version_id",
            _UUID,
            sa.ForeignKey("permission_mapping_versions.version_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("activated_at", _UTC, nullable=False, server_default=_NOW),
        sa.CheckConstraint("singleton", name="active_permission_mapping_singleton_true"),
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
