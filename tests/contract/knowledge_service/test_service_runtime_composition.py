from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.postgres.access_control import (
    PostgresKnowledgeAccessControl,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.knowledge_queries import (
    PostgresKnowledgeQueryRepository,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.application.projection_encoding import (
    DeterministicHashProjectionEncoder,
)
from knowledge_source_service.bootstrap.runtime import compose_runtime
from knowledge_source_service.domain.identities import sha256_json
from knowledge_source_service.delivery.management_http import (
    bearer_operator_authenticator,
)
from knowledge_source_service.ports.agentic import (
    AgenticRetrievalDecision,
    AgenticRetrievalObservation,
)
from knowledge_source_service.ports.search_projection import (
    HybridProjectionResult,
    ProjectionAttestation,
    ProjectionEvidenceUnit,
    ProjectionLaneHit,
)
from knowledge_source_service.ports.snapshot_connections import JsonSnapshotConnection
from knowledge_source_service.ports.snapshots import JsonSnapshot
from proof_agent.capabilities.knowledge.source_service_client import (
    KnowledgeSourceServiceClient,
)
from proof_agent.contracts.knowledge_candidates import KnowledgeCandidateQuery
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse


pytestmark = pytest.mark.postgres_integration


class _RuntimeSnapshotReader:
    def read(self) -> JsonSnapshot:
        return JsonSnapshot(
            content=b'{"records":[{"claim_id":"claim-runtime-1"}]}',
            source_identity_digest=sha256_json(
                {"endpoint": "runtime-snapshot-test"}
            ),
            observed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
            etag='"runtime-v1"',
            last_modified=None,
        )


class _RuntimeSnapshotConnections:
    def contains(self, connection_id: str) -> bool:
        return connection_id == "connection-runtime"

    def resolve(self, connection_id: str) -> JsonSnapshotConnection:
        assert self.contains(connection_id)
        return JsonSnapshotConnection(
            connection_id=connection_id,
            connection_kind="http_json",
            reader=_RuntimeSnapshotReader(),
        )


def test_runtime_composes_management_synchronization_api_and_worker(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    runtime = compose_runtime(
        postgres_dsn=kss_postgres_dsn,
        artifacts=InMemoryImmutableArtifactStore(),
        release_identity="kss-runtime-sync-test",
        dependency_readiness=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
        clock=lambda: now,
        query_id_factory=lambda: "query-unused",
        trace_id_factory=lambda: "trace-runtime-sync-1",
        worker_id="query-worker-runtime-sync-1",
        lease_duration=timedelta(seconds=30),
        result_retention=timedelta(hours=24),
        authenticate_operator=bearer_operator_authenticator(
            operator_id="operator-runtime",
            expected_token="operator-runtime-secret",
        ),
        snapshot_connections=_RuntimeSnapshotConnections(),
        synchronization_id_factory=lambda: "source-sync-runtime-1",
    )
    client = TestClient(runtime.http_application)
    authorization = {"Authorization": "Bearer operator-runtime-secret"}
    client.post(
        "/v1/knowledge-spaces",
        headers=authorization,
        json={"knowledge_space_id": "space-runtime-sync"},
    ).raise_for_status()
    client.post(
        "/v1/knowledge-spaces/space-runtime-sync/knowledge-sources",
        headers=authorization,
        json={"knowledge_source_id": "source-runtime-sync"},
    ).raise_for_status()
    created = client.post(
        "/v1/knowledge-source-synchronizations",
        headers={
            **authorization,
            "Idempotency-Key": "runtime-sync-attempt-1",
        },
        json={
            "knowledge_space_id": "space-runtime-sync",
            "knowledge_source_id": "source-runtime-sync",
            "connection_id": "connection-runtime",
            "display_filename": "claims.snapshot.json",
            "record_path": ["records"],
            "field_types": {"claim_id": "string"},
        },
    )

    assert runtime.synchronization_executor is not None
    worked = runtime.synchronization_executor.run_once()
    completed = client.get(created.headers["location"], headers=authorization)

    assert created.status_code == 202
    assert worked is True
    assert completed.status_code == 200
    assert completed.json()["state"] == "succeeded"
    assert completed.json()["materialized_knowledge_source_version_id"].startswith(
        "source-version-"
    )


def test_runtime_composes_authenticated_api_queue_worker_and_exact_retrieval(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    projection = _InProcessHybridProjection()
    encoder = DeterministicHashProjectionEncoder(dense_dimension=32)
    agentic_controller = _CompleteAfterOneRoundController()
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    catalog.create_space("space-runtime")
    catalog.create_source(
        knowledge_space_id="space-runtime",
        knowledge_source_id="source-runtime",
    )
    catalog.create_base(
        knowledge_space_id="space-runtime",
        knowledge_base_id="base-runtime",
    )
    source = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-runtime",
            knowledge_source_id="source-runtime",
            display_filename="runtime.md",
            media_type="text/markdown",
            content="# 赔付\n航班延误满四小时赔付 300 元。\n".encode(),
        )
    )
    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
        projection=projection,
        encoder=encoder,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-runtime",
            knowledge_base_id="base-runtime",
            knowledge_source_version_ids=(source.version.knowledge_source_version_id,),
        )
    ).release
    access = PostgresKnowledgeAccessControl.from_dsn(kss_postgres_dsn)
    access.register_client(
        client_id="proof-agent-runtime",
        bearer_token="runtime-secret-token-1",
    )
    access.grant_release_query(
        client_grant_id="grant-runtime",
        client_id="proof-agent-runtime",
        knowledge_base_release_id=release.knowledge_base_release_id,
        allowed_strategies=("single_pass", "agentic"),
        max_rounds=1,
        max_model_calls=1,
        max_candidates=20,
        max_model_tokens=1000,
        max_duration_ms=5000,
        effective_access_scope_digest=f"sha256:{'c' * 64}",
    )
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    query_ids = iter(("query-runtime-1", "query-runtime-2"))
    runtime = compose_runtime(
        postgres_dsn=kss_postgres_dsn,
        artifacts=artifacts,
        release_identity="kss-runtime-test",
        dependency_readiness=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
        clock=lambda: now,
        query_id_factory=lambda: next(query_ids),
        trace_id_factory=lambda: "trace-runtime-1",
        worker_id="query-worker-runtime-1",
        lease_duration=timedelta(seconds=30),
        result_retention=timedelta(hours=24),
        projection=projection,
        encoder=encoder,
        agentic_controller=agentic_controller,
    )
    client = TestClient(runtime.http_application)

    denied = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer wrong-secret-token",
            "Idempotency-Key": "runtime-attempt-1",
        },
        json={
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "航班延误赔付多少？",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1000,
                "max_duration_ms": 5000,
            },
            "deadline_at": "2026-08-12T10:01:00Z",
        },
    )
    created = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer runtime-secret-token-1",
            "Idempotency-Key": "runtime-attempt-1",
        },
        json={
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "航班延误 四小时 赔付",
            "strategy": "agentic",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1000,
                "max_duration_ms": 5000,
            },
            "deadline_at": "2026-08-12T10:01:00Z",
        },
    )
    worked = runtime.query_executor.run_once()
    completed = client.get(
        created.headers["location"],
        headers={"Authorization": "Bearer runtime-secret-token-1"},
    )

    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    assert created.status_code == 202
    assert worked is True
    assert completed.status_code == 200
    body = completed.json()
    assert body["state"] == "succeeded"
    candidate = body["result"]["evidence_groups"][0]["candidate_evidence"][0]
    assert candidate["content"]["text"] == "航班延误满四小时赔付 300 元。"
    assert candidate["knowledge_base_release_id"] == release.knowledge_base_release_id
    assert body["result"]["execution_summary"]["strategy"] == "agentic"
    assert len(agentic_controller.observations) == 1
    assert candidate["retrieval_lineage"]["index_identity"] == (
        release.retrieval_projection.index_identity
        if release.retrieval_projection is not None
        else None
    )
    with psycopg.connect(kss_postgres_dsn, row_factory=dict_row) as connection:
        persisted = connection.execute(
            """
            SELECT query_json, result_artifact_json, result_digest
            FROM knowledge_queries
            WHERE knowledge_query_id = 'query-runtime-1'
            """
        ).fetchone()
    assert persisted is not None
    assert persisted["query_json"]["result"] is None
    assert persisted["result_artifact_json"]["object_key"].endswith("/result.json")
    assert persisted["result_digest"] == persisted["result_artifact_json"]["sha256"]
    assert any(key.endswith("/result.json") for key in artifacts.keys())

    proof_client = KnowledgeSourceServiceClient(
        endpoint="https://knowledge.internal",
        http_client=_TestClientGuardedHttpClient(
            client=client,
            after_create=runtime.query_executor.run_once,
        ),
        authorization_header_factory=lambda: "Bearer runtime-secret-token-1",
        sleep=lambda _seconds: None,
        max_polls=2,
    )
    proof_result = proof_client.query(
        KnowledgeCandidateQuery.model_validate(
            {
                "idempotency_key": "runtime-proof-agent-attempt-1",
                "knowledge_base_release_id": release.knowledge_base_release_id,
                "question": "航班延误 四小时 赔付",
                "strategy": "agentic",
                "execution_budget": {
                    "max_rounds": 1,
                    "max_model_calls": 1,
                    "max_candidates": 20,
                    "max_model_tokens": 1000,
                    "max_duration_ms": 5000,
                },
                "deadline_at": "2026-08-12T10:01:00Z",
            }
        )
    )

    assert proof_result.knowledge_query_id == "query-runtime-2"
    assert (
        proof_result.evidence_groups[0].candidate_evidence[0].content.text
        == "航班延误满四小时赔付 300 元。"
    )
    assert len(agentic_controller.observations) == 2

    reaper_repository = PostgresKnowledgeQueryRepository.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    expired_count = reaper_repository.expire_available_results(
        now=now + timedelta(days=2),
        limit=10,
    )
    expired_query = reaper_repository.get("query-runtime-1")

    assert expired_count == 2
    assert expired_query is not None
    assert expired_query.query.result_availability == "expired"
    assert expired_query.query.result is None


