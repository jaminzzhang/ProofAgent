from __future__ import annotations

import pytest
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
pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


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
        "hybrid_metadata_import_jobs",
        "hybrid_publication_preparation_jobs",
        "hybrid_knowledge_source_authority",
        "hybrid_knowledge_publication",
        "hybrid_projection_attestation",
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
        assert expected_tables <= set(inspect(engine).get_table_names())
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
