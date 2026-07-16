from __future__ import annotations

from pathlib import Path

import pytest

from proof_agent.bootstrap.application_services import compose_application_persistence
from proof_agent.capabilities.persistence.local import LocalPersistenceBundle
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database


pytest_plugins = ("postgres_fixtures",)


def test_application_persistence_requires_explicit_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PROOF_AGENT_MODE"):
        compose_application_persistence(environment={}, development_root=tmp_path)


def test_production_composition_rejects_missing_dsn_without_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_local_is_created(_cls: object, _root: Path) -> object:
        raise AssertionError("production attempted to instantiate local persistence")

    monkeypatch.setattr(
        LocalPersistenceBundle,
        "create",
        classmethod(fail_if_local_is_created),
    )

    with pytest.raises(ValueError, match="POSTGRES_DSN"):
        compose_application_persistence(environment={"PROOF_AGENT_MODE": "production"})


@pytest.mark.postgres_integration
def test_production_composition_uses_only_checked_postgres(postgres_dsn: str) -> None:
    upgrade_database(postgres_dsn)

    bundle = compose_application_persistence(
        environment={
            "PROOF_AGENT_MODE": "production",
            "PROOF_AGENT_POSTGRES_DSN": postgres_dsn,
        }
    )
    try:
        assert isinstance(bundle, PostgresPersistenceBundle)
        assert bundle.runs.__class__.__module__.endswith(".postgres.run_repository")
        assert bundle.agents.__class__.__module__.endswith(".postgres.agent_repository")
    finally:
        bundle.close()


def test_development_composition_is_explicitly_local(tmp_path: Path) -> None:
    bundle = compose_application_persistence(
        environment={"PROOF_AGENT_MODE": "development"},
        development_root=tmp_path,
    )
    try:
        assert isinstance(bundle, LocalPersistenceBundle)
    finally:
        bundle.close()


def test_production_composition_modules_do_not_import_local_adapters() -> None:
    project_root = Path(__file__).resolve().parents[1]
    production_paths = (
        project_root / "proof_agent/bootstrap/application_services.py",
        *(project_root / "proof_agent/capabilities/persistence/postgres").glob("*.py"),
    )

    for path in production_paths:
        content = path.read_text(encoding="utf-8")
        assert "persistence.local" not in content, path
        assert "LocalAgentConfigurationStore" not in content, path
        assert "RunStore" not in content, path
        assert "ConversationStore" not in content, path
        assert "LocalMemoryStore" not in content, path
