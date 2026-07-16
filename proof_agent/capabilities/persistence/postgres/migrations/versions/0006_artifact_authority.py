"""Add immutable artifact references, manifests, and owner visibility."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006_artifact_authority"
down_revision: str | None = "0005_egress_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_JSON = postgresql.JSONB(astext_type=sa.Text())
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "artifact_objects",
        sa.Column("object_id", _UUID, primary_key=True),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("display_filename", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("ref_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
        sa.Column("expires_at", _UTC),
        sa.Column("corrupt_at", _UTC),
        sa.UniqueConstraint(
            "bucket",
            "object_key",
            "version_id",
            name="artifact_objects_exact_version_unique",
        ),
        sa.CheckConstraint("size_bytes > 0", name="artifact_objects_size_positive"),
        sa.CheckConstraint(
            "state IN ('verified', 'corrupt')",
            name="artifact_objects_state_known",
        ),
    )
    op.create_index(
        "artifact_objects_owner_idx",
        "artifact_objects",
        ["owner_type", "owner_id"],
    )
    op.create_index(
        "artifact_objects_expiry_idx",
        "artifact_objects",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_table(
        "artifact_manifests",
        sa.Column("manifest_id", _UUID, primary_key=True),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column(
            "manifest_object_id",
            _UUID,
            sa.ForeignKey("artifact_objects.object_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("manifest_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
    )
    op.create_table(
        "artifact_manifest_members",
        sa.Column(
            "manifest_id",
            _UUID,
            sa.ForeignKey("artifact_manifests.manifest_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("member_id", sa.Text(), primary_key=True),
        sa.Column(
            "object_id",
            _UUID,
            sa.ForeignKey("artifact_objects.object_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "manifest_id",
            "object_id",
            name="artifact_manifest_exact_member_unique",
        ),
    )
    op.create_table(
        "artifact_owner_bindings",
        sa.Column("owner_type", sa.Text(), primary_key=True),
        sa.Column("owner_id", sa.Text(), primary_key=True),
        sa.Column(
            "manifest_id",
            _UUID,
            sa.ForeignKey("artifact_manifests.manifest_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("visible_at", _UTC),
        sa.Column("result_available", sa.Boolean(), nullable=False),
        sa.Column("updated_at", _UTC, nullable=False),
        sa.CheckConstraint(
            "visibility IN ('visible', 'expired', 'corrupt')",
            name="artifact_owner_visibility_known",
        ),
        sa.CheckConstraint(
            "(visibility = 'visible' AND visible_at IS NOT NULL AND result_available) OR "
            "(visibility <> 'visible' AND NOT result_available)",
            name="artifact_owner_visibility_consistent",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
