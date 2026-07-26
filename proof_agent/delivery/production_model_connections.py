"""Production Shared Model Connection configuration API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import re
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    ModelConnectionSmokeTestRecord,
    ModelConnectionValidationRecord,
    Permission,
    ProductionSecretHandle,
    SecretPurpose,
    SharedModelConnection,
    SharedModelConnectionDeletionEligibility,
    SharedModelConnectionLifecycleState,
    SharedModelConnectionReferenceSummary,
)
from proof_agent.contracts.persistence import PersistenceConflictError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


router = APIRouter(prefix="/config/model-connections", tags=["model-connections"])

_SUPPORTED_PROVIDERS = frozenset({"deepseek", "openai", "openai_compatible"})
_HIGH_IMPACT_FIELDS = frozenset(
    {"provider", "model_identifier", "base_url", "credential_ref", "timeout_seconds"}
)
_NON_NULL_UPDATE_FIELDS = frozenset(
    {"display_name", "description", "tags", "provider", "model_identifier"}
)


class ProductionModelConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: str | None = None
    display_name: str = Field(min_length=1)
    description: str = ""
    tags: tuple[str, ...] = ()
    provider: str = Field(min_length=1)
    model_identifier: str = Field(min_length=1)
    base_url: str | None = None
    credential_ref: ProductionSecretHandle
    timeout_seconds: float | None = Field(default=None, gt=0)


class ProductionModelConnectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    tags: tuple[str, ...] | None = None
    provider: str | None = Field(default=None, min_length=1)
    model_identifier: str | None = Field(default=None, min_length=1)
    base_url: str | None = None
    credential_ref: ProductionSecretHandle | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    confirm_impact: bool = False


class ProductionModelConnectionLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1)


class ProductionModelConnectionValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get("")
def list_model_connections(
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List PostgreSQL-authoritative production model connections."""

    require_operator_permission(identity, Permission.MODEL_CONNECTION_VIEW)
    with _configuration_uow(request) as uow:
        connections = uow.models.list_model_connections()
        data = [
            _connection_payload(
                connection,
                revision=_current_revision(uow.models, connection.connection_id),
                reference_summary=_reference_summary(
                    uow.models, connection.connection_id
                ),
                audit=uow.audit,
            )
            for connection in connections
        ]
    return {
        "data": data,
        "meta": {
            "total": len(data),
            "credential_reference_type": "secret_handle",
        },
    }


