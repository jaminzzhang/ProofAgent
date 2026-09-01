from __future__ import annotations

import ast
from dataclasses import dataclass
import inspect
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentDraftRecord,
    AuditActorFacts,
    ContractBundle,
    DraftKnowledgeReleaseBindingCandidate,
    DraftAgent,
    ExactArtifactRef,
    FormalProductionAgentPublicationCommandReceipt,
    FormalProductionAgentPublicationCommandResult,
    FormalProductionAgentPublicationCommandState,
    KnowledgeReleaseEvidenceSet,
    WorkflowStageConfig,
    WorkflowStageContextConfig,
    WorkflowStagePromptConfig,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseProjection,
)
from proof_agent.control.agent_configuration_skill_packs import (
    BusinessFlowSkillPackConfiguration,
    BusinessFlowSkillPackCreateCommand,
    BusinessFlowSkillPackUpdateCommand,
)
from proof_agent.delivery.production_agent_configuration import router
import proof_agent.delivery.production_agent_configuration as production_configuration
from proof_agent.errors import ProofAgentError
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationConflict,
    AgentConfigurationInventory,
    AgentConfigurationNotFound,
    AgentConfigurationKnowledgeBindingResult,
    AgentConfigurationSkillPackResult,
    AgentConfigurationSummary,
    AgentConfigurationVersions,
)
from proof_agent.control.production_agent_publication_configuration import (
    ProductionAgentPublicationConfiguration,
    ProductionAgentPublicationConfigurationBlocker,
    ProductionAgentPublicationModelRole,
)
from proof_agent.control.formal_production_agent_publication_command import (
    FormalProductionAgentPublicationCommandRejected,
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

    def list_agents(self) -> AgentConfigurationInventory:
        draft = _draft_record().draft
        return AgentConfigurationInventory(
            agents=(
                AgentConfigurationSummary(
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

    def update_contract(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        agent_yaml: str | None,
        policy_yaml: str | None,
        tools_yaml: str | None,
        actor: AuditActorFacts,
    ) -> AgentDraftRecord:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "expected_revision": expected_revision,
                "agent_yaml": agent_yaml,
                "policy_yaml": policy_yaml,
                "tools_yaml": tools_yaml,
                "actor": actor,
                "operation": "contract_update",
            }
        )
        record = _draft_record()
        bundle = record.draft.contract_bundle.model_copy(
            update={
                "agent_yaml": (
                    record.draft.contract_bundle.agent_yaml if agent_yaml is None else agent_yaml
                ),
                "policy_yaml": (
                    record.draft.contract_bundle.policy_yaml if policy_yaml is None else policy_yaml
                ),
                "tools_yaml": (
                    record.draft.contract_bundle.tools_yaml if tools_yaml is None else tools_yaml
                ),
            }
        )
        return AgentDraftRecord(
            draft=record.draft.model_copy(update={"contract_bundle": bundle}),
            revision=expected_revision + 1,
        )

    def update_workflow_stages(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        template: str | None,
        template_descriptor_version: str | None,
        stages: tuple[WorkflowStageConfig, ...],
        actor: AuditActorFacts,
    ) -> AgentDraftRecord:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "expected_revision": expected_revision,
                "template": template,
                "template_descriptor_version": template_descriptor_version,
                "stages": stages,
                "actor": actor,
                "operation": "workflow_stages_update",
            }
        )
        record = _draft_record()
        return AgentDraftRecord(draft=record.draft, revision=expected_revision + 1)

    def preview_workflow_stage(
        self,
        *,
        agent_id: str,
        draft_id: str,
        stage_id: str,
        prompt: WorkflowStagePromptConfig,
        context_options: dict[str, bool],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "stage_id": stage_id,
                "prompt": prompt,
                "context_options": context_options,
                "operation": "workflow_stage_preview",
            }
        )
        return {
            "stage_id": stage_id,
            "stage_label": "Plan",
            "harness_control_prompt_summary": "Harness control prompt retained.",
            "structured_control_context": {"agent_purpose": "Governed insurance."},
            "business_context_addendum": {
                "present": True,
                "text": "Business Context:\nClaims context",
                "fields": ["business_context"],
            },
            "summary": {"stage_id": stage_id, "prompt_fields": ["business_context"]},
            "truncation_applied": False,
        }

    def get_business_flow_skill_packs(
        self,
        *,
        agent_id: str,
        draft_id: str,
    ) -> AgentConfigurationSkillPackResult:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "operation": "skill_pack_read",
            }
        )
        return _skill_pack_result(revision=1)

    def create_business_flow_skill_pack(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        command: BusinessFlowSkillPackCreateCommand,
        actor: AuditActorFacts,
    ) -> AgentConfigurationSkillPackResult:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "expected_revision": expected_revision,
                "command": command,
                "actor": actor,
                "operation": "skill_pack_create",
            }
        )
        return _skill_pack_result(revision=expected_revision + 1)

    def update_business_flow_skill_pack(
        self,
        *,
        agent_id: str,
        draft_id: str,
        pack_id: str,
        expected_revision: int,
        command: BusinessFlowSkillPackUpdateCommand,
        actor: AuditActorFacts,
    ) -> AgentConfigurationSkillPackResult:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "pack_id": pack_id,
                "expected_revision": expected_revision,
                "command": command,
                "actor": actor,
                "operation": "skill_pack_update",
            }
        )
        return _skill_pack_result(revision=expected_revision + 1)

    def delete_business_flow_skill_pack(
        self,
        *,
        agent_id: str,
        draft_id: str,
        pack_id: str,
        expected_revision: int,
        actor: AuditActorFacts,
    ) -> AgentConfigurationSkillPackResult:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "pack_id": pack_id,
                "expected_revision": expected_revision,
                "actor": actor,
                "operation": "skill_pack_delete",
            }
        )
        return _skill_pack_result(revision=expected_revision + 1)

    def get_knowledge_release_binding_candidate(
        self,
        *,
        agent_id: str,
        draft_id: str,
    ) -> AgentConfigurationKnowledgeBindingResult:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "operation": "knowledge_binding_read",
            }
        )
        return _knowledge_binding_result(revision=1)

    def get_publication_configuration(
        self,
        *,
        agent_id: str,
        draft_id: str,
    ) -> ProductionAgentPublicationConfiguration:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "operation": "publication_configuration_read",
            }
        )
        return _publication_configuration()

    def update_knowledge_release_binding_candidate(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        candidate: DraftKnowledgeReleaseBindingCandidate,
        actor: AuditActorFacts,
    ) -> AgentConfigurationKnowledgeBindingResult:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "expected_revision": expected_revision,
                "candidate": candidate,
                "actor": actor,
                "operation": "knowledge_binding_update",
            }
        )
        return _knowledge_binding_result(
            revision=expected_revision + 1,
            candidate=candidate,
        )

    def list_versions(self, *, agent_id: str) -> AgentConfigurationVersions:
        self.calls.append({"agent_id": agent_id, "operation": "versions"})
        return AgentConfigurationVersions(versions=(), active_version_id=None)

    def rollback_version(
        self,
        *,
        agent_id: str,
        version_id: str,
        expected_active_version_id: str | None,
        actor: AuditActorFacts,
    ) -> object:
        self.calls.append(
            {
                "agent_id": agent_id,
                "version_id": version_id,
                "expected_active_version_id": expected_active_version_id,
                "actor": actor,
                "operation": "rollback",
            }
        )
        return type(
            "RollbackResult",
            (),
            {
                "activation": ActiveAgentVersion(
                    agent_id=agent_id,
                    version_id=version_id,
                    activated_at="2026-09-01T14:00:00Z",
                    activated_by=actor.subject,
                    rollback_from_version_id=expected_active_version_id,
                )
            },
        )()


