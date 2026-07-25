from __future__ import annotations

import inspect
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from typer.testing import CliRunner
import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap import production_roles
from proof_agent.capabilities.persistence.postgres import database
from proof_agent.delivery.cli import app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SLOT_COMPOSE = PROJECT_ROOT / "deploy/production/slot/compose.yaml"


def _compose() -> dict[str, object]:
    return yaml.safe_load(SLOT_COMPOSE.read_text(encoding="utf-8"))


def test_candidate_image_exposes_one_nonrestarting_explicit_migration_job() -> None:
    services = _compose()["services"]
    migrate = services["migrate"]

    assert migrate["image"] == services["api"]["image"]
    assert migrate["profiles"] == ["migration"]
    assert migrate["restart"] == "no"
    assert migrate["command"] == [
        "proof-agent",
        "database",
        "upgrade",
        "--locked",
        "--expand-only",
        "--target",
        "${PROOF_AGENT_RELEASE_SCHEMA:?set the exact candidate schema revision}",
    ]


def test_production_upgrade_cli_requires_explicit_safety_contract() -> None:
    result = CliRunner().invoke(app, ["database", "upgrade", "--help"])

    assert result.exit_code == 0
    assert "--locked" in result.stdout
    assert "--expand-only" in result.stdout
    assert "--target" in result.stdout


def test_every_shipped_migration_is_in_the_reviewed_expand_only_allowlist() -> None:
    config = Config()
    config.set_main_option(
        "script_location",
        str(
            PROJECT_ROOT
            / "proof_agent/capabilities/persistence/postgres/migrations"
        ),
    )
    scripts = ScriptDirectory.from_config(config)

    assert {script.revision for script in scripts.walk_revisions()} == set(
        database.EXPAND_ONLY_REVISIONS
    )


def test_production_upgrade_rejects_missing_safety_acknowledgements(monkeypatch) -> None:
    monkeypatch.setenv("PROOF_AGENT_MODE", "production")

    result = CliRunner().invoke(
        app,
        ["database", "upgrade", "--dsn", "postgresql://proofagent@db/proofagent"],
    )

    assert result.exit_code == 2
    assert "--locked --expand-only --target" in result.stderr


def test_upgrade_rejects_a_target_not_packaged_in_the_image() -> None:
    import pytest

    with pytest.raises(database.UnsafeMigrationError, match="packaged"):
        database.upgrade_database(
            "postgresql://proofagent@db/proofagent",
            target_revision="future_revision",
            expand_only=True,
        )


def test_production_roles_never_upgrade_the_database_implicitly() -> None:
    source = inspect.getsource(production_roles)

    assert "upgrade_database" not in source
    assert "command.upgrade" not in source


def test_database_module_has_no_downgrade_or_contract_migration_api() -> None:
    assert not hasattr(database, "downgrade_database")
    assert not hasattr(database, "contract_database")
