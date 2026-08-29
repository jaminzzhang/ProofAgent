from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import uvicorn
import pytest

from knowledge_source_service.cli import main
from knowledge_source_service.configuration import ApiRuntimeConfiguration
from knowledge_source_service.adapters.opensearch.hybrid_projection import (
    OpenSearchHybridProjection,
)
from knowledge_source_service.adapters.http.agentic_controller import (
    HttpAgenticRetrievalController,
)
from knowledge_source_service.adapters.http.projection_encoder import (
    HttpProjectionTextEncoder,
)
from knowledge_source_service.adapters.http.ocr_extractor import (
    HttpDocumentOcrExtractor,
)
from knowledge_source_service.application.projection_encoding import (
    DeterministicHashProjectionEncoder,
)
from knowledge_source_service.bootstrap import processes


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SERVICE_PROJECT = REPOSITORY_ROOT / "services/knowledge-source-service"
SERVICE_PACKAGE = REPOSITORY_ROOT / "knowledge_source_service"


def test_knowledge_source_service_package_is_at_repository_root() -> None:
    assert SERVICE_PACKAGE.is_dir()
    assert not (SERVICE_PROJECT / "knowledge_source_service").exists()


def test_knowledge_source_service_is_an_independent_python_distribution() -> None:
    with (SERVICE_PROJECT / "pyproject.toml").open("rb") as source:
        configuration = tomllib.load(source)

    assert configuration["project"]["name"] == "knowledge-source-service"
    assert configuration["project"]["requires-python"] == ">=3.12"
    dependencies = set(configuration["project"]["dependencies"])
    assert {"fastapi>=0.111.0", "pydantic>=2.7.0"} <= dependencies
    assert configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"] == {
        "../../knowledge_source_service": "knowledge_source_service"
    }
    assert all("proof-agent" not in dependency.lower() for dependency in dependencies)


