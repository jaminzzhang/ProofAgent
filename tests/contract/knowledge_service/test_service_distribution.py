from __future__ import annotations

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


SERVICE_PROJECT = Path(__file__).resolve().parents[3] / "services/knowledge-source-service"


def test_knowledge_source_service_is_an_independent_python_distribution() -> None:
    with (SERVICE_PROJECT / "pyproject.toml").open("rb") as source:
        configuration = tomllib.load(source)

    assert configuration["project"]["name"] == "knowledge-source-service"
    assert configuration["project"]["requires-python"] == ">=3.12"
    dependencies = set(configuration["project"]["dependencies"])
    assert {"fastapi>=0.111.0", "pydantic>=2.7.0"} <= dependencies
    assert configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "knowledge_source_service"
    ]
    assert all(
        "proof-agent" not in dependency.lower()
        for dependency in dependencies
    )


def test_service_cli_exposes_the_five_isolated_process_roles() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "knowledge_source_service", "roles"],
        cwd=SERVICE_PROJECT,
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
        cwd=SERVICE_PROJECT,
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
        cwd=SERVICE_PROJECT,
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
    assert observed[0][1].object_store_uri == (
        "s3://knowledge-service-test/service-prefix"
    )
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
        match=(
            "KSS OCR configuration is incomplete: "
            "KSS_OCR_BEARER_TOKEN, KSS_OCR_MODEL_REVISION"
        ),
    ):
        processes._ocr_extractor(
            {"KSS_OCR_ENDPOINT": "https://ocr.invalid/v1/extract"}
        )


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
