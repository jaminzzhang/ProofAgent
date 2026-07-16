"""Adopt the existing Hybrid Knowledge authority into the unified schema chain."""

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "0002_hybrid_knowledge_authority"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    migration_path = (
        Path(__file__).resolve().parents[5]
        / "configuration"
        / "migrations"
        / "0001_hybrid_knowledge.sql"
    )
    statements = migration_path.read_text(encoding="utf-8").strip()
    if statements.startswith("BEGIN;"):
        statements = statements.removeprefix("BEGIN;").lstrip()
    if statements.endswith("COMMIT;"):
        statements = statements.removesuffix("COMMIT;").rstrip()
    bind = op.get_bind()
    driver_connection = bind.connection.driver_connection
    if driver_connection is None:
        raise RuntimeError("Alembic PostgreSQL driver connection is unavailable")
    driver_connection.execute(statements, prepare=False)


def downgrade() -> None:
    raise RuntimeError("Production database downgrades are not supported")
