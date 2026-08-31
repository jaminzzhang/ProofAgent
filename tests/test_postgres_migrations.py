from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from proof_agent.capabilities.persistence.postgres.database import (
    MIGRATION_LOCK_KEY,
    DatabaseSchemaTooNewError,
    MigrationLockUnavailableError,
    UnsafeMigrationError,
    check_database,
    current_revision,
    head_revision,
    upgrade_database,
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
        "formal_agent_publication_commands",
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
        formal_command_columns = {
            column["name"] for column in inspector.get_columns("formal_agent_publication_commands")
        }
        assert {
            "execution_fencing_token",
            "lease_owner",
            "lease_expires_at",
            "formal_candidate_sha256",
            "knowledge_release_candidate_sha256",
            "candidate_checkpointed_at",
        } <= formal_command_columns
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

    with pytest.raises(UnsafeMigrationError, match="not declared expand-only"):
        upgrade_database(
            postgres_dsn,
            target_revision=head_revision(),
            expand_only=True,
        )

    revision = upgrade_database(
        postgres_dsn,
        target_revision=head_revision(),
        metadata_v2_cutover=True,
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
