from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proof_agent.contracts import (
    AgentDraftRecord,
    AuditActorFacts,
    ContractBundle,
    DraftAgent,
)
from proof_agent.delivery.production_agent_configuration import router
from proof_agent.control.production_agent_configuration import (
    ProductionAgentConfigurationConflict,
    ProductionAgentConfigurationNotFound,
    ProductionAgentInventory,
    ProductionAgentSummary,
    ProductionAgentVersions,
)
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


@dataclass(frozen=True)
class CreateResult:
    record: AgentDraftRecord
    replayed: bool


class RecordingApplication:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_draft(
        self,
        *,
        display_name: str,
        purpose: str,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> CreateResult:
        self.calls.append(
            {
                "display_name": display_name,
                "purpose": purpose,
                "idempotency_key": idempotency_key,
                "actor": actor,
            }
        )
        return CreateResult(record=_draft_record(), replayed=False)

    def list_agents(self) -> ProductionAgentInventory:
        draft = _draft_record().draft
        return ProductionAgentInventory(
            agents=(
                ProductionAgentSummary(
                    agent_id=draft.agent_id,
                    display_name=draft.display_name,
                    purpose=draft.purpose,
                    draft_count=1,
                    latest_draft_id=draft.draft_id,
                    version_count=0,
                    active_version_id=None,
                    updated_at=draft.updated_at,
                ),
            ),
            can_create=False,
        )

    def get_draft(self, *, agent_id: str, draft_id: str) -> AgentDraftRecord:
        self.calls.append({"agent_id": agent_id, "draft_id": draft_id, "operation": "get"})
        return _draft_record()

    def update_draft(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        display_name: str | None,
        purpose: str | None,
        actor: AuditActorFacts,
    ) -> AgentDraftRecord:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "expected_revision": expected_revision,
                "display_name": display_name,
                "purpose": purpose,
                "actor": actor,
                "operation": "update",
            }
        )
        record = _draft_record()
        return AgentDraftRecord(
            draft=record.draft.model_copy(
                update={
                    "display_name": display_name or record.draft.display_name,
                    "purpose": record.draft.purpose if purpose is None else purpose,
                }
            ),
            revision=expected_revision + 1,
        )

    def list_versions(self, *, agent_id: str) -> ProductionAgentVersions:
        self.calls.append({"agent_id": agent_id, "operation": "versions"})
        return ProductionAgentVersions(versions=(), active_version_id=None)


def _application() -> tuple[FastAPI, RecordingApplication]:
    application = FastAPI()
    service = RecordingApplication()
    application.state.proof_agent_mode = "development"
    application.state.production_agent_configuration_application = service
    application.include_router(router, prefix="/api")
    return application, service


def _draft_record() -> AgentDraftRecord:
    return AgentDraftRecord(
        revision=1,
        draft=DraftAgent(
            agent_id="agent_management_insurance_specialist",
            draft_id="019ba001-1111-7000-8000-000000000701",
            display_name="Insurance Specialist",
            purpose="Answer governed insurance questions.",
            contract_bundle=ContractBundle(
                agent_yaml="schema_version: 3\n",
                policy_yaml="rules: []\n",
                tools_yaml="tools: []\n",
            ),
            created_at="2026-08-12T00:00:00Z",
            updated_at="2026-08-12T00:00:00Z",
            created_by="local-user",
            updated_by="local-user",
        ),
    )


def test_create_production_agent_uses_server_owned_contract_and_returns_revision() -> None:
    application, service = _application()

    response = TestClient(application).post(
        "/api/config/agents",
        headers={"Idempotency-Key": "create-agent-attempt-1"},
        json={
            "display_name": "Insurance Specialist",
            "purpose": "Answer governed insurance questions.",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "agent_id": "agent_management_insurance_specialist",
        "draft_id": "019ba001-1111-7000-8000-000000000701",
        "display_name": "Insurance Specialist",
        "purpose": "Answer governed insurance questions.",
        "created_at": "2026-08-12T00:00:00Z",
        "updated_at": "2026-08-12T00:00:00Z",
        "created_by": "local-user",
        "updated_by": "local-user",
        "version_id": None,
        "validation_records": [],
        "operation_audit": [],
        "revision": 1,
        "capabilities": {
            "mode": "production",
            "editable_modules": ["general"],
            "lifecycle_tabs": ["versions", "contract", "monitor"],
            "actions": {
                "can_validate": False,
                "can_publish": False,
                "can_rollback": False,
            },
        },
    }
    assert service.calls == [
        {
            "display_name": "Insurance Specialist",
            "purpose": "Answer governed insurance questions.",
            "idempotency_key": "create-agent-attempt-1",
            "actor": AuditActorFacts(
                subject="local-user",
                identity_provider="enterprise-oidc",
                session_id="development-session",
                permissions=tuple(sorted(permission.value for permission in _all_permissions())),
            ),
        }
    ]


def test_list_production_agents_declares_server_owned_capabilities() -> None:
    application, _ = _application()

    response = TestClient(application).get("/api/config/agents")

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "agent_id": "agent_management_insurance_specialist",
                "display_name": "Insurance Specialist",
                "purpose": "Answer governed insurance questions.",
                "draft_count": 1,
                "latest_draft_id": "019ba001-1111-7000-8000-000000000701",
                "version_count": 0,
                "active_version_id": None,
                "updated_at": "2026-08-12T00:00:00Z",
            }
        ],
        "meta": {
            "total": 1,
            "capabilities": {
                "mode": "production",
                "can_create": False,
                "can_import_manifest": False,
                "canonical_template": {
                    "id": "agent_management_insurance_specialist",
                    "name": "Agent Management Insurance Specialist",
                    "purpose": (
                        "Assist internal insurance staff with governed, evidence-backed "
                        "insurance knowledge consultation."
                    ),
                    "description": (
                        "Operator-facing Controlled ReAct V3 consultation with "
                        "production publication kept behind candidate gates."
                    ),
                },
            },
        },
    }


