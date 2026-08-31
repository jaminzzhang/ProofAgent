"""Production Agent Draft configuration API."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from proof_agent.contracts import (
    AgentDraftRecord,
    AuditActorFacts,
    DraftKnowledgeReleaseBindingCandidate,
    FormalProductionAgentPublicationCommandRequest,
    FormalProductionAgentPublicationCommandState,
    Permission,
)
from proof_agent.contracts.knowledge_service_management import KnowledgeServiceIdentifier
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationConflict,
    AgentConfigurationNotFound,
)
from proof_agent.control.formal_production_agent_publication_command import (
    FormalProductionAgentPublicationCommandRejected,
)
from proof_agent.control.workflow.templates import (
    list_workflow_templates,
    resolve_workflow_template,
)
from proof_agent.delivery.agent_configuration_workflow_http import (
    WorkflowStagePreviewRequest,
    WorkflowStageUpdateItemRequest,
    workflow_stage_config_request,
    workflow_stage_prompt_config,
    workflow_template_payload,
)
from proof_agent.delivery.agent_configuration_skill_pack_http import (
    BusinessFlowSkillPackCreateFields,
    BusinessFlowSkillPackUpdateFields,
    business_flow_skill_pack_create_command,
    business_flow_skill_pack_result_payload,
    business_flow_skill_pack_update_command,
)
from proof_agent.delivery.http_errors import proof_agent_http_exception
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


router = APIRouter()
agent_router = APIRouter(
    prefix="/config/agents",
    tags=["production-agent-configuration"],
)
workflow_template_router = APIRouter(
    prefix="/config/workflow-templates",
    tags=["production-agent-configuration"],
)

_CANONICAL_TEMPLATE = {
    "id": "agent_management_insurance_specialist",
    "name": "Agent Management Insurance Specialist",
    "purpose": (
        "Assist internal insurance staff with governed, evidence-backed insurance "
        "knowledge consultation."
    ),
    "description": (
        "Operator-facing Controlled ReAct V3 consultation with production publication "
        "kept behind candidate gates."
    ),
}


class ProductionAgentCreateRequest(BaseModel):
    """Browser-safe command for initializing the server-owned sole Agent."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(default="", max_length=4_000)


class ProductionAgentUpdateRequest(BaseModel):
    """Revisioned update for the production Draft Agent's basic metadata."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def require_change(self) -> "ProductionAgentUpdateRequest":
        if self.display_name is None and self.purpose is None:
            raise ValueError("at least one editable field is required")
        return self


class ProductionAgentContractUpdateRequest(BaseModel):
    """Revisioned whole-package candidate for production Draft configuration."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    agent_yaml: str | None = None
    policy_yaml: str | None = None
    tools_yaml: str | None = None

    @model_validator(mode="after")
    def require_candidate_file(self) -> "ProductionAgentContractUpdateRequest":
        if all(value is None for value in (self.agent_yaml, self.policy_yaml, self.tools_yaml)):
            raise ValueError("at least one Contract file is required")
        return self


class ProductionWorkflowStagesUpdateRequest(BaseModel):
    """Revisioned replacement for production Draft Workflow Stage settings."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    template: str | None = Field(default=None, min_length=1, max_length=255)
    template_descriptor_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    stages: list[WorkflowStageUpdateItemRequest]


class ProductionBusinessFlowSkillPackCreateRequest(BusinessFlowSkillPackCreateFields):
    """Revisioned create command for a production Draft Skill Pack."""

    expected_revision: int = Field(ge=1)


class ProductionBusinessFlowSkillPackUpdateRequest(BusinessFlowSkillPackUpdateFields):
    """Revisioned update command for a production Draft Skill Pack."""

    expected_revision: int = Field(ge=1)


class ProductionKnowledgeReleaseBindingUpdateRequest(BaseModel):
    """Secret-free exact KSS Release candidate for one production Draft."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_version_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier


@agent_router.post("/{agent_id}/drafts/{draft_id}/formal-publications")
def publish_formal_production_agent(
    agent_id: str,
    draft_id: str,
    body: FormalProductionAgentPublicationCommandRequest,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Reserve or replay one exact Formal Production Agent publication command."""

    require_operator_permission(identity, Permission.AGENT_PUBLISH)
    try:
        result = _formal_publication_command(request).publish(
            agent_id=agent_id,
            draft_id=draft_id,
            request=body,
            idempotency_key=idempotency_key,
            actor=_audit_actor(request, identity),
        )
    except FormalProductionAgentPublicationCommandRejected as exc:
        raise HTTPException(
            status_code=_formal_command_rejection_status(exc.code),
            detail=exc.code,
        ) from exc
    receipt = result.receipt
    if receipt.state is FormalProductionAgentPublicationCommandState.IN_PROGRESS:
        response.status_code = 202
    elif receipt.state is FormalProductionAgentPublicationCommandState.SUCCEEDED:
        response.status_code = 200 if result.replayed else 201
    else:
        assert receipt.failure_code is not None
        response.status_code = _formal_command_failure_status(receipt.failure_code)
    payload = cast(dict[str, Any], receipt.model_dump(mode="json"))
    payload["replayed"] = result.replayed
    return payload


@workflow_template_router.get("")
def list_production_workflow_templates(
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return the backend-owned Workflow Template catalog."""

    require_operator_permission(identity, Permission.AGENT_VIEW)
    descriptors = list_workflow_templates()
    return {
        "data": [workflow_template_payload(item) for item in descriptors],
        "meta": {"total": len(descriptors)},
    }


@workflow_template_router.get("/{template_id}")
def get_production_workflow_template(
    template_id: str,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one backend-owned Workflow Template Descriptor."""

    require_operator_permission(identity, Permission.AGENT_VIEW)
    try:
        descriptor = resolve_workflow_template(template_id)
    except ProofAgentError as exc:
        raise proof_agent_http_exception(exc) from exc
    return workflow_template_payload(descriptor)


@agent_router.get("")
def list_production_agents(
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_VIEW)
    inventory = _application(request).list_agents()
    data = [
        {
            "agent_id": item.agent_id,
            "display_name": item.display_name,
            "purpose": item.purpose,
            "draft_count": item.draft_count,
            "latest_draft_id": item.latest_draft_id,
            "version_count": item.version_count,
            "active_version_id": item.active_version_id,
            "updated_at": item.updated_at,
        }
        for item in inventory.agents
    ]
    return {
        "data": data,
        "meta": {
            "total": len(data),
            "capabilities": {
                "mode": "production",
                "can_create": (
                    inventory.can_create and Permission.AGENT_EDIT in identity.permissions
                ),
                "can_import_manifest": False,
                "canonical_template": _CANONICAL_TEMPLATE,
            },
        },
    }


@agent_router.post("")
def create_production_agent(
    body: ProductionAgentCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_EDIT)
    try:
        result = _application(request).create_draft(
            display_name=body.display_name,
            purpose=body.purpose,
            idempotency_key=idempotency_key,
            actor=_audit_actor(request, identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.status_code = 200 if result.replayed else 201
    return _draft_payload(result.record)


@agent_router.get("/{agent_id}/drafts/{draft_id}")
def get_production_agent_draft(
    agent_id: str,
    draft_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_VIEW)
    try:
        record = cast(
            AgentDraftRecord,
            _application(request).get_draft(
                agent_id=agent_id,
                draft_id=draft_id,
            ),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    return _draft_payload(record)


@agent_router.patch("/{agent_id}/drafts/{draft_id}")
def update_production_agent_draft(
    agent_id: str,
    draft_id: str,
    body: ProductionAgentUpdateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_EDIT)
    try:
        record = _application(request).update_draft(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=body.expected_revision,
            display_name=body.display_name,
            purpose=body.purpose,
            actor=_audit_actor(request, identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _draft_payload(record)


@agent_router.get("/{agent_id}/drafts/{draft_id}/contract")
def get_production_agent_contract(
    agent_id: str,
    draft_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_VIEW)
    try:
        record = cast(
            AgentDraftRecord,
            _application(request).get_draft(
                agent_id=agent_id,
                draft_id=draft_id,
            ),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    return record.draft.contract_bundle.model_dump(mode="json")


@agent_router.patch("/{agent_id}/drafts/{draft_id}/contract")
def update_production_agent_contract(
    agent_id: str,
    draft_id: str,
    body: ProductionAgentContractUpdateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Validate and atomically update one production Draft Contract candidate."""

    require_operator_permission(identity, Permission.AGENT_EDIT)
    try:
        record = cast(
            AgentDraftRecord,
            _application(request).update_contract(
                agent_id=agent_id,
                draft_id=draft_id,
                expected_revision=body.expected_revision,
                agent_yaml=body.agent_yaml,
                policy_yaml=body.policy_yaml,
                tools_yaml=body.tools_yaml,
                actor=_audit_actor(request, identity),
            ),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except (KeyError, ValueError, ProofAgentError) as exc:
        raise HTTPException(status_code=400, detail="agent_contract_invalid") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_contract_update_failed",
        ) from exc
    return record.draft.contract_bundle.model_dump(mode="json")


@agent_router.get("/{agent_id}/drafts/{draft_id}/skills")
def get_production_agent_skill_packs(
    agent_id: str,
    draft_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return a revisioned, trace-safe production Skill Pack projection."""

    require_operator_permission(identity, Permission.AGENT_VIEW)
    try:
        result = _application(request).get_business_flow_skill_packs(
            agent_id=agent_id,
            draft_id=draft_id,
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except (KeyError, ValueError, ProofAgentError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_skill_pack_read_failed",
        ) from exc
    return business_flow_skill_pack_result_payload(result)


@agent_router.get("/{agent_id}/drafts/{draft_id}/knowledge-binding")
def get_production_agent_knowledge_binding(
    agent_id: str,
    draft_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return Draft authoring intent plus a trace-safe live KSS Release catalog."""

    require_operator_permission(identity, Permission.AGENT_VIEW)
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    try:
        result = _application(request).get_knowledge_release_binding_candidate(
            agent_id=agent_id,
            draft_id=draft_id,
        )
    except AgentConfigurationNotFound as exc:
        raise _configuration_exception(exc) from exc
    except AgentConfigurationConflict as exc:
        raise _knowledge_binding_exception(exc) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=503,
            detail="agent_knowledge_catalog_unavailable",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_knowledge_binding_read_failed",
        ) from exc
    return _knowledge_binding_payload(result)


@agent_router.patch("/{agent_id}/drafts/{draft_id}/knowledge-binding")
def update_production_agent_knowledge_binding(
    agent_id: str,
    draft_id: str,
    body: ProductionKnowledgeReleaseBindingUpdateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Save non-executable exact KSS Release authoring intent with revision CAS."""

    require_operator_permission(identity, Permission.AGENT_EDIT)
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    try:
        result = _application(request).update_knowledge_release_binding_candidate(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=body.expected_revision,
            candidate=DraftKnowledgeReleaseBindingCandidate(
                knowledge_space_id=body.knowledge_space_id,
                knowledge_base_id=body.knowledge_base_id,
                knowledge_base_version_id=body.knowledge_base_version_id,
                knowledge_base_release_id=body.knowledge_base_release_id,
            ),
            actor=_audit_actor(request, identity),
        )
    except AgentConfigurationNotFound as exc:
        raise _configuration_exception(exc) from exc
    except AgentConfigurationConflict as exc:
        raise _knowledge_binding_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_knowledge_binding_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=503,
            detail="agent_knowledge_catalog_unavailable",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_knowledge_binding_update_failed",
        ) from exc
    return _knowledge_binding_payload(result)


@agent_router.get("/{agent_id}/drafts/{draft_id}/publication-configuration")
def get_production_agent_publication_configuration(
    agent_id: str,
    draft_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return a server-authoritative Draft authoring snapshot."""

    require_operator_permission(identity, Permission.AGENT_VIEW)
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    try:
        result = _application(request).get_publication_configuration(
            agent_id=agent_id,
            draft_id=draft_id,
        )
    except AgentConfigurationNotFound as exc:
        raise _configuration_exception(exc) from exc
    except AgentConfigurationConflict as exc:
        if exc.code in {
            "agent_publication_configuration_unavailable",
            "agent_knowledge_catalog_unavailable",
        }:
            raise HTTPException(status_code=503, detail=exc.code) from exc
        raise _configuration_exception(exc) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=503,
            detail="agent_publication_configuration_unavailable",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_publication_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_publication_configuration_read_failed",
        ) from exc
    return _publication_configuration_payload(result)


@agent_router.post("/{agent_id}/drafts/{draft_id}/skills/business-flows")
def create_production_agent_skill_pack(
    agent_id: str,
    draft_id: str,
    body: ProductionBusinessFlowSkillPackCreateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Create a complete production Draft Skill Pack in one command."""

    require_operator_permission(identity, Permission.AGENT_EDIT)
    try:
        result = _application(request).create_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=body.expected_revision,
            command=business_flow_skill_pack_create_command(body),
            actor=_audit_actor(request, identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except (KeyError, ValueError, ProofAgentError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_skill_pack_update_failed",
        ) from exc
    return business_flow_skill_pack_result_payload(result)


@agent_router.patch("/{agent_id}/drafts/{draft_id}/skills/business-flows/{pack_id}")
def update_production_agent_skill_pack(
    agent_id: str,
    draft_id: str,
    pack_id: str,
    body: ProductionBusinessFlowSkillPackUpdateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Update one production Draft Skill Pack with revision CAS."""

    require_operator_permission(identity, Permission.AGENT_EDIT)
    try:
        result = _application(request).update_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            pack_id=pack_id,
            expected_revision=body.expected_revision,
            command=business_flow_skill_pack_update_command(body),
            actor=_audit_actor(request, identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except (KeyError, ValueError, ProofAgentError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_skill_pack_update_failed",
        ) from exc
    return business_flow_skill_pack_result_payload(result)


@agent_router.delete("/{agent_id}/drafts/{draft_id}/skills/business-flows/{pack_id}")
def delete_production_agent_skill_pack(
    agent_id: str,
    draft_id: str,
    pack_id: str,
    request: Request,
    expected_revision: int = Query(ge=1),
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Delete one production Draft Skill Pack with revision CAS."""

    require_operator_permission(identity, Permission.AGENT_EDIT)
    try:
        result = _application(request).delete_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            pack_id=pack_id,
            expected_revision=expected_revision,
            actor=_audit_actor(request, identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except (KeyError, ValueError, ProofAgentError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_skill_pack_update_failed",
        ) from exc
    return business_flow_skill_pack_result_payload(result)


@agent_router.patch("/{agent_id}/drafts/{draft_id}/workflow-stages")
def update_production_agent_workflow_stages(
    agent_id: str,
    draft_id: str,
    body: ProductionWorkflowStagesUpdateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Validate and atomically replace production Draft Workflow Stages."""

    require_operator_permission(identity, Permission.AGENT_EDIT)
    try:
        record = cast(
            AgentDraftRecord,
            _application(request).update_workflow_stages(
                agent_id=agent_id,
                draft_id=draft_id,
                expected_revision=body.expected_revision,
                template=body.template,
                template_descriptor_version=body.template_descriptor_version,
                stages=tuple(workflow_stage_config_request(item) for item in body.stages),
                actor=_audit_actor(request, identity),
            ),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_workflow_stage_configuration_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise proof_agent_http_exception(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_workflow_stage_configuration_failed",
        ) from exc
    return record.draft.contract_bundle.model_dump(mode="json")


@agent_router.post("/{agent_id}/drafts/{draft_id}/workflow-stages/{stage_id}/preview")
def preview_production_agent_workflow_stage(
    agent_id: str,
    draft_id: str,
    stage_id: str,
    body: WorkflowStagePreviewRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Render a bounded Workflow Stage preview without executing a Run."""

    require_operator_permission(identity, Permission.AGENT_VALIDATE)
    try:
        result = _application(request).preview_workflow_stage(
            agent_id=agent_id,
            draft_id=draft_id,
            stage_id=stage_id,
            prompt=workflow_stage_prompt_config(body.prompt),
            context_options=body.context,
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_workflow_stage_preview_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise proof_agent_http_exception(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_workflow_stage_preview_failed",
        ) from exc
    return cast(dict[str, Any], result)


@agent_router.get("/{agent_id}/versions")
def list_production_agent_versions(
    agent_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_VIEW)
    try:
        history = _application(request).list_versions(agent_id=agent_id)
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    data = [_version_payload(version) for version in history.versions]
    return {
        "data": data,
        "meta": {
            "total": len(data),
            "active_version_id": history.active_version_id,
        },
    }


def _application(request: Request) -> Any:
    application = getattr(
        request.app.state,
        "agent_configuration_workspace",
        None,
    )
    if application is None:
        raise HTTPException(
            status_code=503,
            detail="production_agent_configuration_unavailable",
        )
    return application


def _formal_publication_command(request: Request) -> Any:
    command = getattr(
        request.app.state,
        "formal_production_agent_publication_command",
        None,
    )
    if command is None:
        raise HTTPException(
            status_code=503,
            detail="formal_publication_command_unavailable",
        )
    return command


def _formal_command_rejection_status(code: str) -> int:
    if code == "formal_publication_idempotency_conflict":
        return 409
    if code == "formal_publication_idempotency_key_invalid":
        return 422
    return 503


def _formal_command_failure_status(code: str) -> int:
    if code.endswith("_not_found"):
        return 404
    if code.endswith("_conflict") or code in {
        "formal_candidate_authoring_blocked",
        "phase_f_authority_denied",
        "online_smoke_failed",
    }:
        return 409
    if "unavailable" in code or code.endswith("_clock_invalid"):
        return 503
    return 422


def _audit_actor(
    request: Request,
    identity: OperatorIdentityContext,
) -> AuditActorFacts:
    session = getattr(request.state, "session_resolution", None)
    session_id = session.projection.session_id if session is not None else "development-session"
    return AuditActorFacts(
        subject=identity.operator_id,
        identity_provider="enterprise-oidc",
        session_id=session_id,
        permissions=tuple(sorted(item.value for item in identity.permissions)),
    )


def _draft_payload(record: AgentDraftRecord) -> dict[str, Any]:
    payload = record.draft.model_dump(
        mode="json",
        exclude={"contract_bundle", "knowledge_release_binding_candidate"},
    )
    payload["revision"] = record.revision
    payload["capabilities"] = {
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
    }
    return payload


def _version_payload(version: Any) -> dict[str, Any]:
    return {
        "agent_id": version.agent_id,
        "version_id": version.version_id,
        "source_draft_id": version.source_draft_id,
        "validation_run_id": version.validation_run_id,
        "display_name": version.display_name,
        "purpose": version.purpose,
        "published_at": version.published_at,
        "published_by": version.published_by,
        "resolved_knowledge_bindings": (
            version.resolved_knowledge_bindings.model_dump(mode="json")
            if version.resolved_knowledge_bindings is not None
            else None
        ),
        "knowledge_release_record": (
            version.knowledge_release_record.model_dump(mode="json")
            if version.knowledge_release_record is not None
            else None
        ),
        "effective_workflow_stage_configuration": (
            version.effective_workflow_stage_configuration.model_dump(mode="json")
            if version.effective_workflow_stage_configuration is not None
            else None
        ),
        "operation_audit": [
            operation.model_dump(mode="json") for operation in version.operation_audit
        ],
    }


def _configuration_exception(
    error: AgentConfigurationConflict | AgentConfigurationNotFound,
) -> HTTPException:
    status_code = 409 if isinstance(error, AgentConfigurationConflict) else 404
    return HTTPException(status_code=status_code, detail=error.code)


def _knowledge_binding_exception(error: AgentConfigurationConflict) -> HTTPException:
    if error.code == "agent_knowledge_catalog_unavailable":
        return HTTPException(status_code=503, detail=error.code)
    if error.code == "agent_knowledge_release_not_queryable":
        return HTTPException(status_code=400, detail=error.code)
    return _configuration_exception(error)


def _knowledge_binding_payload(result: Any) -> dict[str, Any]:
    candidate = result.record.draft.knowledge_release_binding_candidate
    return {
        "revision": result.record.revision,
        "candidate": (None if candidate is None else candidate.model_dump(mode="json")),
        "readiness": result.catalog.readiness.model_dump(mode="json"),
        "releases": [release.model_dump(mode="json") for release in result.catalog.releases],
    }


def _publication_configuration_payload(result: Any) -> dict[str, Any]:
    candidate = result.knowledge_release_candidate
    return {
        "draft_revision": result.draft_revision,
        "authoring_configuration_state": result.authoring_configuration_state,
        "formal_publication_state": result.formal_publication_state,
        "can_publish_from_dashboard": result.can_publish_from_dashboard,
        "workflow": {
            "template": result.workflow_template,
            "template_descriptor_version": (result.workflow_template_descriptor_version),
        },
        "knowledge": {
            "candidate": (None if candidate is None else candidate.model_dump(mode="json")),
            "queryable": result.knowledge_release_queryable,
        },
        "model_roles": [
            {
                "role": item.role,
                "connection_id": item.connection_id,
                "provider": item.provider,
                "model_identifier": item.model_identifier,
                "lifecycle_state": item.lifecycle_state,
                "configuration_state": item.configuration_state,
            }
            for item in result.model_roles
        ],
        "configuration_blockers": [
            {
                "code": item.code,
                "module_id": item.module_id,
                "message": item.message,
            }
            for item in result.configuration_blockers
        ],
        "formal_requirements": {
            "phase_f_evidence": list(result.phase_f_evidence_requirements),
            "online_smoke_required": result.online_smoke_required,
            "activation_mode": result.activation_mode,
        },
    }


router.include_router(workflow_template_router)
router.include_router(agent_router)