def _application(
    *,
    rollback_enabled: bool = False,
) -> tuple[FastAPI, RecordingApplication]:
    application = FastAPI()
    service = RecordingApplication()
    application.state.proof_agent_mode = "development"
    application.state.agent_configuration_workspace = service
    application.state.production_agent_rollback_enabled = rollback_enabled
    application.include_router(router, prefix="/api")
    return application, service


class _RecordingFormalPublicationCommand:
    def __init__(
        self,
        result: FormalProductionAgentPublicationCommandResult,
        *,
        error: FormalProductionAgentPublicationCommandRejected | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> FormalProductionAgentPublicationCommandResult:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    def get_receipt(self, **kwargs: Any) -> FormalProductionAgentPublicationCommandReceipt:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result.receipt


def _formal_command_result(
    state: FormalProductionAgentPublicationCommandState,
    *,
    replayed: bool = False,
    failure_code: str | None = None,
) -> FormalProductionAgentPublicationCommandResult:
    terminal = state is not FormalProductionAgentPublicationCommandState.IN_PROGRESS
    success = state is FormalProductionAgentPublicationCommandState.SUCCEEDED
    return FormalProductionAgentPublicationCommandResult(
        replayed=replayed,
        receipt=FormalProductionAgentPublicationCommandReceipt(
            command_id="019ba001-1111-7000-8000-000000000805",
            state=state,
            agent_id="agent_management_insurance_specialist",
            draft_id="019ba001-1111-7000-8000-000000000701",
            draft_revision=11,
            request_sha256="1" * 64,
            started_at="2026-08-30T13:05:00Z",
            completed_at="2026-08-30T13:06:00Z" if terminal else None,
            published_version_id=("019ba001-1111-7000-8000-000000000901" if success else None),
            validation_run_id="validation-run-1" if success else None,
            release_reference_id="release-reference-1" if success else None,
            published_at="2026-08-30T13:06:00Z" if success else None,
            failure_code=failure_code,
        ),
    )


def _formal_command_body() -> dict[str, Any]:
    def artifact(name: str, digest: str) -> ExactArtifactRef:
        return ExactArtifactRef(
            artifact_uri=f"s3://formal-publication/{name}.json",
            version_id=f"artifact-{name}",
            sha256=digest * 64,
            size_bytes=128,
            media_type="application/json",
        )

    evidence = KnowledgeReleaseEvidenceSet(
        shadow=artifact("shadow", "1"),
        capacity=artifact("capacity", "2"),
        acceptance=artifact("acceptance", "3"),
        recovery=artifact("recovery", "4"),
    )
    return {
        "draft_revision": 11,
        "evidence": evidence.model_dump(mode="json"),
        "smoke_question": "等待期如何解释？",
    }


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


def _skill_pack_result(*, revision: int) -> AgentConfigurationSkillPackResult:
    return AgentConfigurationSkillPackResult(
        record=AgentDraftRecord(draft=_draft_record().draft, revision=revision),
        configuration=BusinessFlowSkillPackConfiguration(
            enabled=False,
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            addendum_slots=(),
            configuration_issues=(),
            packs=(),
        ),
    )


def _knowledge_binding_candidate() -> DraftKnowledgeReleaseBindingCandidate:
    return DraftKnowledgeReleaseBindingCandidate(
        knowledge_space_id="insurance",
        knowledge_base_id="insurance-guidance",
        knowledge_base_version_id="insurance-guidance-v3",
        knowledge_base_release_id="insurance-guidance-release-7",
    )


def _publication_configuration() -> ProductionAgentPublicationConfiguration:
    return ProductionAgentPublicationConfiguration(
        draft_revision=11,
        authoring_configuration_state="blocked",
        formal_publication_state="workspace_draft_not_bound",
        can_publish_from_dashboard=False,
        workflow_template="react_enterprise_qa_v3",
        workflow_template_descriptor_version="react_enterprise_qa.v3",
        knowledge_release_candidate=_knowledge_binding_candidate(),
        knowledge_release_queryable=True,
        model_roles=(
            ProductionAgentPublicationModelRole(
                role="final_answer",
                connection_id="model_deepseek",
                provider="deepseek",
                model_identifier="deepseek-chat",
                lifecycle_state="ACTIVE",
                configuration_state="ready",
            ),
        ),
        configuration_blockers=(
            ProductionAgentPublicationConfigurationBlocker(
                code="memory_must_be_disabled",
                module_id="memory",
                message="Initial production publication requires Memory to be disabled.",
            ),
        ),
        phase_f_evidence_requirements=(
            "shadow",
            "capacity",
            "acceptance",
            "recovery",
        ),
        online_smoke_required=True,
        activation_mode="postgres_atomic_cas",
    )


def _knowledge_binding_result(
    *,
    revision: int,
    candidate: DraftKnowledgeReleaseBindingCandidate | None = None,
) -> AgentConfigurationKnowledgeBindingResult:
    record = _draft_record()
    return AgentConfigurationKnowledgeBindingResult(
        record=AgentDraftRecord(
            revision=revision,
            draft=record.draft.model_copy(
                update={"knowledge_release_binding_candidate": candidate}
            ),
        ),
        catalog=KnowledgeServiceManagementWorkspace(
            readiness=KnowledgeServiceReadinessProjection(
                state="ready",
                revision="kss-release-2026-08-21",
            ),
            spaces=(),
            sources=(),
            bases=(),
            source_versions=(),
            releases=(
                KnowledgeServiceReleaseProjection(
                    **_knowledge_binding_candidate().model_dump(mode="python"),
                    source_version_count=3,
                    state="queryable",
                ),
            ),
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
            "visible_modules": [
                "general",
                "workflow",
                "skills",
                "knowledge",
                "tools",
                "policy",
                "model",
                "memory",
                "response",
            ],
            "editable_modules": [
                "general",
                "workflow",
                "skills",
                "knowledge",
                "tools",
                "policy",
                "model",
                "memory",
                "response",
            ],
            "lifecycle_tabs": ["publication", "versions", "contract", "monitor"],
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


def test_production_draft_projects_rollback_capability_from_gate_and_permission() -> None:
    application, _ = _application(rollback_enabled=True)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701"
    )

    enabled = TestClient(application).get(route)

    assert enabled.status_code == 200
    assert enabled.json()["capabilities"]["actions"]["can_rollback"] is True

    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )
    denied = TestClient(application).get(route)

    assert denied.status_code == 200
    assert denied.json()["capabilities"]["actions"]["can_rollback"] is False


def test_formal_publication_command_returns_trace_safe_success_and_replay_status() -> None:
    application, _ = _application()
    command = _RecordingFormalPublicationCommand(
        _formal_command_result(FormalProductionAgentPublicationCommandState.SUCCEEDED)
    )
    application.state.formal_production_agent_publication_command = command
    path = (
        "/api/config/agents/agent_management_insurance_specialist/drafts/"
        "019ba001-1111-7000-8000-000000000701/formal-publications"
    )

    response = TestClient(application).post(
        path,
        headers={"Idempotency-Key": "formal-publish-11"},
        json=_formal_command_body(),
    )

    assert response.status_code == 201
    assert response.json()["state"] == "succeeded"
    assert response.json()["replayed"] is False
    serialized = response.text
    assert "formal-publish-11" not in serialized
    assert "等待期如何解释" not in serialized
    assert "artifact-shadow" not in serialized
    call = command.calls[0]
    assert call["agent_id"] == "agent_management_insurance_specialist"
    assert call["draft_id"] == "019ba001-1111-7000-8000-000000000701"
    assert call["idempotency_key"] == "formal-publish-11"
    assert call["actor"].subject == "local-user"

    command.result = _formal_command_result(
        FormalProductionAgentPublicationCommandState.SUCCEEDED,
        replayed=True,
    )
    replay = TestClient(application).post(
        path,
        headers={"Idempotency-Key": "formal-publish-11"},
        json=_formal_command_body(),
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True


def test_formal_publication_command_get_returns_trace_safe_receipt_for_owner() -> None:
    application, _ = _application()
    command = _RecordingFormalPublicationCommand(
        _formal_command_result(FormalProductionAgentPublicationCommandState.IN_PROGRESS)
    )
    application.state.formal_production_agent_publication_command = command
    path = (
        "/api/config/agents/agent_management_insurance_specialist/drafts/"
        "019ba001-1111-7000-8000-000000000701/formal-publications/"
        "019ba001-1111-7000-8000-000000000805"
    )

    response = TestClient(application).get(path)

    assert response.status_code == 200
    assert response.json() == command.result.receipt.model_dump(mode="json")
    serialized = response.text
    assert "replayed" not in serialized
    assert "formal-publish-11" not in serialized
    assert "等待期如何解释" not in serialized
    assert "candidate_checkpoint" not in serialized
    assert "lease_owner" not in serialized
    assert command.calls == [
        {
            "agent_id": "agent_management_insurance_specialist",
            "draft_id": "019ba001-1111-7000-8000-000000000701",
            "command_id": "019ba001-1111-7000-8000-000000000805",
            "actor": AuditActorFacts(
                subject="local-user",
                identity_provider="enterprise-oidc",
                session_id="development-session",
                permissions=tuple(sorted(permission.value for permission in _all_permissions())),
            ),
        }
    ]


def test_formal_publication_command_get_requires_publish_and_hides_missing_resource() -> None:
    application, _ = _application()
    command = _RecordingFormalPublicationCommand(
        _formal_command_result(FormalProductionAgentPublicationCommandState.IN_PROGRESS)
    )
    application.state.formal_production_agent_publication_command = command
    path = (
        "/api/config/agents/agent_management_insurance_specialist/drafts/"
        "019ba001-1111-7000-8000-000000000701/formal-publications/"
        "019ba001-1111-7000-8000-000000000805"
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )

    denied = TestClient(application).get(path)

    assert denied.status_code == 403
    assert command.calls == []

    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset(_all_permissions())
    )
    command.error = FormalProductionAgentPublicationCommandRejected(
        code="formal_publication_command_not_found",
        detail="must not reveal whether another actor owns the command",
    )
    missing = TestClient(application).get(path)

    assert missing.status_code == 404
    assert missing.json() == {"detail": "formal_publication_command_not_found"}
    assert "another actor" not in missing.text


def test_formal_publication_command_exposes_in_progress_and_stable_failure() -> None:
    application, _ = _application()
    command = _RecordingFormalPublicationCommand(
        _formal_command_result(
            FormalProductionAgentPublicationCommandState.IN_PROGRESS,
            replayed=True,
        )
    )
    application.state.formal_production_agent_publication_command = command
    path = (
        "/api/config/agents/agent_management_insurance_specialist/drafts/"
        "019ba001-1111-7000-8000-000000000701/formal-publications"
    )

    in_progress = TestClient(application).post(
        path,
        headers={"Idempotency-Key": "formal-publish-11"},
        json=_formal_command_body(),
    )
    assert in_progress.status_code == 202
    assert in_progress.json()["state"] == "in_progress"

    command.result = _formal_command_result(
        FormalProductionAgentPublicationCommandState.FAILED,
        replayed=True,
        failure_code="online_smoke_unavailable",
    )
    failed = TestClient(application).post(
        path,
        headers={"Idempotency-Key": "formal-publish-11"},
        json=_formal_command_body(),
    )
    assert failed.status_code == 503
    assert failed.json()["failure_code"] == "online_smoke_unavailable"
    assert "private" not in failed.text


def test_formal_publication_command_requires_publish_permission_key_and_strict_body() -> None:
    application, _ = _application()
    command = _RecordingFormalPublicationCommand(
        _formal_command_result(FormalProductionAgentPublicationCommandState.SUCCEEDED)
    )
    application.state.formal_production_agent_publication_command = command
    path = (
        "/api/config/agents/agent_management_insurance_specialist/drafts/"
        "019ba001-1111-7000-8000-000000000701/formal-publications"
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )
    denied = TestClient(application).post(
        path,
        headers={"Idempotency-Key": "formal-publish-11"},
        json=_formal_command_body(),
    )
    assert denied.status_code == 403
    assert command.calls == []

    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset(_all_permissions())
    )
    missing_key = TestClient(application).post(path, json=_formal_command_body())
    assert missing_key.status_code == 422
    private_body = {
        **_formal_command_body(),
        "binding_profile": {"caller": "must-not-control"},
    }
    private = TestClient(application).post(
        path,
        headers={"Idempotency-Key": "formal-publish-11"},
        json=private_body,
    )
    assert private.status_code == 422
    nested_private_body = _formal_command_body()
    nested_private_body["evidence"] = {
        **nested_private_body["evidence"],
        "raw_bundle": "must-not-exist",
    }
    nested_private = TestClient(application).post(
        path,
        headers={"Idempotency-Key": "formal-publish-11"},
        json=nested_private_body,
    )
    assert nested_private.status_code == 422
    assert command.calls == []


