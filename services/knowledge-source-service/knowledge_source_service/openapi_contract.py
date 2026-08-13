"""Deterministic public OpenAPI contract for candidate binding and client checks."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from fastapi import Request

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.adapters.memory.knowledge_queries import (
    InMemoryKnowledgeQueryRepository,
)
from knowledge_source_service.adapters.memory.synchronizations import (
    InMemoryKnowledgeSourceSynchronizationRepository,
)
from knowledge_source_service.application.knowledge_queries import (
    KnowledgeQueryApplication,
    KnowledgeServiceClient,
)
from knowledge_source_service.application.synchronizations import (
    KnowledgeSourceSynchronizationApplication,
)
from knowledge_source_service.delivery.http import create_application
from knowledge_source_service.delivery.management_http import (
    KnowledgeOperator,
    create_management_application,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission


_CONTRACT_TIME = datetime(2026, 1, 1, tzinfo=UTC)


class _OpenApiAuthorizer:
    def authorize(self, *, client_id: str, request: Any) -> KnowledgeQueryAdmission:
        return KnowledgeQueryAdmission(
            knowledge_space_id="openapi-space",
            client_grant_id=f"openapi-grant-{client_id}",
            effective_access_scope_digest=f"sha256:{'0' * 64}",
        )


def build_openapi_contract_bytes() -> bytes:
    """Return canonical bytes for every production API route and schema."""

    artifacts = InMemoryImmutableArtifactStore()
    query_application = KnowledgeQueryApplication(
        repository=InMemoryKnowledgeQueryRepository(),
        authorizer=_OpenApiAuthorizer(),
        clock=lambda: _CONTRACT_TIME,
        id_factory=lambda: "openapi-query",
    )
    application = create_application(
        query_application=query_application,
        authenticate_client=lambda _request: KnowledgeServiceClient(
            client_id="openapi-client"
        ),
        trace_id_factory=lambda: "openapi-trace",
        release_identity="openapi-contract-v1",
        readiness_probe=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
    )
    synchronizations = KnowledgeSourceSynchronizationApplication(
        repository=InMemoryKnowledgeSourceSynchronizationRepository(),
        clock=lambda: _CONTRACT_TIME,
        id_factory=lambda: "openapi-synchronization",
        admit_connection=lambda _connection_id: True,
    )
    management = create_management_application(
        catalog=InMemoryKnowledgeCatalog(),  # type: ignore[arg-type]
        artifacts=artifacts,
        authenticate_operator=_openapi_operator,
        document_pipeline_revision="openapi-document-pipeline-v1",
        dataset_pipeline_revision="openapi-dataset-pipeline-v1",
        max_upload_bytes=1,
        max_dataset_records=1,
        synchronization_application=synchronizations,
    )
    application.include_router(management.router)
    application.exception_handlers.update(management.exception_handlers)
    return json.dumps(
        application.openapi(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _openapi_operator(_request: Request) -> KnowledgeOperator:
    return KnowledgeOperator(operator_id="openapi-operator")


__all__ = ["build_openapi_contract_bytes"]
