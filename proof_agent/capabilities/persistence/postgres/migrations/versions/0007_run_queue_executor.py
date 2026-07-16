"""Add the bounded, fenced PostgreSQL Run queue authority."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0007_run_queue_executor"
down_revision: str | None = "0006_artifact_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("runs", sa.Column("request_sha256", sa.String(64)))
    op.add_column("runs", sa.Column("idempotency_key", sa.Text()))
    op.add_column("runs", sa.Column("request_json", _JSON))
    op.add_column("runs", sa.Column("enqueued_at", _UTC))
    op.add_column("runs", sa.Column("started_at", _UTC))
    op.add_column("runs", sa.Column("completed_at", _UTC))
    op.add_column(
        "runs",
        sa.Column(
            "result_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("runs", sa.Column("artifact_manifest_id", postgresql.UUID(as_uuid=True)))
    op.add_column("runs", sa.Column("terminal_failure_json", _JSON))
    op.execute(
        """
        UPDATE runs
        SET request_sha256 = repeat('0', 64),
            idempotency_key = 'legacy-' || run_id::text,
            request_json = jsonb_build_object('legacy_run_id', run_id::text),
            enqueued_at = created_at,
            started_at = CASE WHEN state <> 'queued' THEN created_at ELSE NULL END,
            completed_at = CASE
                WHEN state IN ('succeeded','failed','cancelled','timed_out') THEN updated_at
                ELSE NULL
            END
        """
    )
    op.alter_column("runs", "request_sha256", nullable=False)
    op.alter_column("runs", "idempotency_key", nullable=False)
    op.alter_column("runs", "request_json", nullable=False)
    op.alter_column("runs", "enqueued_at", nullable=False)
    op.create_unique_constraint(
        "runs_operator_idempotency_uq",
        "runs",
        ["submitted_by", "idempotency_key"],
    )
    op.create_index(
        "runs_queue_order_idx",
        "runs",
        ["created_at", "run_id"],
        postgresql_where=sa.text("state = 'queued'"),
    )
    op.drop_constraint("runs_state_valid", "runs", type_="check")
    op.create_check_constraint(
        "runs_state_valid_v2",
        "runs",
        "state IN ('queued','running','finalizing','succeeded','failed',"
        "'cancel_requested','cancelled','timed_out')",
    )
    op.create_check_constraint(
        "runs_result_binding_consistent",
        "runs",
        "(result_available AND artifact_manifest_id IS NOT NULL AND state = 'succeeded') OR "
        "(NOT result_available AND artifact_manifest_id IS NULL)",
    )

    op.add_column("run_attempts", sa.Column("claim_token", sa.Text()))
    op.add_column(
        "run_attempts",
        sa.Column(
            "activation_epoch",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column("run_attempts", sa.Column("executor_id", sa.Text()))
    op.add_column("run_attempts", sa.Column("heartbeat_at", _UTC))
    op.add_column("run_attempts", sa.Column("deadline_at", _UTC))
    op.add_column("run_attempts", sa.Column("snapshot_json", _JSON))
    op.add_column("run_attempts", sa.Column("snapshot_sha256", sa.String(64)))
    op.add_column(
        "run_attempts",
        sa.Column(
            "result_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "run_attempts", sa.Column("artifact_manifest_id", postgresql.UUID(as_uuid=True))
    )
    op.add_column("run_attempts", sa.Column("terminal_failure_json", _JSON))
    op.drop_constraint("run_attempts_state_valid", "run_attempts", type_="check")
    op.create_check_constraint(
        "run_attempts_state_valid_v2",
        "run_attempts",
        "state IN ('running','finalizing','succeeded','failed',"
        "'cancel_requested','cancelled','timed_out')",
    )
    op.create_check_constraint(
        "run_attempts_result_binding_consistent",
        "run_attempts",
        "(result_available AND artifact_manifest_id IS NOT NULL AND state = 'succeeded') OR "
        "(NOT result_available AND artifact_manifest_id IS NULL)",
    )
    op.create_index(
        "run_attempts_active_capacity_idx",
        "run_attempts",
        ["state", "lease_expires_at"],
        postgresql_where=sa.text(
            "state IN ('running','finalizing','cancel_requested')"
        ),
    )

    op.execute("CREATE SEQUENCE run_fencing_epoch_seq AS bigint START WITH 1")
    op.create_table(
        "run_executor_activations",
        sa.Column("slot", sa.SmallInteger(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("activation_epoch", sa.BigInteger(), nullable=False),
        sa.Column("executor_id", sa.Text()),
        sa.Column("updated_at", _UTC, nullable=False),
        sa.CheckConstraint("slot BETWEEN 1 AND 2", name="run_executor_slot_valid"),
        sa.CheckConstraint(
            "state IN ('standby','active','draining')",
            name="run_executor_activation_state_valid",
        ),
        sa.CheckConstraint(
            "(state = 'active' AND executor_id IS NOT NULL) OR "
            "(state <> 'active' AND executor_id IS NULL)",
            name="run_executor_active_owner_consistent",
        ),
    )
    op.create_index(
        "run_executor_single_active_idx",
        "run_executor_activations",
        ["state"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "run_operator_fairness",
        sa.Column("operator_subject", sa.Text(), primary_key=True),
        sa.Column("last_claimed_at", _UTC, nullable=False),
        sa.Column("claim_count", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("claim_count > 0", name="run_operator_claim_count_positive"),
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