def test_formal_publication_command_maps_idempotency_conflict_without_detail_leak() -> None:
    application, _ = _application()
    command = _RecordingFormalPublicationCommand(
        _formal_command_result(FormalProductionAgentPublicationCommandState.IN_PROGRESS),
        error=FormalProductionAgentPublicationCommandRejected(
            code="formal_publication_idempotency_conflict",
            detail="safe public detail",
        ),
    )
    application.state.formal_production_agent_publication_command = command
    response = TestClient(application).post(
        "/api/config/agents/agent_management_insurance_specialist/drafts/"
        "019ba001-1111-7000-8000-000000000701/formal-publications",
        headers={"Idempotency-Key": "formal-publish-11"},
        json=_formal_command_body(),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "formal_publication_idempotency_conflict"}
    assert "safe public detail" not in response.text


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
    versions = client.get("/api/config/agents/agent_management_insurance_specialist/versions")

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


def test_production_rollback_calls_existing_workspace_when_explicitly_enabled() -> None:
    application, service = _application(rollback_enabled=True)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/versions/"
        "019ba001-1111-7000-8000-000000000901/rollback"
    )

    response = TestClient(application).post(
        route,
        json={
            "expected_active_version_id": "019ba001-1111-7000-8000-000000000902"
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "agent_id": "agent_management_insurance_specialist",
        "version_id": "019ba001-1111-7000-8000-000000000901",
        "activated_at": "2026-09-01T14:00:00Z",
        "activated_by": "local-user",
        "rollback_from_version_id": "019ba001-1111-7000-8000-000000000902",
    }
    assert service.calls == [
        {
            "agent_id": "agent_management_insurance_specialist",
            "version_id": "019ba001-1111-7000-8000-000000000901",
            "expected_active_version_id": "019ba001-1111-7000-8000-000000000902",
            "actor": AuditActorFacts(
                subject="local-user",
                identity_provider="enterprise-oidc",
                session_id="development-session",
                permissions=tuple(
                    sorted(permission.value for permission in _all_permissions())
                ),
            ),
            "operation": "rollback",
        }
    ]


def test_production_rollback_gate_defaults_closed_without_workspace_call() -> None:
    application, service = _application()

    response = TestClient(application).post(
        "/api/config/agents/agent_management_insurance_specialist/versions/"
        "019ba001-1111-7000-8000-000000000901/rollback",
        json={
            "expected_active_version_id": "019ba001-1111-7000-8000-000000000902"
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "production_agent_rollback_unavailable"}
    assert service.calls == []


def test_production_rollback_requires_publish_before_revealing_gate_state() -> None:
    application, service = _application(rollback_enabled=True)
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )

    response = TestClient(application).post(
        "/api/config/agents/agent_management_insurance_specialist/versions/"
        "019ba001-1111-7000-8000-000000000901/rollback",
        json={
            "expected_active_version_id": "019ba001-1111-7000-8000-000000000902"
        },
    )

    assert response.status_code == 403
    assert service.calls == []


def test_production_rollback_requires_strict_nullable_pointer_expectation() -> None:
    application, service = _application(rollback_enabled=True)
    client = TestClient(application)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/versions/"
        "019ba001-1111-7000-8000-000000000901/rollback"
    )

    missing = client.post(route, json={})
    unknown = client.post(
        route,
        json={"expected_active_version_id": None, "retry": True},
    )
    explicit_none = client.post(
        route,
        json={"expected_active_version_id": None},
    )

    assert missing.status_code == 422
    assert unknown.status_code == 422
    assert explicit_none.status_code == 200
    assert service.calls[-1]["expected_active_version_id"] is None


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            AgentConfigurationNotFound(
                code="agent_version_not_found",
                detail="private version detail",
            ),
            404,
            "agent_version_not_found",
        ),
        (
            AgentConfigurationConflict(
                code="agent_rollback_knowledge_release_unavailable",
                detail="private release detail",
            ),
            409,
            "agent_rollback_knowledge_release_unavailable",
        ),
        (
            AgentConfigurationConflict(
                code="active_agent_version_conflict",
                detail="private pointer detail",
            ),
            409,
            "active_agent_version_conflict",
        ),
    ],
)
def test_production_rollback_maps_stable_domain_failures(
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    application, _ = _application(rollback_enabled=True)
    application.state.agent_configuration_workspace = _FailingRollbackApplication(error)

    response = TestClient(application).post(
        "/api/config/agents/agent_management_insurance_specialist/versions/"
        "019ba001-1111-7000-8000-000000000901/rollback",
        json={
            "expected_active_version_id": "019ba001-1111-7000-8000-000000000902"
        },
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "private" not in response.text


def test_production_rollback_maps_catalog_unavailable_without_detail_leak() -> None:
    application, _ = _application(rollback_enabled=True)
    application.state.agent_configuration_workspace = _FailingRollbackApplication(
        AgentConfigurationConflict(
            code="agent_knowledge_catalog_unavailable",
            detail="private KSS endpoint failed",
        )
    )

    response = TestClient(application).post(
        "/api/config/agents/agent_management_insurance_specialist/versions/"
        "019ba001-1111-7000-8000-000000000901/rollback",
        json={
            "expected_active_version_id": "019ba001-1111-7000-8000-000000000902"
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "agent_knowledge_catalog_unavailable"}
    assert "private KSS endpoint" not in response.text


def test_production_rollback_hides_unexpected_internal_failure() -> None:
    application, _ = _application(rollback_enabled=True)
    application.state.agent_configuration_workspace = _FailingRollbackApplication(
        OSError("internal-path:/private/rollback-failure")
    )

    response = TestClient(application, raise_server_exceptions=False).post(
        "/api/config/agents/agent_management_insurance_specialist/versions/"
        "019ba001-1111-7000-8000-000000000901/rollback",
        json={
            "expected_active_version_id": "019ba001-1111-7000-8000-000000000902"
        },
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "production_agent_rollback_failed"}
    assert "/private" not in response.text


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


def test_update_production_contract_delegates_revisioned_candidate_to_workspace() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/contract"
    )

    response = TestClient(application).patch(
        route,
        json={
            "expected_revision": 7,
            "agent_yaml": "schema_version: 3\nresponse:\n  include_review_results: false\n",
        },
    )

    assert response.status_code == 200
    assert response.json()["agent_yaml"].endswith("response:\n  include_review_results: false\n")
    assert service.calls[-1] == {
        "agent_id": "agent_management_insurance_specialist",
        "draft_id": "019ba001-1111-7000-8000-000000000701",
        "expected_revision": 7,
        "agent_yaml": ("schema_version: 3\nresponse:\n  include_review_results: false\n"),
        "policy_yaml": None,
        "tools_yaml": None,
        "actor": AuditActorFacts(
            subject="local-user",
            identity_provider="enterprise-oidc",
            session_id="development-session",
            permissions=tuple(sorted(permission.value for permission in _all_permissions())),
        ),
        "operation": "contract_update",
    }


def test_production_contract_update_requires_permission_revision_and_strict_body() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/contract"
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )

    denied = TestClient(application).patch(
        route,
        json={"expected_revision": 1, "agent_yaml": "schema_version: 3\n"},
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset(_all_permissions())
    )
    missing_revision = TestClient(application).patch(
        route,
        json={"agent_yaml": "schema_version: 3\n"},
    )
    unknown_field = TestClient(application).patch(
        route,
        json={
            "expected_revision": 1,
            "agent_yaml": "schema_version: 3\n",
            "manifest_path": "/private/operator-controlled/agent.yaml",
        },
    )

    assert denied.status_code == 403
    assert missing_revision.status_code == 422
    assert unknown_field.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed.",
            ),
            409,
            "agent_draft_revision_conflict",
        ),
        (ValueError("internal-path:/private/tmp/invalid"), 400, "agent_contract_invalid"),
        (
            ProofAgentError(
                "PA_CONFIG_001",
                "internal-path:/private/tmp/invalid",
                "Do not expose this path.",
            ),
            400,
            "agent_contract_invalid",
        ),
        (OSError("internal-path:/private/tmp/failure"), 500, "agent_contract_update_failed"),
    ],
)
def test_production_contract_update_maps_failures_without_internal_detail(
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    application, _ = _application()
    application.state.agent_configuration_workspace = _FailingContractApplication(error)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/contract"
    )

    response = TestClient(application, raise_server_exceptions=False).patch(
        route,
        json={"expected_revision": 1, "agent_yaml": "schema_version: 3\n"},
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "/private" not in response.text


def test_production_workflow_catalog_is_available_to_viewers() -> None:
    application, _ = _application()
    client = TestClient(application)

    catalog = client.get("/api/config/workflow-templates")
    detail = client.get("/api/config/workflow-templates/react_enterprise_qa_v3")

    assert catalog.status_code == 200
    assert any(item["name"] == "react_enterprise_qa_v3" for item in catalog.json()["data"])
    assert detail.status_code == 200
    assert detail.json()["descriptor_version"] == "react_enterprise_qa.v3"
    assert detail.json()["stages"]


def test_update_and_preview_production_workflow_delegate_typed_commands() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/workflow-stages"
    )
    client = TestClient(application)
    stage_payload = {
        "prompt": {
            "business_context": "Claims context",
            "task_instructions": ["Check coverage."],
            "output_preferences": ["Cite evidence."],
        },
        "context": {"include_agent_purpose": True},
    }

    updated = client.patch(
        route,
        json={
            "expected_revision": 7,
            "template": "react_enterprise_qa_v3",
            "template_descriptor_version": "react_enterprise_qa.v3",
            "stages": [{"id": "plan", **stage_payload}],
        },
    )
    preview = client.post(f"{route}/plan/preview", json=stage_payload)

    assert updated.status_code == 200
    assert updated.json() == _draft_record().draft.contract_bundle.model_dump(mode="json")
    assert preview.status_code == 200
    assert preview.json()["stage_id"] == "plan"
    assert service.calls[-2] == {
        "agent_id": "agent_management_insurance_specialist",
        "draft_id": "019ba001-1111-7000-8000-000000000701",
        "expected_revision": 7,
        "template": "react_enterprise_qa_v3",
        "template_descriptor_version": "react_enterprise_qa.v3",
        "stages": (
            WorkflowStageConfig(
                id="plan",
                prompt=WorkflowStagePromptConfig(
                    business_context="Claims context",
                    task_instructions=("Check coverage.",),
                    output_preferences=("Cite evidence.",),
                ),
                context=WorkflowStageContextConfig(options={"include_agent_purpose": True}),
            ),
        ),
        "actor": AuditActorFacts(
            subject="local-user",
            identity_provider="enterprise-oidc",
            session_id="development-session",
            permissions=tuple(sorted(permission.value for permission in _all_permissions())),
        ),
        "operation": "workflow_stages_update",
    }
    assert service.calls[-1] == {
        "agent_id": "agent_management_insurance_specialist",
        "draft_id": "019ba001-1111-7000-8000-000000000701",
        "stage_id": "plan",
        "prompt": WorkflowStagePromptConfig(
            business_context="Claims context",
            task_instructions=("Check coverage.",),
            output_preferences=("Cite evidence.",),
        ),
        "context_options": {"include_agent_purpose": True},
        "operation": "workflow_stage_preview",
    }


