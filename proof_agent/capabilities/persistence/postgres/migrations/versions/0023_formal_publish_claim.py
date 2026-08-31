"""Add fenced execution claims for formal publication command recovery."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0023_formal_publish_claim"
down_revision: str | None = "0022_formal_publish_cmd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "formal_agent_publication_commands",
        sa.Column("execution_fencing_token", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "formal_agent_publication_commands",
        sa.Column("lease_owner", sa.Text(), nullable=True),
    )
    op.add_column(
        "formal_agent_publication_commands",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "formal_agent_publication_commands_execution_claim",
        "formal_agent_publication_commands",
        "(execution_fencing_token IS NULL AND lease_owner IS NULL AND "
        "lease_expires_at IS NULL) OR "
        "(execution_fencing_token > 0 AND "
        "char_length(lease_owner) BETWEEN 1 AND 128 AND "
        "lease_expires_at IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
