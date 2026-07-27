from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext


class Permission(StrEnum):
    RUN_SUBMIT = "run.submit"
    RUN_VIEW = "run.view"
    RUN_CANCEL = "run.cancel"
    AGENT_VIEW = "agent.view"
    AGENT_EDIT = "agent.edit"
    AGENT_VALIDATE = "agent.validate"
    AGENT_PUBLISH = "agent.publish"
    KNOWLEDGE_SOURCE_VIEW = "knowledge_source.view"
    KNOWLEDGE_SOURCE_EDIT = "knowledge_source.edit"
    KNOWLEDGE_SOURCE_REVIEW = "knowledge_source.review"
    KNOWLEDGE_SOURCE_PUBLISH = "knowledge_source.publish"
    KNOWLEDGE_SOURCE_ARCHIVE = "knowledge_source.archive"
    MODEL_CONNECTION_VIEW = "model_connection.view"
    MODEL_CONNECTION_EDIT = "model_connection.edit"
    MODEL_CONNECTION_VALIDATE = "model_connection.validate"
    MODEL_CONNECTION_ARCHIVE = "model_connection.archive"
    TOOL_SOURCE_VIEW = "tool_source.view"
    TOOL_SOURCE_EDIT = "tool_source.edit"
    TOOL_SOURCE_VALIDATE = "tool_source.validate"
    TOOL_SOURCE_ARCHIVE = "tool_source.archive"
    EVALUATION_VIEW = "evaluation.view"
    EVALUATION_RUN = "evaluation.run"
    EVALUATION_CURATION_REVIEW = "evaluation_curation.review"
    PERMISSION_MAPPING_VIEW = "permission_mapping.view"
    PERMISSION_MAPPING_EDIT = "permission_mapping.edit"
    EGRESS_POLICY_VIEW = "egress_policy.view"
    EGRESS_POLICY_EDIT = "egress_policy.edit"
    SECRET_HANDLE_VIEW = "secret_handle.view"
    SECRET_HANDLE_USE = "secret_handle.use"
    AUDIT_VIEW = "audit.view"
    AUDIT_EXPORT = "audit.export"


class PermissionClaimRule(StrictFrozenModel):
    """One exact trusted OIDC claim value to tenant-global permission grant."""

    claim_path: str = Field(min_length=1)
    claim_value: str = Field(min_length=1)
    permissions: tuple[Permission, ...] = Field(default_factory=tuple)
    institution_authorization: InstitutionAuthorizationContext | None = None

    @model_validator(mode="after")
    def require_unique_permissions(self) -> "PermissionClaimRule":
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("permission rule contains duplicate permissions")
        return self


class PermissionMappingVersion(StrictFrozenModel):
    version_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    rules: tuple[PermissionClaimRule, ...] = Field(default_factory=tuple)
    created_at: str
    created_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_claim_rules(self) -> "PermissionMappingVersion":
        identities = [(rule.claim_path, rule.claim_value) for rule in self.rules]
        if len(identities) != len(set(identities)):
            raise ValueError("permission mapping contains duplicate claim rules")
        return self


class RecoveryOidcGroupMapping(StrictFrozenModel):
    """Deployment-owned immutable recovery claim and minimum permission set."""

    claim_path: str = Field(min_length=1)
    group_name: str = Field(min_length=1)
    permissions: tuple[Permission, ...]

    @model_validator(mode="after")
    def require_recovery_minimum(self) -> "RecoveryOidcGroupMapping":
        required = {
            Permission.PERMISSION_MAPPING_VIEW,
            Permission.PERMISSION_MAPPING_EDIT,
            Permission.AUDIT_VIEW,
        }
        if not required.issubset(self.permissions):
            raise ValueError("Recovery OIDC Group mapping cannot weaken minimum permissions")
        return self


class AuthorizationOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class AuthorizationDecision(StrictFrozenModel):
    outcome: AuthorizationOutcome
    permission: Permission
    subject: str = Field(min_length=1)
    mapping_version_id: str = Field(min_length=1)
    matched_claims: tuple[str, ...] = Field(default_factory=tuple)
    reason_code: str = Field(min_length=1)
