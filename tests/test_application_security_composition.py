from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app
from proof_agent.contracts import (
    AgentDraftRecord,
    ContractBundle,
    DraftAgent,
    OidcPrincipal,
    OperatorSessionProjection,
    Permission,
    RecoveryOidcGroupMapping,
)
from proof_agent.contracts.health import ProductionDeploymentIdentity
from proof_agent.contracts.run_execution import RoleActivationState
from proof_agent.delivery.production_status import ProductionReadinessProbe
from proof_agent.control.production_agent_configuration import (
    ProductionAgentDraftMutation,
)
from proof_agent.control.security.sessions import SessionResolution
from proof_agent.observability.api.security_middleware import SESSION_COOKIE_NAME


class NeverCalledSessionService:
    def resolve_session(self, cookie_token: str, *, now: object) -> object:
        raise AssertionError((cookie_token, now))


def _readiness_probe(
    checks: dict[str, object] | None = None,
) -> ProductionReadinessProbe:
    identity = ProductionDeploymentIdentity(
        release_id="proofagent-2026.07.25-rc1",
        image_digest="a" * 64,
        deployment_slot="green",
        role="api",
        activation_state=RoleActivationState.STANDBY,
        schema_revision="0010_hybrid_knowledge_workflow",
        schema_compatible_from="0010_hybrid_knowledge_workflow",
        schema_compatible_through="0010_hybrid_knowledge_workflow",
        deployment_compatibility_manifest_sha256="b" * 64,
    )
    return ProductionReadinessProbe(
        identity=identity,
        checks=checks  # type: ignore[arg-type]
        or {"postgresql": lambda: True, "s3": lambda: True},
    )


def _production_app(
    tmp_path: Path,
    *,
    session_service: object | None = None,
    agent_configuration_application: object | None = None,
):
    return create_app(
        mode="production",
        operator_session_service=(
            session_service or NeverCalledSessionService()
        ),  # type: ignore[arg-type]
        stable_origin="https://proof-agent.example.com",
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
        production_readiness_probe=_readiness_probe(),
        production_hybrid_intake_service=object(),
        production_knowledge_repository=object(),
        production_hybrid_ingestion_repository=object(),
        production_metadata_review_repository=object(),
        production_hybrid_publication_api=object(),
        production_hybrid_artifact_store=object(),
        production_configuration_uow_factory=object(),
        production_agent_configuration_application=(
            agent_configuration_application or object()
        ),
        knowledge_source_configuration_application=object(),
        knowledge_source_ingestion_application=object(),
        knowledge_source_operations_application=object(),
        knowledge_source_publication_preparation_application=object(),
        knowledge_source_publication_application=object(),
        knowledge_source_workspace_application=object(),
        knowledge_source_metadata_workbook_application=object(),
        release_registry_repository=object(),
        release_bundle_materializer=object(),
        release_bundle_attestation_verifier=object(),
        release_bundle_audit_repository=object(),
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "configuration",
    )


def test_production_app_fails_closed_without_oidc_session_composition(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="OIDC session"):
        create_app(
            mode="production",
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
            agent_configuration_dir=tmp_path / "configuration",
        )


def test_production_app_installs_oidc_routes_and_no_cors_middleware(
    tmp_path: Path,
) -> None:
    application = _production_app(tmp_path)
    middleware_names = {item.cls.__name__ for item in application.user_middleware}

    assert "ProductionSessionSecurityMiddleware" in middleware_names
    assert "CORSMiddleware" not in middleware_names
    assert not hasattr(application.state, "operator_identity_provider")
    assert not hasattr(application.state, "store")
    assert not hasattr(application.state, "conversation_store")
    assert not hasattr(application.state, "agent_configuration_store")
    assert any(route.path == "/api/auth/login" for route in application.routes)
    assert any(
        route.path == "/api/config/model-connections"
        and "POST" in (route.methods or set())
        for route in application.routes
    )
    assert (
        sum(
            route.path == "/api/config/knowledge-sources"
            and "GET" in (route.methods or set())
            for route in application.routes
        )
        == 1
    )
    assert any(
        route.path
        == "/api/config/knowledge-sources/{source_id}/publication-validations"
        and "POST" in (route.methods or set())
        for route in application.routes
    )
    expected_production_agent_routes = {
        ("/api/config/agents", "GET"),
        ("/api/config/agents", "POST"),
        ("/api/config/agents/{agent_id}/drafts/{draft_id}", "GET"),
        ("/api/config/agents/{agent_id}/drafts/{draft_id}", "PATCH"),
        ("/api/config/agents/{agent_id}/drafts/{draft_id}/contract", "GET"),
        ("/api/config/agents/{agent_id}/versions", "GET"),
    }
    actual_production_agent_routes = {
        (route.path, method)
        for route in application.routes
        for method in (route.methods or set())
        if route.path.startswith("/api/config/agents")
    }
    assert expected_production_agent_routes <= actual_production_agent_routes
    assert not any(
        route.path.startswith("/api/config/agents")
        and ({"validate", "publish", "rollback"} & set(route.path.split("/")))
        for route in application.routes
    )
    assert not any(
        route.path
        in {
            "/api/config/knowledge-sources/{source_id}/documents/batch",
            "/api/config/knowledge-sources/{source_id}/publication/validate",
            "/api/config/knowledge-sources/{source_id}/publication/publish",
        }
        for route in application.routes
    )
    assert not any(route.path == "/api/config/agents/import" for route in application.routes)
    assert not (tmp_path / "history").exists()
    assert not (tmp_path / "configuration").exists()

    client = TestClient(application, base_url="https://proof-agent.example.com")
    assert client.get("/livez").json() == {"status": "alive"}
    assert client.get("/readyz").json()["status"] == "ready"
    assert not any(route.path == "/api/docs" for route in application.routes)
    assert not any(route.path == "/api/openapi.json" for route in application.routes)
    assert client.get("/api/runs").status_code == 401


