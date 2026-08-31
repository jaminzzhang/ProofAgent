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


def test_local_production_runs_all_knowledge_source_service_roles() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8"))["services"]
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
        "context": ".",
        "dockerfile": "services/knowledge-source-service/Dockerfile",
        "args": {
            "UV_IMAGE": (
                "ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:"
                "e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
            ),
            "RUNTIME_IMAGE": (
                "python:3.12-slim@sha256:"
                "229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36"
            ),
        },
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
    assert (
        services["kss-database-init"]["environment"]["KSS_DATABASE_PASSWORD"]
        == "${KSS_POSTGRES_PASSWORD}"
    )
    database_init = services["kss-database-init"]["command"][0]
    assert "CREATE ROLE knowledge_source_service LOGIN" in database_init
    assert "OWNER TO knowledge_source_service" in database_init
    assert "WHERE schemaname = 'public'" in database_init
    assert "ALTER TABLE public.%I OWNER TO knowledge_source_service" in database_init
    assert "REASSIGN OWNED" not in database_init
    assert (
        services["kss-migrate"]["depends_on"]["kss-database-init"]["condition"]
        == "service_completed_successfully"
    )
    assert services["kss-api"]["depends_on"]["kss-migrate"]["condition"] == (
        "service_completed_successfully"
    )
    for service_name in (
        "kss-query-executor",
        "kss-knowledge-worker",
        "kss-sync-scheduler",
    ):
        assert services[service_name]["depends_on"]["kss-api"]["condition"] == ("service_healthy")


def test_local_production_knowledge_service_uses_tls_authority_boundaries() -> None:
    services = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8"))["services"]
    api_environment = services["kss-api"]["environment"]
    executor_environment = services["kss-query-executor"]["environment"]

    assert api_environment["KSS_POSTGRES_DSN"] == (
        "postgresql://knowledge_source_service:${KSS_POSTGRES_PASSWORD}"
        "@postgres:5432/knowledge_source_service"
    )
    assert "HYBRID_POSTGRES_DSN" not in services["api"]["environment"]
    assert api_environment["KSS_SEARCH_ENDPOINT"] == ("https://opensearch.internal:9200")
    assert api_environment["KSS_PROJECTION_ENCODER_ENDPOINT"] == (
        "https://models.internal:9449/v1/encode"
    )
    assert api_environment["KSS_AGENTIC_CONTROLLER_ENDPOINT"] == (
        "https://models.internal:9450/v1/next"
    )
    assert api_environment["KSS_OCR_ENDPOINT"] == ("https://models.internal:9451/v1/extract")
    assert executor_environment["KSS_AGENTIC_CONTROLLER_ENDPOINT"] == (
        "https://models.internal:9450/v1/next"
    )
    assert api_environment["SSL_CERT_FILE"] == "/run/tls/ca.crt"
    assert "127.0.0.1:8444:8444" in services["gateway"]["ports"]

    nginx = (PROJECT_ROOT / "docker/production-local/nginx.conf").read_text(encoding="utf-8")
    assert "listen 8444 ssl;" in nginx
    assert "http://kss-api:8080" in nginx
    assert "listen 9449 ssl;" in nginx
    assert "rewrite ^/(.*)$ /kss/projection/$1 break;" in nginx
    assert "listen 9450 ssl;" in nginx
    assert "rewrite ^/(.*)$ /kss/agentic/$1 break;" in nginx
    assert "listen 9451 ssl;" in nginx
    assert "rewrite ^/(.*)$ /kss/ocr/$1 break;" in nginx


def test_local_production_verifier_covers_knowledge_service_authorities() -> None:
    verifier = (PROJECT_ROOT / "scripts/production-local-verify.sh").read_text(encoding="utf-8")

    assert "https://proof-agent.localhost:8444/readyz" in verifier
    assert "-d knowledge_source_service" in verifier
    assert "KSS PostgreSQL authority isolation" in verifier
    assert "rolname = 'knowledge_source_service'" in verifier
    assert "pg_get_userbyid(datdba)" in verifier
    assert "tableowner <> 'knowledge_source_service'" in verifier
    assert "local/proof-agent-knowledge-local" in verifier


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


def test_local_production_connects_dashboard_bff_to_kss_without_browser_secret() -> None:
    compose = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]
    api_environment = services["api"]["environment"]
    vault_environment = services["vault-init"]["environment"]
    vault_command = services["vault-init"]["command"][0]

    assert api_environment["PROOF_AGENT_KSS_ENDPOINT"] == ("https://proof-agent.localhost:8444")
    handle_id = api_environment["PROOF_AGENT_KSS_OPERATOR_SECRET_HANDLE"]
    assert handle_id == "knowledge/source-service/operator"
    locators = json.loads(api_environment["PROOF_AGENT_SECRET_HANDLE_LOCATORS_JSON"])
    assert locators[handle_id] == {
        "mount": "secret",
        "path": "proof-agent/knowledge-source-service-operator",
        "field": "value",
    }
    assert vault_environment["KSS_OPERATOR_BEARER_TOKEN"] == ("${KSS_OPERATOR_BEARER_TOKEN}")
    assert "proof-agent/knowledge-source-service-operator" in vault_command
    assert services["api"]["depends_on"]["kss-api"]["condition"] == ("service_healthy")


