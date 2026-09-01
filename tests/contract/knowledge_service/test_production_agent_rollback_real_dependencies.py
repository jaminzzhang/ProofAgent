from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
import pytest

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.adapters.postgres.release_references import (
    PostgresReleaseLifecycleRepository,
)
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseLifecycleApplication,
)
from knowledge_source_service.bootstrap.runtime import compose_runtime
from knowledge_source_service.contracts.release_references import (
    DeprecateKnowledgeBaseReleaseRequest,
    RetireKnowledgeBaseReleaseRequest,
)
from knowledge_source_service.delivery.management_http import (
    bearer_operator_authenticator,
)
from knowledge_source_service.domain.release_references import ReleaseRetentionPolicy
from proof_agent.capabilities.knowledge.source_service_management_client import (
    KnowledgeSourceServiceManagementClient,
)
from proof_agent.capabilities.persistence.postgres.agent_repository import (
    PostgresAgentLifecycleRepository,
)
from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.configuration_uow import (
    PostgresConfigurationUnitOfWork,
)
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.contracts import (
    ActiveAgentPointerExpectation,
    ActiveAgentVersion,
    AgentPublicationRecord,
    ContractBundle,
    DraftAgent,
    OidcPrincipal,
    OperatorSessionProjection,
    Permission,
    ProductionSecretHandle,
    PublishedAgentVersion,
    RecoveryOidcGroupMapping,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationWorkspace,
)
from proof_agent.control.security.sessions import SessionResolution
from proof_agent.observability.api.app import create_app
from proof_agent.observability.api.security_middleware import SESSION_COOKIE_NAME


pytestmark = pytest.mark.postgres_integration

_AGENT_ID = "agent_management_insurance_specialist"
_TARGET_DRAFT_ID = "019ba001-1111-7000-8000-000000000921"
_CURRENT_DRAFT_ID = "019ba001-1111-7000-8000-000000000922"
_TARGET_VERSION_ID = "019ba001-1111-7000-8000-000000000931"
_CURRENT_VERSION_ID = "019ba001-1111-7000-8000-000000000932"
_KSS_OPERATOR_TOKEN = "operator-rollback-rehearsal-test-token"
_CSRF_TOKEN = "c" * 64


@pytest.fixture
def proof_agent_postgres_engine() -> Iterator[Engine]:
    base_dsn = os.environ.get("PROOF_AGENT_TEST_POSTGRES_DSN", "").strip()
    if not base_dsn:
        if os.environ.get("PROOF_AGENT_REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail("PROOF_AGENT_TEST_POSTGRES_DSN is required for PostgreSQL tests")
        pytest.skip("real PostgreSQL DSN is not configured")
    schema = f"proof_agent_rollback_test_{uuid4().hex}"
    base_engine = create_engine(base_dsn)
    with base_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base_dsn)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    isolated_dsn = url.set(query=query).render_as_string(hide_password=False)
    upgrade_database(isolated_dsn)
    engine = create_engine(isolated_dsn, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        base_engine.dispose()


class _TestClientGuardedHttpClient:
    def __init__(self, client: TestClient) -> None:
        self._client = client
        self.calls: list[tuple[str, str]] = []

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
        self.calls.append((method, target))
        response = self._client.request(
            method,
            target,
            headers=headers,
            content=body,
        )
        return GuardedHttpResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )


class _AuthenticatedSessionService:
    def resolve_session(self, cookie_token: str, *, now: datetime) -> SessionResolution:
        del now
        assert cookie_token == "valid-cookie"
        return SessionResolution(
            projection=OperatorSessionProjection(
                session_id="019ba001-1111-7000-8000-000000000941",
                principal=OidcPrincipal(
                    subject="operator-rollback-rehearsal",
                    issuer="https://identity.example.test",
                    audience="proof-agent",
                    display_name="Rollback Rehearsal Operator",
                    authenticated_at="2026-09-01T14:00:00Z",
                    claims_verified_at="2026-09-01T14:00:00Z",
                ),
                absolute_expires_at="2026-09-02T14:00:00Z",
                idle_expires_at="2026-09-01T15:00:00Z",
                claims_refresh_due_at="2026-09-01T14:30:00Z",
                csrf_token=_CSRF_TOKEN,
                effective_permissions=(
                    Permission.AGENT_VIEW.value,
                    Permission.AGENT_PUBLISH.value,
                ),
            ),
            cookie_token="valid-cookie",
            rotated=False,
        )


