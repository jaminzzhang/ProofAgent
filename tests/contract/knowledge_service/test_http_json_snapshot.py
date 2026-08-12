from __future__ import annotations

from datetime import UTC, datetime

import httpx

from knowledge_source_service.adapters.http.json_snapshot import (
    HttpJsonSnapshotReader,
)
from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.external_snapshots import (
    HttpJsonSnapshotIntakeApplication,
    HttpJsonSnapshotIntakeCommand,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


def test_http_json_is_materialized_once_before_release_query() -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer snapshot-secret-token"
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "ETag": '"claims-revision-7"',
                "Last-Modified": "Tue, 12 Aug 2026 03:00:00 GMT",
            },
            content=(
                b'{"records":[{"claim_id":"claim-1",'
                b'"claim_total":"12345.67","active":true}]}'
            ),
        )

    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    reader = HttpJsonSnapshotReader(
        endpoint="https://claims.example.test/v1/claims",
        bearer_token="snapshot-secret-token",
        max_response_bytes=4096,
        clock=lambda: datetime(2026, 8, 12, 3, 1, tzinfo=UTC),
        resolve_host=lambda _host: ("93.184.216.34",),
        transport=httpx.MockTransport(upstream),
    )
    try:
        publication = HttpJsonSnapshotIntakeApplication(
            artifacts=artifacts,
            catalog=catalog,
            reader=reader,
            pipeline_revision="dataset-pipeline-v1",
            max_content_bytes=4096,
            max_records=10,
        ).create_source_version(
            HttpJsonSnapshotIntakeCommand(
                knowledge_space_id="space-http",
                knowledge_source_id="source-http",
                display_filename="claims.snapshot.json",
                record_path=("records",),
                field_types={
                    "claim_id": "string",
                    "claim_total": "decimal",
                    "active": "boolean",
                },
            )
        )
    finally:
        reader.close()

    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-http",
            knowledge_base_id="base-http",
            knowledge_source_version_ids=(
                publication.version.knowledge_source_version_id,
            ),
        )
    ).release
    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "question": "active claims",
                    "query_constraints": {
                        "filters": [
                            {"field": "active", "operator": "eq", "value": True}
                        ]
                    },
                    "execution_budget": {
                        "max_rounds": 1,
                        "max_model_calls": 1,
                        "max_candidates": 10,
                        "max_model_tokens": 100,
                        "max_duration_ms": 1000,
                    },
                    "deadline_at": "2026-08-12T04:00:00Z",
                }
            ),
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-http",
                client_grant_id="grant-http",
                effective_access_scope_digest=f"sha256:{'a' * 64}",
            ),
        )
    )

    assert len(requests) == 1
    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.structured_data.fields[1].value == "12345.67"
    assert publication.original_artifact.media_type == "application/json"
