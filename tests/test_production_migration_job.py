from __future__ import annotations

import base64
import hashlib
import json
import inspect
from pathlib import Path
import subprocess
import sys
from datetime import UTC, datetime

from alembic.config import Config
from alembic.script import ScriptDirectory
from click import unstyle
from typer.testing import CliRunner
import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap import production_roles
from proof_agent.capabilities.persistence.postgres import database
from proof_agent.delivery.cli import app
from proof_agent.deployment import load_deployment_compatibility_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SLOT_COMPOSE = PROJECT_ROOT / "deploy/production/slot/compose.yaml"
LOCAL_PRODUCTION_COMPOSE = PROJECT_ROOT / "docker-compose.production-local.yml"


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


def test_local_production_uses_the_same_locked_expand_only_migration_contract() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8"))["services"]

    assert services["database-migrate"]["command"] == [
        "database",
        "upgrade",
        "--locked",
        "--expand-only",
        "--target",
        database.head_revision(),
    ]


def test_default_stack_has_no_kss_roles_or_image() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text())["services"]
    assert not any("kss" in name for name in services)
    assert "KSS_IMAGE" not in str(services)
    assert "postgres" in services and "run-executor" in services


def test_default_gateway_removes_kss_upstreams_but_preserves_core_tls() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text())["services"]
    assert "127.0.0.1:8444:8444" not in services["gateway"]["ports"]
    nginx = (PROJECT_ROOT / "docker/production-local/nginx.conf").read_text()
    assert "kss-api" not in nginx and "/kss/" not in nginx
    assert "listen 8443 ssl" in nginx and "listen 8200 ssl" in nginx


def test_default_verifier_checks_core_dependencies_without_kss_calls() -> None:
    verifier = (PROJECT_ROOT / "scripts/production-local-verify.sh").read_text()
    assert "8444" not in verifier and "knowledge_source_service" not in verifier
    assert "verify_runtime.py" not in verifier
    assert "local/proof-agent-local" in verifier
    assert "security_configuration_state" in verifier
    assert "/oidc/realms/" in verifier and "/livez" in verifier
    assert "core infrastructure checks only" in verifier


def test_local_production_query_authority_verifier_requires_one_explicit_release() -> None:
    verifier = (PROJECT_ROOT / "scripts/production-local-verify-query-authority.sh").read_text(
        encoding="utf-8"
    )

    assert "EXACT_RELEASE_ID=$1" in verifier
    assert "replace-with-exact-kss-release-id" in verifier
    assert 'PROOF_AGENT_KSS_RELEASE_ID="$EXACT_RELEASE_ID"' in verifier
    assert "/opt/proof-agent-local/verify_kss_query_authority.py" in verifier
    assert '"$ROOT_DIR/scripts/production-local-up.sh"' not in verifier
    assert "down" not in verifier


def test_local_production_formal_preflight_requires_one_exact_draft_revision() -> None:
    verifier = (
        PROJECT_ROOT / "scripts/production-local-verify-formal-publication-preflight.sh"
    ).read_text(encoding="utf-8")

    assert "EXACT_AGENT_ID=$1" in verifier
    assert "EXACT_DRAFT_ID=$2" in verifier
    assert "EXACT_DRAFT_REVISION=$3" in verifier
    assert 'PROOF_AGENT_PREFLIGHT_AGENT_ID="$EXACT_AGENT_ID"' in verifier
    assert 'PROOF_AGENT_PREFLIGHT_DRAFT_ID="$EXACT_DRAFT_ID"' in verifier
    assert 'PROOF_AGENT_PREFLIGHT_DRAFT_REVISION="$EXACT_DRAFT_REVISION"' in verifier
    assert "/opt/proof-agent-local/verify_formal_publication_preflight.py" in verifier
    assert '"$ROOT_DIR/scripts/production-local-up.sh"' not in verifier
    assert "formal-publications" not in verifier
    assert "down" not in verifier