def _template_bundle() -> ContractBundle:
    return ContractBundle(
        agent_yaml=(
            f"name: {_AGENT_ID}\n"
            "purpose: Verify an isolated real-dependency rollback.\n"
            "workflow:\n"
            "  template: react_enterprise_qa_v3\n"
            "capabilities:\n"
            "  tools:\n"
            "    enabled: false\n"
            "  memory:\n"
            "    enabled: false\n"
        ),
        policy_yaml="rules: []\n",
        tools_yaml="tools: []\n",
    )


def _draft(*, draft_id: str, purpose: str, updated_at: str) -> DraftAgent:
    return DraftAgent(
        agent_id=_AGENT_ID,
        draft_id=draft_id,
        display_name="Rollback Rehearsal Agent",
        purpose=purpose,
        contract_bundle=_template_bundle(),
        created_at="2026-09-01T14:00:00Z",
        updated_at=updated_at,
        created_by="operator-rollback-rehearsal",
        updated_by="operator-rollback-rehearsal",
    )


def _publication(
    draft: DraftAgent,
    *,
    version_id: str,
    release_id: str,
    published_at: str,
    expected_active_version_id: str | None,
) -> AgentPublicationRecord:
    version = PublishedAgentVersion(
        agent_id=draft.agent_id,
        version_id=version_id,
        source_draft_id=draft.draft_id,
        validation_run_id=f"run_{version_id}",
        display_name=draft.display_name,
        purpose=draft.purpose,
        contract_bundle=draft.contract_bundle,
        published_at=published_at,
        published_by="operator-rollback-rehearsal",
        resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
            bindings=(
                ResolvedKnowledgeSourceServiceBinding(
                    binding_id="rollback-rehearsal-knowledge",
                    knowledge_base_release_id=release_id,
                    client_credential_ref=ProductionSecretHandle(
                        protocol_id="hashicorp-vault-2.0-kv-v2",
                        handle_id="test/rollback-rehearsal/kss-client",
                        purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
                        version_id="test-version-1",
                    ),
                    admission_scorer_id="rollback-rehearsal-scorer",
                    admission_scorer_revision="rollback-rehearsal-scorer.v1",
                ),
            )
        ),
    )
    return AgentPublicationRecord(
        version=version,
        activation=ActiveAgentVersion(
            agent_id=draft.agent_id,
            version_id=version_id,
            activated_at=published_at,
            activated_by="operator-rollback-rehearsal",
        ),
        draft_revision=1,
        active_pointer_expectation=ActiveAgentPointerExpectation(
            version_id=expected_active_version_id
        ),
    )


def _seed_agent_versions(
    engine: Engine,
    *,
    release_id: str,
) -> tuple[AgentPublicationRecord, AgentPublicationRecord]:
    repository = PostgresAgentLifecycleRepository(engine)
    target_draft = repository.save_draft(
        _draft(
            draft_id=_TARGET_DRAFT_ID,
            purpose="Target immutable rollback version",
            updated_at="2026-09-01T14:00:00Z",
        ),
        expected_revision=0,
    )
    target = _publication(
        target_draft.draft,
        version_id=_TARGET_VERSION_ID,
        release_id=release_id,
        published_at="2026-09-01T14:01:00Z",
        expected_active_version_id=None,
    )
    repository.publish_version(target, expected_draft_revision=target_draft.revision)

    current_draft = repository.save_draft(
        _draft(
            draft_id=_CURRENT_DRAFT_ID,
            purpose="Current immutable rollback version",
            updated_at="2026-09-01T14:02:00Z",
        ),
        expected_revision=0,
    )
    current = _publication(
        current_draft.draft,
        version_id=_CURRENT_VERSION_ID,
        release_id=release_id,
        published_at="2026-09-01T14:03:00Z",
        expected_active_version_id=_TARGET_VERSION_ID,
    )
    repository.publish_version(current, expected_draft_revision=current_draft.revision)
    return target, current