class _InProcessHybridProjection:
    def __init__(self) -> None:
        self._generations: dict[str, tuple[ProjectionEvidenceUnit, ...]] = {}

    def rebuild(
        self,
        *,
        index_identity: str,
        dense_dimension: int,
        documents: tuple[ProjectionEvidenceUnit, ...],
    ) -> ProjectionAttestation:
        self._generations[index_identity] = documents
        return ProjectionAttestation(
            index_identity=index_identity,
            mapping_digest=sha256_json({"dense_dimension": dense_dimension}),
            corpus_digest=sha256_json(
                [
                    {
                        "evidence_unit_id": document.evidence_unit_id,
                        "knowledge_source_version_id": (
                            document.knowledge_source_version_id
                        ),
                        "content_hash": document.content_hash,
                        "dense_vector": document.dense_vector,
                        "sparse_vector": dict(document.sparse_vector),
                    }
                    for document in documents
                ]
            ),
            document_count=len(documents),
        )

    def query(
        self,
        *,
        index_identity: str,
        lexical_query: str,
        dense_vector: tuple[float, ...],
        sparse_vector: dict[str, float],
        top_k: int,
    ) -> HybridProjectionResult:
        del lexical_query, dense_vector, sparse_vector
        documents = self._generations[index_identity][:top_k]

        def hits(lane: str) -> tuple[ProjectionLaneHit, ...]:
            return tuple(
                ProjectionLaneHit(
                    lane=lane,  # type: ignore[arg-type]
                    evidence_unit_id=document.evidence_unit_id,
                    native_score=float(len(documents) - rank + 1),
                    lane_rank=rank,
                    index_identity=index_identity,
                )
                for rank, document in enumerate(documents, start=1)
            )

        return HybridProjectionResult(
            lexical=hits("lexical"),
            sparse=hits("sparse"),
            dense=hits("dense"),
        )

    def verify_generation(self, attestation: ProjectionAttestation) -> None:
        assert len(self._generations[attestation.index_identity]) == (
            attestation.document_count
        )


class _CompleteAfterOneRoundController:
    def __init__(self) -> None:
        self.observations: list[AgenticRetrievalObservation] = []

    def decide(
        self,
        observation: AgenticRetrievalObservation,
    ) -> AgenticRetrievalDecision:
        self.observations.append(observation)
        return AgenticRetrievalDecision(
            action="complete",
            revised_question=None,
            model_tokens_used=0,
        )


class _TestClientGuardedHttpClient:
    def __init__(
        self,
        *,
        client: TestClient,
        after_create: Any,
    ) -> None:
        self._client = client
        self._after_create = after_create

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Any = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        del timeout_seconds
        parsed = urlsplit(url)
        response = self._client.request(
            method,
            parsed.path,
            headers=headers,
            content=body,
        )
        if method == "POST" and response.status_code == 202:
            self._after_create()
        return GuardedHttpResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )
