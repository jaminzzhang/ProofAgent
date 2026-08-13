from __future__ import annotations

import base64
import json
import inspect
from pathlib import Path
import subprocess
import sys
from datetime import UTC, datetime

from alembic.config import Config
from alembic.script import ScriptDirectory
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
    services = yaml.safe_load(
        LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    )["services"]

    assert services["database-migrate"]["command"] == [
        "database",
        "upgrade",
        "--locked",
        "--expand-only",
        "--target",
        database.head_revision(),
    ]


def test_local_production_runs_all_knowledge_source_service_roles() -> None:
    services = yaml.safe_load(
        LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    )["services"]
    role_services = {
        "kss-api": "api",
        "kss-query-executor": "query-executor",
        "kss-knowledge-worker": "knowledge-worker",
        "kss-sync-scheduler": "sync-scheduler",
        "kss-migrate": "migrate",
    }

    images = {services[name]["image"] for name in role_services}
    assert images == {"proofagent-knowledge-source-service:production-local"}
    assert services["kss-api"]["build"] == {
        "context": "./services/knowledge-source-service",
        "dockerfile": "Dockerfile",
    }
    for service_name, role in role_services.items():
        service = services[service_name]
        assert service["command"] == [role]
        assert service["user"] == "10001:10001"
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["tmpfs"] == ["/tmp:size=64m,mode=0700,uid=10001,gid=10001"]

    assert services["kss-migrate"]["restart"] == "no"
    assert services["kss-database-init"]["image"] == services["postgres"]["image"]
    assert services["kss-database-init"]["restart"] == "no"
    assert services["kss-database-init"]["environment"][
        "KSS_DATABASE_PASSWORD"
    ] == "${KSS_POSTGRES_PASSWORD}"
    database_init = services["kss-database-init"]["command"][0]
    assert "CREATE ROLE knowledge_source_service LOGIN" in database_init
    assert "OWNER TO knowledge_source_service" in database_init
    assert "WHERE schemaname = 'public'" in database_init
    assert "ALTER TABLE public.%I OWNER TO knowledge_source_service" in database_init
    assert "REASSIGN OWNED" not in database_init
    assert services["kss-migrate"]["depends_on"]["kss-database-init"][
        "condition"
    ] == "service_completed_successfully"
    assert services["kss-api"]["depends_on"]["kss-migrate"]["condition"] == (
        "service_completed_successfully"
    )
    for service_name in (
        "kss-query-executor",
        "kss-knowledge-worker",
        "kss-sync-scheduler",
    ):
        assert services[service_name]["depends_on"]["kss-api"]["condition"] == (
            "service_healthy"
        )


def test_local_production_knowledge_service_uses_tls_authority_boundaries() -> None:
    services = yaml.safe_load(
        LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    )["services"]
    api_environment = services["kss-api"]["environment"]
    executor_environment = services["kss-query-executor"]["environment"]

    assert api_environment["KSS_POSTGRES_DSN"] == (
        "postgresql://knowledge_source_service:${KSS_POSTGRES_PASSWORD}"
        "@postgres:5432/knowledge_source_service"
    )
    assert api_environment["KSS_POSTGRES_DSN"] != services["api"]["environment"][
        "HYBRID_POSTGRES_DSN"
    ]
    assert api_environment["KSS_SEARCH_ENDPOINT"] == (
        "https://opensearch.internal:9200"
    )
    assert api_environment["KSS_PROJECTION_ENCODER_ENDPOINT"] == (
        "https://models.internal:9449/v1/encode"
    )
    assert api_environment["KSS_AGENTIC_CONTROLLER_ENDPOINT"] == (
        "https://models.internal:9450/v1/next"
    )
    assert api_environment["KSS_OCR_ENDPOINT"] == (
        "https://models.internal:9451/v1/extract"
    )
    assert executor_environment["KSS_AGENTIC_CONTROLLER_ENDPOINT"] == (
        "https://models.internal:9450/v1/next"
    )
    assert api_environment["SSL_CERT_FILE"] == "/run/tls/ca.crt"
    assert "127.0.0.1:8444:8444" in services["gateway"]["ports"]

    nginx = (PROJECT_ROOT / "docker/production-local/nginx.conf").read_text(
        encoding="utf-8"
    )
    assert "listen 8444 ssl;" in nginx
    assert "http://kss-api:8080" in nginx
    assert "listen 9449 ssl;" in nginx
    assert "rewrite ^/(.*)$ /kss/projection/$1 break;" in nginx
    assert "listen 9450 ssl;" in nginx
    assert "rewrite ^/(.*)$ /kss/agentic/$1 break;" in nginx
    assert "listen 9451 ssl;" in nginx
    assert "rewrite ^/(.*)$ /kss/ocr/$1 break;" in nginx


def test_local_production_verifier_covers_knowledge_service_authorities() -> None:
    verifier = (PROJECT_ROOT / "scripts/production-local-verify.sh").read_text(
        encoding="utf-8"
    )

    assert "https://proof-agent.localhost:8444/readyz" in verifier
    assert "-d knowledge_source_service" in verifier
    assert "KSS PostgreSQL authority isolation" in verifier
    assert "rolname = 'knowledge_source_service'" in verifier
    assert "pg_get_userbyid(datdba)" in verifier
    assert "tableowner <> 'knowledge_source_service'" in verifier
    assert "local/proof-agent-knowledge-local" in verifier


def test_local_production_bootstraps_only_the_designated_reference_profile_source() -> None:
    services = yaml.safe_load(
        LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    )["services"]
    bootstrap = services["reference-metadata-bootstrap"]

    assert bootstrap["restart"] == "no"
    assert bootstrap["entrypoint"] == ["python"]
    assert bootstrap["command"] == [
        "/opt/proof-agent-local/bootstrap_reference_metadata.py"
    ]
    assert bootstrap["depends_on"]["database-migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert bootstrap["depends_on"]["hybrid-migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["api"]["depends_on"]["reference-metadata-bootstrap"][
        "condition"
    ] == "service_completed_successfully"
    assert services["knowledge-worker"]["environment"][
        "PA_KNOWLEDGE_REFERENCE_PROFILE_SOURCE_IDS"
    ] == "ks_insurance"


def test_local_production_supplies_current_api_startup_contract() -> None:
    services = yaml.safe_load(
        LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    )["services"]
    environment = services["api"]["environment"]

    assert environment["PROOF_AGENT_IMAGE_DIGEST"].startswith(
        "${PROOF_AGENT_IMAGE_DIGEST:-"
    )
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
    trusted_keys = json.loads(
        environment["PROOF_AGENT_RELEASE_TRUSTED_ED25519_KEYS_JSON"]
    )
    assert all(len(base64.b64decode(value, validate=True)) == 32 for value in trusted_keys.values())
    assert any(
        str(entry).startswith("/var/lib/proof-agent/release-bundle-cache:")
        for entry in services["api"]["tmpfs"]
    )
    assert any(
        str(entry).endswith(
            ":/run/proof-agent-config/deployment-compatibility-manifest.json:ro"
        )
        for entry in services["api"]["volumes"]
    )


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