def _compose_kss_management_client(
    kss_postgres_dsn: str,
) -> tuple[
    KnowledgeSourceServiceManagementClient,
    _TestClientGuardedHttpClient,
    str,
]:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(kss_postgres_dsn, artifacts=artifacts)
    space_id = "space-rollback-rehearsal"
    source_id = "source-rollback-rehearsal"
    base_id = "base-rollback-rehearsal"
    catalog.create_space(space_id)
    catalog.create_source(
        knowledge_space_id=space_id,
        knowledge_source_id=source_id,
    )
    catalog.create_base(
        knowledge_space_id=space_id,
        knowledge_base_id=base_id,
    )
    source = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-rollback-rehearsal-v1",
        max_content_bytes=1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id=space_id,
            knowledge_source_id=source_id,
            display_filename="rollback-rehearsal.md",
            media_type="text/markdown",
            content=b"# Synthetic rollback rehearsal\nOne immutable test fact.\n",
        )
    )
    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id=space_id,
            knowledge_base_id=base_id,
            knowledge_source_version_ids=(source.version.knowledge_source_version_id,),
        )
    )
    runtime = compose_runtime(
        postgres_dsn=kss_postgres_dsn,
        artifacts=artifacts,
        release_identity="kss-rollback-rehearsal-runtime-v1",
        dependency_readiness=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
        clock=lambda: datetime(2026, 9, 1, 14, 4, tzinfo=UTC),
        query_id_factory=lambda: "query-unused-rollback-rehearsal",
        trace_id_factory=lambda: "trace-unused-rollback-rehearsal",
        worker_id="worker-unused-rollback-rehearsal",
        lease_duration=timedelta(seconds=30),
        result_retention=timedelta(hours=24),
        authenticate_operator=bearer_operator_authenticator(
            operator_id="proof-agent-rollback-rehearsal",
            expected_token=_KSS_OPERATOR_TOKEN,
        ),
    )
    guarded = _TestClientGuardedHttpClient(TestClient(runtime.http_application))
    management = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal",
        http_client=guarded,
        authorization_header_factory=lambda: f"Bearer {_KSS_OPERATOR_TOKEN}",
    )
    return management, guarded, release.release.knowledge_base_release_id


def _production_test_application(
    tmp_path: Path,
    *,
    workspace: AgentConfigurationWorkspace,
):
    return create_app(
        mode="production",
        operator_session_service=_AuthenticatedSessionService(),
        stable_origin="https://proof-agent.example.test",
        security_configuration_repository=object(),  # type: ignore[arg-type]
        secret_provider=object(),  # type: ignore[arg-type]
        recovery_oidc_group_mapping=RecoveryOidcGroupMapping(
            claim_path="groups",
            group_name="proof-agent-recovery",
            permissions=(
                Permission.PERMISSION_MAPPING_VIEW,
                Permission.PERMISSION_MAPPING_EDIT,
                Permission.AUDIT_VIEW,
            ),
        ),
        run_queue_repository=object(),  # type: ignore[arg-type]
        run_artifact_result_reader=object(),  # type: ignore[arg-type]
        conversation_repository=object(),  # type: ignore[arg-type]
        published_agent_registry=object(),
        guarded_http_client=object(),  # type: ignore[arg-type]
        production_readiness_probe=lambda: object(),
        production_configuration_uow_factory=object(),
        agent_configuration_workspace=workspace,
        production_agent_rollback_enabled=True,
        formal_production_agent_publication_command=object(),
        knowledge_service_management_client=object(),
        release_registry_repository=object(),
        release_bundle_materializer=object(),
        release_bundle_attestation_verifier=object(),
        release_bundle_audit_repository=object(),
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "configuration",
    )


def _rollback(
    application: Any,
    *,
    target_version_id: str,
    expected_active_version_id: str,
) -> Any:
    client = TestClient(application, base_url="https://proof-agent.example.test")
    client.cookies.set(SESSION_COOKIE_NAME, "valid-cookie")
    return client.post(
        f"/api/config/agents/{_AGENT_ID}/versions/{target_version_id}/rollback",
        headers={
            "Origin": "https://proof-agent.example.test",
            "X-CSRF-Token": _CSRF_TOKEN,
        },
        json={"expected_active_version_id": expected_active_version_id},
    )