def test_local_production_draft_memory_disable_requires_one_exact_cas_target() -> None:
    command = (PROJECT_ROOT / "scripts/production-local-disable-draft-memory.sh").read_text(
        encoding="utf-8"
    )

    assert "EXACT_AGENT_ID=$1" in command
    assert "EXACT_DRAFT_ID=$2" in command
    assert "EXPECTED_DRAFT_REVISION=$3" in command
    assert 'PROOF_AGENT_DRAFT_MEMORY_AGENT_ID="$EXACT_AGENT_ID"' in command
    assert 'PROOF_AGENT_DRAFT_MEMORY_DRAFT_ID="$EXACT_DRAFT_ID"' in command
    assert 'PROOF_AGENT_DRAFT_MEMORY_EXPECTED_REVISION="$EXPECTED_DRAFT_REVISION"' in command
    assert "/opt/proof-agent-local/disable_draft_memory.py" in command
    assert '"$ROOT_DIR/scripts/production-local-up.sh"' not in command
    assert "formal-publications" not in command
    assert "down" not in command


def test_local_production_has_no_embedded_hybrid_bootstrap() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8"))["services"]

    assert "reference-metadata-bootstrap" not in services
    assert "hybrid-migrate" not in services
    assert "knowledge-worker" not in services


def test_local_production_supplies_current_api_startup_contract() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8"))["services"]
    environment = services["api"]["environment"]

    assert environment["PROOF_AGENT_IMAGE_DIGEST"].startswith("${PROOF_AGENT_IMAGE_DIGEST:-")
    assert environment["PROOF_AGENT_DEPLOYMENT_SLOT"] == "blue"
    assert environment["PROOF_AGENT_ACTIVATION_STATE"] == "active"
    assert environment["PROOF_AGENT_DEPLOYMENT_COMPATIBILITY_MANIFEST"] == (
        "/run/proof-agent-config/deployment-compatibility-manifest.json"
    )
    assert environment["PROOF_AGENT_RELEASE_BUNDLE_CACHE_DIR"] == (
        "/var/lib/proof-agent/release-bundle-cache"
    )
    assert environment["PROOF_AGENT_SECRET_PROBE_HANDLE"] in json.loads(
        environment["PROOF_AGENT_SECRET_HANDLE_LOCATORS_JSON"]
    )
    trusted_keys = json.loads(environment["PROOF_AGENT_RELEASE_TRUSTED_ED25519_KEYS_JSON"])
    assert all(len(base64.b64decode(value, validate=True)) == 32 for value in trusted_keys.values())
    assert any(
        str(entry).startswith("/var/lib/proof-agent/release-bundle-cache:")
        for entry in services["api"]["tmpfs"]
    )
    assert any(
        str(entry).endswith(":/run/proof-agent-config/deployment-compatibility-manifest.json:ro")
        for entry in services["api"]["volumes"]
    )


def test_default_api_environment_does_not_resolve_kss_operator_credentials() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text())["services"]
    environment = services["api"]["environment"]
    assert not any(key.startswith("PROOF_AGENT_KSS_") for key in environment)
    locators = json.loads(environment["PROOF_AGENT_SECRET_HANDLE_LOCATORS_JSON"])
    assert "knowledge/source-service/operator" not in locators
    assert "oidc-client-secret" in locators and "csrf-key" in locators


def test_default_vault_initialization_does_not_seed_kss_credentials() -> None:
    init = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text())["services"]["vault-init"]
    assert not any(key.startswith("KSS_") for key in init["environment"])
    assert "knowledge-source-service" not in init["command"][0]
    assert "chmod 0400" in init["command"][0]


def test_default_executor_keeps_core_authorities_without_legacy_grant_clients() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text())["services"]
    executor = services["run-executor"]
    assert "reference-client" not in str(executor)
    assert "PROOF_AGENT_POSTGRES_DSN" in executor["environment"]
    assert "PROOF_AGENT_VAULT_AGENT_TOKEN_FILE" in executor["environment"]


def test_local_production_compatibility_fixture_is_fresh_and_explicitly_local(
    tmp_path: Path,
) -> None:
    output = tmp_path / "deployment-compatibility-manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(
                PROJECT_ROOT
                / "docker/production-local/generate_deployment_compatibility_manifest.py"
            ),
            str(output),
        ],
        check=True,
    )

    manifest = load_deployment_compatibility_manifest(
        output,
        checked_at=datetime.now(UTC),
    )

    assert all("Local Harness" in component.product for component in manifest.components)


def test_production_upgrade_cli_requires_explicit_safety_contract() -> None:
    result = CliRunner().invoke(app, ["database", "upgrade", "--help"])

    assert result.exit_code == 0
    help_text = unstyle(result.stdout)
    assert "--locked" in help_text
    assert "--expand-only" in help_text
    assert "--target" in help_text


