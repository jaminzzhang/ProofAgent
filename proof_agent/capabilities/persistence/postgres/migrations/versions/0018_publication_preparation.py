"""Add durable fenced publication preparation jobs."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0018_publication_preparation"
down_revision: str | None = "0017_metadata_import_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hybrid_publication_preparation_jobs",
        sa.Column("preparation_job_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "operation_id",
            sa.Text(),
            sa.ForeignKey("knowledge_source_operations.operation_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("validation_id", sa.Text(), nullable=False, unique=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("source_draft_version_id", sa.Text(), nullable=False),
        sa.Column("smoke_query", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.Text()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("prepared_commit_json", JSONB()),
        sa.Column("failure_code", sa.Text()),
        sa.Column("safe_reason", sa.Text()),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "source_revision > 0 AND fencing_token >= 0",
            name="hybrid_publication_preparation_positive_versions",
        ),
        sa.CheckConstraint(
            "state IN ('READY','CLAIMED','PREPARED','FAILED')",
            name="hybrid_publication_preparation_state",
        ),
        sa.CheckConstraint(
            "(state = 'CLAIMED') = "
            "(worker_id IS NOT NULL AND claimed_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="hybrid_publication_preparation_claim",
        ),
        sa.CheckConstraint(
            "(state IN ('PREPARED','FAILED')) = (completed_at IS NOT NULL)",
            name="hybrid_publication_preparation_terminal",
        ),
        sa.CheckConstraint(
            "(state = 'PREPARED') = (prepared_commit_json IS NOT NULL)",
            name="hybrid_publication_preparation_result",
        ),
        sa.CheckConstraint(
            "(state = 'FAILED') = "
            "(failure_code IS NOT NULL AND safe_reason IS NOT NULL)",
            name="hybrid_publication_preparation_failure",
        ),
    )
    op.create_index(
        "hybrid_publication_preparation_claim_idx",
        "hybrid_publication_preparation_jobs",
        ["state", "created_at", "preparation_job_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