def test_production_rollback_rehearsal_uses_real_kss_http_and_postgres_authorities(
    tmp_path: Path,
    proof_agent_postgres_engine: Engine,
    kss_postgres_dsn: str,
) -> None:
    management, guarded, release_id = _compose_kss_management_client(kss_postgres_dsn)
    target, current = _seed_agent_versions(
        proof_agent_postgres_engine,
        release_id=release_id,
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=lambda: PostgresConfigurationUnitOfWork(
            proof_agent_postgres_engine
        ),
        template_bundle=_template_bundle(),
        knowledge_release_catalog=management,
        clock=lambda: datetime(2026, 9, 1, 14, 5, tzinfo=UTC),
    )

    response = _rollback(
        _production_test_application(tmp_path, workspace=workspace),
        target_version_id=target.version.version_id,
        expected_active_version_id=current.version.version_id,
    )

    assert response.status_code == 200
    assert response.json()["version_id"] == target.version.version_id
    agents = PostgresAgentLifecycleRepository(proof_agent_postgres_engine)
    active = agents.get_active(_AGENT_ID)
    assert active is not None
    assert active.version_id == target.version.version_id
    assert active.rollback_from_version_id == current.version.version_id
    audits = PostgresAuditRepository(proof_agent_postgres_engine).list_for_target(
        target_type="agent_version",
        target_id=target.version.version_id,
    )
    assert len(audits) == 1
    assert audits[0].event_type == "agent.version.rolled_back"
    assert ("GET", "/readyz") in guarded.calls
    assert any(path.endswith("/releases") for method, path in guarded.calls if method == "GET")


def test_production_rollback_rehearsal_fails_closed_after_real_kss_retirement(
    tmp_path: Path,
    proof_agent_postgres_engine: Engine,
    kss_postgres_dsn: str,
) -> None:
    management, guarded, release_id = _compose_kss_management_client(kss_postgres_dsn)
    target, current = _seed_agent_versions(
        proof_agent_postgres_engine,
        release_id=release_id,
    )
    lifecycle = KnowledgeBaseReleaseLifecycleApplication(
        repository=PostgresReleaseLifecycleRepository.from_dsn(kss_postgres_dsn),
        retention_policy=ReleaseRetentionPolicy(
            policy_id="rollback-rehearsal-zero-retention",
            minimum_age=timedelta(0),
        ),
    )
    scope = {
        "knowledge_space_id": "space-rollback-rehearsal",
        "knowledge_base_id": "base-rollback-rehearsal",
        "knowledge_base_release_id": release_id,
    }
    lifecycle.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(**scope),
        operator_id="operator-rollback-rehearsal",
        idempotency_key="rollback-rehearsal-deprecate",
    )
    lifecycle.retire(
        RetireKnowledgeBaseReleaseRequest(**scope),
        operator_id="operator-rollback-rehearsal",
        idempotency_key="rollback-rehearsal-retire",
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=lambda: PostgresConfigurationUnitOfWork(
            proof_agent_postgres_engine
        ),
        template_bundle=_template_bundle(),
        knowledge_release_catalog=management,
        clock=lambda: datetime(2026, 9, 1, 14, 5, tzinfo=UTC),
    )

    response = _rollback(
        _production_test_application(tmp_path, workspace=workspace),
        target_version_id=target.version.version_id,
        expected_active_version_id=current.version.version_id,
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "agent_rollback_knowledge_release_unavailable"
    }
    assert PostgresAgentLifecycleRepository(proof_agent_postgres_engine).get_active(
        _AGENT_ID
    ) == current.activation
    assert PostgresAuditRepository(proof_agent_postgres_engine).list_for_target(
        target_type="agent_version",
        target_id=target.version.version_id,
    ) == ()
    assert ("GET", "/readyz") in guarded.calls
    assert any(path.endswith("/releases") for method, path in guarded.calls if method == "GET")
