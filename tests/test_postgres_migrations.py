from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from proof_agent.configuration.hybrid_migrations import apply_hybrid_migrations
from proof_agent.capabilities.persistence.postgres.database import (
    MIGRATION_LOCK_KEY,
    DatabaseSchemaTooNewError,
    MigrationLockUnavailableError,
    check_database,
    current_revision,
    head_revision,
    upgrade_database,
)
from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_repository import (
    PostgresKnowledgeSourceOperationRepository,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
)
pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _upgrade_to_revision(postgres_dsn: str, revision: str) -> None:
    config = Config()
    config.set_main_option(
        "script_location",
        "proof_agent/capabilities/persistence/postgres/migrations",
    )
    engine = create_engine(postgres_dsn)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def test_upgrade_empty_database_to_head_and_repeat(postgres_dsn: str) -> None:
    expected_tables = {
        "active_agent_versions",
        "agent_drafts",
        "agent_versions",
        "agent_version_shared_asset_refs",
        "audit_events",
        "case_memory_records",
        "configuration_validations",
        "conversation_turns",
        "conversations",
        "knowledge_snapshots",
        "knowledge_ingestion_attempts",
        "knowledge_source_idempotency",
        "knowledge_source_operations",
        "knowledge_source_versions",
        "knowledge_sources",
        "hybrid_document_candidates",
        "hybrid_metadata_review_decisions",
        "hybrid_metadata_review_sets",
        "hybrid_metadata_reviews",
        "hybrid_metadata_import_jobs",
        "hybrid_publication_preparation_jobs",
        "hybrid_knowledge_source_authority",
        "hybrid_knowledge_publication",
        "hybrid_projection_attestation",
        "insurance_metadata_profiles",
        "insurance_metadata_profile_revisions",
        "knowledge_source_metadata_bindings",
        "legacy_hybrid_metadata_reviews",
        "model_connection_versions",
        "model_connection_credentials",
        "model_connections",
        "prepared_knowledge_publications",
        "release_registry",
        "run_attempts",
        "runs",
        "tool_source_versions",
        "tool_sources",
    }

    first = upgrade_database(postgres_dsn)
    second = upgrade_database(postgres_dsn)

    engine = create_engine(postgres_dsn)
    try:
        assert first == head_revision()
        assert second == first
        assert current_revision(engine) == first
        inspector = inspect(engine)
        assert expected_tables <= set(inspector.get_table_names())
        review_columns = {
            column["name"] for column in inspector.get_columns("hybrid_metadata_reviews")
        }
        assert {
            "review_set_id",
            "profile_revision_id",
            "scope",
            "canonical_anchor",
            "current",
            "approved_metadata_revision_id",
        } <= review_columns
    finally:
        engine.dispose()


def test_upgrade_adopts_real_historical_hybrid_ddl(postgres_dsn: str) -> None:
    psycopg_dsn = postgres_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    historical = apply_hybrid_migrations(psycopg_dsn)

    revision = upgrade_database(postgres_dsn)

    engine = create_engine(postgres_dsn)
    try:
        tables = set(inspect(engine).get_table_names())
        assert historical.migration_name == "0001_hybrid_knowledge.sql"
        assert revision == head_revision()
        assert "hybrid_knowledge_publication" in tables
        assert "agent_drafts" in tables
        assert check_database(engine).current_revision == revision
    finally:
        engine.dispose()


def test_upgrade_adopts_released_model_credential_revision(postgres_dsn: str) -> None:
    _upgrade_to_revision(postgres_dsn, "0011_model_credential")

    engine = create_engine(postgres_dsn)
    try:
        assert current_revision(engine) == "0011_model_credential"
        assert "model_connection_credentials" in inspect(engine).get_table_names()
        assert "production_worker_role_activations" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    revision = upgrade_database(
        postgres_dsn,
        target_revision=head_revision(),
        expand_only=True,
    )

    engine = create_engine(postgres_dsn)
    try:
        tables = set(inspect(engine).get_table_names())
        assert revision == head_revision()
        assert current_revision(engine) == revision
        assert "model_connection_credentials" in tables
        assert "production_worker_role_activations" in tables
    finally:
        engine.dispose()


