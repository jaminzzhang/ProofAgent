"""Link Hybrid ingestion work to the unified asynchronous operation authority."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0019_ingestion_operation_link"
down_revision: str | None = "0018_publication_preparation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hybrid_ingestion_jobs",
        sa.Column("operation_id", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            WITH latest_operation AS (
                SELECT DISTINCT ON (audit.target_id)
                       audit.target_id AS job_id,
                       audit.metadata_json ->> 'operation_id' AS operation_id
                  FROM audit_events AS audit
                  JOIN knowledge_source_operations AS operation
                    ON operation.operation_id = audit.metadata_json ->> 'operation_id'
                 WHERE audit.target_type = 'hybrid_ingestion_job'
                   AND audit.event_type IN (
                       'hybrid_pdf.upload_document.admitted',
                       'hybrid_pdf.replace_document.admitted',
                       'hybrid_ingestion.retry_ingestion.admitted'
                   )
                 ORDER BY audit.target_id, audit.occurred_at DESC, audit.audit_id DESC
            )
            UPDATE hybrid_ingestion_jobs AS job
               SET operation_id = latest.operation_id
              FROM latest_operation AS latest
             WHERE job.operation_id IS NULL
               AND latest.job_id = job.job_id::text
            """
        )
    )
    op.create_foreign_key(
        "hybrid_ingestion_job_operation",
        "hybrid_ingestion_jobs",
        "knowledge_source_operations",
        ["operation_id"],
        ["operation_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "hybrid_ingestion_job_operation_unique",
        "hybrid_ingestion_jobs",
        ["operation_id"],
    )
    op.execute(
        sa.text(
            """
            UPDATE knowledge_source_operations AS operation
               SET status = CASE job.state
                       WHEN 'CLAIMED' THEN 'running'
                       WHEN 'CANCEL_REQUESTED' THEN 'cancel_requested'
                       WHEN 'REVIEW_REQUIRED' THEN 'succeeded'
                       WHEN 'COMPLETED' THEN 'succeeded'
                       WHEN 'FAILED' THEN 'failed'
                       WHEN 'CANCELLED' THEN 'cancelled'
                       ELSE 'queued'
                   END,
                   stage = CASE job.state
                       WHEN 'CLAIMED' THEN 'ingestion_processing'
                       WHEN 'RETRY_SCHEDULED' THEN 'ingestion_retry_scheduled'
                       WHEN 'CANCEL_REQUESTED' THEN 'ingestion_cancellation_requested'
                       WHEN 'REVIEW_REQUIRED' THEN 'ingestion_review_required'
                       WHEN 'COMPLETED' THEN 'ingestion_completed'
                       WHEN 'FAILED' THEN 'ingestion_failed'
                       WHEN 'CANCELLED' THEN 'ingestion_cancelled'
                       ELSE 'ingestion_queued'
                   END,
                   operation_json = operation.operation_json || jsonb_build_object(
                       'status', CASE job.state
                           WHEN 'CLAIMED' THEN 'running'
                           WHEN 'CANCEL_REQUESTED' THEN 'cancel_requested'
                           WHEN 'REVIEW_REQUIRED' THEN 'succeeded'
                           WHEN 'COMPLETED' THEN 'succeeded'
                           WHEN 'FAILED' THEN 'failed'
                           WHEN 'CANCELLED' THEN 'cancelled'
                           ELSE 'queued'
                       END,
                       'stage', CASE job.state
                           WHEN 'CLAIMED' THEN 'ingestion_processing'
                           WHEN 'RETRY_SCHEDULED' THEN 'ingestion_retry_scheduled'
                           WHEN 'CANCEL_REQUESTED' THEN 'ingestion_cancellation_requested'
                           WHEN 'REVIEW_REQUIRED' THEN 'ingestion_review_required'
                           WHEN 'COMPLETED' THEN 'ingestion_completed'
                           WHEN 'FAILED' THEN 'ingestion_failed'
                           WHEN 'CANCELLED' THEN 'ingestion_cancelled'
                           ELSE 'ingestion_queued'
                       END,
                       'outcome_code', CASE job.state
                           WHEN 'REVIEW_REQUIRED' THEN 'hybrid_ingestion_review_required'
                           WHEN 'COMPLETED' THEN 'hybrid_ingestion_completed'
                           WHEN 'FAILED' THEN CASE job.failure_code
                               WHEN 'PA_HYBRID_WORKER_INTEGRITY'
                                   THEN 'hybrid_ingestion_integrity_failed'
                               WHEN 'PA_HYBRID_RETRY_EXHAUSTED'
                                   THEN 'hybrid_ingestion_retries_exhausted'
                               ELSE 'hybrid_ingestion_failed'
                           END
                           WHEN 'CANCELLED' THEN 'hybrid_ingestion_cancelled'
                           ELSE NULL
                       END,
                       'outcome_detail', CASE job.state
                           WHEN 'REVIEW_REQUIRED' THEN job.safe_reason
                           WHEN 'COMPLETED' THEN 'Hybrid document ingestion completed.'
                           WHEN 'FAILED' THEN job.safe_reason
                           WHEN 'CANCELLED' THEN 'Hybrid document ingestion was cancelled.'
                           ELSE NULL
                       END,
                       'updated_at', job.updated_at,
                       'completed_at', CASE
                           WHEN job.state IN (
                               'REVIEW_REQUIRED', 'COMPLETED', 'FAILED', 'CANCELLED'
                           ) THEN job.updated_at
                           ELSE NULL
                       END
                   ),
                   updated_at = job.updated_at,
                   completed_at = CASE
                       WHEN job.state IN (
                           'REVIEW_REQUIRED', 'COMPLETED', 'FAILED', 'CANCELLED'
                       ) THEN job.updated_at
                       ELSE NULL
                   END
              FROM hybrid_ingestion_jobs AS job
             WHERE operation.operation_id = job.operation_id
               AND operation.status IN ('queued', 'running', 'cancel_requested')
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
