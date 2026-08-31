"""Compose the independently running API and Query Executor roles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import inspect
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError

from knowledge_source_service.adapters.postgres.access_control import (
    PostgresKnowledgeAccessControl,
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
from knowledge_source_service.adapters.postgres.connection_profiles import (
    PostgresConnectionProfileRepository,
)
from knowledge_source_service.application.connection_profiles import ConnectionProfileApplication
from knowledge_source_service.adapters.postgres.base_preparations import (
    PostgresBasePreparationRepository,
)
from knowledge_source_service.adapters.postgres.release_references import (
    PostgresReleaseLifecycleRepository,
    PostgresReleaseReferenceRepository,
)
from knowledge_source_service.application.base_preparations import (
    KnowledgeBasePreparationApplication,
)
from knowledge_source_service.application.base_preparation_builder import (
    KnowledgeReleaseCandidateBuilder,
)
from knowledge_source_service.application.base_preparation_worker import (
    BasePreparationExecutor,
    BasePreparationWorker,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
)
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseLifecycleApplication,
    KnowledgeBaseReleaseReferenceApplication,
)
from knowledge_source_service.ports.connection_profiles import (
    ConnectionProfileDeploymentPolicy,
    ConnectionProfileSnapshotReaders,
)
from knowledge_source_service.application.agentic_retrieval import (
    BoundedAgenticKnowledgeRetrievalEngine,
    UnavailableAgenticRetrievalController,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.indexed_retrieval import (
    IndexedHybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_queries import KnowledgeQueryApplication
from knowledge_source_service.application.projection_encoding import ProjectionTextEncoder
from knowledge_source_service.application.query_grants import (
    KnowledgeQueryGrantProvisioningApplication,
)
from knowledge_source_service.application.query_executor import KnowledgeQueryExecutor
from knowledge_source_service.application.synchronization_executor import (
    KnowledgeSourceSynchronizationExecutor,
)
from knowledge_source_service.application.synchronizations import (
    KnowledgeSourceSynchronizationApplication,
)
from knowledge_source_service.delivery.http import (
    InvalidIdempotencyKey,
    bearer_client_authenticator,
    create_application,
)
from knowledge_source_service.delivery.management_http import (
    AuthenticateKnowledgeOperator,
    create_management_application,
)
from knowledge_source_service.contracts.access_control import KnowledgeQueryGrantPolicy
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.agentic import AgenticRetrievalController
from knowledge_source_service.ports.ocr import DocumentOcrExtractor
from knowledge_source_service.ports.search_projection import HybridSearchProjection
from knowledge_source_service.ports.snapshot_connections import (
    KnowledgeSnapshotConnectionRegistry,
)


@dataclass(frozen=True)
class BasePreparationExecutionConfiguration:
    """Server-owned one-shot execution policy for Release Preparation."""

    worker_id: str
    lease_duration: timedelta
    candidate_ttl: timedelta


@dataclass(frozen=True)
class KnowledgeServiceRuntime:
    """Explicit role handles without an in-memory authority singleton."""

    http_application: FastAPI
    query_executor: KnowledgeQueryExecutor
    synchronization_executor: KnowledgeSourceSynchronizationExecutor | None = None
    base_preparation_executor: BasePreparationExecutor | None = None


def compose_runtime(
    *,
    postgres_dsn: str,
    artifacts: ImmutableArtifactStore,
    release_identity: str,
    dependency_readiness: Callable[[], Mapping[str, bool]],
    clock: Callable[[], datetime],
    query_id_factory: Callable[[], str],
    trace_id_factory: Callable[[], str],
    worker_id: str,
    lease_duration: timedelta,
    result_retention: timedelta,
    authenticate_operator: AuthenticateKnowledgeOperator | None = None,
    document_pipeline_revision: str = "document-pipeline-v1",
    dataset_pipeline_revision: str = "dataset-pipeline-v1",
    max_upload_bytes: int = 50 * 1024 * 1024,
    max_dataset_records: int = 100_000,
    projection: HybridSearchProjection | None = None,
    encoder: ProjectionTextEncoder | None = None,
    agentic_controller: AgenticRetrievalController | None = None,
    ocr_extractor: DocumentOcrExtractor | None = None,
    snapshot_connections: KnowledgeSnapshotConnectionRegistry | None = None,
    synchronization_id_factory: Callable[[], str] | None = None,
    managed_connection_profiles: bool = False,
    connection_profile_policy: ConnectionProfileDeploymentPolicy | None = None,
    connection_profile_id_factory: Callable[[], str] | None = None,
    profile_snapshot_readers: ConnectionProfileSnapshotReaders | None = None,
    base_preparation_id_factory: Callable[[], str] | None = None,
    base_preparation_execution: BasePreparationExecutionConfiguration | None = None,
    query_grant_policy: KnowledgeQueryGrantPolicy | None = None,
) -> KnowledgeServiceRuntime:
    """Compose all online authority ports from durable PostgreSQL/S3 dependencies."""

    if not release_identity.strip():
        raise ValueError("release_identity must not be blank")
    if base_preparation_id_factory is not None and authenticate_operator is None:
        raise ValueError("preparation management requires operator authentication")
    if query_grant_policy is not None and authenticate_operator is None:
        raise ValueError("Query Grant provisioning requires operator authentication")
    if (projection is None) != (encoder is None):
        raise ValueError("projection and encoder must be configured together")
    if managed_connection_profiles:
        if snapshot_connections is not None:
            raise ValueError("managed profiles cannot share static connection authority")
        if connection_profile_id_factory is None or synchronization_id_factory is None:
            raise ValueError(
                "managed profiles require profile and synchronization identity factories"
            )
    elif any(
        value is not None
        for value in (
            connection_profile_policy,
            connection_profile_id_factory,
            profile_snapshot_readers,
        )
    ):
        raise ValueError("profile dependencies require explicit managed profile mode")
    elif (snapshot_connections is None) != (synchronization_id_factory is None):
        raise ValueError(
            "snapshot connections and synchronization identity factory must be configured together"
        )
    query_repository = PostgresKnowledgeQueryRepository.from_dsn(
        postgres_dsn,
        artifacts=artifacts,
    )
    access_control = PostgresKnowledgeAccessControl.from_dsn(postgres_dsn)
    catalog = PostgresKnowledgeCatalog.from_dsn(
        postgres_dsn,
        artifacts=artifacts,
    )
    query_application = KnowledgeQueryApplication(
        repository=query_repository,
        authorizer=access_control,
        clock=clock,
        id_factory=query_id_factory,
    )
    single_pass_engine = (
        HybridKnowledgeRetrievalEngine(catalog=catalog)
        if projection is None or encoder is None
        else IndexedHybridKnowledgeRetrievalEngine(
            catalog=catalog,
            projection=projection,
            encoder=encoder,
        )
    )
    retrieval_engine = BoundedAgenticKnowledgeRetrievalEngine(
        single_pass_engine=single_pass_engine,
        controller=(
            agentic_controller
            if agentic_controller is not None
            else UnavailableAgenticRetrievalController()
        ),
    )
    query_executor = KnowledgeQueryExecutor(
        repository=query_repository,
        retrieval_engine=retrieval_engine,
        clock=clock,
        result_retention=result_retention,
        trace_id_factory=trace_id_factory,
        worker_id=worker_id,
        lease_duration=lease_duration,
    )
    base_preparation_executor: BasePreparationExecutor | None = None
    if base_preparation_execution is not None:
        base_preparation_executor = BasePreparationExecutor(
            worker=BasePreparationWorker(
                repository=PostgresBasePreparationRepository.from_dsn(postgres_dsn),
                worker_id=base_preparation_execution.worker_id,
                lease_duration=base_preparation_execution.lease_duration,
            ),
            builder=KnowledgeReleaseCandidateBuilder(
                releases=KnowledgeReleaseApplication(
                    artifacts=artifacts,
                    catalog=catalog,
                    projection=projection,
                    encoder=encoder,
                )
            ),
            candidate_ttl=base_preparation_execution.candidate_ttl,
        )
    synchronization_application: KnowledgeSourceSynchronizationApplication | None = None
    synchronization_executor: KnowledgeSourceSynchronizationExecutor | None = None
    profiles = (
        ConnectionProfileApplication(
            repository=PostgresConnectionProfileRepository.from_dsn(postgres_dsn),
            policy=connection_profile_policy,
            clock=clock,
            id_factory=connection_profile_id_factory,
        )
        if managed_connection_profiles and connection_profile_id_factory is not None
        else None
    )
    if synchronization_id_factory is not None and (
        snapshot_connections is not None or profiles is not None
    ):
        synchronization_repository = PostgresKnowledgeSourceSynchronizationRepository.from_dsn(
            postgres_dsn
        )
        synchronization_application = KnowledgeSourceSynchronizationApplication(
            repository=synchronization_repository,
            clock=clock,
            id_factory=synchronization_id_factory,
            admit_connection=None
            if snapshot_connections is None
            else snapshot_connections.contains,
            connection_profiles=profiles,
        )
    if synchronization_id_factory is not None and (
        snapshot_connections is not None or profile_snapshot_readers is not None
    ):
        synchronization_executor = KnowledgeSourceSynchronizationExecutor(
            repository=synchronization_repository,
            connections=snapshot_connections,
            connection_profiles=profiles,
            profile_snapshot_readers=profile_snapshot_readers,
            artifacts=artifacts,
            catalog=catalog,
            pipeline_revision=dataset_pipeline_revision,
            max_content_bytes=max_upload_bytes,
            max_records=max_dataset_records,
            clock=clock,
            trace_id_factory=trace_id_factory,
            worker_id=worker_id,
            lease_duration=lease_duration,
        )
    http_application = create_application(
        query_application=query_application,
        release_references=KnowledgeBaseReleaseReferenceApplication(
            repository=PostgresReleaseReferenceRepository.from_dsn(postgres_dsn)
        ),
        authenticate_client=bearer_client_authenticator(access_control.authenticate_bearer_token),
        trace_id_factory=trace_id_factory,
        release_identity=release_identity,
        readiness_probe=dependency_readiness,
    )
    if authenticate_operator is not None:
        public_validation_handler = http_application.exception_handlers.get(RequestValidationError)
        public_idempotency_handler = http_application.exception_handlers.get(InvalidIdempotencyKey)
        management = create_management_application(
            catalog=catalog,
            artifacts=artifacts,
            authenticate_operator=authenticate_operator,
            document_pipeline_revision=document_pipeline_revision,
            dataset_pipeline_revision=dataset_pipeline_revision,
            max_upload_bytes=max_upload_bytes,
            max_dataset_records=max_dataset_records,
            projection=projection,
            encoder=encoder,
            ocr_extractor=ocr_extractor,
            synchronization_application=synchronization_application,
            connection_profiles=profiles,
            base_preparations=(
                KnowledgeBasePreparationApplication(
                    repository=PostgresBasePreparationRepository.from_dsn(postgres_dsn),
                    clock=clock,
                    id_factory=base_preparation_id_factory,
                )
                if base_preparation_id_factory is not None
                else None
            ),
            release_lifecycle=KnowledgeBaseReleaseLifecycleApplication(
                repository=PostgresReleaseLifecycleRepository.from_dsn(postgres_dsn)
            ),
            query_grants=(
                KnowledgeQueryGrantProvisioningApplication(
                    registry=access_control,
                    policy=query_grant_policy,
                )
                if query_grant_policy is not None
                else None
            ),
        )
        http_application.include_router(management.router)
        http_application.exception_handlers.update(management.exception_handlers)
        _preserve_public_client_exception_contract(
            application=http_application,
            exception_type=RequestValidationError,
            public_handler=public_validation_handler,
            management_handler=management.exception_handlers.get(RequestValidationError),
        )
        _preserve_public_client_exception_contract(
            application=http_application,
            exception_type=InvalidIdempotencyKey,
            public_handler=public_idempotency_handler,
            management_handler=management.exception_handlers.get(InvalidIdempotencyKey),
        )
    return KnowledgeServiceRuntime(
        http_application=http_application,
        query_executor=query_executor,
        synchronization_executor=synchronization_executor,
        base_preparation_executor=base_preparation_executor,
    )


def _preserve_public_client_exception_contract(
    *,
    application: FastAPI,
    exception_type: type[Exception],
    public_handler: Any,
    management_handler: Any,
) -> None:
    if public_handler is None or management_handler is None:
        raise ValueError("combined KSS delivery is missing a required exception handler")

    async def dispatch(request: Request, error: Exception) -> Response:
        handler = public_handler if _is_public_client_path(request.url.path) else management_handler
        response = handler(request, error)
        if inspect.isawaitable(response):
            response = await response
        return cast(Response, response)

    application.add_exception_handler(exception_type, dispatch)


def _is_public_client_path(path: str) -> bool:
    return path == "/v1/knowledge-base-release-references" or path.startswith(
        "/v1/knowledge-queries"
    )