def test_production_workflow_requires_permissions_revision_and_strict_body() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/workflow-stages"
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )
    client = TestClient(application)

    denied_update = client.patch(
        route,
        json={"expected_revision": 1, "stages": []},
    )
    denied_preview = client.post(
        f"{route}/plan/preview",
        json={"prompt": {}, "context": {}},
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset(_all_permissions())
    )
    missing_revision = client.patch(route, json={"stages": []})
    unknown_field = client.patch(
        route,
        json={"expected_revision": 1, "stages": [], "execute": True},
    )

    assert denied_update.status_code == 403
    assert denied_preview.status_code == 403
    assert missing_revision.status_code == 422
    assert unknown_field.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            AgentConfigurationNotFound(
                code="agent_draft_not_found",
                detail="The Agent Draft was not found.",
            ),
            404,
            "agent_draft_not_found",
        ),
        (
            AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed.",
            ),
            409,
            "agent_draft_revision_conflict",
        ),
        (
            ValueError("internal-path:/private/tmp/workflow-invalid"),
            400,
            "agent_workflow_stage_configuration_invalid",
        ),
        (
            OSError("internal-path:/private/tmp/workflow-failed"),
            500,
            "agent_workflow_stage_configuration_failed",
        ),
    ],
)
def test_production_workflow_update_maps_failures_without_internal_detail(
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    application, _ = _application()
    application.state.agent_configuration_workspace = _FailingWorkflowApplication(error)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/workflow-stages"
    )

    response = TestClient(application, raise_server_exceptions=False).patch(
        route,
        json={"expected_revision": 1, "stages": []},
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "/private" not in response.text


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            ValueError("internal-path:/private/tmp/preview-invalid"),
            400,
            "agent_workflow_stage_preview_invalid",
        ),
        (
            OSError("internal-path:/private/tmp/preview-failed"),
            500,
            "agent_workflow_stage_preview_failed",
        ),
    ],
)
def test_production_workflow_preview_maps_failures_without_internal_detail(
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    application, _ = _application()
    application.state.agent_configuration_workspace = _FailingWorkflowApplication(error)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/"
        "workflow-stages/plan/preview"
    )

    response = TestClient(application, raise_server_exceptions=False).post(
        route,
        json={"prompt": {}, "context": {}},
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "/private" not in response.text


def test_production_skill_pack_routes_delegate_revisioned_typed_commands() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/skills"
    )
    client = TestClient(application)

    read = client.get(route)
    created = client.post(
        f"{route}/business-flows",
        json={
            "expected_revision": 7,
            "id": "appeals_qa",
            "label": "Appeals QA",
            "description": "Appeals guidance.",
            "intent_patterns": ["appeal status"],
            "stage_prompt_addenda": {
                "plan": {
                    "business_context": "Appeals context.",
                    "task_instructions": ["Check coverage."],
                    "output_preferences": ["Cite evidence."],
                }
            },
        },
    )
    updated = client.patch(
        f"{route}/business-flows/appeals_qa",
        json={
            "expected_revision": 8,
            "label": "Appeals Specialist",
            "description": "Updated appeals guidance.",
        },
    )
    deleted = client.delete(f"{route}/business-flows/appeals_qa?expected_revision=9")

    assert read.status_code == 200
    assert read.json()["revision"] == 1
    assert created.status_code == 200
    assert created.json()["revision"] == 8
    assert updated.status_code == 200
    assert updated.json()["revision"] == 9
    assert deleted.status_code == 200
    assert deleted.json()["revision"] == 10
    assert [call["operation"] for call in service.calls] == [
        "skill_pack_read",
        "skill_pack_create",
        "skill_pack_update",
        "skill_pack_delete",
    ]
    assert service.calls[1]["expected_revision"] == 7
    assert service.calls[1]["command"] == BusinessFlowSkillPackCreateCommand(
        pack_id="appeals_qa",
        label="Appeals QA",
        description="Appeals guidance.",
        intent_patterns=("appeal status",),
        stage_prompt_addenda={
            "plan": WorkflowStagePromptConfig(
                business_context="Appeals context.",
                task_instructions=("Check coverage.",),
                output_preferences=("Cite evidence.",),
            )
        },
        admission={},
    )
    assert service.calls[2]["pack_id"] == "appeals_qa"
    assert service.calls[2]["expected_revision"] == 8
    assert service.calls[2]["command"] == BusinessFlowSkillPackUpdateCommand(
        label="Appeals Specialist",
        description="Updated appeals guidance.",
    )
    assert service.calls[3]["pack_id"] == "appeals_qa"
    assert service.calls[3]["expected_revision"] == 9


