"""Explicit migration runner for the service-owned PostgreSQL schema."""

from __future__ import annotations

import hashlib
from importlib.resources import files
import json

import psycopg


_MIGRATIONS = (
    ("0001_knowledge_queries", "0001_knowledge_queries.sql"),
    ("0002_knowledge_catalog", "0002_knowledge_catalog.sql"),
    ("0003_knowledge_access", "0003_knowledge_access.sql"),
    ("0004_query_result_artifacts", "0004_query_result_artifacts.sql"),
    (
        "0005_release_projection_attestation",
        "0005_release_projection_attestation.sql",
    ),
    ("0006_source_synchronizations", "0006_source_synchronizations.sql"),
)
_MIGRATION_LOCK_ID = 4_934_575_833_127_731_121


def knowledge_service_migration_contract_bytes() -> bytes:
    """Bind the ordered packaged SQL migration set as canonical JSON bytes."""

    migrations = []
    migration_root = files("knowledge_source_service.migrations")
    for revision, resource_name in _MIGRATIONS:
        content = migration_root.joinpath(resource_name).read_bytes()
        migrations.append(
            {
                "length": len(content),
                "resource": resource_name,
                "revision": revision,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return json.dumps(
        {
            "head_revision": _MIGRATIONS[-1][0],
            "migrations": migrations,
            "schema_version": "knowledge-source-service.migration-contract.v1",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def apply_knowledge_service_migrations(dsn: str) -> None:
    """Apply packaged migrations under one transaction-scoped advisory lock."""

    with psycopg.connect(_psycopg_dsn(dsn)) as connection:
        with connection.transaction():
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kss_schema_migrations (
                    revision text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
                )
                """
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (_MIGRATION_LOCK_ID,),
            )
            for revision, resource_name in _MIGRATIONS:
                exists = connection.execute(
                    "SELECT 1 FROM kss_schema_migrations WHERE revision = %s",
                    (revision,),
                ).fetchone()
                if exists is not None:
                    continue
                migration_sql = (
                    files("knowledge_source_service.migrations")
                    .joinpath(resource_name)
                    .read_text(encoding="utf-8")
                )
                connection.execute(migration_sql)
                connection.execute(
                    "INSERT INTO kss_schema_migrations (revision) VALUES (%s)",
                    (revision,),
                )


def _psycopg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


__all__ = [
    "apply_knowledge_service_migrations",
    "knowledge_service_migration_contract_bytes",
]