def test_service_image_requires_immutable_build_images_and_a_frozen_lock() -> None:
    dockerfile = (SERVICE_PROJECT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (SERVICE_PROJECT / "Dockerfile.dockerignore").read_text(encoding="utf-8")

    assert "ARG UV_IMAGE" in dockerfile
    assert "ARG RUNTIME_IMAGE" in dockerfile
    assert "FROM ${UV_IMAGE} AS python-build" in dockerfile
    assert "FROM ${RUNTIME_IMAGE} AS runtime" in dockerfile
    assert "FROM python:3.12-slim" not in dockerfile
    assert "WORKDIR /src/services/knowledge-source-service" in dockerfile
    assert (
        "COPY services/knowledge-source-service/pyproject.toml "
        "services/knowledge-source-service/uv.lock ./"
    ) in dockerfile
    assert "COPY knowledge_source_service /src/knowledge_source_service" in dockerfile
    assert "UV_PROJECT_ENVIRONMENT=/opt/knowledge-source-service/venv" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "/opt/knowledge-source-service/venv /opt/knowledge-source-service/venv" in dockerfile
    assert dockerignore.splitlines() == [
        "**",
        "!services/",
        "!services/knowledge-source-service/",
        "!services/knowledge-source-service/pyproject.toml",
        "!services/knowledge-source-service/uv.lock",
        "!knowledge_source_service/",
        "!knowledge_source_service/**",
    ]


def test_openapi_contract_is_canonical_and_covers_both_api_surfaces() -> None:
    from knowledge_source_service.openapi_contract import (
        build_openapi_contract_bytes,
    )

    contract = build_openapi_contract_bytes()
    payload = json.loads(contract)

    assert contract == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert {
        "/livez",
        "/readyz",
        "/v1/knowledge-queries",
        "/v1/knowledge-spaces",
        "/v1/knowledge-source-synchronizations",
        "/v1/connection-profiles",
        "/v1/connection-profiles/{profile_id}:publish",
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/draft",
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/release-preparations",
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/release-preparations/{preparation_id}",
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/release-preparations/{preparation_id}:cancel",
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/release-preparations/{preparation_id}:publish",
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/preparation-audit",
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/releases/{knowledge_base_release_id}/deletion-eligibility",
    } <= set(payload["paths"])
    schemas = payload["components"]["schemas"]
    assert {
        "QueuedReleasePreparation",
        "RunningReleasePreparation",
        "CancelledReleasePreparation",
        "ReadyReleasePreparation",
        "ExpiredReleasePreparation",
        "ConsumedReleasePreparation",
        "FailedReleasePreparation",
    } <= set(schemas)
    assert "PreparationClaim" not in schemas
    for schema_name in (
        "RunningReleasePreparation",
        "CancelledReleasePreparation",
        "ReadyReleasePreparation",
        "ExpiredReleasePreparation",
        "ConsumedReleasePreparation",
        "FailedReleasePreparation",
    ):
        assert not {
            "candidate_json",
            "release_manifest_artifact",
            "lease_worker_id",
            "lease_fencing_token",
            "lease_expires_at",
            "published_release_id",
        } & set(schemas[schema_name]["properties"])
    assert schemas["KnowledgeBaseReleaseSummaryResource"]["properties"]["state"]["enum"] == [
        "queryable",
        "deprecated",
        "retired",
        "revoked",
    ]
    deletion_properties = schemas["KnowledgeBaseReleaseDeletionEligibilityAssessment"]["properties"]
    assert {
        "release_state",
        "eligible",
        "blockers",
        "active_reference_count",
        "deregistered_reference_count",
        "artifact_retention_state",
    } <= set(deletion_properties)
    assert not {
        "external_resource_id",
        "release_reference_id",
        "credential",
        "token",
    } & set(deletion_properties)
    publication_operation = payload["paths"][
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/release-preparations/{preparation_id}:publish"
    ]["post"]
    assert "requestBody" not in publication_operation
    assert publication_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ConsumedReleasePreparation"
    }
    cancellation_operation = payload["paths"][
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/release-preparations/{preparation_id}:cancel"
    ]["post"]
    assert "requestBody" not in cancellation_operation
    assert cancellation_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CancelledReleasePreparation"
    }
    assert hashlib.sha256(contract).hexdigest() == (
        "ce34e8b4fbcd16c90201890cb8e466980132aedbbfc0dce35dedec155749ce3a"
    )


