"""Persist the terminal receipt outcome as the Run list read model."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0008_run_receipt_outcome"
down_revision: str | None = "0007_run_queue_executor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs", sa.Column("conversation_id", postgresql.UUID(as_uuid=True))
    )
    op.execute(
        """
        UPDATE runs
        SET conversation_id = (request_json ->> 'conversation_id')::uuid
        WHERE jsonb_typeof(request_json -> 'conversation_id') = 'string'
          AND (request_json ->> 'conversation_id') ~*
              '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        """
    )
    op.create_index(
        "runs_single_active_conversation_idx",
        "runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text(
            "conversation_id IS NOT NULL AND state IN "
            "('queued','running','finalizing','cancel_requested')"
        ),
    )
    op.add_column("runs", sa.Column("receipt_outcome", sa.Text()))
    op.add_column("run_attempts", sa.Column("receipt_outcome", sa.Text()))
    op.create_check_constraint(
        "runs_receipt_outcome_visible",
        "runs",
        "receipt_outcome IS NULL OR (state = 'succeeded' AND result_available)",
    )
    op.create_check_constraint(
        "run_attempts_receipt_outcome_visible",
        "run_attempts",
        "receipt_outcome IS NULL OR (state = 'succeeded' AND result_available)",
    )
    op.create_index(
        "runs_receipt_outcome_idx",
        "runs",
        ["receipt_outcome", "created_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
