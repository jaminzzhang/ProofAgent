"""Add durable workflow tasks and atomic answer resume outbox."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0025_workflow_tasks"
down_revision: str | None = "0024_formal_candidate_checkpoint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_tasks",
        sa.Column("task_id", sa.Text(), primary_key=True),
        sa.Column("actor_subject", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("agent_version", sa.Text(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("goal_revision", sa.BigInteger(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_content_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version > 0 AND goal_revision > 0 AND schema_version = 1",
            name="workflow_tasks_versions",
        ),
        sa.CheckConstraint(
            "phase IN ('active','waiting_for_input','paused','complete','failed','cancelled')",
            name="workflow_tasks_phase",
        ),
        sa.CheckConstraint("snapshot_sha256 ~ '^[a-f0-9]{64}$'", name="workflow_tasks_digest"),
        sa.CheckConstraint(
            "raw_content_expires_at <= created_at + interval '90 days' AND raw_content_expires_at > created_at",
            name="workflow_tasks_retention",
        ),
    )
    op.create_index(
        "workflow_tasks_owner", "workflow_tasks", ["actor_subject", "agent_id", "agent_version"]
    )
    op.create_index("workflow_tasks_retention", "workflow_tasks", ["raw_content_expires_at"])
    op.create_table(
        "workflow_task_resumes",
        sa.Column("intent_id", sa.Text(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Text(),
            sa.ForeignKey("workflow_tasks.task_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_subject", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("agent_version", sa.Text(), nullable=False),
        sa.Column("goal_revision", sa.BigInteger(), nullable=False),
        sa.Column("intent_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Text()),
    )
    op.create_index(
        "workflow_task_resumes_pending",
        "workflow_task_resumes",
        ["created_at"],
        postgresql_where=sa.text("run_id IS NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