def test_local_production_wires_versioned_kss_runtime_credentials() -> None:
    compose = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]
    api_environment = services["api"]["environment"]
    kss_api_environment = services["kss-api"]["environment"]
    vault_environment = services["vault-init"]["environment"]
    vault_command = services["vault-init"]["command"][0]
    model_plane_environment = services["model-plane"]["environment"]
    runtime_bootstrap = services["kss-runtime-client-bootstrap"]

    locators = json.loads(api_environment["PROOF_AGENT_SECRET_HANDLE_LOCATORS_JSON"])
    runtime_handle = api_environment["PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE"]
    assert runtime_handle == "knowledge/source-service/runtime-client-v2"
    assert locators[runtime_handle] == {
        "mount": "secret",
        "path": "proof-agent/knowledge-source-service-runtime-client-v2",
        "field": "value",
    }
    assert "knowledge/source-service/client" not in locators
    assert locators["knowledge/admission-scorer"] == {
        "mount": "secret",
        "path": "proof-agent/knowledge-admission-scorer",
        "field": "value",
    }
    assert api_environment["PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID"] == "1"
    assert api_environment["PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION"] == (
        "insurance-evidence-admission.local-compatibility.v1"
    )
    assert api_environment["PROOF_AGENT_FORMAL_PUBLICATION_COMMAND_LEASE_SECONDS"] == "900"
    assert {
        key: api_environment[key]
        for key in (
            "PROOF_AGENT_KSS_QUERY_MAX_ROUNDS",
            "PROOF_AGENT_KSS_QUERY_MAX_MODEL_CALLS",
            "PROOF_AGENT_KSS_QUERY_MAX_CANDIDATES",
            "PROOF_AGENT_KSS_QUERY_MAX_MODEL_TOKENS",
            "PROOF_AGENT_KSS_QUERY_MAX_DURATION_MS",
        )
    } == {
        "PROOF_AGENT_KSS_QUERY_MAX_ROUNDS": "2",
        "PROOF_AGENT_KSS_QUERY_MAX_MODEL_CALLS": "2",
        "PROOF_AGENT_KSS_QUERY_MAX_CANDIDATES": "20",
        "PROOF_AGENT_KSS_QUERY_MAX_MODEL_TOKENS": "1000",
        "PROOF_AGENT_KSS_QUERY_MAX_DURATION_MS": "10000",
    }
    assert vault_environment["KSS_RUNTIME_CLIENT_V2_BEARER_TOKEN"] == (
        "${KSS_RUNTIME_CLIENT_V2_BEARER_TOKEN}"
    )
    assert "KSS_AGENT_CLIENT_BEARER_TOKEN" not in vault_environment
    assert vault_environment["KSS_ADMISSION_SCORER_BEARER_TOKEN"] == (
        "${KSS_ADMISSION_SCORER_BEARER_TOKEN}"
    )
    assert "proof-agent/knowledge-source-service-runtime-client-v2" in vault_command
    assert "proof-agent/knowledge-source-service-client" not in vault_command
    assert "proof-agent/knowledge-admission-scorer" in vault_command
    assert model_plane_environment["KSS_ADMISSION_SCORER_BEARER_TOKEN"] == (
        "${KSS_ADMISSION_SCORER_BEARER_TOKEN}"
    )
    policy = json.loads(kss_api_environment["KSS_QUERY_GRANT_POLICY_JSON"])
    assert policy["client_id"] == runtime_bootstrap["environment"]["KSS_RUNTIME_CLIENT_ID"]
    assert api_environment["PROOF_AGENT_KSS_RUNTIME_CLIENT_ID"] == policy["client_id"]
    assert policy["client_id"] == "proof-agent-production-local-v2"
    assert policy["allowed_strategies"] == ["single_pass", "agentic"]
    assert policy["execution_budget"] == {
        "max_rounds": int(api_environment["PROOF_AGENT_KSS_QUERY_MAX_ROUNDS"]),
        "max_model_calls": int(api_environment["PROOF_AGENT_KSS_QUERY_MAX_MODEL_CALLS"]),
        "max_candidates": int(api_environment["PROOF_AGENT_KSS_QUERY_MAX_CANDIDATES"]),
        "max_model_tokens": int(api_environment["PROOF_AGENT_KSS_QUERY_MAX_MODEL_TOKENS"]),
        "max_duration_ms": int(api_environment["PROOF_AGENT_KSS_QUERY_MAX_DURATION_MS"]),
    }
    assert policy["effective_access_scope_digest"].startswith("sha256:")
    assert len(policy["effective_access_scope_digest"]) == 71
    assert runtime_bootstrap["environment"]["KSS_RUNTIME_CLIENT_BEARER_TOKEN"] == (
        "${KSS_RUNTIME_CLIENT_V2_BEARER_TOKEN}"
    )
    assert runtime_bootstrap["command"] == [
        "-m",
        "knowledge_source_service.bootstrap.runtime_client",
    ]
    assert runtime_bootstrap["restart"] == "no"
    assert runtime_bootstrap["read_only"] is True
    assert runtime_bootstrap["cap_drop"] == ["ALL"]
    assert runtime_bootstrap["security_opt"] == ["no-new-privileges:true"]
    assert (
        services["kss-api"]["depends_on"]["kss-runtime-client-bootstrap"]["condition"]
        == "service_completed_successfully"
    )
    assert "KSS_RUNTIME_CLIENT_BEARER_TOKEN" not in kss_api_environment

    bootstrap_script = (
        PROJECT_ROOT / "knowledge_source_service" / "bootstrap" / "runtime_client.py"
    ).read_text(encoding="utf-8")
    assert "register_client" in bootstrap_script
    assert "grant_release_query" not in bootstrap_script
    assert (
        services["security-bootstrap"]["environment"]["PROOF_AGENT_MODEL_EGRESS_CIDRS"]
        == "${PROOF_AGENT_MODEL_EGRESS_CIDRS:-}"
    )

    prepare = (PROJECT_ROOT / "scripts/production-local-prepare.sh").read_text(encoding="utf-8")
    assert "ensure_random_secret KSS_RUNTIME_CLIENT_V2_BEARER_TOKEN" in prepare
    assert "ensure_random_secret KSS_AGENT_CLIENT_BEARER_TOKEN" not in prepare
    assert "PROOF_AGENT_MODEL_EGRESS_CIDRS" in prepare
    assert "api.deepseek.com" in prepare
    assert "refresh_public_setting PROOF_AGENT_MODEL_EGRESS_CIDRS" in prepare


