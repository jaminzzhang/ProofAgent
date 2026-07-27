"""Add durable Knowledge Source API V1 operations."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0014_knowledge_source_v1"
down_revision: str | None = "0013_release_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "knowledge_source_operations",
        sa.Column("operation_id", sa.Text(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey("knowledge_sources.source_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("operation_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
        sa.Column("updated_at", _UTC, nullable=False),
        sa.Column("completed_at", _UTC),
        sa.CheckConstraint(
            "status IN ('queued','running','cancel_requested','succeeded','failed','cancelled')",
            name="knowledge_source_operation_status_known",
        ),
        sa.CheckConstraint(
            "source_revision >= 1",
            name="knowledge_source_operation_revision_positive",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="knowledge_source_operation_update_time",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded','failed','cancelled') AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded','failed','cancelled') AND completed_at IS NULL)",
            name="knowledge_source_operation_completion_shape",
        ),
    )
    op.create_index(
        "knowledge_source_operations_source_idx",
        "knowledge_source_operations",
        ["source_id", "created_at", "operation_id"],
    )
    op.create_table(
        "knowledge_source_idempotency",
        sa.Column("operator_subject", sa.Text(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey("knowledge_sources.source_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("command", sa.Text(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column(
            "operation_id",
            sa.Text(),
            sa.ForeignKey(
                "knowledge_source_operations.operation_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column("outcome_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False),
        sa.Column("expires_at", _UTC, nullable=False),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name="knowledge_source_idempotency_digest",
        ),
        sa.CheckConstraint(
            "expires_at >= created_at",
            name="knowledge_source_idempotency_expiry",
        ),
    )
    op.create_index(
        "knowledge_source_idempotency_expiry_idx",
        "knowledge_source_idempotency",
        ["expires_at"],
    )
    op.create_table(
        "knowledge_ingestion_attempts",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hybrid_ingestion_jobs.job_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("initiation", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.Text()),
        sa.Column("attempt_json", _JSON, nullable=False),
        sa.Column("started_at", _UTC, nullable=False),
        sa.Column("updated_at", _UTC, nullable=False),
        sa.Column("completed_at", _UTC),
        sa.UniqueConstraint(
            "job_id",
            "attempt_number",
            name="knowledge_ingestion_attempt_ordinal",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1 AND fencing_token >= 1",
            name="knowledge_ingestion_attempt_counters",
        ),
        sa.CheckConstraint(
            "initiation IN ('automatic','manual')",
            name="knowledge_ingestion_attempt_initiation",
        ),
        sa.CheckConstraint(
            "state IN ('running','succeeded','failed','cancelled')",
            name="knowledge_ingestion_attempt_state",
        ),
        sa.CheckConstraint(
            "(state = 'running') = (completed_at IS NULL)",
            name="knowledge_ingestion_attempt_completion",
        ),
        sa.CheckConstraint(
            "updated_at >= started_at",
            name="knowledge_ingestion_attempt_update_time",
        ),
    )
    op.create_index(
        "knowledge_ingestion_attempts_job_idx",
        "knowledge_ingestion_attempts",
        ["job_id", "attempt_number"],
    )
    op.create_table(
        "prepared_knowledge_publications",
        sa.Column("validation_id", sa.Text(), primary_key=True),
        sa.Column(
            "operation_id",
            sa.Text(),
            sa.ForeignKey(
                "knowledge_source_operations.operation_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column("attempt_id", sa.Text(), nullable=False, unique=True),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey("knowledge_sources.source_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_draft_version_id", sa.Text(), nullable=False),
        sa.Column("candidate_digest", sa.String(64), nullable=False),
        sa.Column("generation_id", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("staged_projection_id", sa.Text(), nullable=False),
        sa.Column("attestation_sha256", sa.String(64), nullable=False),
        sa.Column("smoke_result_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("prepared_json", _JSON, nullable=False),
        sa.Column("prepared_at", _UTC, nullable=False),
        sa.Column("consumed_at", _UTC),
        sa.UniqueConstraint(
            "source_id",
            "fencing_token",
            name="prepared_knowledge_publication_source_fence",
        ),
        sa.CheckConstraint(
            "fencing_token >= 1",
            name="prepared_knowledge_publication_fence_positive",
        ),
        sa.CheckConstraint(
            "candidate_digest ~ '^[0-9a-f]{64}$' AND "
            "manifest_sha256 ~ '^[0-9a-f]{64}$' AND "
            "attestation_sha256 ~ '^[0-9a-f]{64}$' AND "
            "smoke_result_sha256 ~ '^[0-9a-f]{64}$'",
            name="prepared_knowledge_publication_digests",
        ),
        sa.CheckConstraint(
            "state IN ('prepared','consumed','invalidated')",
            name="prepared_knowledge_publication_state",
        ),
        sa.CheckConstraint(
            "(state = 'consumed') = (consumed_at IS NOT NULL)",
            name="prepared_knowledge_publication_consumption",
        ),
    )
    op.create_index(
        "prepared_knowledge_publications_source_idx",
        "prepared_knowledge_publications",
        ["source_id", "prepared_at", "validation_id"],
    )
    op.add_column(
        "hybrid_ingestion_jobs",
        sa.Column("cancel_requested_at", _UTC),
    )
    op.add_column(
        "hybrid_ingestion_jobs",
        sa.Column("cancel_requested_by", sa.Text()),
    )
    op.add_column(
        "hybrid_ingestion_jobs",
        sa.Column("cancelled_at", _UTC),
    )
    op.drop_constraint(
        "hybrid_ingestion_jobs_state",
        "hybrid_ingestion_jobs",
        type_="check",
    )
    op.drop_constraint(
        "hybrid_ingestion_jobs_fence",
        "hybrid_ingestion_jobs",
        type_="check",
    )
    op.drop_constraint(
        "hybrid_ingestion_jobs_claim",
        "hybrid_ingestion_jobs",
        type_="check",
    )
    op.drop_constraint(
        "hybrid_ingestion_jobs_terminal",
        "hybrid_ingestion_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "hybrid_ingestion_jobs_state",
        "hybrid_ingestion_jobs",
        "state IN ('READY','CLAIMED','RETRY_SCHEDULED','CANCEL_REQUESTED',"
        "'COMPLETED','REVIEW_REQUIRED','FAILED','CANCELLED')",
    )
    op.create_check_constraint(
        "hybrid_ingestion_jobs_fence",
        "hybrid_ingestion_jobs",
        "(state = 'READY' AND fencing_token = 0) OR "
        "(state = 'CANCELLED' AND fencing_token >= 0) OR "
        "(state NOT IN ('READY','CANCELLED') AND fencing_token > 0)",
    )
    op.create_check_constraint(
        "hybrid_ingestion_jobs_claim",
        "hybrid_ingestion_jobs",
        "(state IN ('CLAIMED','CANCEL_REQUESTED')) = "
        "(worker_id IS NOT NULL AND claimed_at IS NOT NULL "
        "AND lease_expires_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "hybrid_ingestion_jobs_terminal",
        "hybrid_ingestion_jobs",
        "(state IN ('COMPLETED','FAILED','CANCELLED')) = "
        "(completed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "hybrid_ingestion_jobs_cancellation",
        "hybrid_ingestion_jobs",
        "(state IN ('CANCEL_REQUESTED','CANCELLED')) = "
        "(cancel_requested_at IS NOT NULL AND cancel_requested_by IS NOT NULL)",
    )
    op.create_check_constraint(
        "hybrid_ingestion_jobs_cancelled",
        "hybrid_ingestion_jobs",
        "(state = 'CANCELLED') = (cancelled_at IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
