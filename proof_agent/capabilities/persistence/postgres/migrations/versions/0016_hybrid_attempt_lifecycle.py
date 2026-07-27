"""Bind Hybrid job scheduling to immutable attempt initiation history."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0016_hybrid_attempt_lifecycle"
down_revision: str | None = "0015_hybrid_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hybrid_ingestion_jobs",
        sa.Column(
            "next_attempt_initiation",
            sa.Text(),
            nullable=False,
            server_default="automatic",
        ),
    )
    op.create_check_constraint(
        "hybrid_ingestion_jobs_attempt_initiation",
        "hybrid_ingestion_jobs",
        "next_attempt_initiation IN ('automatic','manual')",
    )
    op.drop_constraint(
        "hybrid_ingestion_jobs_fence",
        "hybrid_ingestion_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "hybrid_ingestion_jobs_fence",
        "hybrid_ingestion_jobs",
        "(state IN ('READY','CANCELLED') AND fencing_token >= 0) OR "
        "(state NOT IN ('READY','CANCELLED') AND fencing_token > 0)",
    )
    op.alter_column(
        "hybrid_ingestion_jobs",
        "next_attempt_initiation",
        server_default=None,
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