@router.post("", status_code=201)
def create_model_connection(
    body: ProductionModelConnectionCreateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Create one PostgreSQL-authoritative production model connection."""

    require_operator_permission(identity, Permission.MODEL_CONNECTION_EDIT)
    _require_provider(body.provider)
    _require_model_secret_handle(request, body.credential_ref)
    now = _now()
    connection = SharedModelConnection(
        connection_id=_connection_id(body.connection_id, body.display_name),
        display_name=body.display_name.strip(),
        description=body.description,
        tags=body.tags,
        provider=body.provider,
        model_identifier=body.model_identifier,
        base_url=body.base_url,
        credential_ref=body.credential_ref,
        timeout_seconds=body.timeout_seconds,
        lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    try:
        with _configuration_uow(request) as uow:
            version = uow.models.save_connection(connection, expected_revision=0)
            uow.audit.append(
                _audit_event(
                    request,
                    identity=identity,
                    event_type="model_connection.created",
                    connection=connection,
                    metadata={
                        "provider": connection.provider,
                        "model_identifier": connection.model_identifier,
                        "credential_ref": body.credential_ref.model_dump(mode="json"),
                    },
                )
            )
            uow.commit()
    except PersistenceConflictError as exc:
        raise HTTPException(status_code=409, detail="model_connection_conflict") from exc
    return _connection_payload(connection, revision=version.revision)


@router.get("/{connection_id}")
def get_model_connection(
    connection_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one production model connection."""

    require_operator_permission(identity, Permission.MODEL_CONNECTION_VIEW)
    with _configuration_uow(request) as uow:
        connection = _require_connection(uow.models, connection_id)
        revision = _current_revision(uow.models, connection_id)
        reference_summary = _reference_summary(uow.models, connection_id)
        return _connection_payload(
            connection,
            revision=revision,
            reference_summary=reference_summary,
            audit=uow.audit,
        )


@router.patch("/{connection_id}")
def update_model_connection(
    connection_id: str,
    body: ProductionModelConnectionUpdateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Conditionally update one production model connection."""

    require_operator_permission(identity, Permission.MODEL_CONNECTION_EDIT)
    if body.provider is not None:
        _require_provider(body.provider)
    if "credential_ref" in body.model_fields_set:
        if body.credential_ref is None:
            raise HTTPException(status_code=422, detail="model_credential_handle_required")
        _require_model_secret_handle(request, body.credential_ref)
    with _configuration_uow(request) as uow:
        existing = _require_connection(uow.models, connection_id)
        changed_fields = _changed_update_fields(body)
        null_fields = sorted(
            field
            for field in changed_fields
            if field in _NON_NULL_UPDATE_FIELDS and getattr(body, field) is None
        )
        if null_fields:
            raise HTTPException(
                status_code=422,
                detail={"non_nullable_fields": null_fields},
            )
        current_revision = _current_revision(uow.models, connection_id)
        if current_revision != body.expected_revision:
            raise HTTPException(status_code=409, detail="model_connection_conflict")
        reference_summary = _reference_summary(uow.models, connection_id)
        if not changed_fields:
            return _connection_payload(
                existing,
                revision=current_revision,
                reference_summary=reference_summary,
            )
        high_impact_fields = sorted(_HIGH_IMPACT_FIELDS.intersection(changed_fields))
        reference_count = (
            reference_summary.draft_agent_reference_count
            + reference_summary.published_agent_version_reference_count
            + reference_summary.knowledge_source_reference_count
        )
        if high_impact_fields and reference_count and not body.confirm_impact:
            raise HTTPException(
                status_code=409,
                detail={
                    "requires_impact_review": True,
                    "changed_fields": high_impact_fields,
                    "reference_summary": reference_summary.model_dump(mode="json"),
                },
            )
        values = {
            field: getattr(body, field)
            for field in changed_fields
        }
        values["updated_at"] = _now()
        updated = existing.model_copy(update=values)
        try:
            version = uow.models.save_connection(
                updated,
                expected_revision=body.expected_revision,
            )
            uow.audit.append(
                _audit_event(
                    request,
                    identity=identity,
                    event_type="model_connection.updated",
                    connection=updated,
                    metadata={
                        "changed_fields": sorted(changed_fields),
                        "impact_confirmed": bool(high_impact_fields and reference_count),
                        "reference_summary": reference_summary.model_dump(mode="json"),
                    },
                )
            )
            uow.commit()
        except PersistenceConflictError as exc:
            raise HTTPException(status_code=409, detail="model_connection_conflict") from exc
    return _connection_payload(
        updated,
        revision=version.revision,
        reference_summary=reference_summary,
    )


@router.post("/{connection_id}/archive")
def archive_model_connection(
    connection_id: str,
    body: ProductionModelConnectionLifecycleRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Archive one production model connection without deleting retained state."""

    require_operator_permission(identity, Permission.MODEL_CONNECTION_ARCHIVE)
    return _transition_lifecycle(
        request,
        identity=identity,
        connection_id=connection_id,
        expected_revision=body.expected_revision,
        lifecycle_state=SharedModelConnectionLifecycleState.ARCHIVED,
        event_type="model_connection.archived",
        reason=body.reason,
    )


@router.post("/{connection_id}/restore")
def restore_model_connection(
    connection_id: str,
    body: ProductionModelConnectionLifecycleRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Restore one archived production model connection."""

    require_operator_permission(identity, Permission.MODEL_CONNECTION_ARCHIVE)
    return _transition_lifecycle(
        request,
        identity=identity,
        connection_id=connection_id,
        expected_revision=body.expected_revision,
        lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
        event_type="model_connection.restored",
        reason=body.reason,
    )


@router.post("/{connection_id}/validate")
def validate_model_connection(
    connection_id: str,
    body: ProductionModelConnectionValidationRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Validate the production Secret Handle without exposing resolved material."""

    del body
    require_operator_permission(identity, Permission.MODEL_CONNECTION_VALIDATE)
    require_operator_permission(identity, Permission.SECRET_HANDLE_VIEW)
    require_operator_permission(identity, Permission.SECRET_HANDLE_USE)
    with _configuration_uow(request) as uow:
        connection = _require_connection(uow.models, connection_id)
        handle = _production_handle(connection)
        validation = _secret_provider(request).validate(handle, checked_at=_now())
        record = ModelConnectionValidationRecord(
            validation_id=f"modelvalidation_{uuid4().hex[:8]}",
            connection_id=connection.connection_id,
            status="passed" if validation.resolvable else "failed",
            created_at=validation.checked_at,
            created_by=identity.operator_id,
            provider=connection.provider,
            model_identifier=connection.model_identifier,
            credential_ref=handle,
            error_code=None if validation.resolvable else validation.reason_code,
            message=(
                "Model connection Secret Handle validation passed."
                if validation.resolvable
                else "Model connection Secret Handle is not resolvable."
            ),
        )
        uow.audit.append(
            _audit_event(
                request,
                identity=identity,
                event_type="model_connection.validated",
                connection=connection,
                metadata={"record": record.model_dump(mode="json")},
            )
        )
        uow.commit()
    return record.model_dump(mode="json")


@router.post("/{connection_id}/smoke-test")
def smoke_test_model_connection(
    connection_id: str,
    body: ProductionModelConnectionValidationRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Record a bounded skipped probe until remote smoke execution is enabled."""

    del body
    require_operator_permission(identity, Permission.MODEL_CONNECTION_VALIDATE)
    require_operator_permission(identity, Permission.SECRET_HANDLE_VIEW)
    require_operator_permission(identity, Permission.SECRET_HANDLE_USE)
    with _configuration_uow(request) as uow:
        connection = _require_connection(uow.models, connection_id)
        handle = _production_handle(connection)
        validation = _secret_provider(request).validate(handle, checked_at=_now())
        record = ModelConnectionSmokeTestRecord(
            smoke_test_id=f"modelsmoke_{uuid4().hex[:8]}",
            connection_id=connection.connection_id,
            status="skipped" if validation.resolvable else "failed",
            created_at=validation.checked_at,
            created_by=identity.operator_id,
            provider=connection.provider,
            model_identifier=connection.model_identifier,
            credential_ref=handle,
            request_sent=False,
            error_code=None if validation.resolvable else validation.reason_code,
            message=(
                "Remote smoke test is not enabled; Secret Handle validation passed."
                if validation.resolvable
                else "Remote smoke test was not sent because the Secret Handle failed validation."
            ),
        )
        uow.audit.append(
            _audit_event(
                request,
                identity=identity,
                event_type="model_connection.smoke_tested",
                connection=connection,
                metadata={"record": record.model_dump(mode="json")},
            )
        )
        uow.commit()
    return record.model_dump(mode="json")


@router.get("/{connection_id}/references")
def get_model_connection_references(
    connection_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return exact retained configuration reference counts."""

    require_operator_permission(identity, Permission.MODEL_CONNECTION_VIEW)
    with _configuration_uow(request) as uow:
        _require_connection(uow.models, connection_id)
        summary = _reference_summary(uow.models, connection_id)
    return summary.model_dump(mode="json")


@router.get("/{connection_id}/deletion-eligibility")
def get_model_connection_deletion_eligibility(
    connection_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Explain why retained production state cannot be physically deleted."""

    require_operator_permission(identity, Permission.MODEL_CONNECTION_VIEW)
    with _configuration_uow(request) as uow:
        connection = _require_connection(uow.models, connection_id)
        summary = _reference_summary(uow.models, connection_id)
    blockers: list[str] = []
    if connection.lifecycle_state is not SharedModelConnectionLifecycleState.ARCHIVED:
        blockers.append("lifecycle_state_active")
    if (
        summary.draft_agent_reference_count
        + summary.published_agent_version_reference_count
        + summary.knowledge_source_reference_count
        > 0
    ):
        blockers.append("configuration_references")
    if summary.in_flight_operation_count > 0:
        blockers.append("in_flight_operations")
    if summary.audit_retention_blocked:
        blockers.append("audit_retention")
    eligibility = SharedModelConnectionDeletionEligibility(
        connection_id=connection_id,
        eligible=not blockers,
        lifecycle_state=connection.lifecycle_state,
        reference_summary=summary,
        blockers=tuple(blockers),
    )
    return eligibility.model_dump(mode="json")


def _configuration_uow(request: Request) -> Any:
    factory = getattr(request.app.state, "production_configuration_uow_factory", None)
    if not callable(factory):
        raise HTTPException(status_code=503, detail="configuration_uow_unavailable")
    return factory()


def _secret_provider(request: Request) -> Any:
    provider = getattr(request.app.state, "secret_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="secret_provider_unavailable")
    return provider


def _require_provider(provider: str) -> None:
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=422, detail="unsupported_model_provider")


def _changed_update_fields(
    body: ProductionModelConnectionUpdateRequest,
) -> tuple[str, ...]:
    mutable_fields = (
        "display_name",
        "description",
        "tags",
        "provider",
        "model_identifier",
        "base_url",
        "credential_ref",
        "timeout_seconds",
    )
    return tuple(field for field in mutable_fields if field in body.model_fields_set)


def _require_connection(models: Any, connection_id: str) -> SharedModelConnection:
    connection = models.get_model_connection(connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="model_connection_not_found")
    return cast(SharedModelConnection, connection)


def _current_revision(models: Any, connection_id: str) -> int:
    version = models.resolve_version(connection_id)
    if version is None:
        raise HTTPException(status_code=503, detail="model_connection_version_unavailable")
    return cast(int, version.revision)


def _reference_summary(
    models: Any,
    connection_id: str,
) -> SharedModelConnectionReferenceSummary:
    method = getattr(models, "get_model_connection_reference_summary", None)
    if callable(method):
        return cast(SharedModelConnectionReferenceSummary, method(connection_id))
    return SharedModelConnectionReferenceSummary(
        connection_id=connection_id,
        draft_agent_reference_count=0,
        published_agent_version_reference_count=0,
        knowledge_source_reference_count=0,
        audit_retention_blocked=True,
    )


def _require_model_secret_handle(
    request: Request,
    handle: ProductionSecretHandle,
) -> None:
    if handle.purpose is not SecretPurpose.MODEL_CREDENTIAL:
        raise HTTPException(status_code=422, detail="model_credential_handle_required")
    provider = _secret_provider(request)
    if handle.protocol_id != getattr(provider, "protocol_id", None):
        raise HTTPException(status_code=422, detail="secret_provider_protocol_mismatch")


def _production_handle(connection: SharedModelConnection) -> ProductionSecretHandle:
    handle = connection.credential_ref
    if not isinstance(handle, ProductionSecretHandle):
        raise HTTPException(status_code=422, detail="model_credential_handle_required")
    return handle


def _transition_lifecycle(
    request: Request,
    *,
    identity: OperatorIdentityContext,
    connection_id: str,
    expected_revision: int,
    lifecycle_state: SharedModelConnectionLifecycleState,
    event_type: str,
    reason: str,
) -> dict[str, Any]:
    with _configuration_uow(request) as uow:
        existing = _require_connection(uow.models, connection_id)
        if existing.lifecycle_state is lifecycle_state:
            raise HTTPException(status_code=409, detail="model_connection_lifecycle_conflict")
        updated = existing.model_copy(
            update={"lifecycle_state": lifecycle_state, "updated_at": _now()}
        )
        try:
            version = uow.models.save_connection(
                updated,
                expected_revision=expected_revision,
            )
            uow.audit.append(
                _audit_event(
                    request,
                    identity=identity,
                    event_type=event_type,
                    connection=updated,
                    metadata={"reason": reason.strip()},
                )
            )
            uow.commit()
        except PersistenceConflictError as exc:
            raise HTTPException(status_code=409, detail="model_connection_conflict") from exc
    return _connection_payload(updated, revision=version.revision)


def _connection_id(explicit: str | None, display_name: str) -> str:
    source = explicit if explicit is not None else display_name
    normalized = re.sub(r"[^a-z0-9_]+", "_", source.strip().lower().replace("-", "_"))
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise HTTPException(status_code=422, detail="model_connection_id_invalid")
    if not normalized.startswith("model_"):
        normalized = f"model_{normalized}"
    return normalized


def _connection_payload(
    connection: SharedModelConnection,
    *,
    revision: int,
    reference_summary: SharedModelConnectionReferenceSummary | None = None,
    audit: Any | None = None,
) -> dict[str, Any]:
    summary = reference_summary or SharedModelConnectionReferenceSummary(
        connection_id=connection.connection_id,
        draft_agent_reference_count=0,
        published_agent_version_reference_count=0,
        knowledge_source_reference_count=0,
        audit_retention_blocked=True,
    )
    last_validation, last_smoke_test = _latest_check_records(
        audit,
        connection_id=connection.connection_id,
    )
    payload = connection.model_dump(mode="json")
    payload.update(
        {
            "revision": revision,
            "reference_summary": summary.model_dump(mode="json"),
            "last_validation": (
                None if last_validation is None else last_validation.model_dump(mode="json")
            ),
            "last_smoke_test": (
                None if last_smoke_test is None else last_smoke_test.model_dump(mode="json")
            ),
        }
    )
    return payload


def _latest_check_records(
    audit: Any | None,
    *,
    connection_id: str,
) -> tuple[ModelConnectionValidationRecord | None, ModelConnectionSmokeTestRecord | None]:
    method = getattr(audit, "list_for_target", None)
    if not callable(method):
        return None, None
    events = method(target_type="model_connection", target_id=connection_id)
    validation: ModelConnectionValidationRecord | None = None
    smoke_test: ModelConnectionSmokeTestRecord | None = None
    for event in reversed(events):
        metadata = getattr(event, "metadata", None)
        record = metadata.get("record") if isinstance(metadata, Mapping) else None
        if not isinstance(record, Mapping):
            continue
        try:
            if validation is None and event.event_type == "model_connection.validated":
                validation = ModelConnectionValidationRecord.model_validate(record)
            if smoke_test is None and event.event_type == "model_connection.smoke_tested":
                smoke_test = ModelConnectionSmokeTestRecord.model_validate(record)
        except (TypeError, ValueError):
            continue
        if validation is not None and smoke_test is not None:
            break
    return validation, smoke_test


def _audit_event(
    request: Request,
    *,
    identity: OperatorIdentityContext,
    event_type: str,
    connection: SharedModelConnection,
    metadata: dict[str, Any],
) -> AuditMetadataRecord:
    session = getattr(request.state, "session_resolution", None)
    session_id = (
        session.projection.session_id if session is not None else "test-or-development-session"
    )
    return AuditMetadataRecord(
        audit_id=str(uuid4()),
        category=AuditCategory.CONFIGURATION,
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject=identity.operator_id,
            identity_provider="enterprise-oidc",
            session_id=session_id,
            permissions=tuple(sorted(item.value for item in identity.permissions)),
        ),
        occurred_at=_now(),
        target_type="model_connection",
        target_id=connection.connection_id,
        metadata=metadata,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
