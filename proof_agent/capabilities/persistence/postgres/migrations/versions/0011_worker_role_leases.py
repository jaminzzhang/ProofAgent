"""Add durable fenced leases for production worker roles."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_worker_role_leases"
down_revision: str | None = "0010_hybrid_knowledge_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "production_worker_role_activations",
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("activation_epoch", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.Text()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("role"),
        sa.CheckConstraint(
            "role IN ('run_executor','knowledge_worker')",
            name="production_worker_role_name",
        ),
        sa.CheckConstraint(
            "slot IN (1,2)",
            name="production_worker_role_slot",
        ),
        sa.CheckConstraint(
            "state IN ('standby','active','draining')",
            name="production_worker_role_state",
        ),
        sa.CheckConstraint(
            "activation_epoch >= 0",
            name="production_worker_role_epoch",
        ),
        sa.CheckConstraint(
            "((state = 'standby' AND owner_id IS NULL "
            "AND heartbeat_at IS NULL AND lease_expires_at IS NULL) OR "
            "(state IN ('active','draining') AND owner_id IS NOT NULL "
            "AND heartbeat_at IS NOT NULL AND lease_expires_at > heartbeat_at))",
            name="production_worker_role_lease_shape",
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO production_worker_role_activations "
            "(role, slot, state, activation_epoch, owner_id, heartbeat_at, "
            "lease_expires_at, updated_at) VALUES "
            "('run_executor', 1, 'standby', 0, NULL, NULL, NULL, CURRENT_TIMESTAMP), "
            "('knowledge_worker', 1, 'standby', 0, NULL, NULL, NULL, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
