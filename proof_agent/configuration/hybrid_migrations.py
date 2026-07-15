"""Explicit PostgreSQL schema installation for the Hybrid Knowledge authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any


_MIGRATION_LOCK_ID = 7_215_081_946_311_520_026


@dataclass(frozen=True, slots=True)
class HybridMigrationResult:
    migration_name: str
    sha256: str


def apply_hybrid_migrations(
    dsn: str,
    *,
    connect: Callable[..., Any] | None = None,
    migration_path: Path | None = None,
) -> HybridMigrationResult:
    """Apply the idempotent schema under one transaction-scoped PostgreSQL advisory lock."""

    if type(dsn) is not str or not dsn.strip():
        raise ValueError("Hybrid PostgreSQL DSN must be non-empty")
    path = migration_path or Path(__file__).with_name("migrations") / "0001_hybrid_knowledge.sql"
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if connect is None:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - optional production dependency
            raise RuntimeError("Hybrid migrations require the 'production' extra") from exc
        connect = psycopg.connect
    with connect(dsn.strip()) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
        connection.execute(content.decode("utf-8"), prepare=False)
    return HybridMigrationResult(migration_name=path.name, sha256=digest)


__all__ = ["HybridMigrationResult", "apply_hybrid_migrations"]
