"""Add production Hybrid intake metadata and review authority."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010_hybrid_knowledge_workflow"
down_revision: str | None = "0009_hybrid_ingestion_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hybrid_ingestion_jobs",
        sa.Column(
            "filename",
            sa.Text(),
            nullable=False,
            server_default="document.pdf",
        ),
    )
    op.add_column(
        "hybrid_ingestion_jobs",
        sa.Column(
            "uploaded_by",
            sa.Text(),
            nullable=False,
            server_default="migration",
        ),
    )
    op.alter_column("hybrid_ingestion_jobs", "filename", server_default=None)
    op.alter_column("hybrid_ingestion_jobs", "uploaded_by", server_default=None)
    op.create_table(
        "hybrid_metadata_reviews",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_version", sa.Integer(), nullable=False),
        sa.Column("review_identity", sa.String(64), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("publication_blocked", sa.Boolean(), nullable=False),
        sa.Column("review_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_id", "review_id"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["knowledge_sources.source_id"],
        ),
        sa.CheckConstraint("review_version > 0", name="hybrid_metadata_reviews_version"),
        sa.CheckConstraint(
            "state IN ('review_required','ready_for_review','approved','corrected','rejected')",
            name="hybrid_metadata_reviews_state",
        ),
        sa.CheckConstraint(
            "(state = 'approved') = (publication_blocked = FALSE)",
            name="hybrid_metadata_reviews_publication",
        ),
    )
    op.create_index(
        "hybrid_metadata_reviews_source_state_idx",
        "hybrid_metadata_reviews",
        ["source_id", "state", "review_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