def test_openapi_contract_cli_emits_the_exact_canonical_bytes() -> None:
    from knowledge_source_service.openapi_contract import (
        build_openapi_contract_bytes,
    )

    result = subprocess.run(
        [sys.executable, "-m", "knowledge_source_service", "openapi-contract"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert result.stdout == build_openapi_contract_bytes()


def test_migration_contract_is_canonical_and_binds_every_packaged_revision() -> None:
    from knowledge_source_service.adapters.postgres.migrations import (
        knowledge_service_migration_contract_bytes,
    )

    contract = knowledge_service_migration_contract_bytes()
    payload = json.loads(contract)

    assert contract == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert payload["head_revision"] == "0018_release_revocation"
    assert [item["revision"] for item in payload["migrations"]] == [
        f"{number:04d}_{name}"
        for number, name in (
            (1, "knowledge_queries"),
            (2, "knowledge_catalog"),
            (3, "knowledge_access"),
            (4, "query_result_artifacts"),
            (5, "release_projection_attestation"),
            (6, "source_synchronizations"),
            (7, "connection_profiles"),
            (8, "profile_synchronizations"),
            (9, "base_preparations"),
            (10, "preparation_leases"),
            (11, "preparation_results"),
            (12, "preparation_publications"),
            (13, "preparation_cancellations"),
            (14, "release_references"),
            (15, "release_deprecation"),
            (16, "release_retirement"),
            (17, "release_reference_deregistration"),
            (18, "release_revocation"),
        )
    ]
    assert hashlib.sha256(contract).hexdigest() == (
        "7a382fd03b767c56b13bf8f8260b6a808ddec91ff0fb41ff014f6b6a64669fef"
    )


def test_migration_contract_cli_emits_the_exact_canonical_bytes() -> None:
    from knowledge_source_service.adapters.postgres.migrations import (
        knowledge_service_migration_contract_bytes,
    )

    result = subprocess.run(
        [sys.executable, "-m", "knowledge_source_service", "migration-contract"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert result.stdout == knowledge_service_migration_contract_bytes()


def test_service_cli_exposes_the_five_isolated_process_roles() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "knowledge_source_service", "roles"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "api",
        "query-executor",
        "knowledge-worker",
        "sync-scheduler",
        "migrate",
    ]


def test_api_role_configuration_check_fails_closed_without_required_dependencies() -> None:
    missing = subprocess.run(
        [sys.executable, "-m", "knowledge_source_service", "api", "--check-config"],
        cwd=REPOSITORY_ROOT,
        env={},
        check=False,
        capture_output=True,
        text=True,
    )
    configured_environment = {
        "KSS_POSTGRES_DSN": "postgresql://knowledge-service@db/knowledge",
        "KSS_OBJECT_STORE_URI": "s3://knowledge-service-test",
        "KSS_SEARCH_ENDPOINT": "https://search.invalid.example",
        "KSS_RELEASE_IDENTITY": "sha256:test-release",
    }
    configured = subprocess.run(
        [sys.executable, "-m", "knowledge_source_service", "api", "--check-config"],
        cwd=REPOSITORY_ROOT,
        env=configured_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert missing.returncode == 2
    assert missing.stdout == ""
    assert missing.stderr == (
        "missing required configuration: KSS_OBJECT_STORE_URI, KSS_POSTGRES_DSN, "
        "KSS_RELEASE_IDENTITY, KSS_SEARCH_ENDPOINT\n"
    )
    assert configured.returncode == 0, configured.stderr
    assert configured.stdout == "configuration valid\n"
    assert all(value not in configured.stdout for value in configured_environment.values())


def test_runtime_configuration_reads_postgres_dsn_from_hardened_secret_file(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "postgres-dsn"
    secret.write_text("postgresql://knowledge-service@db/knowledge\n", encoding="utf-8")
    secret.chmod(0o600)

    configuration = ApiRuntimeConfiguration.from_environment(
        {
            "KSS_POSTGRES_DSN_FILE": str(secret),
            "KSS_OBJECT_STORE_URI": "s3://knowledge-service-test",
            "KSS_SEARCH_ENDPOINT": "https://search.invalid.example",
            "KSS_RELEASE_IDENTITY": "sha256:test-release",
        }
    )

    assert configuration.postgres_dsn == "postgresql://knowledge-service@db/knowledge"


def test_runtime_configuration_rejects_ambiguous_or_weak_secret_files(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "postgres-dsn"
    secret.write_text("postgresql://knowledge-service@db/knowledge\n", encoding="utf-8")
    common = {
        "KSS_OBJECT_STORE_URI": "s3://knowledge-service-test",
        "KSS_SEARCH_ENDPOINT": "https://search.invalid.example",
        "KSS_RELEASE_IDENTITY": "sha256:test-release",
    }

    secret.chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        ApiRuntimeConfiguration.from_environment({**common, "KSS_POSTGRES_DSN_FILE": str(secret)})

    secret.chmod(0o600)
    with pytest.raises(ValueError, match="both"):
        ApiRuntimeConfiguration.from_environment(
            {
                **common,
                "KSS_POSTGRES_DSN": "postgresql://other@db/knowledge",
                "KSS_POSTGRES_DSN_FILE": str(secret),
            }
        )


def test_distribution_exposes_one_console_entry_point_per_process_role() -> None:
    with (SERVICE_PROJECT / "pyproject.toml").open("rb") as source:
        configuration = tomllib.load(source)

    assert configuration["project"]["scripts"] == {
        "knowledge-source-service": "knowledge_source_service.cli:console_main",
        "knowledge-source-api": "knowledge_source_service.cli:api_main",
        "knowledge-query-executor": "knowledge_source_service.cli:query_executor_main",
        "knowledge-worker": "knowledge_source_service.cli:knowledge_worker_main",
        "knowledge-sync-scheduler": "knowledge_source_service.cli:sync_scheduler_main",
        "knowledge-source-migrate": "knowledge_source_service.cli:migrate_main",
    }


def test_api_role_dispatches_the_validated_runtime_instead_of_only_checking_config() -> None:
    environment = {
        "KSS_POSTGRES_DSN": "postgresql://knowledge-service@db/knowledge",
        "KSS_OBJECT_STORE_URI": "s3://knowledge-service-test/service-prefix",
        "KSS_SEARCH_ENDPOINT": "https://search.invalid.example",
        "KSS_RELEASE_IDENTITY": "sha256:test-release",
    }
    observed: list[tuple[str, ApiRuntimeConfiguration, Mapping[str, str]]] = []

    def run_role(
        role: str,
        configuration: ApiRuntimeConfiguration,
        source: Mapping[str, str],
    ) -> int:
        observed.append((role, configuration, source))
        return 0

    exit_status = main(
        ["api"],
        environment=environment,
        role_runner=run_role,
    )

    assert exit_status == 0
    assert observed[0][0] == "api"
    assert observed[0][1].object_store_uri == ("s3://knowledge-service-test/service-prefix")
    assert observed[0][2] is environment


def test_api_process_wires_release_pinned_hybrid_projection(
    monkeypatch: object,
) -> None:
    configuration = ApiRuntimeConfiguration(
        postgres_dsn="postgresql://knowledge-service@db/knowledge",
        object_store_uri="s3://knowledge-service-test/service-prefix",
        search_endpoint="https://search.invalid.example",
        release_identity="sha256:test-release",
    )
    observed: dict[str, object] = {}
    fake_artifacts = object()

    monkeypatch.setattr(  # type: ignore[attr-defined]
        processes,
        "_s3_artifact_store",
        lambda _configuration, _environment: fake_artifacts,
    )

    def capture_runtime(**arguments: object) -> SimpleNamespace:
        observed.update(arguments)
        return SimpleNamespace(http_application=object(), query_executor=object())

    monkeypatch.setattr(  # type: ignore[attr-defined]
        processes,
        "compose_runtime",
        capture_runtime,
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        uvicorn,
        "run",
        lambda *_args, **_kwargs: None,
    )

    status = processes.run_process_role(
        "api",
        configuration,
        {
            "KSS_AGENTIC_CONTROLLER_ENDPOINT": (
                "https://controller.invalid/v1/retrieval-decisions"
            ),
            "KSS_AGENTIC_CONTROLLER_BEARER_TOKEN": "controller-secret-token",
            "KSS_PROJECTION_ENCODER_ENDPOINT": "https://encoder.invalid/v1/encode",
            "KSS_PROJECTION_ENCODER_BEARER_TOKEN": "encoder-secret-token",
            "KSS_DENSE_ENCODER_REVISION": "private-dense-v7",
            "KSS_SPARSE_ENCODER_REVISION": "private-sparse-v4",
            "KSS_DENSE_DIMENSION": "128",
            "KSS_OCR_ENDPOINT": "https://ocr.invalid/v1/extract",
            "KSS_OCR_BEARER_TOKEN": "ocr-secret-token",
            "KSS_OCR_MODEL_REVISION": "ocr-private-v3",
        },
    )

    assert status == 0
    assert isinstance(observed["projection"], OpenSearchHybridProjection)
    assert isinstance(observed["encoder"], HttpProjectionTextEncoder)
    assert isinstance(
        observed["agentic_controller"],
        HttpAgenticRetrievalController,
    )
    assert isinstance(observed["ocr_extractor"], HttpDocumentOcrExtractor)


def test_non_api_roles_do_not_resolve_the_operator_secret_file() -> None:
    assert (
        processes._operator_authenticator(  # noqa: SLF001 - role boundary contract
            "query-executor",
            {"KSS_OPERATOR_BEARER_TOKEN_FILE": "/run/secrets/not-mounted-for-query"},
        )
        is None
    )


def test_explicit_deterministic_encoder_accepts_an_overridden_dimension() -> None:
    encoder = processes._projection_encoder(
        {
            "KSS_DETERMINISTIC_ENCODER_ENABLED": "1",
            "KSS_DENSE_DIMENSION": "64",
        }
    )

    assert isinstance(encoder, DeterministicHashProjectionEncoder)
    assert encoder.dense_dimension == 64


def test_sync_scheduler_runs_bounded_result_expiration_batch(
    monkeypatch: object,
) -> None:
    configuration = ApiRuntimeConfiguration(
        postgres_dsn="postgresql://knowledge-service@db/knowledge",
        object_store_uri="s3://knowledge-service-test/service-prefix",
        search_endpoint="https://search.invalid.example",
        release_identity="sha256:test-release",
    )
    observed: list[int] = []

    class FakeRepository:
        def expire_available_results(self, *, now: object, limit: int) -> int:
            assert now is not None
            observed.append(limit)
            return 3

    monkeypatch.setattr(  # type: ignore[attr-defined]
        processes.PostgresKnowledgeQueryRepository,
        "from_dsn",
        lambda _dsn: FakeRepository(),
    )

    status = processes.run_process_role(
        "sync-scheduler",
        configuration,
        {"KSS_RUN_ONCE": "1", "KSS_RESULT_REAPER_BATCH_SIZE": "25"},
    )

    assert status == 0
    assert observed == [25]


def test_ocr_runtime_configuration_fails_closed_with_precise_missing_keys() -> None:
    with pytest.raises(
        ValueError,
        match=("KSS OCR configuration is incomplete: KSS_OCR_BEARER_TOKEN, KSS_OCR_MODEL_REVISION"),
    ):
        processes._ocr_extractor({"KSS_OCR_ENDPOINT": "https://ocr.invalid/v1/extract"})


def test_knowledge_worker_role_runs_bounded_release_integrity_work(
    monkeypatch: object,
) -> None:
    configuration = ApiRuntimeConfiguration(
        postgres_dsn="postgresql://knowledge-service@db/knowledge",
        object_store_uri="s3://knowledge-service-test/service-prefix",
        search_endpoint="https://search.invalid.example",
        release_identity="sha256:test-release",
    )
    artifacts = object()
    projection = SimpleNamespace(close=lambda: None)
    observed: dict[str, object] = {}
    monkeypatch.setattr(  # type: ignore[attr-defined]
        processes,
        "_s3_artifact_store",
        lambda _configuration, _environment: artifacts,
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        processes,
        "OpenSearchHybridProjection",
        lambda *, endpoint: projection,
    )

    def run_worker(
        worker_configuration: ApiRuntimeConfiguration,
        environment: Mapping[str, str],
        worker_artifacts: object,
        worker_projection: object,
    ) -> int:
        observed.update(
            configuration=worker_configuration,
            environment=environment,
            artifacts=worker_artifacts,
            projection=worker_projection,
        )
        return 0

    monkeypatch.setattr(  # type: ignore[attr-defined]
        processes,
        "_run_knowledge_worker",
        run_worker,
        raising=False,
    )

    status = processes.run_process_role(
        "knowledge-worker",
        configuration,
        {"KSS_RUN_ONCE": "1", "KSS_KNOWLEDGE_WORK_BATCH_SIZE": "25"},
    )

    assert status == 0
    assert observed["configuration"] is configuration
    assert observed["artifacts"] is artifacts
    assert observed["projection"] is projection
