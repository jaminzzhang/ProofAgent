from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError


MIGRATION_LOCK_KEY: Final = int.from_bytes(b"PROOFAGE", byteorder="big", signed=True)
_MIGRATIONS_DIR = Path(__file__).with_name("migrations")
EXPAND_ONLY_REVISIONS: Final = frozenset(
    {
        "0001_foundation",
        "0002_hybrid_knowledge_authority",
        "0003_identity_security",
        "0004_oidc_sessions",
        "0005_egress_policy",
        "0006_artifact_authority",
        "0007_run_queue_executor",
        "0008_run_receipt_outcome",
        "0009_hybrid_ingestion_jobs",
        "0010_hybrid_knowledge_workflow",
        "0011_worker_role_leases",
        "0012_model_credential",
    }
)


class DatabaseConfigurationError(ValueError):
    """The configured production database URL is not PostgreSQL/psycopg."""


class DatabaseUpgradeRequiredError(RuntimeError):
    """The database is empty or behind the application migration head."""


class DatabaseSchemaTooNewError(RuntimeError):
    """The database migration identity is unknown to this application build."""


class MigrationLockUnavailableError(RuntimeError):
    """Another process owns the global Proof Agent migration lock."""


class UnsafeMigrationError(RuntimeError):
    """The requested migration path is not declared expand-only."""


@dataclass(frozen=True)
class DatabaseCheckResult:
    current_revision: str
    head_revision: str


def create_postgres_engine(dsn: str) -> Engine:
    """Create the production SQLAlchemy engine with an explicit psycopg driver."""

    url = _normalize_postgres_url(dsn)
    return create_engine(url, pool_pre_ping=True)


def _normalize_postgres_url(dsn: str) -> URL:
    if not dsn.strip():
        raise DatabaseConfigurationError("PostgreSQL DSN is required")
    url = make_url(dsn)
    if url.get_backend_name() != "postgresql":
        raise DatabaseConfigurationError("production persistence requires PostgreSQL")
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.get_driver_name() != "psycopg":
        raise DatabaseConfigurationError("production persistence requires psycopg 3")
    return url


def head_revision() -> str:
    revision = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic migration head is missing")
    return revision


def current_revision(engine: Engine) -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as connection:
        value = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    return str(value)


def check_database(engine_or_dsn: Engine | str) -> DatabaseCheckResult:
    """Fail closed unless the database is exactly compatible with this build."""

    engine, owns_engine = _resolve_engine(engine_or_dsn)
    try:
        current = current_revision(engine)
        head = head_revision()
        if current is None:
            raise DatabaseUpgradeRequiredError("database has not been migrated")
        if current == head:
            return DatabaseCheckResult(current_revision=current, head_revision=head)
        script = ScriptDirectory.from_config(_alembic_config())
        try:
            known = script.get_revision(current)
        except CommandError as exc:
            raise DatabaseSchemaTooNewError(
                f"database schema revision {current!r} is unknown to this build"
            ) from exc
        if known is None:
            raise DatabaseSchemaTooNewError(
                f"database schema revision {current!r} is unknown to this build"
            )
        raise DatabaseUpgradeRequiredError(
            f"database schema revision {current!r} is behind application head {head!r}"
        )
    finally:
        if owns_engine:
            engine.dispose()


def upgrade_database(
    dsn: str,
    *,
    lock_timeout_seconds: float = 30.0,
    target_revision: str | None = None,
    expand_only: bool = False,
) -> str:
    """Run locked expand-only migrations; application startup never calls this function."""

    if lock_timeout_seconds <= 0:
        raise ValueError("lock_timeout_seconds must be positive")
    target = target_revision or head_revision()
    if target != head_revision():
        raise UnsafeMigrationError(
            "migration target must equal the schema head packaged in this image"
        )
    engine = create_postgres_engine(dsn)
    try:
        installed_revision = current_revision(engine)
        if expand_only:
            _require_expand_only_path(installed_revision, target)
        with engine.connect() as connection, connection.begin():
            connection.execute(
                text("SELECT set_config('lock_timeout', :timeout, true)"),
                {"timeout": f"{max(1, int(lock_timeout_seconds * 1000))}ms"},
            )
            try:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": MIGRATION_LOCK_KEY},
                )
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) == "55P03":
                    raise MigrationLockUnavailableError(
                        "timed out waiting for the PostgreSQL migration lock"
                    ) from exc
                raise
            config = _alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, target)
        revision = current_revision(engine)
        if revision is None:
            raise RuntimeError("migration completed without an Alembic revision")
        return revision
    finally:
        engine.dispose()


def _require_expand_only_path(current: str | None, target: str) -> None:
    scripts = ScriptDirectory.from_config(_alembic_config())
    try:
        revisions = tuple(scripts.iterate_revisions(target, current))
    except CommandError as exc:
        raise UnsafeMigrationError("migration path is not known to this image") from exc
    unsafe = tuple(
        revision.revision
        for revision in revisions
        if revision.revision not in EXPAND_ONLY_REVISIONS
    )
    if unsafe:
        raise UnsafeMigrationError(
            "migration path contains a revision not declared expand-only: "
            + ", ".join(unsafe)
        )


def _resolve_engine(engine_or_dsn: Engine | str) -> tuple[Engine, bool]:
    if isinstance(engine_or_dsn, str):
        return create_postgres_engine(engine_or_dsn), True
    return engine_or_dsn, False


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return config