def test_production_skill_pack_routes_require_permissions_revision_and_strict_body() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/skills"
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )
    client = TestClient(application)

    readable = client.get(route)
    denied_create = client.post(
        f"{route}/business-flows",
        json={
            "expected_revision": 1,
            "id": "appeals_qa",
            "label": "Appeals QA",
            "description": "Appeals guidance.",
        },
    )
    denied_update = client.patch(
        f"{route}/business-flows/appeals_qa",
        json={"expected_revision": 1, "label": "Appeals Specialist"},
    )
    denied_delete = client.delete(f"{route}/business-flows/appeals_qa?expected_revision=1")
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.edit")})
    )
    denied_read = client.get(route)
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset(_all_permissions())
    )
    missing_create_revision = client.post(
        f"{route}/business-flows",
        json={
            "id": "appeals_qa",
            "label": "Appeals QA",
            "description": "Appeals guidance.",
        },
    )
    missing_update_revision = client.patch(
        f"{route}/business-flows/appeals_qa",
        json={"label": "Appeals Specialist"},
    )
    missing_delete_revision = client.delete(f"{route}/business-flows/appeals_qa")
    unknown_field = client.post(
        f"{route}/business-flows",
        json={
            "expected_revision": 1,
            "id": "appeals_qa",
            "label": "Appeals QA",
            "description": "Appeals guidance.",
            "definition": "/private/operator-controlled/skills.yaml",
        },
    )

    assert readable.status_code == 200
    assert denied_create.status_code == 403
    assert denied_update.status_code == 403
    assert denied_delete.status_code == 403
    assert denied_read.status_code == 403
    assert missing_create_revision.status_code == 422
    assert missing_update_revision.status_code == 422
    assert missing_delete_revision.status_code == 422
    assert unknown_field.status_code == 422
    assert [call["operation"] for call in service.calls] == ["skill_pack_read"]


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed.",
            ),
            409,
            "agent_draft_revision_conflict",
        ),
        (
            ValueError("internal-path:/private/tmp/skill-pack-invalid"),
            400,
            "agent_skill_pack_configuration_invalid",
        ),
        (
            ProofAgentError(
                "PA_CONFIG_001",
                "internal-path:/private/tmp/skill-pack-invalid",
                "Do not expose this path.",
            ),
            400,
            "agent_skill_pack_configuration_invalid",
        ),
        (
            OSError("internal-path:/private/tmp/skill-pack-failed"),
            500,
            "agent_skill_pack_update_failed",
        ),
    ],
)
def test_production_skill_pack_mutation_maps_failures_without_internal_detail(
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    application, _ = _application()
    application.state.agent_configuration_workspace = _FailingSkillPackApplication(error)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/skills/business-flows"
    )

    response = TestClient(application, raise_server_exceptions=False).post(
        route,
        json={
            "expected_revision": 1,
            "id": "appeals_qa",
            "label": "Appeals QA",
            "description": "Appeals guidance.",
        },
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "/private" not in response.text


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            ValueError("internal-path:/private/tmp/skill-pack-invalid"),
            400,
            "agent_skill_pack_configuration_invalid",
        ),
        (
            OSError("internal-path:/private/tmp/skill-pack-failed"),
            500,
            "agent_skill_pack_read_failed",
        ),
    ],
)
def test_production_skill_pack_read_maps_failures_without_internal_detail(
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    application, _ = _application()
    application.state.agent_configuration_workspace = _FailingSkillPackApplication(error)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/skills"
    )

    response = TestClient(application, raise_server_exceptions=False).get(route)

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "/private" not in response.text


