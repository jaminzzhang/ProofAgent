from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest
from pydantic import ValidationError
import yaml  # type: ignore[import-untyped]

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.postgres.access_control import (
    KnowledgeAccessConflict,
    PostgresKnowledgeAccessControl,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.knowledge_queries import (
    PostgresKnowledgeQueryRepository,
)
from knowledge_source_service.adapters.postgres.release_references import (
    PostgresReleaseLifecycleRepository,
    PostgresReleaseReferenceRepository,
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
from knowledge_source_service.application.query_grants import (
    KnowledgeQueryGrantProvisioningApplication,
)
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseLifecycleApplication,
)
from knowledge_source_service.application.projection_encoding import (
    DeterministicHashProjectionEncoder,
)
from knowledge_source_service.bootstrap.runtime import (
    BasePreparationExecutionConfiguration,
    compose_runtime,
)
from knowledge_source_service.bootstrap.reference_client import (
    provision_reference_client,
)
from knowledge_source_service.bootstrap.runtime_client import provision_runtime_client
from knowledge_source_service.configuration import ApiRuntimeConfiguration
from knowledge_source_service.contracts.access_control import (
    KnowledgeQueryGrantPolicy,
    ProvisionKnowledgeQueryGrantRequest,
)
from knowledge_source_service.contracts.release_references import (
    DeprecateKnowledgeBaseReleaseRequest,
    RetireKnowledgeBaseReleaseRequest,
)
from knowledge_source_service.domain.identities import sha256_json
from knowledge_source_service.domain.release_references import ReleaseRetentionPolicy
from knowledge_source_service.delivery.management_http import (
    bearer_operator_authenticator,
)
from knowledge_source_service.contracts.connection_profiles import HttpSnapshotProfile
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
from proof_agent.capabilities.knowledge.source_service_management_client import (
    KnowledgeSourceServiceManagementClient,
)
from proof_agent.capabilities.knowledge.source_service_query_grant_provisioner import (
    KnowledgeSourceServiceQueryGrantProvisioner,
)
from proof_agent.capabilities.knowledge.source_service_release_reference_registrar import (
    KnowledgeSourceServiceReleaseReferenceRegistrar,
)
from proof_agent.contracts import (
    Permission,
    ProductionAgentKnowledgeQueryGrantRequest,
    ProductionAgentReleaseReferenceRequest,
)
from proof_agent.contracts.knowledge_candidates import KnowledgeCandidateQuery
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.delivery.knowledge_service_management_api import (
    router as knowledge_service_management_router,
)
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


pytestmark = pytest.mark.postgres_integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class _RuntimeSnapshotReader:
    def read(self) -> JsonSnapshot:
        return JsonSnapshot(
            content=b'{"records":[{"claim_id":"claim-runtime-1"}]}',
            source_identity_digest=sha256_json({"endpoint": "runtime-snapshot-test"}),
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


class _RuntimeConnectionProfilePolicy:
    def validate(self, configuration: HttpSnapshotProfile) -> str:
        assert configuration.kind == "http_json"
        return "runtime-profile-policy-v1"


def test_runtime_requires_operator_authentication_for_query_grant_policy() -> None:
    with pytest.raises(
        ValueError,
        match="Query Grant provisioning requires operator authentication",
    ):
        compose_runtime(
            postgres_dsn="not-used-before-query-grant-auth-validation",
            artifacts=InMemoryImmutableArtifactStore(),
            release_identity="kss-query-grant-auth-test",
            dependency_readiness=lambda: {},
            clock=lambda: datetime(2026, 8, 30, tzinfo=UTC),
            query_id_factory=lambda: "query-unused",
            trace_id_factory=lambda: "trace-unused",
            worker_id="worker-unused",
            lease_duration=timedelta(seconds=30),
            result_retention=timedelta(hours=24),
            query_grant_policy=KnowledgeQueryGrantPolicy(
                client_id="proof-agent-runtime",
                allowed_strategies=("single_pass",),
                execution_budget={
                    "max_rounds": 1,
                    "max_model_calls": 1,
                    "max_candidates": 20,
                    "max_model_tokens": 1000,
                    "max_duration_ms": 5000,
                },
                effective_access_scope_digest=f"sha256:{'c' * 64}",
            ),
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


def test_proof_agent_bff_manages_profile_and_sync_through_real_kss_postgres(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    runtime = compose_runtime(
        postgres_dsn=kss_postgres_dsn,
        artifacts=InMemoryImmutableArtifactStore(),
        release_identity="kss-runtime-profile-bff-test",
        dependency_readiness=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
        clock=lambda: datetime(2026, 8, 29, 6, 30, tzinfo=UTC),
        query_id_factory=lambda: "query-unused",
        trace_id_factory=lambda: "trace-unused",
        worker_id="query-worker-unused",
        lease_duration=timedelta(seconds=30),
        result_retention=timedelta(hours=24),
        authenticate_operator=bearer_operator_authenticator(
            operator_id="proof-agent-management",
            expected_token="operator-runtime-secret",
        ),
        managed_connection_profiles=True,
        connection_profile_policy=_RuntimeConnectionProfilePolicy(),
        connection_profile_id_factory=lambda: "profile-runtime-1",
        synchronization_id_factory=lambda: "sync-runtime-profile-1",
    )
    kss_client = TestClient(runtime.http_application)
    management = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal",
        http_client=_TestClientGuardedHttpClient(
            client=kss_client,
            after_create=lambda: None,
        ),
        authorization_header_factory=lambda: "Bearer operator-runtime-secret",
    )
    app = FastAPI()
    app.state.knowledge_service_management_client = management
    app.include_router(knowledge_service_management_router, prefix="/api")
    app.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id="operator-browser",
        display_name="Browser Operator",
        permissions=frozenset(
            {
                Permission.KNOWLEDGE_SOURCE_VIEW,
                Permission.KNOWLEDGE_SOURCE_EDIT,
            }
        ),
    )
    browser = TestClient(app)
    profile_draft = {
        "knowledge_space_id": "space-runtime-profile",
        "knowledge_source_id": "source-runtime-profile",
        "configuration": {
            "kind": "http_json",
            "endpoint": "https://snapshot.example.test/v1/claims",
            "credential": {"handle_id": "claims-reader", "version": 3},
            "egress_policy_id": "egress-claims",
            "trust_root_id": "trust-internal",
            "max_response_bytes": 1_048_576,
        },
    }

    browser.post(
        "/api/config/knowledge-service/spaces",
        json={"knowledge_space_id": "space-runtime-profile"},
    ).raise_for_status()
    browser.post(
        "/api/config/knowledge-service/spaces/space-runtime-profile/sources",
        json={"knowledge_source_id": "source-runtime-profile"},
    ).raise_for_status()
    created = browser.post(
        "/api/config/knowledge-service/connection-profiles",
        headers={"Idempotency-Key": "runtime-profile-create-1"},
        json=profile_draft,
    )
    validated = browser.post(
        "/api/config/knowledge-service/connection-profiles/profile-runtime-1:validate",
        headers={"Idempotency-Key": "runtime-profile-validate-1"},
        json={"expected_revision": 1},
    )
    published = browser.post(
        "/api/config/knowledge-service/connection-profiles/profile-runtime-1:publish",
        headers={"Idempotency-Key": "runtime-profile-publish-1"},
        json={"expected_revision": 1},
    )
    synchronization_request = {
        "knowledge_space_id": "space-runtime-profile",
        "knowledge_source_id": "source-runtime-profile",
        "connection_profile": {
            "connection_profile_id": "profile-runtime-1",
            "revision": 1,
        },
        "display_filename": "claims.json",
        "record_path": ["claims"],
        "field_types": {"claim_id": "string", "claim_total": "decimal"},
    }
    submitted = browser.post(
        "/api/config/knowledge-service/synchronizations",
        headers={"Idempotency-Key": "runtime-profile-sync-1"},
        json=synchronization_request,
    )
    replayed = browser.post(
        "/api/config/knowledge-service/synchronizations",
        headers={"Idempotency-Key": "runtime-profile-sync-1"},
        json=synchronization_request,
    )
    fetched = browser.get("/api/config/knowledge-service/synchronizations/sync-runtime-profile-1")

    assert created.status_code == 201
    assert created.json()["state"] == "draft"
    assert validated.status_code == 200
    assert validated.json()["state"] == "validated"
    assert published.status_code == 200
    assert published.json()["state"] == "published"
    assert submitted.status_code == 202
    assert replayed.status_code == 200
    assert submitted.json() == replayed.json() == fetched.json()
    assert submitted.json()["state"] == "queued"
    assert submitted.json()["connection_profile"]["revision"] == 1
    for response in (created, validated, published, submitted, replayed, fetched):
        assert "snapshot.example.test" not in response.text
        assert "claims-reader" not in response.text
        assert "egress-claims" not in response.text
        assert "trust-internal" not in response.text
        assert "operator-runtime-secret" not in response.text


def test_proof_agent_bff_manages_base_preparation_through_real_kss_postgres(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    preparation_ids = iter(
        (
            "preparation-runtime-bff-1",
            "preparation-runtime-bff-cancel-1",
            "preparation-runtime-bff-expire-1",
        )
    )
    runtime = compose_runtime(
        postgres_dsn=kss_postgres_dsn,
        artifacts=artifacts,
        release_identity="kss-runtime-base-preparation-bff-test",
        dependency_readiness=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
        clock=lambda: datetime(2026, 8, 29, 7, 0, tzinfo=UTC),
        query_id_factory=lambda: "query-unused",
        trace_id_factory=lambda: "trace-unused",
        worker_id="query-worker-unused",
        lease_duration=timedelta(seconds=30),
        result_retention=timedelta(hours=24),
        authenticate_operator=bearer_operator_authenticator(
            operator_id="proof-agent-management",
            expected_token="operator-runtime-secret",
        ),
        base_preparation_id_factory=lambda: next(preparation_ids),
    )
    kss_client = TestClient(runtime.http_application)
    management = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal",
        http_client=_TestClientGuardedHttpClient(
            client=kss_client,
            after_create=lambda: None,
        ),
        authorization_header_factory=lambda: "Bearer operator-runtime-secret",
    )
    app = FastAPI()
    app.state.knowledge_service_management_client = management
    app.include_router(knowledge_service_management_router, prefix="/api")
    app.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id="operator-browser",
        display_name="Browser Operator",
        permissions=frozenset(
            {
                Permission.KNOWLEDGE_SOURCE_VIEW,
                Permission.KNOWLEDGE_SOURCE_EDIT,
            }
        ),
    )
    browser = TestClient(app)
    space_id = "space-runtime-preparation"
    source_id = "source-runtime-preparation"
    base_id = "base-runtime-preparation"

    browser.post(
        "/api/config/knowledge-service/spaces",
        json={"knowledge_space_id": space_id},
    ).raise_for_status()
    browser.post(
        f"/api/config/knowledge-service/spaces/{space_id}/sources",
        json={"knowledge_source_id": source_id},
    ).raise_for_status()
    browser.post(
        f"/api/config/knowledge-service/spaces/{space_id}/bases",
        json={"knowledge_base_id": base_id},
    ).raise_for_status()
    catalog = PostgresKnowledgeCatalog.from_dsn(kss_postgres_dsn, artifacts=artifacts)
    source = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id=space_id,
            knowledge_source_id=source_id,
            display_filename="runtime-preparation.md",
            media_type="text/markdown",
            content=b"Synthetic Base Preparation vertical fixture.",
        )
    )
    draft_path = f"/api/config/knowledge-service/spaces/{space_id}/bases/{base_id}/draft"
    draft_request = {
        "expected_revision": 0,
        "members": [
            {
                "knowledge_source_id": source_id,
                "selection": "exact",
                "knowledge_source_version_id": source.version.knowledge_source_version_id,
            }
        ],
    }

    saved = browser.put(
        draft_path,
        headers={"Idempotency-Key": "runtime-base-draft-1"},
        json=draft_request,
    )
    historical = browser.get(draft_path, params={"revision": 1})
    preparations_path = f"{draft_path.removesuffix('/draft')}/release-preparations"
    submitted = browser.post(
        preparations_path,
        headers={"Idempotency-Key": "runtime-preparation-1"},
        json={"draft_revision": 1},
    )
    replayed = browser.post(
        preparations_path,
        headers={"Idempotency-Key": "runtime-preparation-1"},
        json={"draft_revision": 1},
    )
    queued = browser.get(submitted.headers["location"])

    assert runtime.base_preparation_executor is None
    execution_runtime = compose_runtime(
        postgres_dsn=kss_postgres_dsn,
        artifacts=artifacts,
        release_identity="kss-runtime-base-preparation-executor-test",
        dependency_readiness=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
        clock=lambda: datetime(2026, 8, 29, 7, 1, tzinfo=UTC),
        query_id_factory=lambda: "query-unused",
        trace_id_factory=lambda: "trace-unused",
        worker_id="query-worker-unused",
        lease_duration=timedelta(seconds=30),
        result_retention=timedelta(hours=24),
        base_preparation_execution=BasePreparationExecutionConfiguration(
            worker_id="base-preparation-worker-runtime-1",
            lease_duration=timedelta(seconds=30),
            candidate_ttl=timedelta(hours=1),
        ),
    )
    assert execution_runtime.base_preparation_executor is not None
    executed = execution_runtime.base_preparation_executor.run_once()
    fetched = browser.get(submitted.headers["location"])
    assert (
        catalog.list_releases(
            knowledge_space_id=space_id,
            knowledge_base_id=base_id,
        )
        == ()
    )
    published = browser.post(f"{submitted.headers['location']}:publish")
    recovered = browser.get(submitted.headers["location"])
    cancellation_target = browser.post(
        preparations_path,
        headers={"Idempotency-Key": "runtime-preparation-cancel-target-1"},
        json={"draft_revision": 1},
    )
    cancelled = browser.post(
        f"{cancellation_target.headers['location']}:cancel",
        headers={"Idempotency-Key": "runtime-preparation-cancel-1"},
    )
    cancelled_replay = browser.post(
        f"{cancellation_target.headers['location']}:cancel",
        headers={"Idempotency-Key": "runtime-preparation-cancel-1"},
    )
    cancelled_current = browser.get(cancellation_target.headers["location"])
    expiry_target = browser.post(
        preparations_path,
        headers={"Idempotency-Key": "runtime-preparation-expiry-target-1"},
        json={"draft_revision": 1},
    )
    expiry_ready = execution_runtime.base_preparation_executor.run_once()
    assert expiry_ready is not None and expiry_ready.state == "ready"
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute(
            """UPDATE knowledge_release_preparations
               SET candidate_expires_at = terminal_at + interval '1 microsecond',
                   resource_json = jsonb_set(
                       resource_json,
                       '{expires_at}',
                       to_jsonb(terminal_at + interval '1 microsecond')
                   )
               WHERE release_preparation_id = %s""",
            (expiry_ready.release_preparation_id,),
        )
    expired = browser.post(f"{expiry_target.headers['location']}:expire")
    expired_replay = browser.post(f"{expiry_target.headers['location']}:expire")
    expired_current = browser.get(expiry_target.headers["location"])
    audit_path = f"{draft_path.removesuffix('/draft')}/preparation-audit"
    audit_page_one = browser.get(audit_path, params={"offset": 0, "limit": 2})
    audit_page_two = browser.get(audit_path, params={"offset": 2, "limit": 2})
    audit_page_three = browser.get(audit_path, params={"offset": 4, "limit": 2})

    assert saved.status_code == 200
    assert saved.json() == historical.json()
    assert saved.json()["revision"] == 1
    assert submitted.status_code == 202
    assert replayed.status_code == 202
    assert submitted.json() == replayed.json() == queued.json()
    assert submitted.json()["state"] == "queued"
    assert submitted.json()["draft_revision"] == 1
    assert submitted.json()["base_version"]["members"] == [
        {
            "knowledge_source_id": source_id,
            "knowledge_source_version_id": source.version.knowledge_source_version_id,
        }
    ]
    assert executed is not None
    assert executed.state == "ready"
    assert fetched.status_code == 200
    assert fetched.json()["state"] == "ready"
    assert "artifact" not in fetched.text
    assert "worker" not in fetched.text
    assert published.status_code == 200
    assert published.headers["location"] == submitted.headers["location"]
    assert published.json() == recovered.json()
    assert published.json()["state"] == "consumed"
    assert published.json()["knowledge_base_release_id"] == executed.knowledge_base_release_id
    assert cancellation_target.status_code == 202
    assert cancellation_target.json()["state"] == "queued"
    assert cancelled.status_code == 200
    assert cancelled.headers["location"] == cancellation_target.headers["location"]
    assert cancelled.json() == cancelled_replay.json() == cancelled_current.json()
    assert cancelled.json()["state"] == "cancelled"
    assert expiry_target.status_code == 202
    assert expiry_target.json()["state"] == "queued"
    assert expired.status_code == 200
    assert expired.headers["location"] == expiry_target.headers["location"]
    assert expired.json() == expired_replay.json() == expired_current.json()
    assert expired.json()["state"] == "expired"
    assert audit_page_one.status_code == 200
    assert audit_page_two.status_code == 200
    assert audit_page_three.status_code == 200
    assert audit_page_one.json()["page"] == {
        "offset": 0,
        "limit": 2,
        "total": 5,
        "returned": 2,
        "has_more": True,
    }
    assert audit_page_two.json()["page"] == {
        "offset": 2,
        "limit": 2,
        "total": 5,
        "returned": 2,
        "has_more": True,
    }
    assert audit_page_three.json()["page"] == {
        "offset": 4,
        "limit": 2,
        "total": 5,
        "returned": 1,
        "has_more": False,
    }
    audit_entries = (
        audit_page_one.json()["entries"]
        + audit_page_two.json()["entries"]
        + audit_page_three.json()["entries"]
    )
    assert sorted(entry["action"] for entry in audit_entries) == [
        "cancel",
        "save_draft",
        "start",
        "start",
        "start",
    ]
    assert {entry["actor"]["identity_kind"] for entry in audit_entries} == {"kss_service_operator"}
    assert {entry["actor"]["operator_id"] for entry in audit_entries} == {"proof-agent-management"}
    assert "operator-browser" not in audit_page_one.text + audit_page_two.text
    releases = catalog.list_releases(
        knowledge_space_id=space_id,
        knowledge_base_id=base_id,
    )
    assert len(releases) == 1
    assert releases[0].knowledge_base_release_id == executed.knowledge_base_release_id
    for response in (
        saved,
        historical,
        submitted,
        replayed,
        fetched,
        published,
        recovered,
        cancellation_target,
        cancelled,
        cancelled_replay,
        cancelled_current,
        expiry_target,
        expired,
        expired_replay,
        expired_current,
        audit_page_one,
        audit_page_two,
        audit_page_three,
    ):
        assert "operator-runtime-secret" not in response.text
        assert "worker_id" not in response.text
        assert "fencing_token" not in response.text
        assert "lease_expires_at" not in response.text


