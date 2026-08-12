"""Production Agent Draft configuration API."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from proof_agent.contracts import AgentDraftRecord, AuditActorFacts, Permission
from proof_agent.control.production_agent_configuration import (
    ProductionAgentConfigurationConflict,
    ProductionAgentConfigurationNotFound,
)
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


router = APIRouter(prefix="/config/agents", tags=["production-agent-configuration"])

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


@router.get("")
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
                    inventory.can_create
                    and Permission.AGENT_EDIT in identity.permissions
                ),
                "can_import_manifest": False,
                "canonical_template": _CANONICAL_TEMPLATE,
            },
        },
    }


@router.post("")
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
    except (ProductionAgentConfigurationConflict, ProductionAgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.status_code = 200 if result.replayed else 201
    return _draft_payload(result.record)


@router.get("/{agent_id}/drafts/{draft_id}")
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
    except (ProductionAgentConfigurationConflict, ProductionAgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    return _draft_payload(record)


@router.patch("/{agent_id}/drafts/{draft_id}")
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
    except (ProductionAgentConfigurationConflict, ProductionAgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _draft_payload(record)


@router.get("/{agent_id}/drafts/{draft_id}/contract")
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
    except (ProductionAgentConfigurationConflict, ProductionAgentConfigurationNotFound) as exc:
        raise _configuration_exception(exc) from exc
    return record.draft.contract_bundle.model_dump(mode="json")


@router.get("/{agent_id}/versions")
def list_production_agent_versions(
    agent_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_VIEW)
    try:
        history = _application(request).list_versions(agent_id=agent_id)
    except (ProductionAgentConfigurationConflict, ProductionAgentConfigurationNotFound) as exc:
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
        "production_agent_configuration_application",
        None,
    )
    if application is None:
        raise HTTPException(
            status_code=503,
            detail="production_agent_configuration_unavailable",
        )
    return application


def _audit_actor(
    request: Request,
    identity: OperatorIdentityContext,
) -> AuditActorFacts:
    session = getattr(request.state, "session_resolution", None)
    session_id = (
        session.projection.session_id
        if session is not None
        else "development-session"
    )
    return AuditActorFacts(
        subject=identity.operator_id,
        identity_provider="enterprise-oidc",
        session_id=session_id,
        permissions=tuple(sorted(item.value for item in identity.permissions)),
    )


def _draft_payload(record: AgentDraftRecord) -> dict[str, Any]:
    payload = record.draft.model_dump(mode="json", exclude={"contract_bundle"})
    payload["revision"] = record.revision
    payload["capabilities"] = {
        "mode": "production",
        "editable_modules": ["general"],
        "lifecycle_tabs": ["versions", "contract", "monitor"],
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
            operation.model_dump(mode="json")
            for operation in version.operation_audit
        ],
    }


def _configuration_exception(
    error: ProductionAgentConfigurationConflict | ProductionAgentConfigurationNotFound,
) -> HTTPException:
    status_code = (
        409 if isinstance(error, ProductionAgentConfigurationConflict) else 404
    )
    return HTTPException(status_code=status_code, detail=error.code)
