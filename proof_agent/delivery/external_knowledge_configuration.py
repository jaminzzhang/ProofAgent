"""External Knowledge authoring over the existing revisioned Agent Contract."""

from typing import Any

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Request

from proof_agent.contracts import AuditActorFacts, Permission
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationConflict,
    AgentConfigurationNotFound,
)
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


router = APIRouter(prefix="/config/agents", tags=["external-knowledge"])


def _workspace(request: Request) -> Any:
    workspace = getattr(request.app.state, "agent_configuration_workspace", None)
    if workspace is None:
        raise HTTPException(503, "agent_configuration_unavailable")
    return workspace


def _bindings(raw: Any) -> tuple[ExternalKnowledgeBinding, ...]:
    if not isinstance(raw, list) or len(raw) > 5:
        raise ValueError("invalid bindings")
    bindings = tuple(ExternalKnowledgeBinding.model_validate(item) for item in raw)
    if len({item.binding_id for item in bindings}) != len(bindings):
        raise ValueError("duplicate bindings")
    return bindings


def _projection(record: Any) -> dict[str, Any]:
    raw = yaml.safe_load(record.draft.contract_bundle.agent_yaml)
    bindings = _bindings(raw.get("knowledge_bindings", []))
    return {
        "revision": record.revision,
        "bindings": [item.model_dump(mode="json") for item in bindings],
    }


@router.get("/{agent_id}/drafts/{draft_id}/external-knowledge")
def read_external_knowledge(
    agent_id: str,
    draft_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_VIEW)
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    try:
        return _projection(_workspace(request).get_draft(agent_id=agent_id, draft_id=draft_id))
    except AgentConfigurationNotFound:
        raise HTTPException(404, "agent_draft_not_found") from None
    except (ValueError, TypeError, AttributeError, yaml.YAMLError, RecursionError):
        raise HTTPException(400, "external_knowledge_configuration_invalid") from None


@router.patch("/{agent_id}/drafts/{draft_id}/external-knowledge")
async def save_external_knowledge(
    agent_id: str,
    draft_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_EDIT)
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    try:
        # Parse behind a sanitized boundary: validation responses must not echo pasted keys.
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"expected_revision", "bindings"}:
            raise ValueError("invalid fields")
        revision = body["expected_revision"]
        if type(revision) is not int or revision < 1:
            raise ValueError("invalid revision")
        bindings = _bindings(body["bindings"])
        if request.app.state.proof_agent_mode == "production" and any(
            item.credential_ref.protocol_id == "local-environment-v1"
            or not item.credential_ref.version_id
            for item in bindings
        ):
            raise ValueError("production credentials must be versioned server handles")
        workspace = _workspace(request)
        record = workspace.get_draft(agent_id=agent_id, draft_id=draft_id)
        raw = yaml.safe_load(record.draft.contract_bundle.agent_yaml)
        raw["knowledge_bindings"] = [item.model_dump(mode="json") for item in bindings]
        session = getattr(request.state, "session_resolution", None)
        saved = workspace.update_contract(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=revision,
            agent_yaml=yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
            policy_yaml=None,
            tools_yaml=None,
            actor=AuditActorFacts(
                subject=identity.operator_id,
                identity_provider="enterprise-oidc" if session else "local-development",
                session_id=session.projection.session_id if session else "development-session",
                permissions=tuple(sorted(item.value for item in identity.permissions)),
            ),
        )
        return _projection(saved)
    except AgentConfigurationConflict:
        raise HTTPException(409, "agent_draft_revision_conflict") from None
    except AgentConfigurationNotFound:
        raise HTTPException(404, "agent_draft_not_found") from None
    except (ValueError, TypeError, AttributeError, yaml.YAMLError, RecursionError):
        raise HTTPException(400, "external_knowledge_configuration_invalid") from None
