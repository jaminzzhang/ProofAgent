"""Add authoritative Hybrid document candidate selection."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0015_hybrid_candidates"
down_revision: str | None = "0014_knowledge_source_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hybrid_document_candidates",
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey("knowledge_sources.source_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("candidate_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("pending_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "candidate_revision_id IS NOT NULL OR pending_revision_id IS NOT NULL",
            name="hybrid_document_candidate_has_revision",
        ),
        sa.CheckConstraint(
            "candidate_revision_id IS NULL OR pending_revision_id IS NULL "
            "OR candidate_revision_id <> pending_revision_id",
            name="hybrid_document_candidate_distinct_revisions",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "document_id", "candidate_revision_id"],
            [
                "hybrid_ingestion_jobs.source_id",
                "hybrid_ingestion_jobs.document_id",
                "hybrid_ingestion_jobs.revision_id",
            ],
            ondelete="RESTRICT",
            name="hybrid_document_candidate_selected_job",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "document_id", "pending_revision_id"],
            [
                "hybrid_ingestion_jobs.source_id",
                "hybrid_ingestion_jobs.document_id",
                "hybrid_ingestion_jobs.revision_id",
            ],
            ondelete="RESTRICT",
            name="hybrid_document_candidate_pending_job",
        ),
    )
    op.create_index(
        "hybrid_document_candidates_source_idx",
        "hybrid_document_candidates",
        ["source_id", "document_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