def test_direct_cutover_migrations_are_not_declared_expand_only() -> None:
    config = Config()
    config.set_main_option(
        "script_location",
        str(PROJECT_ROOT / "proof_agent/capabilities/persistence/postgres/migrations"),
    )
    scripts = ScriptDirectory.from_config(config)

    shipped = {script.revision for script in scripts.walk_revisions()}

    assert database.EXPAND_ONLY_REVISIONS <= shipped
    assert "0020_metadata_review_v2" not in database.EXPAND_ONLY_REVISIONS
    assert "0021_metadata_workbook_v2" not in database.EXPAND_ONLY_REVISIONS
    assert database.METADATA_V2_DIRECT_CUTOVER_REVISIONS == frozenset(
        {"0020_metadata_review_v2", "0021_metadata_workbook_v2"}
    )


def test_expand_only_upgrade_rejects_metadata_v2_cutover_path() -> None:
    import pytest

    with pytest.raises(
        database.UnsafeMigrationError,
        match="0020_metadata_review_v2, 0021_metadata_workbook_v2",
    ):
        database._require_expand_only_path(  # noqa: SLF001 - safety contract regression
            "0019_ingestion_operation_link",
            "0021_metadata_workbook_v2",
        )


def test_metadata_v2_cutover_mode_rejects_a_path_without_the_direct_transition() -> None:
    import pytest

    with pytest.raises(database.UnsafeMigrationError, match="does not contain"):
        database._require_metadata_v2_direct_cutover_path(  # noqa: SLF001
            "0021_metadata_workbook_v2",
            "0021_metadata_workbook_v2",
        )


def test_production_upgrade_rejects_missing_safety_acknowledgements(monkeypatch) -> None:
    monkeypatch.setenv("PROOF_AGENT_MODE", "production")

    result = CliRunner().invoke(
        app,
        ["database", "upgrade", "--dsn", "postgresql://proofagent@db/proofagent"],
    )

    assert result.exit_code == 2
    assert "--locked --expand-only --target" in result.stderr


def test_metadata_v2_cutover_requires_a_stopped_stack_and_exact_backup_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROOF_AGENT_MODE", "production")

    result = CliRunner().invoke(
        app,
        [
            "database",
            "cutover-metadata-v2",
            "--dsn",
            "postgresql://proofagent@db/proofagent",
            "--target",
            database.head_revision(),
        ],
    )

    assert result.exit_code == 2
    assert "maintenance-window-authorized" in result.stderr
    assert "application-writes-stopped" in result.stderr
    assert "workers-stopped" in result.stderr
    assert "backup-evidence" in result.stderr


def test_metadata_v2_cutover_runs_the_non_expand_migration_only_after_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence = tmp_path / "pre-cutover-backup-evidence.json"
    evidence.write_bytes(b'{"restore_drill":"passed"}\n')
    evidence_sha256 = hashlib.sha256(evidence.read_bytes()).hexdigest()
    observed: dict[str, object] = {}

    def upgrade(
        dsn: str,
        *,
        lock_timeout_seconds: float,
        target_revision: str,
        expand_only: bool,
        metadata_v2_cutover: bool,
    ) -> str:
        observed.update(
            dsn=dsn,
            lock_timeout_seconds=lock_timeout_seconds,
            target_revision=target_revision,
            expand_only=expand_only,
            metadata_v2_cutover=metadata_v2_cutover,
        )
        return target_revision

    monkeypatch.setattr(database, "upgrade_database", upgrade)
    result = CliRunner().invoke(
        app,
        [
            "database",
            "cutover-metadata-v2",
            "--dsn",
            "postgresql://proofagent@db/proofagent",
            "--locked",
            "--maintenance-window-authorized",
            "--application-writes-stopped",
            "--workers-stopped",
            "--backup-evidence",
            str(evidence),
            "--backup-evidence-sha256",
            evidence_sha256,
            "--target",
            database.head_revision(),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert observed["target_revision"] == database.head_revision()
    assert observed["expand_only"] is False
    assert observed["metadata_v2_cutover"] is True
    assert json.loads(result.stdout) == {
        "backup_evidence_sha256": evidence_sha256,
        "revision": database.head_revision(),
        "status": "metadata_v2_cutover_completed",
    }


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