@pytest.mark.parametrize(
    ("method", "suffix", "request_kwargs"),
    [
        (
            "PATCH",
            "/appeals_qa",
            {"json": {"expected_revision": 1, "label": "Appeals Specialist"}},
        ),
        ("DELETE", "/appeals_qa?expected_revision=1", {}),
    ],
)
def test_production_skill_pack_update_and_delete_map_dependency_failures(
    method: str,
    suffix: str,
    request_kwargs: dict[str, Any],
) -> None:
    application, _ = _application()
    application.state.agent_configuration_workspace = _FailingSkillPackApplication(
        OSError("internal-path:/private/tmp/skill-pack-failed")
    )
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/"
        f"skills/business-flows{suffix}"
    )

    response = TestClient(application, raise_server_exceptions=False).request(
        method,
        route,
        **request_kwargs,
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "agent_skill_pack_update_failed"}
    assert "/private" not in response.text


def test_production_knowledge_binding_routes_delegate_exact_revisioned_candidate() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/knowledge-binding"
    )
    client = TestClient(application)

    read = client.get(route)
    updated = client.patch(
        route,
        json={
            "expected_revision": 7,
            "knowledge_space_id": "insurance",
            "knowledge_base_id": "insurance-guidance",
            "knowledge_base_version_id": "insurance-guidance-v3",
            "knowledge_base_release_id": "insurance-guidance-release-7",
        },
    )

    assert read.status_code == 200
    assert read.json()["revision"] == 1
    assert read.json()["candidate"] is None
    assert read.json()["readiness"] == {
        "state": "ready",
        "revision": "kss-release-2026-08-21",
        "blockers": [],
    }
    assert read.json()["releases"] == [
        {
            "knowledge_space_id": "insurance",
            "knowledge_base_id": "insurance-guidance",
            "knowledge_base_version_id": "insurance-guidance-v3",
            "knowledge_base_release_id": "insurance-guidance-release-7",
            "source_version_count": 3,
            "state": "queryable",
        }
    ]
    assert updated.status_code == 200
    assert updated.json()["revision"] == 8
    assert updated.json()["candidate"] == _knowledge_binding_candidate().model_dump(mode="json")
    assert [call["operation"] for call in service.calls] == [
        "knowledge_binding_read",
        "knowledge_binding_update",
    ]
    assert service.calls[-1]["expected_revision"] == 7
    assert service.calls[-1]["candidate"] == _knowledge_binding_candidate()


