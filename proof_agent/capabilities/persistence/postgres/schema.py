from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


metadata = sa.MetaData()
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
UTC_TIMESTAMP = sa.DateTime(timezone=True)

agent_drafts = sa.Table(
    "agent_drafts",
    metadata,
    sa.Column("draft_id", UUID, primary_key=True),
    sa.Column("agent_id", sa.Text(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("draft_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

agent_versions = sa.Table(
    "agent_versions",
    metadata,
    sa.Column("version_id", UUID, primary_key=True),
    sa.Column("agent_id", sa.Text(), nullable=False),
    sa.Column("source_draft_id", UUID, nullable=False),
    sa.Column("source_draft_revision", sa.Integer(), nullable=False),
    sa.Column("version_json", JSONB, nullable=False),
    sa.Column("published_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("published_by", sa.Text(), nullable=False),
)

active_agent_versions = sa.Table(
    "active_agent_versions",
    metadata,
    sa.Column("agent_id", sa.Text(), primary_key=True),
    sa.Column("version_id", UUID, nullable=False),
    sa.Column("activation_json", JSONB, nullable=False),
    sa.Column("activated_at", UTC_TIMESTAMP, nullable=False),
)

knowledge_sources = sa.Table(
    "knowledge_sources",
    metadata,
    sa.Column("source_id", sa.Text(), primary_key=True),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("lifecycle_state", sa.Text(), nullable=False),
    sa.Column("configuration_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

knowledge_source_versions = sa.Table(
    "knowledge_source_versions",
    metadata,
    sa.Column("version_id", UUID, primary_key=True),
    sa.Column("source_id", sa.Text(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("content_sha256", sa.String(64), nullable=False),
    sa.Column("version_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
)

knowledge_snapshots = sa.Table(
    "knowledge_snapshots",
    metadata,
    sa.Column("snapshot_id", UUID, primary_key=True),
    sa.Column("source_version_id", UUID, nullable=False),
    sa.Column("manifest_sha256", sa.String(64), nullable=False),
    sa.Column("snapshot_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
)

model_connections = sa.Table(
    "model_connections",
    metadata,
    sa.Column("connection_id", sa.Text(), primary_key=True),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("lifecycle_state", sa.Text(), nullable=False),
    sa.Column("configuration_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

model_connection_versions = sa.Table(
    "model_connection_versions",
    metadata,
    sa.Column("version_id", UUID, primary_key=True),
    sa.Column("connection_id", sa.Text(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("content_sha256", sa.String(64), nullable=False),
    sa.Column("version_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
)

model_connection_credentials = sa.Table(
    "model_connection_credentials",
    metadata,
    sa.Column(
        "connection_id",
        sa.Text(),
        sa.ForeignKey("model_connections.connection_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column("key_version", sa.Text(), nullable=False),
    sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.CheckConstraint(
        "octet_length(ciphertext) BETWEEN 29 AND 16412",
        name="ck_model_connection_credentials_ciphertext_size",
    ),
)

tool_sources = sa.Table(
    "tool_sources",
    metadata,
    sa.Column("source_id", sa.Text(), primary_key=True),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("lifecycle_state", sa.Text(), nullable=False),
    sa.Column("configuration_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

tool_source_versions = sa.Table(
    "tool_source_versions",
    metadata,
    sa.Column("version_id", UUID, primary_key=True),
    sa.Column("source_id", sa.Text(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("content_sha256", sa.String(64), nullable=False),
    sa.Column("version_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
)

agent_version_shared_asset_refs = sa.Table(
    "agent_version_shared_asset_refs",
    metadata,
    sa.Column("agent_version_id", UUID, primary_key=True),
    sa.Column("asset_kind", sa.Text(), primary_key=True),
    sa.Column("asset_id", sa.Text(), primary_key=True),
    sa.Column("asset_version_id", UUID, nullable=False),
    sa.Column("asset_revision", sa.Integer(), nullable=False),
    sa.Column("content_sha256", sa.String(64), nullable=False),
)

runs = sa.Table(
    "runs",
    metadata,
    sa.Column("run_id", UUID, primary_key=True),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("state_version", sa.Integer(), nullable=False),
    sa.Column("run_purpose", sa.Text(), nullable=False),
    sa.Column("agent_id", sa.Text(), nullable=False),
    sa.Column("agent_version_id", UUID, nullable=False),
    sa.Column("submitted_by", sa.Text(), nullable=False),
    sa.Column("request_sha256", sa.String(64), nullable=False),
    sa.Column("idempotency_key", sa.Text(), nullable=False),
    sa.Column("conversation_id", UUID),
    sa.Column("request_json", JSONB, nullable=False),
    sa.Column("enqueued_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("started_at", UTC_TIMESTAMP),
    sa.Column("completed_at", UTC_TIMESTAMP),
    sa.Column("result_available", sa.Boolean(), nullable=False),
    sa.Column("artifact_manifest_id", UUID),
    sa.Column("receipt_outcome", sa.Text()),
    sa.Column("terminal_failure_json", JSONB),
    sa.Column("run_metadata_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

run_attempts = sa.Table(
    "run_attempts",
    metadata,
    sa.Column("attempt_id", UUID, primary_key=True),
    sa.Column("run_id", UUID, nullable=False),
    sa.Column("attempt_number", sa.Integer(), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("state_version", sa.Integer(), nullable=False),
    sa.Column("fencing_token", sa.BigInteger(), nullable=False),
    sa.Column("claim_token", sa.Text()),
    sa.Column("activation_epoch", sa.BigInteger(), nullable=False),
    sa.Column("executor_id", sa.Text()),
    sa.Column("lease_owner", sa.Text()),
    sa.Column("heartbeat_at", UTC_TIMESTAMP),
    sa.Column("lease_expires_at", UTC_TIMESTAMP),
    sa.Column("deadline_at", UTC_TIMESTAMP),
    sa.Column("snapshot_json", JSONB),
    sa.Column("snapshot_sha256", sa.String(64)),
    sa.Column("result_available", sa.Boolean(), nullable=False),
    sa.Column("artifact_manifest_id", UUID),
    sa.Column("receipt_outcome", sa.Text()),
    sa.Column("terminal_failure_json", JSONB),
    sa.Column("attempt_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

run_executor_activations = sa.Table(
    "run_executor_activations",
    metadata,
    sa.Column("slot", sa.SmallInteger(), primary_key=True),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("activation_epoch", sa.BigInteger(), nullable=False),
    sa.Column("executor_id", sa.Text()),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

production_worker_role_activations = sa.Table(
    "production_worker_role_activations",
    metadata,
    sa.Column("role", sa.Text(), primary_key=True),
    sa.Column("slot", sa.SmallInteger(), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("activation_epoch", sa.BigInteger(), nullable=False),
    sa.Column("owner_id", sa.Text()),
    sa.Column("heartbeat_at", UTC_TIMESTAMP),
    sa.Column("lease_expires_at", UTC_TIMESTAMP),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

run_operator_fairness = sa.Table(
    "run_operator_fairness",
    metadata,
    sa.Column("operator_subject", sa.Text(), primary_key=True),
    sa.Column("last_claimed_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("claim_count", sa.BigInteger(), nullable=False),
)

conversations = sa.Table(
    "conversations",
    metadata,
    sa.Column("conversation_id", UUID, primary_key=True),
    sa.Column("agent_id", sa.Text(), nullable=False),
    sa.Column("title", sa.Text()),
    sa.Column("pinned", sa.Boolean(), nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

conversation_turns = sa.Table(
    "conversation_turns",
    metadata,
    sa.Column("turn_id", UUID, primary_key=True),
    sa.Column("conversation_id", UUID, nullable=False),
    sa.Column("ordinal", sa.Integer(), nullable=False),
    sa.Column("run_id", UUID, nullable=False),
    sa.Column("turn_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("raw_text_expires_at", UTC_TIMESTAMP, nullable=False),
)

case_memory_records = sa.Table(
    "case_memory_records",
    metadata,
    sa.Column("memory_id", UUID, primary_key=True),
    sa.Column("case_id", UUID, nullable=False),
    sa.Column("agent_id", sa.Text(), nullable=False),
    sa.Column("source_run_id", UUID, nullable=False),
    sa.Column("source_turn_id", UUID, nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("memory_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
)

audit_events = sa.Table(
    "audit_events",
    metadata,
    sa.Column("audit_id", UUID, primary_key=True),
    sa.Column("category", sa.Text(), nullable=False),
    sa.Column("event_type", sa.Text(), nullable=False),
    sa.Column("outcome", sa.Text(), nullable=False),
    sa.Column("actor_json", JSONB, nullable=False),
    sa.Column("target_type", sa.Text(), nullable=False),
    sa.Column("target_id", sa.Text(), nullable=False),
    sa.Column("metadata_json", JSONB, nullable=False),
    sa.Column("occurred_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
)

security_configuration_state = sa.Table(
    "security_configuration_state",
    metadata,
    sa.Column("singleton", sa.Boolean(), primary_key=True),
    sa.Column("permission_mapping_revision", sa.Integer(), nullable=False),
    sa.Column("egress_policy_revision", sa.Integer(), nullable=False),
    sa.Column("permission_epoch", sa.BigInteger(), nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

permission_mapping_versions = sa.Table(
    "permission_mapping_versions",
    metadata,
    sa.Column("version_id", UUID, primary_key=True),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("mapping_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("created_by", sa.Text(), nullable=False),
)

active_permission_mapping = sa.Table(
    "active_permission_mapping",
    metadata,
    sa.Column("singleton", sa.Boolean(), primary_key=True),
    sa.Column("version_id", UUID, nullable=False),
    sa.Column("activated_at", UTC_TIMESTAMP, nullable=False),
)

egress_policy_versions = sa.Table(
    "egress_policy_versions",
    metadata,
    sa.Column("version_id", UUID, primary_key=True),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("policy_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("created_by", sa.Text(), nullable=False),
)

active_egress_policy = sa.Table(
    "active_egress_policy",
    metadata,
    sa.Column("singleton", sa.Boolean(), primary_key=True),
    sa.Column("version_id", UUID, nullable=False),
    sa.Column("activated_at", UTC_TIMESTAMP, nullable=False),
)

oidc_login_attempts = sa.Table(
    "oidc_login_attempts",
    metadata,
    sa.Column("state_sha256", sa.String(64), primary_key=True),
    sa.Column("nonce_envelope", postgresql.BYTEA(), nullable=False),
    sa.Column("pkce_verifier_envelope", postgresql.BYTEA(), nullable=False),
    sa.Column("envelope_key_version", sa.Text(), nullable=False),
    sa.Column("redirect_uri", sa.Text(), nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("consumed_at", UTC_TIMESTAMP),
)

operator_sessions = sa.Table(
    "operator_sessions",
    metadata,
    sa.Column("session_id", UUID, primary_key=True),
    sa.Column("session_version", sa.Integer(), nullable=False),
    sa.Column("session_token_sha256", sa.String(64), nullable=False, unique=True),
    sa.Column("principal_json", JSONB, nullable=False),
    sa.Column("provider_token_envelope", postgresql.BYTEA(), nullable=False),
    sa.Column("envelope_key_version", sa.Text(), nullable=False),
    sa.Column("permission_mapping_version_id", UUID),
    sa.Column("permission_epoch", sa.BigInteger(), nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("absolute_expires_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("idle_expires_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("claims_verified_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("revoked_at", UTC_TIMESTAMP),
)

artifact_objects = sa.Table(
    "artifact_objects",
    metadata,
    sa.Column("object_id", UUID, primary_key=True),
    sa.Column("bucket", sa.Text(), nullable=False),
    sa.Column("object_key", sa.Text(), nullable=False),
    sa.Column("version_id", sa.Text(), nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("owner_type", sa.Text(), nullable=False),
    sa.Column("owner_id", sa.Text(), nullable=False),
    sa.Column("content_type", sa.Text(), nullable=False),
    sa.Column("display_filename", sa.Text()),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("ref_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP),
    sa.Column("corrupt_at", UTC_TIMESTAMP),
    sa.UniqueConstraint("bucket", "object_key", "version_id"),
)

artifact_manifests = sa.Table(
    "artifact_manifests",
    metadata,
    sa.Column("manifest_id", UUID, primary_key=True),
    sa.Column("owner_type", sa.Text(), nullable=False),
    sa.Column("owner_id", sa.Text(), nullable=False),
    sa.Column("manifest_object_id", UUID, nullable=False, unique=True),
    sa.Column("manifest_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
)

artifact_manifest_members = sa.Table(
    "artifact_manifest_members",
    metadata,
    sa.Column("manifest_id", UUID, primary_key=True),
    sa.Column("member_id", sa.Text(), primary_key=True),
    sa.Column("object_id", UUID, nullable=False),
    sa.UniqueConstraint("manifest_id", "object_id"),
)

artifact_owner_bindings = sa.Table(
    "artifact_owner_bindings",
    metadata,
    sa.Column("owner_type", sa.Text(), primary_key=True),
    sa.Column("owner_id", sa.Text(), primary_key=True),
    sa.Column("manifest_id", UUID, nullable=False, unique=True),
    sa.Column("visibility", sa.Text(), nullable=False),
    sa.Column("visible_at", UTC_TIMESTAMP),
    sa.Column("result_available", sa.Boolean(), nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

release_registry = sa.Table(
    "release_registry",
    metadata,
    sa.Column("release_id", sa.Text(), primary_key=True),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("candidate_binding_sha256", sa.String(64), nullable=False, unique=True),
    sa.Column("release_manifest_object_id", UUID, nullable=False, unique=True),
    sa.Column("bundle_index_object_id", UUID, unique=True),
    sa.Column("detached_attestation_object_id", UUID, unique=True),
    sa.Column("trust_identity_json", JSONB),
    sa.Column("registry_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("created_by", sa.Text(), nullable=False),
    sa.Column("finalized_at", UTC_TIMESTAMP),
)

knowledge_source_operations = sa.Table(
    "knowledge_source_operations",
    metadata,
    sa.Column("operation_id", sa.Text(), primary_key=True),
    sa.Column("source_id", sa.Text(), nullable=False),
    sa.Column("command", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("stage", sa.Text(), nullable=False),
    sa.Column("source_revision", sa.BigInteger(), nullable=False),
    sa.Column("operation_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("completed_at", UTC_TIMESTAMP),
)

knowledge_source_idempotency = sa.Table(
    "knowledge_source_idempotency",
    metadata,
    sa.Column("operator_subject", sa.Text(), primary_key=True),
    sa.Column("source_id", sa.Text(), primary_key=True),
    sa.Column("command", sa.Text(), primary_key=True),
    sa.Column("idempotency_key", sa.Text(), primary_key=True),
    sa.Column("request_sha256", sa.String(64), nullable=False),
    sa.Column("operation_id", sa.Text(), nullable=False, unique=True),
    sa.Column("outcome_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
)

knowledge_ingestion_attempts = sa.Table(
    "knowledge_ingestion_attempts",
    metadata,
    sa.Column("attempt_id", UUID, primary_key=True),
    sa.Column("job_id", UUID, nullable=False),
    sa.Column("attempt_number", sa.Integer(), nullable=False),
    sa.Column("initiation", sa.Text(), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("fencing_token", sa.BigInteger(), nullable=False),
    sa.Column("worker_id", sa.Text()),
    sa.Column("attempt_json", JSONB, nullable=False),
    sa.Column("started_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("completed_at", UTC_TIMESTAMP),
    sa.UniqueConstraint("job_id", "attempt_number"),
)

prepared_knowledge_publications = sa.Table(
    "prepared_knowledge_publications",
    metadata,
    sa.Column("validation_id", sa.Text(), primary_key=True),
    sa.Column("operation_id", sa.Text(), nullable=False, unique=True),
    sa.Column("attempt_id", sa.Text(), nullable=False, unique=True),
    sa.Column("fencing_token", sa.BigInteger(), nullable=False),
    sa.Column("source_id", sa.Text(), nullable=False),
    sa.Column("source_draft_version_id", sa.Text(), nullable=False),
    sa.Column("candidate_digest", sa.String(64), nullable=False),
    sa.Column("generation_id", sa.Text(), nullable=False),
    sa.Column("manifest_sha256", sa.String(64), nullable=False),
    sa.Column("staged_projection_id", sa.Text(), nullable=False),
    sa.Column("attestation_sha256", sa.String(64), nullable=False),
    sa.Column("smoke_result_sha256", sa.String(64), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("prepared_json", JSONB, nullable=False),
    sa.Column("prepared_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("consumed_at", UTC_TIMESTAMP),
    sa.UniqueConstraint("source_id", "fencing_token"),
)

hybrid_ingestion_jobs = sa.Table(
    "hybrid_ingestion_jobs",
    metadata,
    sa.Column("job_id", UUID, primary_key=True),
    sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
    sa.Column("source_id", sa.Text(), nullable=False),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("revision_id", UUID, nullable=False),
    sa.Column("request_identity", sa.Text(), nullable=False),
    sa.Column("request_sha256", sa.String(64), nullable=False),
    sa.Column("request_json", JSONB, nullable=False),
    sa.Column("filename", sa.Text(), nullable=False),
    sa.Column("uploaded_by", sa.Text(), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("fencing_token", sa.BigInteger(), nullable=False),
    sa.Column("worker_id", sa.Text()),
    sa.Column("auto_retry_count", sa.Integer(), nullable=False),
    sa.Column("max_auto_retries", sa.Integer(), nullable=False),
    sa.Column("next_attempt_initiation", sa.Text(), nullable=False),
    sa.Column("next_attempt_at", UTC_TIMESTAMP),
    sa.Column("claimed_at", UTC_TIMESTAMP),
    sa.Column("lease_expires_at", UTC_TIMESTAMP),
    sa.Column("safe_reason", sa.Text()),
    sa.Column("failure_code", sa.Text()),
    sa.Column("failure_classification", sa.Text()),
    sa.Column("result_json", JSONB),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("completed_at", UTC_TIMESTAMP),
    sa.Column("cancel_requested_at", UTC_TIMESTAMP),
    sa.Column("cancel_requested_by", sa.Text()),
    sa.Column("cancelled_at", UTC_TIMESTAMP),
    sa.UniqueConstraint("source_id", "document_id", "revision_id"),
    sa.CheckConstraint(
        "next_attempt_initiation IN ('automatic','manual')",
        name="hybrid_ingestion_jobs_attempt_initiation",
    ),
)

hybrid_document_candidates = sa.Table(
    "hybrid_document_candidates",
    metadata,
    sa.Column("source_id", sa.Text(), primary_key=True),
    sa.Column("document_id", UUID, primary_key=True),
    sa.Column("candidate_revision_id", UUID),
    sa.Column("pending_revision_id", UUID),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.CheckConstraint(
        "candidate_revision_id IS NOT NULL OR pending_revision_id IS NOT NULL",
        name="hybrid_document_candidate_has_revision",
    ),
    sa.CheckConstraint(
        "candidate_revision_id IS NULL OR pending_revision_id IS NULL "
        "OR candidate_revision_id <> pending_revision_id",
        name="hybrid_document_candidate_distinct_revisions",
    ),
    sa.ForeignKeyConstraint(
        ["source_id", "document_id", "candidate_revision_id"],
        [
            "hybrid_ingestion_jobs.source_id",
            "hybrid_ingestion_jobs.document_id",
            "hybrid_ingestion_jobs.revision_id",
        ],
        ondelete="RESTRICT",
        name="hybrid_document_candidate_selected_job",
    ),
    sa.ForeignKeyConstraint(
        ["source_id", "document_id", "pending_revision_id"],
        [
            "hybrid_ingestion_jobs.source_id",
            "hybrid_ingestion_jobs.document_id",
            "hybrid_ingestion_jobs.revision_id",
        ],
        ondelete="RESTRICT",
        name="hybrid_document_candidate_pending_job",
    ),
)

hybrid_metadata_reviews = sa.Table(
    "hybrid_metadata_reviews",
    metadata,
    sa.Column("source_id", sa.Text(), primary_key=True),
    sa.Column("review_id", sa.Text(), primary_key=True),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("revision_id", UUID, nullable=False),
    sa.Column("review_version", sa.Integer(), nullable=False),
    sa.Column("review_identity", sa.String(64), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("publication_blocked", sa.Boolean(), nullable=False),
    sa.Column("review_json", JSONB, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
)

hybrid_metadata_import_jobs = sa.Table(
    "hybrid_metadata_import_jobs",
    metadata,
    sa.Column("import_job_id", UUID, primary_key=True),
    sa.Column("operation_id", sa.Text(), nullable=False, unique=True),
    sa.Column("source_id", sa.Text(), nullable=False),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("revision_id", UUID, nullable=False),
    sa.Column("source_revision", sa.BigInteger(), nullable=False),
    sa.Column("request_sha256", sa.String(64), nullable=False),
    sa.Column("filename", sa.Text(), nullable=False),
    sa.Column("original_ref_json", JSONB, nullable=False),
    sa.Column("content_sha256", sa.String(64), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("fencing_token", sa.BigInteger(), nullable=False),
    sa.Column("worker_id", sa.Text()),
    sa.Column("claimed_at", UTC_TIMESTAMP),
    sa.Column("lease_expires_at", UTC_TIMESTAMP),
    sa.Column("failure_code", sa.Text()),
    sa.Column("safe_reason", sa.Text()),
    sa.Column("result_import_id", sa.Text()),
    sa.Column("created_by", sa.Text(), nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("completed_at", UTC_TIMESTAMP),
)

hybrid_publication_preparation_jobs = sa.Table(
    "hybrid_publication_preparation_jobs",
    metadata,
    sa.Column("preparation_job_id", UUID, primary_key=True),
    sa.Column("operation_id", sa.Text(), nullable=False, unique=True),
    sa.Column("validation_id", sa.Text(), nullable=False, unique=True),
    sa.Column("source_id", sa.Text(), nullable=False),
    sa.Column("source_revision", sa.BigInteger(), nullable=False),
    sa.Column("source_draft_version_id", sa.Text(), nullable=False),
    sa.Column("smoke_query", sa.Text(), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("fencing_token", sa.BigInteger(), nullable=False),
    sa.Column("worker_id", sa.Text()),
    sa.Column("claimed_at", UTC_TIMESTAMP),
    sa.Column("lease_expires_at", UTC_TIMESTAMP),
    sa.Column("prepared_commit_json", JSONB),
    sa.Column("failure_code", sa.Text()),
    sa.Column("safe_reason", sa.Text()),
    sa.Column("created_by", sa.Text(), nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("completed_at", UTC_TIMESTAMP),
)
