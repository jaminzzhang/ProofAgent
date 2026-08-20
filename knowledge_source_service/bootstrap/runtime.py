"""Compose the independently running API and Query Executor roles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import FastAPI

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
from knowledge_source_service.application.query_executor import KnowledgeQueryExecutor
from knowledge_source_service.application.synchronization_executor import (
    KnowledgeSourceSynchronizationExecutor,
)
from knowledge_source_service.application.synchronizations import (
    KnowledgeSourceSynchronizationApplication,
)
from knowledge_source_service.delivery.http import (
    bearer_client_authenticator,
    create_application,
)
from knowledge_source_service.delivery.management_http import (
    AuthenticateKnowledgeOperator,
    create_management_application,
)
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.agentic import AgenticRetrievalController
from knowledge_source_service.ports.ocr import DocumentOcrExtractor
from knowledge_source_service.ports.search_projection import HybridSearchProjection
from knowledge_source_service.ports.snapshot_connections import (
    KnowledgeSnapshotConnectionRegistry,
)


@dataclass(frozen=True)
class KnowledgeServiceRuntime:
    """Explicit role handles without an in-memory authority singleton."""

    http_application: FastAPI
    query_executor: KnowledgeQueryExecutor
    synchronization_executor: KnowledgeSourceSynchronizationExecutor | None = None


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
) -> KnowledgeServiceRuntime:
    """Compose all online authority ports from durable PostgreSQL/S3 dependencies."""

    if not release_identity.strip():
        raise ValueError("release_identity must not be blank")
    if (projection is None) != (encoder is None):
        raise ValueError("projection and encoder must be configured together")
    if (snapshot_connections is None) != (synchronization_id_factory is None):
        raise ValueError(
            "snapshot connections and synchronization identity factory "
            "must be configured together"
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
    synchronization_application: KnowledgeSourceSynchronizationApplication | None = None
    synchronization_executor: KnowledgeSourceSynchronizationExecutor | None = None
    if snapshot_connections is not None and synchronization_id_factory is not None:
        synchronization_repository = (
            PostgresKnowledgeSourceSynchronizationRepository.from_dsn(postgres_dsn)
        )
        synchronization_application = KnowledgeSourceSynchronizationApplication(
            repository=synchronization_repository,
            clock=clock,
            id_factory=synchronization_id_factory,
            admit_connection=snapshot_connections.contains,
        )
        synchronization_executor = KnowledgeSourceSynchronizationExecutor(
            repository=synchronization_repository,
            connections=snapshot_connections,
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
        authenticate_client=bearer_client_authenticator(
            access_control.authenticate_bearer_token
        ),
        trace_id_factory=trace_id_factory,
        release_identity=release_identity,
        readiness_probe=dependency_readiness,
    )
    if authenticate_operator is not None:
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
        )
        http_application.include_router(management.router)
        http_application.exception_handlers.update(management.exception_handlers)
    return KnowledgeServiceRuntime(
        http_application=http_application,
        query_executor=query_executor,
        synchronization_executor=synchronization_executor,
    )
