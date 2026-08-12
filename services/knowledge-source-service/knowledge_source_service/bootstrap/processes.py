"""Blocking process-role runners for the independent service distribution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import ipaddress
import os
import time
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

import psycopg

from knowledge_source_service.adapters.configured.snapshot_connections import (
    ConfiguredSnapshotConnectionRegistry,
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
from knowledge_source_service.adapters.opensearch.hybrid_projection import (
    OpenSearchHybridProjection,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.knowledge_queries import (
    PostgresKnowledgeQueryRepository,
)
from knowledge_source_service.adapters.postgres.synchronizations import (
    PostgresKnowledgeSourceSynchronizationRepository,
)
from knowledge_source_service.adapters.s3.artifacts import S3ImmutableArtifactStore
from knowledge_source_service.application.projection_encoding import (
    DeterministicHashProjectionEncoder,
    ProjectionTextEncoder,
)
from knowledge_source_service.application.integrity_worker import (
    KnowledgeReleaseIntegrityWorker,
)
from knowledge_source_service.application.synchronization_executor import (
    KnowledgeSourceSynchronizationExecutor,
)
from knowledge_source_service.bootstrap.runtime import compose_runtime
from knowledge_source_service.configuration import ApiRuntimeConfiguration
from knowledge_source_service.delivery.management_http import bearer_operator_authenticator


def run_process_role(
    role: str,
    configuration: ApiRuntimeConfiguration,
    environment: Mapping[str, str],
) -> int:
    """Start one blocking role after configuration has already been validated."""

    if role == "migrate":
        apply_knowledge_service_migrations(configuration.postgres_dsn)
        return 0
    if role == "sync-scheduler":
        return _run_sync_scheduler(configuration, environment)
    artifacts = _s3_artifact_store(configuration, environment)
    projection = OpenSearchHybridProjection(endpoint=configuration.search_endpoint)
    if role == "knowledge-worker":
        try:
            return _run_knowledge_worker(
                configuration,
                environment,
                artifacts,
                projection,
            )
        finally:
            projection.close()
    encoder = _projection_encoder(environment)
    agentic_controller = _agentic_controller(environment)
    ocr_extractor = _ocr_extractor(environment) if role == "api" else None
    operator_token = environment.get("KSS_OPERATOR_BEARER_TOKEN", "").strip()
    operator_authenticator = (
        None
        if not operator_token
        else bearer_operator_authenticator(
            operator_id=environment.get("KSS_OPERATOR_ID", "bootstrap-operator"),
            expected_token=operator_token,
        )
    )
    try:
        snapshot_connections = (
            ConfiguredSnapshotConnectionRegistry.from_environment(
                environment,
                clock=lambda: datetime.now(UTC),
                enable_resolution=False,
            )
            if role == "api"
            else None
        )
        runtime = compose_runtime(
            postgres_dsn=configuration.postgres_dsn,
            artifacts=artifacts,
            release_identity=configuration.release_identity,
            dependency_readiness=lambda: _dependency_readiness(
                configuration,
                artifacts,
            ),
            clock=lambda: datetime.now(UTC),
            query_id_factory=lambda: f"knowledge-query-{uuid4().hex}",
            trace_id_factory=lambda: f"trace-{uuid4().hex}",
            worker_id=environment.get(
                "KSS_QUERY_WORKER_ID",
                f"{os.uname().nodename}-{uuid4().hex}",
            ),
            lease_duration=timedelta(
                seconds=_positive_integer(environment, "KSS_QUERY_LEASE_SECONDS", 60)
            ),
            result_retention=timedelta(
                seconds=_positive_integer(
                    environment,
                    "KSS_QUERY_RESULT_RETENTION_SECONDS",
                    86_400,
                )
            ),
            authenticate_operator=operator_authenticator,
            document_pipeline_revision=environment.get(
                "KSS_DOCUMENT_PIPELINE_REVISION",
                "document-pipeline-v1",
            ),
            dataset_pipeline_revision=environment.get(
                "KSS_DATASET_PIPELINE_REVISION",
                "dataset-pipeline-v1",
            ),
            max_upload_bytes=_positive_integer(
                environment,
                "KSS_MAX_UPLOAD_BYTES",
                50 * 1024 * 1024,
            ),
            max_dataset_records=_positive_integer(
                environment,
                "KSS_MAX_DATASET_RECORDS",
                100_000,
            ),
            projection=projection,
            encoder=encoder,
            agentic_controller=agentic_controller,
            ocr_extractor=ocr_extractor,
            snapshot_connections=snapshot_connections,
            synchronization_id_factory=(
                (lambda: f"source-sync-{uuid4().hex}")
                if snapshot_connections is not None
                else None
            ),
        )
        if role == "api":
            try:
                import uvicorn
            except ImportError as error:  # pragma: no cover - distribution dependency
                raise RuntimeError("API role requires uvicorn") from error
            uvicorn.run(
                runtime.http_application,
                host=environment.get("KSS_API_HOST", "0.0.0.0"),
                port=_positive_integer(environment, "KSS_API_PORT", 8080),
                access_log=False,
                proxy_headers=False,
                server_header=False,
            )
            return 0
        if role == "query-executor":
            idle_seconds = _positive_integer(
                environment,
                "KSS_QUERY_IDLE_MILLISECONDS",
                200,
            ) / 1000
            try:
                while True:
                    if not runtime.query_executor.run_once():
                        time.sleep(idle_seconds)
            except KeyboardInterrupt:
                return 0
        raise ValueError("unknown Knowledge Source Service process role")
    finally:
        if agentic_controller is not None:
            agentic_controller.close()
        if ocr_extractor is not None:
            ocr_extractor.close()
        close_encoder = getattr(encoder, "close", None)
        if close_encoder is not None:
            close_encoder()
        projection.close()


def _ocr_extractor(
    environment: Mapping[str, str],
) -> HttpDocumentOcrExtractor | None:
    fields = {
        key: environment.get(key, "").strip()
        for key in (
            "KSS_OCR_ENDPOINT",
            "KSS_OCR_BEARER_TOKEN",
            "KSS_OCR_MODEL_REVISION",
        )
    }
    if any(fields.values()):
        missing = tuple(key for key, value in fields.items() if not value)
        if missing:
            raise ValueError(
                "KSS OCR configuration is incomplete: " + ", ".join(missing)
            )
        return HttpDocumentOcrExtractor(
            endpoint=fields["KSS_OCR_ENDPOINT"],
            bearer_token=fields["KSS_OCR_BEARER_TOKEN"],
            model_revision=fields["KSS_OCR_MODEL_REVISION"],
        )
    return None


def _agentic_controller(
    environment: Mapping[str, str],
) -> HttpAgenticRetrievalController | None:
    endpoint = environment.get("KSS_AGENTIC_CONTROLLER_ENDPOINT", "").strip()
    bearer_token = environment.get(
        "KSS_AGENTIC_CONTROLLER_BEARER_TOKEN",
        "",
    ).strip()
    if bool(endpoint) != bool(bearer_token):
        raise ValueError(
            "KSS Agentic controller endpoint and credential are required together"
        )
    if not endpoint:
        return None
    return HttpAgenticRetrievalController(
        endpoint=endpoint,
        bearer_token=bearer_token,
    )


def _projection_encoder(
    environment: Mapping[str, str],
) -> ProjectionTextEncoder:
    fields = {
        "endpoint": environment.get("KSS_PROJECTION_ENCODER_ENDPOINT", "").strip(),
        "bearer_token": environment.get(
            "KSS_PROJECTION_ENCODER_BEARER_TOKEN",
            "",
        ).strip(),
        "dense_revision": environment.get(
            "KSS_DENSE_ENCODER_REVISION",
            "",
        ).strip(),
        "sparse_revision": environment.get(
            "KSS_SPARSE_ENCODER_REVISION",
            "",
        ).strip(),
        "dense_dimension": environment.get("KSS_DENSE_DIMENSION", "").strip(),
    }
    if any(fields.values()):
        missing = tuple(key for key, value in fields.items() if not value)
        if missing:
            raise ValueError(
                "KSS projection encoder configuration is incomplete: "
                + ", ".join(missing)
            )
        return HttpProjectionTextEncoder(
            endpoint=fields["endpoint"],
            bearer_token=fields["bearer_token"],
            dense_revision=fields["dense_revision"],
            sparse_revision=fields["sparse_revision"],
            dense_dimension=_positive_integer(
                environment,
                "KSS_DENSE_DIMENSION",
                384,
            ),
        )
    if environment.get("KSS_DETERMINISTIC_ENCODER_ENABLED", "").strip() != "1":
        raise ValueError(
            "a private projection encoder is required; deterministic encoding "
            "must be explicitly enabled"
        )
    return DeterministicHashProjectionEncoder(
        dense_dimension=_positive_integer(environment, "KSS_DENSE_DIMENSION", 384)
    )


def _run_sync_scheduler(
    configuration: ApiRuntimeConfiguration,
    environment: Mapping[str, str],
) -> int:
    repository = PostgresKnowledgeQueryRepository.from_dsn(
        configuration.postgres_dsn
    )
    batch_size = _positive_integer(
        environment,
        "KSS_RESULT_REAPER_BATCH_SIZE",
        1000,
    )
    interval_seconds = _positive_integer(
        environment,
        "KSS_RESULT_REAPER_INTERVAL_SECONDS",
        60,
    )
    run_once = environment.get("KSS_RUN_ONCE", "").strip()
    if run_once not in {"", "0", "1"}:
        raise ValueError("KSS_RUN_ONCE must be 0 or 1")
    try:
        while True:
            repository.expire_available_results(
                now=datetime.now(UTC),
                limit=batch_size,
            )
            if run_once == "1":
                return 0
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        return 0


def _run_knowledge_worker(
    configuration: ApiRuntimeConfiguration,
    environment: Mapping[str, str],
    artifacts: S3ImmutableArtifactStore,
    projection: OpenSearchHybridProjection,
) -> int:
    catalog = PostgresKnowledgeCatalog.from_dsn(
        configuration.postgres_dsn,
        artifacts=artifacts,
    )
    worker = KnowledgeReleaseIntegrityWorker(
        catalog=catalog,
        projection=projection,
    )
    synchronization_repository = (
        PostgresKnowledgeSourceSynchronizationRepository.from_dsn(
            configuration.postgres_dsn
        )
    )
    snapshot_connections = ConfiguredSnapshotConnectionRegistry.from_environment(
        environment,
        clock=lambda: datetime.now(UTC),
        enable_resolution=True,
    )
    synchronization_executor = KnowledgeSourceSynchronizationExecutor(
        repository=synchronization_repository,
        connections=snapshot_connections,
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=environment.get(
            "KSS_DATASET_PIPELINE_REVISION",
            "dataset-pipeline-v1",
        ),
        max_content_bytes=_positive_integer(
            environment,
            "KSS_MAX_UPLOAD_BYTES",
            50 * 1024 * 1024,
        ),
        max_records=_positive_integer(
            environment,
            "KSS_MAX_DATASET_RECORDS",
            100_000,
        ),
        clock=lambda: datetime.now(UTC),
        trace_id_factory=lambda: f"trace-{uuid4().hex}",
        worker_id=environment.get(
            "KSS_KNOWLEDGE_WORKER_ID",
            f"{os.uname().nodename}-{uuid4().hex}",
        ),
        lease_duration=timedelta(
            seconds=_positive_integer(
                environment,
                "KSS_SYNCHRONIZATION_LEASE_SECONDS",
                60,
            )
        ),
    )
    batch_size = _positive_integer(
        environment,
        "KSS_KNOWLEDGE_WORK_BATCH_SIZE",
        100,
    )
    if batch_size > 1000:
        raise ValueError("KSS_KNOWLEDGE_WORK_BATCH_SIZE exceeds its bound")
    synchronization_batch_size = _positive_integer(
        environment,
        "KSS_SYNCHRONIZATION_BATCH_SIZE",
        25,
    )
    if synchronization_batch_size > 1000:
        raise ValueError("KSS_SYNCHRONIZATION_BATCH_SIZE exceeds its bound")
    interval_seconds = _positive_integer(
        environment,
        "KSS_KNOWLEDGE_WORK_INTERVAL_SECONDS",
        300,
    )
    run_once = environment.get("KSS_RUN_ONCE", "").strip()
    if run_once not in {"", "0", "1"}:
        raise ValueError("KSS_RUN_ONCE must be 0 or 1")
    try:
        while True:
            for _ in range(synchronization_batch_size):
                if not synchronization_executor.run_once():
                    break
            cursor: str | None = None
            while True:
                batch = worker.run_batch(
                    after_release_id=cursor,
                    limit=batch_size,
                )
                if batch.verified_releases < batch_size:
                    break
                if batch.next_release_id is None:
                    raise RuntimeError("Release integrity worker lost its page cursor")
                cursor = batch.next_release_id
            if run_once == "1":
                return 0
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        synchronization_repository.close()
        catalog.close()


def _s3_artifact_store(
    configuration: ApiRuntimeConfiguration,
    environment: Mapping[str, str],
) -> S3ImmutableArtifactStore:
    bucket, key_prefix = _object_store_coordinates(configuration.object_store_uri)
    endpoint = environment.get("KSS_S3_ENDPOINT", "").strip() or None
    if endpoint is not None:
        _validate_custom_endpoint(
            endpoint,
            allow_insecure=environment.get("KSS_S3_ALLOW_INSECURE_ENDPOINT") == "1",
        )
    try:
        import boto3  # type: ignore[import-untyped]
        from botocore.config import Config  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - distribution dependency
        raise RuntimeError("S3 role requires boto3 and botocore") from error
    client_arguments: dict[str, Any] = {
        "endpoint_url": endpoint,
        "region_name": environment.get("KSS_S3_REGION", "").strip() or None,
        "config": Config(
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 2, "mode": "standard"},
            proxies={},
            s3={"addressing_style": "path" if endpoint is not None else "auto"},
        ),
    }
    access_key = environment.get("KSS_S3_ACCESS_KEY_ID", "").strip()
    secret_key = environment.get("KSS_S3_SECRET_ACCESS_KEY", "").strip()
    if bool(access_key) != bool(secret_key):
        raise ValueError("both KSS S3 static credential fields are required together")
    if access_key:
        client_arguments.update(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
    client = boto3.client("s3", **client_arguments)
    try:
        return S3ImmutableArtifactStore(
            client=client,
            bucket=bucket,
            key_prefix=key_prefix,
        )
    except BaseException:
        client.close()
        raise


def _object_store_coordinates(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "s3"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
    ):
        raise ValueError("KSS_OBJECT_STORE_URI must be an unambiguous s3://bucket/prefix URI")
    key_prefix = unquote(parsed.path).strip("/")
    return parsed.netloc, f"{key_prefix}/" if key_prefix else ""


def _validate_custom_endpoint(endpoint: str, *, allow_insecure: bool) -> None:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("KSS_S3_ENDPOINT is invalid")
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not loopback and not allow_insecure:
        raise ValueError("non-loopback HTTP S3 endpoint requires explicit opt-in")


def _dependency_readiness(
    configuration: ApiRuntimeConfiguration,
    artifacts: S3ImmutableArtifactStore,
) -> dict[str, bool]:
    return {
        "postgresql": _postgres_ready(configuration.postgres_dsn),
        "object_storage": artifacts.is_ready(),
        "search": _search_ready(configuration.search_endpoint),
    }


def _postgres_ready(dsn: str) -> bool:
    try:
        with psycopg.connect(
            dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            connect_timeout=3,
        ) as connection:
            return connection.execute("SELECT 1").fetchone() == (1,)
    except Exception:
        return False


def _search_ready(endpoint: str) -> bool:
    try:
        target = f"{endpoint.rstrip('/')}/_cluster/health"
        response = build_opener(ProxyHandler({})).open(target, timeout=3)
        try:
            return bool(200 <= response.status < 300)
        finally:
            response.close()
    except Exception:
        return False


def _positive_integer(
    environment: Mapping[str, str],
    key: str,
    default: int,
) -> int:
    raw = environment.get(key, "").strip()
    try:
        value = default if not raw else int(raw)
    except ValueError as error:
        raise ValueError(f"{key} must be a positive integer") from error
    if value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value
