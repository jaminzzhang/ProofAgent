"""Create the expand-only PostgreSQL transactional foundation."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UTC = sa.DateTime(timezone=True)
_JSON = postgresql.JSONB(astext_type=sa.Text())
_UUID = postgresql.UUID(as_uuid=True)
_UUID_DEFAULT = sa.text("gen_random_uuid()")
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "agent_drafts",
        sa.Column("draft_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("draft_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _UTC, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("agent_id", "draft_id", name="agent_drafts_identity_uq"),
        sa.CheckConstraint("revision > 0", name="agent_drafts_revision_positive"),
        sa.CheckConstraint("updated_at >= created_at", name="agent_drafts_time_order"),
    )
    op.create_index("agent_drafts_agent_idx", "agent_drafts", ["agent_id"])

    op.create_table(
        "agent_versions",
        sa.Column("version_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column(
            "source_draft_id",
            _UUID,
            sa.ForeignKey("agent_drafts.draft_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_draft_revision", sa.Integer(), nullable=False),
        sa.Column("version_json", _JSON, nullable=False),
        sa.Column("published_at", _UTC, nullable=False, server_default=_NOW),
        sa.Column("published_by", sa.Text(), nullable=False),
        sa.UniqueConstraint("agent_id", "version_id", name="agent_versions_identity_uq"),
        sa.CheckConstraint(
            "source_draft_revision > 0", name="agent_versions_draft_revision_positive"
        ),
    )
    op.create_index("agent_versions_agent_idx", "agent_versions", ["agent_id"])

    op.create_table(
        "active_agent_versions",
        sa.Column("agent_id", sa.Text(), primary_key=True),
        sa.Column(
            "version_id",
            _UUID,
            sa.ForeignKey("agent_versions.version_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("activation_json", _JSON, nullable=False),
        sa.Column("activated_at", _UTC, nullable=False, server_default=_NOW),
    )

    _create_shared_asset_tables()

    op.create_table(
        "agent_version_shared_asset_refs",
        sa.Column(
            "agent_version_id",
            _UUID,
            sa.ForeignKey("agent_versions.version_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("asset_kind", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), primary_key=True),
        sa.Column("asset_version_id", _UUID, nullable=False),
        sa.Column("asset_revision", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "asset_kind IN ('knowledge_source','model_connection','tool_source')",
            name="agent_version_shared_asset_kind_valid",
        ),
        sa.CheckConstraint(
            "asset_revision > 0", name="agent_version_shared_asset_revision_positive"
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="agent_version_shared_asset_digest_valid",
        ),
    )
    op.create_index(
        "agent_version_shared_asset_version_idx",
        "agent_version_shared_asset_refs",
        ["asset_kind", "asset_id", "asset_version_id"],
    )

    op.create_table(
        "configuration_validations",
        sa.Column("validation_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("draft_id", _UUID, nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("validation_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["agent_drafts.draft_id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "draft_revision > 0", name="configuration_validations_revision_positive"
        ),
    )

    op.create_table(
        "runs",
        sa.Column("run_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("run_purpose", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("agent_version_id", _UUID, nullable=False),
        sa.Column("submitted_by", sa.Text(), nullable=False),
        sa.Column("run_metadata_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _UTC, nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(
            ["agent_version_id"], ["agent_versions.version_id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("state_version > 0", name="runs_state_version_positive"),
        sa.CheckConstraint(
            "state IN ('queued','running','finalizing','succeeded','failed','cancelled','timed_out')",
            name="runs_state_valid",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="runs_time_order"),
    )

    op.create_table(
        "run_attempts",
        sa.Column("attempt_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column(
            "run_id",
            _UUID,
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_expires_at", _UTC),
        sa.Column("attempt_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _UTC, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("run_id", "attempt_number", name="run_attempts_number_uq"),
        sa.UniqueConstraint("run_id", "fencing_token", name="run_attempts_fencing_uq"),
        sa.CheckConstraint("attempt_number > 0", name="run_attempts_number_positive"),
        sa.CheckConstraint("state_version > 0", name="run_attempts_state_version_positive"),
        sa.CheckConstraint("fencing_token > 0", name="run_attempts_fencing_positive"),
        sa.CheckConstraint(
            "state IN ('queued','running','finalizing','succeeded','failed','cancelled','timed_out')",
            name="run_attempts_state_valid",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="run_attempts_time_order"),
    )

    op.create_table(
        "conversations",
        sa.Column("conversation_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _UTC, nullable=False, server_default=_NOW),
        sa.CheckConstraint("updated_at >= created_at", name="conversations_time_order"),
    )

    op.create_table(
        "conversation_turns",
        sa.Column("turn_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column(
            "conversation_id",
            _UUID,
            sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("run_id", _UUID, nullable=False),
        sa.Column("turn_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
        sa.Column("raw_text_expires_at", _UTC, nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("conversation_id", "ordinal", name="conversation_turns_order_uq"),
        sa.UniqueConstraint("conversation_id", "run_id", name="conversation_turns_run_uq"),
        sa.CheckConstraint("ordinal > 0", name="conversation_turns_ordinal_positive"),
        sa.CheckConstraint(
            "raw_text_expires_at > created_at", name="conversation_turns_expiry_after_create"
        ),
    )

    op.create_table(
        "case_memory_records",
        sa.Column("memory_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("case_id", _UUID, nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("source_run_id", _UUID, nullable=False),
        sa.Column("source_turn_id", _UUID, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("memory_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
        sa.Column("expires_at", _UTC, nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["conversations.conversation_id"]),
        sa.ForeignKeyConstraint(["source_run_id"], ["runs.run_id"]),
        sa.ForeignKeyConstraint(["source_turn_id"], ["conversation_turns.turn_id"]),
        sa.CheckConstraint(
            "status IN ('active','superseded','deleted')", name="case_memory_status_valid"
        ),
        sa.CheckConstraint("expires_at > created_at", name="case_memory_expiry_after_create"),
        sa.CheckConstraint(
            "expires_at <= created_at + INTERVAL '30 days'",
            name="case_memory_retention_max_30_days",
        ),
    )
    op.create_index(
        "case_memory_active_lookup_idx",
        "case_memory_records",
        ["agent_id", "case_id", "expires_at"],
    )

    op.create_table(
        "audit_events",
        sa.Column("audit_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("actor_json", _JSON, nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("metadata_json", _JSON, nullable=False),
        sa.Column("occurred_at", _UTC, nullable=False),
        sa.Column("expires_at", _UTC, nullable=False),
        sa.CheckConstraint(
            "category IN ('configuration','security','run','operations')",
            name="audit_events_category_valid",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded','denied','failed')", name="audit_events_outcome_valid"
        ),
        sa.CheckConstraint("expires_at > occurred_at", name="audit_events_expiry_after_event"),
    )
    op.create_index("audit_events_time_idx", "audit_events", ["occurred_at"])


def _create_shared_asset_tables() -> None:
    for base_name, id_name in (
        ("knowledge_sources", "source_id"),
        ("model_connections", "connection_id"),
        ("tool_sources", "source_id"),
    ):
        op.create_table(
            base_name,
            sa.Column(id_name, sa.Text(), primary_key=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("lifecycle_state", sa.Text(), nullable=False),
            sa.Column("configuration_json", _JSON, nullable=False),
            sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
            sa.Column("updated_at", _UTC, nullable=False, server_default=_NOW),
            sa.CheckConstraint("revision > 0", name=f"{base_name}_revision_positive"),
            sa.CheckConstraint("updated_at >= created_at", name=f"{base_name}_time_order"),
        )

    for table_name, base_name, id_name in (
        ("knowledge_source_versions", "knowledge_sources", "source_id"),
        ("model_connection_versions", "model_connections", "connection_id"),
        ("tool_source_versions", "tool_sources", "source_id"),
    ):
        op.create_table(
            table_name,
            sa.Column("version_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
            sa.Column(
                id_name,
                sa.Text(),
                sa.ForeignKey(f"{base_name}.{id_name}", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("version_json", _JSON, nullable=False),
            sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
            sa.UniqueConstraint(id_name, "revision", name=f"{table_name}_revision_uq"),
            sa.CheckConstraint("revision > 0", name=f"{table_name}_revision_positive"),
            sa.CheckConstraint(
                "content_sha256 ~ '^[0-9a-f]{64}$'", name=f"{table_name}_digest_valid"
            ),
        )

    op.create_table(
        "knowledge_snapshots",
        sa.Column("snapshot_id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column(
            "source_version_id",
            _UUID,
            sa.ForeignKey("knowledge_source_versions.version_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_json", _JSON, nullable=False),
        sa.Column("created_at", _UTC, nullable=False, server_default=_NOW),
        sa.UniqueConstraint(
            "source_version_id", "manifest_sha256", name="knowledge_snapshots_manifest_uq"
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'", name="knowledge_snapshots_digest_valid"
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