def test_runtime_composes_release_deletion_read_fail_closed_without_artifact_authority(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(kss_postgres_dsn, artifacts=artifacts)
    catalog.create_space("space-lifecycle")
    catalog.create_source(
        knowledge_space_id="space-lifecycle",
        knowledge_source_id="source-lifecycle",
    )
    catalog.create_base(
        knowledge_space_id="space-lifecycle",
        knowledge_base_id="base-lifecycle",
    )
    source = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-lifecycle",
            knowledge_source_id="source-lifecycle",
            display_filename="lifecycle.md",
            media_type="text/markdown",
            content=b"# Synthetic lifecycle fixture\nOne retained fact.\n",
        )
    )
    release = (
        KnowledgeReleaseApplication(
            artifacts=artifacts,
            catalog=catalog,
        )
        .publish(
            PublishKnowledgeReleaseCommand(
                knowledge_space_id="space-lifecycle",
                knowledge_base_id="base-lifecycle",
                knowledge_source_version_ids=(source.version.knowledge_source_version_id,),
            )
        )
        .release
    )
    lifecycle = KnowledgeBaseReleaseLifecycleApplication(
        repository=PostgresReleaseLifecycleRepository.from_dsn(kss_postgres_dsn),
        retention_policy=ReleaseRetentionPolicy(
            policy_id="runtime-zero-retention",
            minimum_age=timedelta(0),
        ),
    )
    lifecycle.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id="space-lifecycle",
            knowledge_base_id="base-lifecycle",
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="operator-runtime",
        idempotency_key="deprecate-runtime-release",
    )
    lifecycle.retire(
        RetireKnowledgeBaseReleaseRequest(
            knowledge_space_id="space-lifecycle",
            knowledge_base_id="base-lifecycle",
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="operator-runtime",
        idempotency_key="retire-runtime-release",
    )
    runtime = compose_runtime(
        postgres_dsn=kss_postgres_dsn,
        artifacts=artifacts,
        release_identity="kss-runtime-lifecycle-test",
        dependency_readiness=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
        clock=lambda: datetime(2026, 8, 29, tzinfo=UTC),
        query_id_factory=lambda: "query-unused",
        trace_id_factory=lambda: "trace-unused",
        worker_id="query-worker-unused",
        lease_duration=timedelta(seconds=30),
        result_retention=timedelta(hours=24),
        authenticate_operator=bearer_operator_authenticator(
            operator_id="operator-runtime",
            expected_token="operator-runtime-secret",
        ),
    )

    response = TestClient(runtime.http_application).get(
        (
            "/v1/knowledge-spaces/space-lifecycle/knowledge-bases/base-lifecycle/"
            f"releases/{release.knowledge_base_release_id}/deletion-eligibility"
        ),
        headers={"Authorization": "Bearer operator-runtime-secret"},
    )

    assert response.status_code == 200
    assert response.json()["release_state"] == "retired"
    assert response.json()["eligible"] is False
    assert response.json()["blockers"] == ["artifact_retention_unverified"]
    assert response.json()["artifact_retention_state"] == "unverified"


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
    release = (
        KnowledgeReleaseApplication(
            artifacts=artifacts,
            catalog=catalog,
            projection=projection,
            encoder=encoder,
        )
        .publish(
            PublishKnowledgeReleaseCommand(
                knowledge_space_id="space-runtime",
                knowledge_base_id="base-runtime",
                knowledge_source_version_ids=(source.version.knowledge_source_version_id,),
            )
        )
        .release
    )
    other_source = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-runtime",
            knowledge_source_id="source-runtime",
            display_filename="runtime-v2.md",
            media_type="text/markdown",
            content="# 其他版本\n这是另一个可查询 Release。\n".encode(),
        )
    )
    other_release = (
        KnowledgeReleaseApplication(
            artifacts=artifacts,
            catalog=catalog,
            projection=projection,
            encoder=encoder,
        )
        .publish(
            PublishKnowledgeReleaseCommand(
                knowledge_space_id="space-runtime",
                knowledge_base_id="base-runtime",
                knowledge_source_version_ids=(other_source.version.knowledge_source_version_id,),
            )
        )
        .release
    )
    compose = yaml.safe_load(
        (REPOSITORY_ROOT / "docker-compose.production-local.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    runtime_bootstrap_environment = services["kss-runtime-client-bootstrap"]["environment"]
    grant_policy = ApiRuntimeConfiguration.from_environment(
        services["kss-api"]["environment"]
    ).query_grant_policy
    assert grant_policy is not None
    access = PostgresKnowledgeAccessControl.from_dsn(kss_postgres_dsn)
    historical_client_id = "proof-agent-production-local"
    provision_runtime_client(
        access,
        client_id=historical_client_id,
        bearer_token="historical-runtime-secret-token-05r",
    )
    historical_grant = access.grant_release_query(
        client_grant_id="historical-query-grant-05r",
        client_id=historical_client_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
        allowed_strategies=("single_pass",),
        max_rounds=1,
        max_model_calls=1,
        max_candidates=10,
        max_model_tokens=500,
        max_duration_ms=5000,
        effective_access_scope_digest=f"sha256:{'9' * 64}",
    )
    provision_runtime_client(
        access,
        client_id=runtime_bootstrap_environment["KSS_RUNTIME_CLIENT_ID"],
        bearer_token="runtime-secret-token-1",
    )
    assert grant_policy.client_id == runtime_bootstrap_environment["KSS_RUNTIME_CLIENT_ID"]
    assert grant_policy.client_id == "proof-agent-production-local-v2"
    assert grant_policy.client_id != historical_grant.client_id
    grant_request = ProvisionKnowledgeQueryGrantRequest(
        knowledge_base_release_id=release.knowledge_base_release_id,
    )
    with pytest.raises(ValidationError):
        ProvisionKnowledgeQueryGrantRequest.model_validate(
            {
                **grant_request.model_dump(mode="json"),
                "knowledge_space_id": release.knowledge_space_id,
                "client_id": "proof-agent-formal-publication-reference",
                "execution_budget": grant_policy.execution_budget.model_dump(mode="json"),
            }
        )
    provision_reference_client(
        access,
        client_id="proof-agent-formal-publication-reference",
        bearer_token="reference-secret-token-05j",
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
        authenticate_operator=bearer_operator_authenticator(
            operator_id="operator-runtime",
            expected_token="operator-runtime-secret",
        ),
        query_grant_policy=grant_policy,
        projection=projection,
        encoder=encoder,
        agentic_controller=agentic_controller,
    )
    client = TestClient(runtime.http_application)
    operator_authorization = {"Authorization": "Bearer operator-runtime-secret"}
    reference_registrar = KnowledgeSourceServiceReleaseReferenceRegistrar(
        endpoint="https://knowledge.internal",
        http_client=_TestClientGuardedHttpClient(
            client=client,
            after_create=lambda: None,
        ),
        authorization_header_factory=lambda: "Bearer reference-secret-token-05j",
    )
    reference_request = ProductionAgentReleaseReferenceRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
        external_resource_id="provisional-agent-version-runtime-05n",
    )
    first_reference = reference_registrar.register_release_reference(
        reference_request,
        idempotency_key="formal-agent-reference:provisional-agent-version-runtime-05n",
    )
    replayed_reference = reference_registrar.register_release_reference(
        reference_request,
        idempotency_key="formal-agent-reference:provisional-agent-version-runtime-05n",
    )
    reference_ledger = PostgresReleaseReferenceRepository.from_dsn(kss_postgres_dsn)

    assert replayed_reference == first_reference
    assert first_reference.authenticated_client_id == ("proof-agent-formal-publication-reference")
    assert reference_ledger.get(first_reference.release_reference_id) is not None
    assert len(reference_ledger.audit(release.knowledge_base_release_id)) == 1

    grant_provisioner = KnowledgeSourceServiceQueryGrantProvisioner(
        endpoint="https://knowledge.internal",
        http_client=_TestClientGuardedHttpClient(
            client=client,
            after_create=lambda: None,
        ),
        authorization_header_factory=lambda: "Bearer operator-runtime-secret",
    )
    proof_agent_grant_request = ProductionAgentKnowledgeQueryGrantRequest(
        knowledge_base_release_id=release.knowledge_base_release_id,
    )
    provisioned = grant_provisioner.provision_query_grant(proof_agent_grant_request)
    replayed = grant_provisioner.provision_query_grant(proof_agent_grant_request)
    unauthorized_provisioning = client.post(
        "/v1/knowledge-query-grants",
        headers={"Authorization": "Bearer runtime-secret-token-1"},
        json=grant_request.model_dump(mode="json"),
    )
    unauthorized_reference_provisioning = client.post(
        "/v1/knowledge-query-grants",
        headers={"Authorization": "Bearer reference-secret-token-05j"},
        json=grant_request.model_dump(mode="json"),
    )
    forged_policy_sentinel = "forged-query-grant-policy-secret-sentinel"
    forged_provisioning = client.post(
        "/v1/knowledge-query-grants",
        headers=operator_authorization,
        json={
            **grant_request.model_dump(mode="json"),
            "client_id": forged_policy_sentinel,
        },
    )

    assert replayed == provisioned
    grant = provisioned.model_dump(mode="json")
    assert grant["schema_version"] == "knowledge-query-grant.v1"
    assert grant["client_id"] == grant_policy.client_id
    assert grant["client_grant_id"] != historical_grant.client_grant_id
    assert grant["knowledge_space_id"] == release.knowledge_space_id
    assert grant["knowledge_base_release_id"] == release.knowledge_base_release_id
    assert grant["execution_budget"] == grant_policy.execution_budget.model_dump(mode="json")
    assert grant["allowed_strategies"] == ["single_pass", "agentic"]
    assert unauthorized_provisioning.status_code == 401
    assert unauthorized_provisioning.json()["code"] == "invalid_operator_credential"
    assert unauthorized_reference_provisioning.status_code == 401
    assert unauthorized_reference_provisioning.json()["code"] == ("invalid_operator_credential")
    assert forged_provisioning.status_code == 422
    assert forged_provisioning.json()["code"] == "invalid_management_request"
    assert forged_policy_sentinel not in forged_provisioning.text
    with pytest.raises(KnowledgeAccessConflict):
        KnowledgeQueryGrantProvisioningApplication(
            registry=access,
            policy=grant_policy.model_copy(
                update={
                    "execution_budget": grant_policy.execution_budget.model_copy(
                        update={"max_candidates": 21}
                    )
                }
            ),
        ).provision(grant_request)
    forged_client_sentinel = "forged-runtime-client-secret-sentinel"
    invalid_reference = client.post(
        "/v1/knowledge-base-release-references",
        headers={
            "Authorization": "Bearer runtime-secret-token-1",
            "Idempotency-Key": "formal-agent-reference:invalid-runtime-body",
        },
        json={
            "knowledge_space_id": release.knowledge_space_id,
            "knowledge_base_id": release.knowledge_base_id,
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "external_resource_kind": "published_agent_version",
            "external_resource_id": "provisional-invalid-runtime-version",
            "purpose": "execution_or_rollback",
            "authenticated_client_id": forged_client_sentinel,
        },
    )

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
    reference_query_denied = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer reference-secret-token-05j",
            "Idempotency-Key": "reference-client-query-without-grant",
        },
        json={
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "专用 Reference client 不应获得查询权限",
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
    other_release_denied = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer runtime-secret-token-1",
            "Idempotency-Key": "runtime-other-release-attempt",
        },
        json={
            "knowledge_base_release_id": other_release.knowledge_base_release_id,
            "question": "不得越界到其他 Release",
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
    over_budget_denied = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer runtime-secret-token-1",
            "Idempotency-Key": "runtime-over-budget-attempt",
        },
        json={
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "不得超过 Grant 预算",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 21,
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

    assert invalid_reference.status_code == 422
    assert invalid_reference.json()["code"] == "invalid_knowledge_service_request"
    assert forged_client_sentinel not in invalid_reference.text
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    assert reference_query_denied.status_code == 403
    assert reference_query_denied.json()["code"] == "knowledge_query_access_denied"
    assert other_release_denied.status_code == 403
    assert other_release_denied.json()["code"] == "knowledge_query_access_denied"
    assert over_budget_denied.status_code == 403
    assert over_budget_denied.json()["code"] == "knowledge_query_access_denied"
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
                        "knowledge_source_version_id": (document.knowledge_source_version_id),
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
        assert len(self._generations[attestation.index_identity]) == (attestation.document_count)


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
        target = parsed.path
        if parsed.query:
            target = f"{target}?{parsed.query}"
        response = self._client.request(
            method,
            target,
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
