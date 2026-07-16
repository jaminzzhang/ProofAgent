from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    EgressOriginRule,
    EgressPolicyVersion,
    Permission,
    PermissionClaimRule,
    PermissionMappingVersion,
    ProductionSecretHandle,
    RecoveryOidcGroupMapping,
)
from proof_agent.contracts.persistence import PersistenceConflictError
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.ports.security_configuration import (
    SecurityConfigurationRepository,
)
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


router = APIRouter(prefix="/security", tags=["security"])


class PermissionMappingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    rules: tuple[PermissionClaimRule, ...] = ()


class EgressPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    rules: tuple[EgressOriginRule, ...] = ()


class SecretHandleValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: ProductionSecretHandle


@router.get("/permission-mappings")
def list_permission_mappings(
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.PERMISSION_MAPPING_VIEW)
    repository = _repository(request)
    return {
        "active": repository.get_active_permission_mapping(),
        "versions": repository.list_permission_mappings(),
        "recovery_mapping": _recovery_mapping(request),
        "permission_epoch": repository.permission_epoch(),
    }


@router.post("/permission-mappings", status_code=201)
def create_permission_mapping(
    body: PermissionMappingCreateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> PermissionMappingVersion:
    require_operator_permission(identity, Permission.PERMISSION_MAPPING_EDIT)
    recovery = _recovery_mapping(request)
    if any(
        rule.claim_path == recovery.claim_path and rule.claim_value == recovery.group_name
        for rule in body.rules
    ):
        raise HTTPException(status_code=422, detail="recovery_mapping_is_immutable")
    version = PermissionMappingVersion(
        version_id=body.version_id,
        revision=body.expected_revision + 1,
        rules=body.rules,
        created_at=_now(),
        created_by=identity.operator_id,
    )
    try:
        return _repository(request).append_permission_mapping(
            version,
            expected_revision=body.expected_revision,
        )
    except PersistenceConflictError as exc:
        raise HTTPException(status_code=409, detail="permission_mapping_conflict") from exc


@router.post("/permission-mappings/{version_id}/activate")
def activate_permission_mapping(
    version_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> PermissionMappingVersion:
    require_operator_permission(identity, Permission.PERMISSION_MAPPING_EDIT)
    return _repository(request).activate_permission_mapping(
        version_id,
        audit_event=_activation_audit(
            request,
            identity=identity,
            event_type="permission_mapping.activated",
            target_type="permission_mapping_version",
            target_id=version_id,
        ),
    )


@router.get("/egress-policies")
def list_egress_policies(
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.EGRESS_POLICY_VIEW)
    repository = _repository(request)
    return {
        "active": repository.get_active_egress_policy(),
        "versions": repository.list_egress_policies(),
    }


@router.post("/egress-policies", status_code=201)
def create_egress_policy(
    body: EgressPolicyCreateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> EgressPolicyVersion:
    require_operator_permission(identity, Permission.EGRESS_POLICY_EDIT)
    version = EgressPolicyVersion(
        version_id=body.version_id,
        revision=body.expected_revision + 1,
        rules=body.rules,
        created_at=_now(),
        created_by=identity.operator_id,
    )
    try:
        return _repository(request).append_egress_policy(
            version,
            expected_revision=body.expected_revision,
        )
    except PersistenceConflictError as exc:
        raise HTTPException(status_code=409, detail="egress_policy_conflict") from exc


@router.post("/egress-policies/{version_id}/activate")
def activate_egress_policy(
    version_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> EgressPolicyVersion:
    require_operator_permission(identity, Permission.EGRESS_POLICY_EDIT)
    return _repository(request).activate_egress_policy(
        version_id,
        audit_event=_activation_audit(
            request,
            identity=identity,
            event_type="egress_policy.activated",
            target_type="egress_policy_version",
            target_id=version_id,
        ),
    )


@router.post("/secret-handles/validate")
def validate_secret_handle(
    body: SecretHandleValidationRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.SECRET_HANDLE_VIEW)
    require_operator_permission(identity, Permission.SECRET_HANDLE_USE)
    validation = _secret_provider(request).validate(body.handle, checked_at=_now())
    return validation.model_dump(mode="json")


def _repository(request: Request) -> SecurityConfigurationRepository:
    repository = getattr(request.app.state, "security_configuration_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="security_configuration_unavailable")
    return cast(SecurityConfigurationRepository, repository)


def _secret_provider(request: Request) -> SecretProvider:
    provider = getattr(request.app.state, "secret_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="secret_provider_unavailable")
    return cast(SecretProvider, provider)


def _recovery_mapping(request: Request) -> RecoveryOidcGroupMapping:
    mapping = getattr(request.app.state, "recovery_oidc_group_mapping", None)
    if mapping is None:
        raise HTTPException(status_code=503, detail="recovery_mapping_unavailable")
    return cast(RecoveryOidcGroupMapping, mapping)


def _activation_audit(
    request: Request,
    *,
    identity: OperatorIdentityContext,
    event_type: str,
    target_type: str,
    target_id: str,
) -> AuditMetadataRecord:
    session = getattr(request.state, "session_resolution", None)
    session_id = (
        session.projection.session_id if session is not None else "development-session"
    )
    return AuditMetadataRecord(
        audit_id=str(uuid4()),
        category=AuditCategory.SECURITY,
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject=identity.operator_id,
            identity_provider="enterprise-oidc",
            session_id=session_id,
            permissions=tuple(sorted(item.value for item in identity.permissions)),
        ),
        occurred_at=_now(),
        target_type=target_type,
        target_id=target_id,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
