"""Add the finalized Release Registry authority."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0013_release_registry"
down_revision: str | None = "0012_model_credential"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_JSON = postgresql.JSONB(astext_type=sa.Text())
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "release_registry",
        sa.Column("release_id", sa.Text(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("candidate_binding_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "release_manifest_object_id",
            _UUID,
            sa.ForeignKey("artifact_objects.object_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "bundle_index_object_id",
            _UUID,
            sa.ForeignKey("artifact_objects.object_id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column(
            "detached_attestation_object_id",
            _UUID,
            sa.ForeignKey("artifact_objects.object_id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("trust_identity_json", _JSON),
        sa.Column("registry_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("finalized_at", _UTC),
        sa.CheckConstraint(
            "state IN ('PREPARING','FINALIZED')",
            name="release_registry_state_known",
        ),
        sa.CheckConstraint(
            "candidate_binding_sha256 ~ '^[0-9a-f]{64}$'",
            name="release_registry_candidate_digest",
        ),
        sa.CheckConstraint(
            "(state = 'PREPARING' AND bundle_index_object_id IS NULL "
            "AND detached_attestation_object_id IS NULL AND trust_identity_json IS NULL "
            "AND finalized_at IS NULL) OR "
            "(state = 'FINALIZED' AND bundle_index_object_id IS NOT NULL "
            "AND detached_attestation_object_id IS NOT NULL "
            "AND trust_identity_json IS NOT NULL AND finalized_at IS NOT NULL)",
            name="release_registry_finalization_shape",
        ),
        sa.CheckConstraint(
            "finalized_at IS NULL OR finalized_at >= created_at",
            name="release_registry_finalization_time",
        ),
    )
    op.create_index(
        "release_registry_created_idx",
        "release_registry",
        ["created_at", "release_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