def test_local_production_wires_a_dedicated_reference_registration_client() -> None:
    compose = yaml.safe_load(LOCAL_PRODUCTION_COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]
    api_environment = services["api"]["environment"]
    vault_environment = services["vault-init"]["environment"]
    vault_command = services["vault-init"]["command"][0]
    bootstrap = services["kss-reference-client-bootstrap"]

    reference_handle = api_environment["PROOF_AGENT_KSS_REFERENCE_CLIENT_SECRET_HANDLE"]
    assert reference_handle == "knowledge/source-service/reference-client"
    assert api_environment["PROOF_AGENT_KSS_REFERENCE_CLIENT_SECRET_VERSION_ID"] == "1"
    assert api_environment["PA_KNOWLEDGE_EVALUATION_ENDPOINT"] == ("https://models.internal:9448")
    assert reference_handle not in {
        api_environment["PROOF_AGENT_KSS_OPERATOR_SECRET_HANDLE"],
        api_environment["PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE"],
    }
    locators = json.loads(api_environment["PROOF_AGENT_SECRET_HANDLE_LOCATORS_JSON"])
    assert locators[reference_handle] == {
        "mount": "secret",
        "path": "proof-agent/knowledge-source-service-reference-client",
        "field": "value",
    }
    assert "KSS_REFERENCE_CLIENT_BEARER_TOKEN" not in api_environment
    assert vault_environment["KSS_REFERENCE_CLIENT_BEARER_TOKEN"] == (
        "${KSS_REFERENCE_CLIENT_BEARER_TOKEN}"
    )
    assert "proof-agent/knowledge-source-service-reference-client" in vault_command

    assert bootstrap["environment"]["KSS_REFERENCE_CLIENT_ID"] == (
        "proof-agent-formal-publication-reference"
    )
    assert bootstrap["environment"]["KSS_REFERENCE_CLIENT_BEARER_TOKEN"] == (
        "${KSS_REFERENCE_CLIENT_BEARER_TOKEN}"
    )
    assert bootstrap["restart"] == "no"
    assert bootstrap["read_only"] is True
    assert bootstrap["cap_drop"] == ["ALL"]
    assert bootstrap["security_opt"] == ["no-new-privileges:true"]
    assert (
        services["kss-api"]["depends_on"]["kss-reference-client-bootstrap"]["condition"]
        == "service_completed_successfully"
    )

    bootstrap_script = (
        PROJECT_ROOT / "knowledge_source_service" / "bootstrap" / "reference_client.py"
    ).read_text(encoding="utf-8")
    assert "register_client" in bootstrap_script
    assert "grant_release_query" not in bootstrap_script

    prepare = (PROJECT_ROOT / "scripts/production-local-prepare.sh").read_text(encoding="utf-8")
    assert "ensure_random_secret KSS_REFERENCE_CLIENT_BEARER_TOKEN" in prepare


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
