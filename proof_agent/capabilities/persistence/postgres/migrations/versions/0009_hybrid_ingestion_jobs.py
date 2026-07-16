"""Add the fenced PostgreSQL Hybrid PDF ingestion queue."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0009_hybrid_ingestion_jobs"
down_revision: str | None = "0008_run_receipt_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hybrid_ingestion_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey("knowledge_sources.source_id"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_identity", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("request_json", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("worker_id", sa.Text()),
        sa.Column("auto_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_auto_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("safe_reason", sa.Text()),
        sa.Column("failure_code", sa.Text()),
        sa.Column("failure_classification", sa.Text()),
        sa.Column("result_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('READY','CLAIMED','RETRY_SCHEDULED','COMPLETED',"
            "'REVIEW_REQUIRED','FAILED')",
            name="hybrid_ingestion_jobs_state",
        ),
        sa.CheckConstraint(
            "fencing_token >= 0 AND auto_retry_count >= 0 AND "
            "auto_retry_count <= max_auto_retries",
            name="hybrid_ingestion_jobs_counters",
        ),
        sa.CheckConstraint(
            "(state = 'READY' AND fencing_token = 0) OR "
            "(state <> 'READY' AND fencing_token > 0)",
            name="hybrid_ingestion_jobs_fence",
        ),
        sa.CheckConstraint(
            "(state = 'CLAIMED') = "
            "(worker_id IS NOT NULL AND claimed_at IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="hybrid_ingestion_jobs_claim",
        ),
        sa.CheckConstraint(
            "(state = 'COMPLETED') = (result_json IS NOT NULL)",
            name="hybrid_ingestion_jobs_result",
        ),
        sa.CheckConstraint(
            "(state IN ('COMPLETED','FAILED')) = (completed_at IS NOT NULL)",
            name="hybrid_ingestion_jobs_terminal",
        ),
        sa.UniqueConstraint("source_id", "document_id", "revision_id"),
    )
    op.create_index(
        "hybrid_ingestion_jobs_claim_idx",
        "hybrid_ingestion_jobs",
        ["state", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
