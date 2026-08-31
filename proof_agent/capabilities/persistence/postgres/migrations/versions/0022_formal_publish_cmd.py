"""Add durable idempotency receipts for formal Agent publication commands."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0022_formal_publish_cmd"
down_revision: str | None = "0021_metadata_workbook_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "formal_agent_publication_commands",
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("receipt_json", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("command_id"),
        sa.UniqueConstraint(
            "actor_subject",
            "idempotency_key",
            name="formal_agent_publication_commands_actor_key",
        ),
        sa.CheckConstraint(
            "state IN ('in_progress','succeeded','failed')",
            name="formal_agent_publication_commands_state",
        ),
        sa.CheckConstraint(
            "draft_revision > 0",
            name="formal_agent_publication_commands_revision",
        ),
        sa.CheckConstraint(
            "char_length(actor_subject) BETWEEN 1 AND 255",
            name="formal_agent_publication_commands_actor",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 128",
            name="formal_agent_publication_commands_key",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name="formal_agent_publication_commands_digest",
        ),
        sa.CheckConstraint(
            "(state = 'in_progress' AND completed_at IS NULL) OR "
            "(state IN ('succeeded','failed') AND completed_at IS NOT NULL)",
            name="formal_agent_publication_commands_completion",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
