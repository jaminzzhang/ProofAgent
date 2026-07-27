"""Add durable fenced metadata workbook import jobs."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0017_metadata_import_jobs"
down_revision: str | None = "0016_hybrid_attempt_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hybrid_metadata_import_jobs",
        sa.Column("import_job_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "operation_id",
            sa.Text(),
            sa.ForeignKey("knowledge_source_operations.operation_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("original_ref_json", JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.Text()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.Text()),
        sa.Column("safe_reason", sa.Text()),
        sa.Column("result_import_id", sa.Text()),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["source_id", "document_id", "revision_id"],
            [
                "hybrid_ingestion_jobs.source_id",
                "hybrid_ingestion_jobs.document_id",
                "hybrid_ingestion_jobs.revision_id",
            ],
            ondelete="RESTRICT",
            name="hybrid_metadata_import_exact_revision",
        ),
        sa.CheckConstraint(
            "source_revision > 0 AND fencing_token >= 0",
            name="hybrid_metadata_import_positive_versions",
        ),
        sa.CheckConstraint(
            "state IN ('READY','CLAIMED','COMPLETED','FAILED')",
            name="hybrid_metadata_import_state",
        ),
        sa.CheckConstraint(
            "(state = 'CLAIMED') = "
            "(worker_id IS NOT NULL AND claimed_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="hybrid_metadata_import_claim",
        ),
        sa.CheckConstraint(
            "(state IN ('COMPLETED','FAILED')) = (completed_at IS NOT NULL)",
            name="hybrid_metadata_import_terminal",
        ),
        sa.CheckConstraint(
            "(state = 'COMPLETED') = (result_import_id IS NOT NULL)",
            name="hybrid_metadata_import_result",
        ),
        sa.CheckConstraint(
            "(state = 'FAILED') = "
            "(failure_code IS NOT NULL AND safe_reason IS NOT NULL)",
            name="hybrid_metadata_import_failure",
        ),
    )
    op.create_index(
        "hybrid_metadata_import_claim_idx",
        "hybrid_metadata_import_jobs",
        ["state", "created_at", "import_job_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