def test_read_production_draft_contract_and_versions_after_creation() -> None:
    application, service = _application()
    client = TestClient(application)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701"
    )

    draft = client.get(route)
    contract = client.get(f"{route}/contract")
    versions = client.get(
        "/api/config/agents/agent_management_insurance_specialist/versions"
    )

    assert draft.status_code == 200
    assert draft.json()["revision"] == 1
    assert contract.status_code == 200
    assert contract.json() == {
        "agent_yaml": "schema_version: 3\n",
        "policy_yaml": "rules: []\n",
        "tools_yaml": "tools: []\n",
        "extra_files": {},
        "advanced_fields": {},
    }
    assert versions.status_code == 200
    assert versions.json() == {
        "data": [],
        "meta": {"total": 0, "active_version_id": None},
    }
    assert [call["operation"] for call in service.calls] == [
        "get",
        "get",
        "versions",
    ]


def test_update_production_draft_requires_and_returns_next_revision() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701"
    )

    response = TestClient(application).patch(
        route,
        json={
            "expected_revision": 1,
            "display_name": "Governed Insurance Specialist",
        },
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Governed Insurance Specialist"
    assert response.json()["revision"] == 2
    assert service.calls[-1] == {
        "agent_id": "agent_management_insurance_specialist",
        "draft_id": "019ba001-1111-7000-8000-000000000701",
        "expected_revision": 1,
        "display_name": "Governed Insurance Specialist",
        "purpose": None,
        "actor": AuditActorFacts(
            subject="local-user",
            identity_provider="enterprise-oidc",
            session_id="development-session",
            permissions=tuple(sorted(permission.value for permission in _all_permissions())),
        ),
        "operation": "update",
    }


def test_create_rejects_browser_paths_and_requires_an_idempotency_key() -> None:
    application, service = _application()
    client = TestClient(application)

    browser_path = client.post(
        "/api/config/agents",
        headers={"Idempotency-Key": "create-agent-attempt-1"},
        json={
            "display_name": "Insurance Specialist",
            "purpose": "Answer governed insurance questions.",
            "manifest_path": "/tmp/operator-controlled/agent.yaml",
        },
    )
    missing_key = client.post(
        "/api/config/agents",
        json={
            "display_name": "Insurance Specialist",
            "purpose": "Answer governed insurance questions.",
        },
    )

    assert browser_path.status_code == 422
    assert missing_key.status_code == 422
    assert service.calls == []


def test_production_agent_commands_enforce_permissions_and_stable_conflicts() -> None:
    application, service = _application()
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )
    denied = TestClient(application).post(
        "/api/config/agents",
        headers={"Idempotency-Key": "create-agent-attempt-1"},
        json={"display_name": "Insurance Specialist"},
    )

    assert denied.status_code == 403
    assert service.calls == []

    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset(_all_permissions())
    )
    application.state.production_agent_configuration_application = _ConflictApplication()
    conflict = TestClient(application).post(
        "/api/config/agents",
        headers={"Idempotency-Key": "create-agent-attempt-1"},
        json={"display_name": "Insurance Specialist"},
    )
    missing = TestClient(application).get(
        "/api/config/agents/agent_management_insurance_specialist/drafts/unknown"
    )

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "sole_agent_already_exists"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "agent_draft_not_found"}


class _StaticIdentityProvider:
    def __init__(self, permissions: frozenset[Any]) -> None:
        self._permissions = permissions

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id="operator-1",
            display_name="Operator One",
            permissions=self._permissions,
        )


class _ConflictApplication(RecordingApplication):
    def create_draft(self, **kwargs: Any) -> CreateResult:
        del kwargs
        raise ProductionAgentConfigurationConflict(
            code="sole_agent_already_exists",
            detail="Already initialized.",
        )

    def get_draft(self, *, agent_id: str, draft_id: str) -> AgentDraftRecord:
        del agent_id, draft_id
        raise ProductionAgentConfigurationNotFound(
            code="agent_draft_not_found",
            detail="Not found.",
        )


def _permission(value: str) -> Any:
    from proof_agent.contracts import Permission

    return Permission(value)


def _all_permissions() -> tuple[Any, ...]:
    from proof_agent.contracts import Permission

    return tuple(Permission)
