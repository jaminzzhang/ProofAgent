"""Add Workbook V2 export, preview, and apply authority."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021_metadata_workbook_v2"
down_revision: str | None = "0020_metadata_review_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "hybrid_metadata_review_decisions_action",
        "hybrid_metadata_review_decisions",
        type_="check",
    )
    op.create_check_constraint(
        "hybrid_metadata_review_decisions_action",
        "hybrid_metadata_review_decisions",
        "action IN ('save_draft','workbook_apply','approve','reject')",
    )
    op.create_table(
        "hybrid_metadata_workbook_exports",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("export_id", sa.Text(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_revision_id", sa.Text(), nullable=False),
        sa.Column("review_set_id", sa.Text(), nullable=False),
        sa.Column("review_set_identity", sa.String(64), nullable=False),
        sa.Column("review_set_generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("manifest_json", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_ref_json", postgresql.JSONB(), nullable=False),
        sa.Column("authority_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("source_id", "export_id"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.source_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "review_set_id"],
            [
                "hybrid_metadata_review_sets.source_id",
                "hybrid_metadata_review_sets.review_set_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "state IN ('available','consumed','expired','stale')",
            name="hybrid_metadata_workbook_exports_state",
        ),
        sa.CheckConstraint(
            "review_set_generation > 0",
            name="hybrid_metadata_workbook_exports_generation",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="hybrid_metadata_workbook_exports_expiry",
        ),
    )
    op.create_index(
        "hybrid_metadata_workbook_exports_document_idx",
        "hybrid_metadata_workbook_exports",
        ["source_id", "document_id", "revision_id", "created_at"],
    )
    op.create_table(
        "hybrid_metadata_workbook_previews",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("preview_id", sa.Text(), nullable=False),
        sa.Column("export_id", sa.Text(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preview_identity", sa.String(64)),
        sa.Column("current_review_set_identity", sa.String(64)),
        sa.Column("current_review_set_generation", sa.Integer()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("preview_json", postgresql.JSONB()),
        sa.Column("validation_report_json", postgresql.JSONB()),
        sa.Column("original_ref_json", postgresql.JSONB(), nullable=False),
        sa.Column("authority_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("source_id", "preview_id"),
        sa.ForeignKeyConstraint(
            ["source_id", "export_id"],
            [
                "hybrid_metadata_workbook_exports.source_id",
                "hybrid_metadata_workbook_exports.export_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "state IN ('validation_failed','conflicts','ready_to_apply',"
            "'applied','expired','stale')",
            name="hybrid_metadata_workbook_previews_state",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="hybrid_metadata_workbook_previews_expiry",
        ),
        sa.CheckConstraint(
            "(state = 'validation_failed') = (validation_report_json IS NOT NULL)",
            name="hybrid_metadata_workbook_previews_report",
        ),
        sa.CheckConstraint(
            "(state <> 'validation_failed') = (preview_json IS NOT NULL)",
            name="hybrid_metadata_workbook_previews_projection",
        ),
    )
    op.create_index(
        "hybrid_metadata_workbook_previews_export_idx",
        "hybrid_metadata_workbook_previews",
        ["source_id", "export_id", "created_at"],
    )
    op.create_table(
        "hybrid_metadata_workbook_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.Text()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.Text()),
        sa.Column("safe_reason", sa.Text()),
        sa.Column("job_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("job_id"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["knowledge_source_operations.operation_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.source_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("operation_id"),
        sa.CheckConstraint(
            "command IN ('generate_export','create_preview','apply_preview')",
            name="hybrid_metadata_workbook_jobs_command",
        ),
        sa.CheckConstraint(
            "state IN ('READY','CLAIMED','COMPLETED','FAILED')",
            name="hybrid_metadata_workbook_jobs_state",
        ),
        sa.CheckConstraint(
            "source_revision > 0 AND fencing_token >= 0",
            name="hybrid_metadata_workbook_jobs_positive",
        ),
    )
    op.create_index(
        "hybrid_metadata_workbook_jobs_claim_idx",
        "hybrid_metadata_workbook_jobs",
        ["state", "created_at", "job_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Metadata Workbook V2 direct cutover does not support downgrade")