def test_production_agent_create_runs_behind_session_csrf_and_oidc_identity(
    tmp_path: Path,
) -> None:
    session_service = _AuthenticatedSessionService()
    agent_application = _RecordingAgentApplication()
    application = _production_app(
        tmp_path,
        session_service=session_service,
        agent_configuration_application=agent_application,
    )
    client = TestClient(
        application,
        base_url="https://proof-agent.example.com",
    )
    payload = {
        "display_name": "Insurance Specialist",
        "purpose": "Answer governed insurance questions.",
    }

    assert client.post("/api/config/agents", json=payload).status_code == 401
    client.cookies.set(SESSION_COOKIE_NAME, "valid-cookie")
    assert client.post("/api/config/agents", json=payload).status_code == 403
    response = client.post(
        "/api/config/agents",
        headers={
            "Origin": "https://proof-agent.example.com",
            "X-CSRF-Token": "c" * 64,
            "Idempotency-Key": "create-agent-attempt-1",
        },
        json=payload,
    )

    assert response.status_code == 201
    assert response.json()["agent_id"] == "agent_management_insurance_specialist"
    assert agent_application.calls[0]["actor"].subject == "operator-1"
    assert agent_application.calls[0]["actor"].session_id == (
        "019ba001-1111-7000-8000-000000000401"
    )


class _AuthenticatedSessionService:
    def resolve_session(self, cookie_token: str, *, now: datetime) -> SessionResolution:
        del now
        assert cookie_token == "valid-cookie"
        return SessionResolution(
            projection=OperatorSessionProjection(
                session_id="019ba001-1111-7000-8000-000000000401",
                principal=OidcPrincipal(
                    subject="operator-1",
                    issuer="https://identity.example.com",
                    audience="proof-agent",
                    display_name="Operator One",
                    authenticated_at="2026-08-12T00:00:00Z",
                    claims_verified_at="2026-08-12T00:00:00Z",
                ),
                absolute_expires_at="2026-08-19T00:00:00Z",
                idle_expires_at="2026-08-13T00:00:00Z",
                claims_refresh_due_at="2026-08-12T01:00:00Z",
                csrf_token="c" * 64,
                effective_permissions=(
                    Permission.AGENT_VIEW.value,
                    Permission.AGENT_EDIT.value,
                ),
            ),
            cookie_token="valid-cookie",
            rotated=False,
        )


class _RecordingAgentApplication:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_draft(self, **kwargs: Any) -> ProductionAgentDraftMutation:
        self.calls.append(kwargs)
        return ProductionAgentDraftMutation(
            record=AgentDraftRecord(
                revision=1,
                draft=DraftAgent(
                    agent_id="agent_management_insurance_specialist",
                    draft_id="019ba001-1111-7000-8000-000000000701",
                    display_name=kwargs["display_name"],
                    purpose=kwargs["purpose"],
                    contract_bundle=ContractBundle(
                        agent_yaml="schema_version: 3\n",
                        policy_yaml="rules: []\n",
                        tools_yaml="tools: []\n",
                    ),
                    created_at="2026-08-12T00:00:00Z",
                    updated_at="2026-08-12T00:00:00Z",
                    created_by="operator-1",
                    updated_by="operator-1",
                ),
            )
        )


def test_production_readiness_is_sanitized_and_fails_closed(tmp_path: Path) -> None:
    application = _production_app(tmp_path)

    def fail() -> bool:
        raise RuntimeError("postgresql://secret@database/internal")

    application.state.production_readiness_probe = _readiness_probe(
        {"postgresql": fail, "s3": lambda: True}
    )
    # The route closes over the factory argument, so exercise the bounded projection directly.
    result = application.state.production_readiness_probe()

    assert result.ready is False
    assert result.public_payload() == {
        "status": "not_ready",
        "release_id": "proofagent-2026.07.25-rc1",
        "image_digest": "a" * 64,
        "deployment_slot": "green",
        "role": "api",
        "activation_state": "STANDBY",
        "schema": {
            "revision": "0010_hybrid_knowledge_workflow",
            "compatible_from": "0010_hybrid_knowledge_workflow",
            "compatible_through": "0010_hybrid_knowledge_workflow",
        },
        "deployment_compatibility_manifest_sha256": "b" * 64,
        "components": {"postgresql": "unavailable", "s3": "ready"},
    }