def test_production_knowledge_binding_requires_both_authority_permissions_and_strict_revision() -> (
    None
):
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/knowledge-binding"
    )
    client = TestClient(application)
    candidate = _knowledge_binding_candidate().model_dump(mode="json")

    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )
    denied_read_without_kss = client.get(route)
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("knowledge_source.view")})
    )
    denied_read_without_agent = client.get(route)
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset(
            {
                _permission("agent.view"),
                _permission("knowledge_source.view"),
            }
        )
    )
    readable = client.get(route)
    denied_update_without_edit = client.patch(
        route,
        json={"expected_revision": 1, **candidate},
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset(
            {
                _permission("agent.edit"),
                _permission("knowledge_source.view"),
            }
        )
    )
    missing_revision = client.patch(route, json=candidate)
    unknown_field = client.patch(
        route,
        json={
            "expected_revision": 1,
            **candidate,
            "client_credential_ref": "/private/operator-secret",
        },
    )

    assert denied_read_without_kss.status_code == 403
    assert denied_read_without_agent.status_code == 403
    assert readable.status_code == 200
    assert denied_update_without_edit.status_code == 403
    assert missing_revision.status_code == 422
    assert unknown_field.status_code == 422
    assert [call["operation"] for call in service.calls] == ["knowledge_binding_read"]