def test_ingestion_operation_link_migration_backfills_terminal_failure(
    postgres_dsn: str,
) -> None:
    _upgrade_to_revision(postgres_dsn, "0018_publication_preparation")
    engine = create_engine(postgres_dsn)
    now = datetime(2026, 7, 28, 8, tzinfo=UTC)
    source_id = f"ks_{uuid4().hex}"
    job_id = uuid4()
    operation_id = f"ksop_{uuid4().hex}"
    try:
        PostgresKnowledgeAssetRepository(engine).save_source(
            KnowledgeSource(
                source_id=source_id,
                name="Migration backfill",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ),
            expected_revision=0,
        )
        PostgresKnowledgeSourceOperationRepository(engine).save(
            KnowledgeSourceOperation(
                operation_id=operation_id,
                source_id=source_id,
                command="upload_document",
                status="queued",
                stage="ingestion_queued",
                source_revision=1,
                poll_after_ms=1_000,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO hybrid_ingestion_jobs (
                        job_id, idempotency_key, source_id, document_id, revision_id,
                        request_identity, request_sha256, request_json, filename,
                        uploaded_by, state, fencing_token, worker_id, auto_retry_count,
                        max_auto_retries, next_attempt_initiation, next_attempt_at,
                        claimed_at, lease_expires_at, safe_reason, failure_code,
                        failure_classification, result_json, created_at, updated_at,
                        completed_at, cancel_requested_at, cancel_requested_by, cancelled_at
                    ) VALUES (
                        :job_id, :idempotency_key, :source_id, :document_id, :revision_id,
                        :request_identity, :request_sha256, '{}'::jsonb, 'failed.pdf',
                        'operator-1', 'FAILED', 1, NULL, 0, 2, 'automatic', NULL,
                        NULL, NULL, :safe_reason, 'PA_HYBRID_WORKER_INTEGRITY',
                        'non_recoverable', NULL, :created_at, :updated_at,
                        :completed_at, NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "job_id": job_id,
                    "idempotency_key": str(job_id),
                    "source_id": source_id,
                    "document_id": uuid4(),
                    "revision_id": uuid4(),
                    "request_identity": f"{source_id}:document:revision",
                    "request_sha256": "f" * 64,
                    "safe_reason": (
                        "Hybrid artifact build failed deterministic integrity validation."
                    ),
                    "created_at": now,
                    "updated_at": now + timedelta(seconds=1),
                    "completed_at": now + timedelta(seconds=1),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO audit_events (
                        audit_id, category, event_type, outcome, actor_json,
                        target_type, target_id, metadata_json, occurred_at, expires_at
                    ) VALUES (
                        :audit_id, 'operations', 'hybrid_pdf.upload_document.admitted',
                        'succeeded', '{}'::jsonb, 'hybrid_ingestion_job', :target_id,
                        jsonb_build_object('operation_id', CAST(:operation_id AS text)),
                        :occurred_at, :expires_at
                    )
                    """
                ),
                {
                    "audit_id": uuid4(),
                    "target_id": str(job_id),
                    "operation_id": operation_id,
                    "occurred_at": now,
                    "expires_at": now + timedelta(days=365),
                },
            )
    finally:
        engine.dispose()

    _upgrade_to_revision(postgres_dsn, "0019_ingestion_operation_link")

    engine = create_engine(postgres_dsn)
    try:
        with engine.connect() as connection:
            linked = connection.execute(
                text(
                    "SELECT operation_id FROM hybrid_ingestion_jobs WHERE job_id=:job_id"
                ),
                {"job_id": job_id},
            ).scalar_one()
        operation = PostgresKnowledgeSourceOperationRepository(engine).get(operation_id)
        assert linked == operation_id
        assert operation is not None
        assert operation.status == "failed"
        assert operation.stage == "ingestion_failed"
        assert operation.outcome_code == "hybrid_ingestion_integrity_failed"
        assert operation.completed_at is not None
    finally:
        engine.dispose()


def test_upgrade_uses_one_advisory_lock(postgres_dsn: str) -> None:
    engine = create_engine(postgres_dsn)
    try:
        with engine.connect() as blocker:
            transaction = blocker.begin()
            blocker.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": MIGRATION_LOCK_KEY},
            )
            with pytest.raises(MigrationLockUnavailableError):
                upgrade_database(postgres_dsn, lock_timeout_seconds=0.05)
            transaction.rollback()
    finally:
        engine.dispose()


def test_check_rejects_database_schema_newer_than_application(postgres_dsn: str) -> None:
    upgrade_database(postgres_dsn)
    engine = create_engine(postgres_dsn)
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='future_revision'"))
        with pytest.raises(DatabaseSchemaTooNewError):
            check_database(engine)
    finally:
        engine.dispose()


def test_database_module_has_no_production_downgrade_api() -> None:
    from proof_agent.capabilities.persistence.postgres import database

    assert not hasattr(database, "downgrade_database")


def test_alembic_revision_identifiers_fit_the_installed_version_column() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(Config("alembic.ini"))

    assert all(len(revision.revision) <= 32 for revision in scripts.walk_revisions())
