"""External Knowledge authoring over the existing revisioned Agent Contract."""

from typing import Any
from datetime import UTC, datetime
import os

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from proof_agent.contracts import AuditActorFacts, Permission
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.contracts.knowledge_connection import (
    KnowledgeConnectionAuthorization,
    binding_digest,
)
from proof_agent.capabilities.egress.knowledge_connections import (
    binding_origin,
    verify_authorization_dns,
)
from proof_agent.bootstrap.external_knowledge import (
    development_knowledge_dependencies,
    ExternalKnowledgeRuntime,
)
from proof_agent.control.security.egress import EgressDeniedError
from proof_agent.errors import ProofAgentError
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


def _managed(request: Request) -> bool:
    return (
        request.app.state.proof_agent_mode != "development"
        or getattr(request.app.state, "guarded_http_client", None) is not None
        or bool(os.environ.get("PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY"))
    )


def _projection(record: Any, request: Request, identity: OperatorIdentityContext) -> dict[str, Any]:
    raw = yaml.safe_load(record.draft.contract_bundle.agent_yaml)
    bindings = _bindings(raw.get("knowledge_bindings", []))
    return {
        "revision": record.revision,
        "bindings": [item.model_dump(mode="json") for item in bindings],
        "can_authorize": not _managed(request)
        and Permission.EGRESS_POLICY_EDIT in identity.permissions
        and Permission.AGENT_EDIT in identity.permissions,
        "can_check": Permission.SECRET_HANDLE_USE in identity.permissions,
        "authorization_mode": "managed" if _managed(request) else "development",
        "connections": [
            {
                "binding_id": item.binding_id,
                "origin": binding_origin(item).value,
                "address_mode": next(
                    (
                        grant.address_mode
                        for grant in record.draft.knowledge_connection_authorizations
                        if grant.binding_sha256 == binding_digest(item)
                    ),
                    None,
                ),
                "authorized": any(
                    grant.binding_sha256 == binding_digest(item)
                    for grant in record.draft.knowledge_connection_authorizations
                ),
            }
            for item in bindings
        ],
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
        return _projection(
            _workspace(request).get_draft(agent_id=agent_id, draft_id=draft_id), request, identity
        )
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
        if (
            not isinstance(body, dict)
            or not {"expected_revision", "bindings"} <= set(body)
            or set(body) - {"expected_revision", "bindings", "authorize"}
        ):
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
        if record.revision != revision:
            raise HTTPException(409, "agent_draft_revision_conflict")
        grants = None
        if "authorize" in body:
            require_operator_permission(identity, Permission.EGRESS_POLICY_EDIT)
            if _managed(request):
                raise HTTPException(409, "external_knowledge_policy_managed_by_server")
            option = body["authorize"]
            if (
                not isinstance(option, dict)
                or set(option) != {"allow_local_proxy"}
                or type(option["allow_local_proxy"]) is not bool
            ):
                raise ValueError("invalid authorization")
            grants = tuple(
                KnowledgeConnectionAuthorization(
                    binding_sha256=binding_digest(item),
                    origin=binding_origin(item),
                    address_mode="local_proxy_dns" if option["allow_local_proxy"] else "public_dns",
                    authorized_by=identity.operator_id,
                    authorized_at=datetime.now(UTC).isoformat(),
                )
                for item in bindings
            )
            for grant in grants:
                await run_in_threadpool(verify_authorization_dns, grant)
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
            knowledge_connection_authorizations=grants,
        )
        return _projection(saved, request, identity)
    except EgressDeniedError:
        raise HTTPException(400, "external_knowledge_dns_not_allowed") from None
    except AgentConfigurationConflict:
        raise HTTPException(409, "agent_draft_revision_conflict") from None
    except AgentConfigurationNotFound:
        raise HTTPException(404, "agent_draft_not_found") from None
    except (ValueError, TypeError, AttributeError, yaml.YAMLError, RecursionError):
        raise HTTPException(400, "external_knowledge_configuration_invalid") from None


@router.post("/{agent_id}/drafts/{draft_id}/external-knowledge/check")
def check_external_knowledge(
    agent_id: str,
    draft_id: str,
    body: dict[str, Any],
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, Permission.AGENT_VIEW)
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    require_operator_permission(identity, Permission.SECRET_HANDLE_USE)
    if set(body) != {"expected_revision"} or type(body["expected_revision"]) is not int:
        raise HTTPException(400, "external_knowledge_configuration_invalid")
    workspace = _workspace(request)
    try:
        record = workspace.get_draft(agent_id=agent_id, draft_id=draft_id)
    except AgentConfigurationNotFound:
        raise HTTPException(404, "agent_draft_not_found") from None
    if record.revision != body["expected_revision"]:
        raise HTTPException(409, "agent_draft_revision_conflict")
    try:
        bindings = _bindings(
            yaml.safe_load(record.draft.contract_bundle.agent_yaml).get("knowledge_bindings", [])
        )
    except (ValueError, TypeError, AttributeError, yaml.YAMLError):
        raise HTTPException(400, "external_knowledge_configuration_invalid") from None
    results = []
    for binding in bindings:
        status = _check_connection(binding, record, request)
        results.append({"binding_id": binding.binding_id, "status": status})
    # Never attach stale diagnostics to a newer draft after network I/O.
    if workspace.get_draft(agent_id=agent_id, draft_id=draft_id).revision != record.revision:
        raise HTTPException(409, "agent_draft_revision_conflict")
    return {"revision": record.revision, "connections": results}


def _check_connection(binding: ExternalKnowledgeBinding, record: Any, request: Request) -> str:
    if not _managed(request) and not any(
        grant.binding_sha256 == binding_digest(binding)
        for grant in record.draft.knowledge_connection_authorizations
    ):
        return "authorization_required"
    try:
        http, secrets = development_knowledge_dependencies(
            getattr(request.app.state, "guarded_http_client", None),
            getattr(request.app.state, "secret_provider", None),
            configuration_store=getattr(request.app.state, "agent_configuration_store", None),
            agent_id=record.draft.agent_id,
            bindings=(binding,),
        )
        if http is None or secrets is None:
            return "server_configuration_required"
        validation = secrets.validate(
            binding.credential_ref, checked_at=datetime.now(UTC).isoformat()
        )
        if (
            not validation.resolvable
            or validation.provider_version_id != binding.credential_ref.version_id
        ):
            return "credential_unavailable"
        ExternalKnowledgeRuntime(
            (binding,), http_client=http, secret_provider=secrets, timeout_seconds=5
        ).query(binding.binding_id, "connection check")
        return "ready"
    except ProofAgentError as exc:
        if "credential_unavailable" in exc.message:
            return "credential_unavailable"
        if any(
            reason in exc.message
            for reason in (
                "unauthorized",
                "forbidden",
                "namespace_unavailable",
                "dataset_unavailable",
            )
        ):
            return "provider_rejected"
        return "connection_failed"
    except Exception:
        return "connection_failed"