@pytest.mark.parametrize(
    ("error", "method", "status_code", "detail"),
    [
        (
            AgentConfigurationNotFound(
                code="agent_draft_not_found",
                detail="The Agent Draft was not found.",
            ),
            "GET",
            404,
            "agent_draft_not_found",
        ),
        (
            AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed.",
            ),
            "PATCH",
            409,
            "agent_draft_revision_conflict",
        ),
        (
            AgentConfigurationConflict(
                code="agent_knowledge_release_not_queryable",
                detail="internal-path:/private/kss/release",
            ),
            "PATCH",
            400,
            "agent_knowledge_release_not_queryable",
        ),
        (
            AgentConfigurationConflict(
                code="agent_knowledge_catalog_unavailable",
                detail="internal-path:/private/kss/catalog",
            ),
            "PATCH",
            503,
            "agent_knowledge_catalog_unavailable",
        ),
        (
            ProofAgentError(
                "PA_KNOWLEDGE_002",
                "internal-path:/private/kss/dependency",
                "Do not expose this path.",
            ),
            "GET",
            503,
            "agent_knowledge_catalog_unavailable",
        ),
        (
            OSError("internal-path:/private/kss/failure"),
            "PATCH",
            500,
            "agent_knowledge_binding_update_failed",
        ),
    ],
)
def test_production_knowledge_binding_maps_failures_without_internal_detail(
    error: Exception,
    method: str,
    status_code: int,
    detail: str,
) -> None:
    application, _ = _application()
    application.state.agent_configuration_workspace = _FailingKnowledgeBindingApplication(error)
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/knowledge-binding"
    )
    request_kwargs: dict[str, Any] = {}
    if method == "PATCH":
        request_kwargs["json"] = {
            "expected_revision": 1,
            **_knowledge_binding_candidate().model_dump(mode="json"),
        }

    response = TestClient(application, raise_server_exceptions=False).request(
        method,
        route,
        **request_kwargs,
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "/private" not in response.text


def test_production_configuration_delivery_does_not_import_persistence_or_compilers() -> None:
    tree = ast.parse(inspect.getsource(production_configuration))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert not imported_modules.intersection(
        {
            "proof_agent.configuration.local_store",
            "proof_agent.capabilities.persistence.postgres",
            "proof_agent.bootstrap.loader",
            "proof_agent.configuration.compiler",
            "yaml",
        }
    )


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


def test_production_publication_configuration_returns_trace_safe_authoritative_projection() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/publication-configuration"
    )

    response = TestClient(application).get(route)

    assert response.status_code == 200
    assert response.json() == {
        "draft_revision": 11,
        "authoring_configuration_state": "blocked",
        "formal_publication_state": "workspace_draft_not_bound",
        "can_publish_from_dashboard": False,
        "workflow": {
            "template": "react_enterprise_qa_v3",
            "template_descriptor_version": "react_enterprise_qa.v3",
        },
        "knowledge": {
            "candidate": _knowledge_binding_candidate().model_dump(mode="json"),
            "queryable": True,
        },
        "model_roles": [
            {
                "role": "final_answer",
                "connection_id": "model_deepseek",
                "provider": "deepseek",
                "model_identifier": "deepseek-chat",
                "lifecycle_state": "ACTIVE",
                "configuration_state": "ready",
            }
        ],
        "configuration_blockers": [
            {
                "code": "memory_must_be_disabled",
                "module_id": "memory",
                "message": ("Initial production publication requires Memory to be disabled."),
            }
        ],
        "formal_requirements": {
            "phase_f_evidence": ["shadow", "capacity", "acceptance", "recovery"],
            "online_smoke_required": True,
            "activation_mode": "postgres_atomic_cas",
        },
    }
    assert "credential" not in response.text
    assert "base_url" not in response.text
    assert service.calls == [
        {
            "agent_id": "agent_management_insurance_specialist",
            "draft_id": "019ba001-1111-7000-8000-000000000701",
            "operation": "publication_configuration_read",
        }
    ]


def test_production_publication_configuration_requires_agent_and_knowledge_view() -> None:
    application, service = _application()
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/publication-configuration"
    )
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("agent.view")})
    )

    missing_knowledge_view = TestClient(application).get(route)
    application.state.operator_identity_provider = _StaticIdentityProvider(
        frozenset({_permission("knowledge_source.view")})
    )
    missing_agent_view = TestClient(application).get(route)

    assert missing_knowledge_view.status_code == 403
    assert missing_agent_view.status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            AgentConfigurationNotFound(
                code="agent_draft_not_found",
                detail="internal-path:/private/draft",
            ),
            404,
            "agent_draft_not_found",
        ),
        (
            AgentConfigurationConflict(
                code="agent_publication_configuration_unavailable",
                detail="internal-path:/private/configuration",
            ),
            503,
            "agent_publication_configuration_unavailable",
        ),
        (
            AgentConfigurationConflict(
                code="agent_knowledge_catalog_unavailable",
                detail="internal-path:/private/catalog",
            ),
            503,
            "agent_knowledge_catalog_unavailable",
        ),
        (
            ProofAgentError(
                "PA_KNOWLEDGE_002",
                "internal-path:/private/kss",
                "Do not expose this path.",
            ),
            503,
            "agent_publication_configuration_unavailable",
        ),
        (
            ValueError("internal-path:/private/invalid"),
            400,
            "agent_publication_configuration_invalid",
        ),
        (
            OSError("internal-path:/private/failure"),
            500,
            "agent_publication_configuration_read_failed",
        ),
    ],
)
def test_production_publication_configuration_maps_failures_without_internal_detail(
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    application, _ = _application()
    application.state.agent_configuration_workspace = _FailingPublicationConfigurationApplication(
        error
    )
    route = (
        "/api/config/agents/agent_management_insurance_specialist/"
        "drafts/019ba001-1111-7000-8000-000000000701/publication-configuration"
    )

    response = TestClient(application, raise_server_exceptions=False).get(route)

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "/private" not in response.text


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
    application.state.agent_configuration_workspace = _ConflictApplication()
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
        raise AgentConfigurationConflict(
            code="sole_agent_already_exists",
            detail="Already initialized.",
        )

    def get_draft(self, *, agent_id: str, draft_id: str) -> AgentDraftRecord:
        del agent_id, draft_id
        raise AgentConfigurationNotFound(
            code="agent_draft_not_found",
            detail="Not found.",
        )


class _FailingRollbackApplication(RecordingApplication):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def rollback_version(self, **kwargs: Any) -> object:
        del kwargs
        raise self._error


class _FailingContractApplication(RecordingApplication):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def update_contract(self, **kwargs: Any) -> AgentDraftRecord:
        del kwargs
        raise self._error


class _FailingPublicationConfigurationApplication(RecordingApplication):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def get_publication_configuration(self, **kwargs: Any) -> Any:
        del kwargs
        raise self._error


class _FailingWorkflowApplication(RecordingApplication):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def update_workflow_stages(self, **kwargs: Any) -> AgentDraftRecord:
        del kwargs
        raise self._error

    def preview_workflow_stage(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        raise self._error


class _FailingSkillPackApplication(RecordingApplication):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def get_business_flow_skill_packs(self, **kwargs: Any) -> AgentConfigurationSkillPackResult:
        del kwargs
        raise self._error

    def create_business_flow_skill_pack(self, **kwargs: Any) -> AgentConfigurationSkillPackResult:
        del kwargs
        raise self._error

    def update_business_flow_skill_pack(self, **kwargs: Any) -> AgentConfigurationSkillPackResult:
        del kwargs
        raise self._error

    def delete_business_flow_skill_pack(self, **kwargs: Any) -> AgentConfigurationSkillPackResult:
        del kwargs
        raise self._error


class _FailingKnowledgeBindingApplication(RecordingApplication):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def get_knowledge_release_binding_candidate(
        self, **kwargs: Any
    ) -> AgentConfigurationKnowledgeBindingResult:
        del kwargs
        raise self._error

    def update_knowledge_release_binding_candidate(
        self, **kwargs: Any
    ) -> AgentConfigurationKnowledgeBindingResult:
        del kwargs
        raise self._error


def _permission(value: str) -> Any:
    from proof_agent.contracts import Permission

    return Permission(value)


def _all_permissions() -> tuple[Any, ...]:
    from proof_agent.contracts import Permission

    return tuple(Permission)
