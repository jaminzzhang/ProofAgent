"""Add immutable Formal Candidate checkpoints to publication commands."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0024_formal_candidate_checkpoint"
down_revision: str | None = "0023_formal_publish_claim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "formal_agent_publication_commands",
        sa.Column("formal_candidate_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "formal_agent_publication_commands",
        sa.Column(
            "knowledge_release_candidate_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "formal_agent_publication_commands",
        sa.Column("candidate_checkpointed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "formal_agent_publication_commands_candidate_checkpoint",
        "formal_agent_publication_commands",
        "(formal_candidate_sha256 IS NULL AND "
        "knowledge_release_candidate_sha256 IS NULL AND "
        "candidate_checkpointed_at IS NULL) OR "
        "(formal_candidate_sha256 ~ '^[0-9a-f]{64}$' AND "
        "knowledge_release_candidate_sha256 ~ '^[0-9a-f]{64}$' AND "
        "candidate_checkpointed_at IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
