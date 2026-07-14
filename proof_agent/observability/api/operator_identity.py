"""Operator identity and permission helpers for internal API commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from fastapi import HTTPException

from proof_agent.contracts import InstitutionAuthorizationContext


class OperatorPermission(StrEnum):
    """Named permissions for internal operator-facing command surfaces."""

    APPROVAL_RESOLVE = "approval.resolve"
    RUN_VIEW = "run.view"
    AGENT_VIEW = "agent.view"
    AGENT_EDIT = "agent.edit"
    AGENT_VALIDATE = "agent.validate"
    AGENT_PUBLISH = "agent.publish"
    KNOWLEDGE_SOURCE_VIEW = "knowledge_source.view"
    KNOWLEDGE_SOURCE_EDIT = "knowledge_source.edit"
    KNOWLEDGE_SOURCE_PUBLISH = "knowledge_source.publish"
    KNOWLEDGE_SOURCE_ARCHIVE = "knowledge_source.archive"
    MODEL_CONNECTION_VIEW = "model_connection.view"
    MODEL_CONNECTION_EDIT = "model_connection.edit"
    MODEL_CONNECTION_VALIDATE = "model_connection.validate"
    MODEL_CONNECTION_ARCHIVE = "model_connection.archive"
    TOOL_SOURCE_VIEW = "tool_source.view"
    TOOL_SOURCE_EDIT = "tool_source.edit"
    TOOL_SOURCE_ARCHIVE = "tool_source.archive"
    EVALUATION_CURATION_REVIEW = "evaluation_curation.review"


@dataclass(frozen=True)
class OperatorIdentityContext:
    """Internal operator identity and permissions admitted at command boundaries."""

    operator_id: str
    display_name: str
    permissions: frozenset[OperatorPermission]
    institution_authorization: InstitutionAuthorizationContext = field(
        default_factory=InstitutionAuthorizationContext
    )


class LocalOperatorIdentityProvider:
    """Deterministic local-mode identity provider for single-user development."""

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id="local-user",
            display_name="Local Operator",
            permissions=frozenset(OperatorPermission),
        )


def require_operator_permission(
    identity: OperatorIdentityContext,
    permission: OperatorPermission,
) -> None:
    """Raise when an operator identity lacks a required permission."""

    if permission not in identity.permissions:
        raise HTTPException(
            status_code=403,
            detail=f"Operator lacks required permission: {permission.value}",
        )
