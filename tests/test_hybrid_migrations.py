from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from proof_agent.configuration.hybrid_migrations import apply_hybrid_migrations


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, statement: str, params: Any = None, **kwargs: Any) -> None:
        self.calls.append((statement, params if params is not None else kwargs))


def test_hybrid_migration_serializes_and_applies_the_exact_schema(tmp_path: Path) -> None:
    migration = tmp_path / "0001_hybrid_knowledge.sql"
    migration.write_text("CREATE TABLE IF NOT EXISTS authority(id text);", encoding="utf-8")
    connection = _Connection()
    dsns: list[str] = []

    result = apply_hybrid_migrations(
        "postgresql://authority",
        migration_path=migration,
        connect=lambda dsn: (dsns.append(dsn), connection)[1],
    )

    assert dsns == ["postgresql://authority"]
    assert connection.calls[0][0] == "SELECT pg_advisory_xact_lock(%s)"
    assert connection.calls[1][0] == migration.read_text(encoding="utf-8")
    assert result.sha256 == hashlib.sha256(migration.read_bytes()).hexdigest()
