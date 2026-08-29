"""Operator HTTP API for Source intake and exact Knowledge Base publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import re
import secrets
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import Field

from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    KnowledgeCatalogConflict,
    KnowledgeCatalogIntegrityError,
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.application.dataset_intake import (
    CsvDatasetIntakeApplication,
    CsvDatasetIntakeCommand,
    ParquetDatasetIntakeApplication,
    ParquetDatasetIntakeCommand,
    XlsxDatasetIntakeApplication,
    XlsxDatasetIntakeCommand,
)
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.application.json_dataset_intake import (
    JsonDatasetIntakeApplication,
    JsonDatasetIntakeCommand,
)
from knowledge_source_service.application.projection_encoding import ProjectionTextEncoder
from knowledge_source_service.application.synchronizations import (
    KnowledgeSourceSynchronizationApplication,
    KnowledgeSourceSynchronizationIdempotencyConflict,
)
from knowledge_source_service.application.connection_profiles import ConnectionProfileApplication
from knowledge_source_service.application.base_preparations import (
    KnowledgeBasePreparationApplication,
)
from knowledge_source_service.contracts.base_preparations import (
    BaseIdentifier,
    BasePreparationAuditCollection,
    BasePreparationRejectionEntry,
    KnowledgeBaseDraft,
    QueuedReleasePreparation,
    ReleasePreparationResource,
    SaveKnowledgeBaseDraftRequest,
    StartReleasePreparationRequest,
)
from knowledge_source_service.domain.base_preparations import BasePreparationError
from knowledge_source_service.contracts.connection_profiles import (
    ConnectionProfileAuditCollection,
    ConnectionProfileAuditEntry,
    ConnectionProfileDraft,
    ConnectionProfileRevisionCommand,
    ConnectionProfileRejectionEntry,
    ConnectionProfileView,
    ProfileIdentifier,
    ReviseConnectionProfileRequest,
)
from knowledge_source_service.domain.connection_profiles import ConnectionProfileError
from knowledge_source_service.contracts.base import NonBlankText, StrictContract
from knowledge_source_service.contracts.synchronizations import (
    SourceSynchronizationRequest,
    SourceSynchronizationResource,
)
from knowledge_source_service.contracts.results import Sha256Digest
from knowledge_source_service.domain.knowledge_catalog import StructuredValueType
from knowledge_source_service.domain.synchronizations import (
    KnowledgeSourceSynchronizationPersistenceConflict,
)
from knowledge_source_service.delivery.http import (
    InvalidIdempotencyKey,
    require_idempotency_key,
)
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.ocr import DocumentOcrExtractor
from knowledge_source_service.ports.search_projection import HybridSearchProjection


@dataclass(frozen=True)
class KnowledgeOperator:
    operator_id: str
    permissions: frozenset[str] = frozenset()


AuthenticateKnowledgeOperator = Callable[[Request], KnowledgeOperator]


class InvalidKnowledgeOperatorCredential(PermissionError):
    """The request has no valid operator Bearer credential."""


class KnowledgeOperatorPermissionDenied(PermissionError):
    """An authenticated identity lacks the command's global named permission."""


def bearer_operator_authenticator(
    *,
    operator_id: str,
    expected_token: str,
    permissions: frozenset[str] = frozenset({"knowledge_source.view", "knowledge_source.edit"}),
) -> AuthenticateKnowledgeOperator:
    """Create a constant-time operator authenticator from secret configuration."""

    if not operator_id.strip() or len(expected_token) < 16:
        raise ValueError("operator identity configuration is invalid")

    def authenticate(request: Request) -> KnowledgeOperator:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or token != token.strip()
            or " " in token
            or not secrets.compare_digest(token, expected_token)
        ):
            raise InvalidKnowledgeOperatorCredential
        return KnowledgeOperator(operator_id=operator_id, permissions=permissions)

    return authenticate


class CreateKnowledgeSpaceRequest(StrictContract):
    knowledge_space_id: NonBlankText


class KnowledgeSpaceResource(StrictContract):
    schema_version: Literal["knowledge-space.v1"] = "knowledge-space.v1"
    knowledge_space_id: NonBlankText


class ManagementCollectionSummary(StrictContract):
    total: int = Field(ge=0, le=10_000)


class KnowledgeSpaceCollectionResource(StrictContract):
    schema_version: Literal["knowledge-space-collection.v1"] = "knowledge-space-collection.v1"
    data: tuple[KnowledgeSpaceResource, ...] = Field(max_length=1_000)
    summary: ManagementCollectionSummary


class CreateKnowledgeSourceRequest(StrictContract):
    knowledge_source_id: NonBlankText


class KnowledgeSourceResource(StrictContract):
    schema_version: Literal["knowledge-source.v1"] = "knowledge-source.v1"
    knowledge_space_id: NonBlankText
    knowledge_source_id: NonBlankText


class KnowledgeSourceCollectionResource(StrictContract):
    schema_version: Literal["knowledge-source-collection.v1"] = "knowledge-source-collection.v1"
    data: tuple[KnowledgeSourceResource, ...] = Field(max_length=10_000)
    summary: ManagementCollectionSummary


class CreateKnowledgeBaseRequest(StrictContract):
    knowledge_base_id: NonBlankText


class KnowledgeBaseResource(StrictContract):
    schema_version: Literal["knowledge-base.v1"] = "knowledge-base.v1"
    knowledge_space_id: NonBlankText
    knowledge_base_id: NonBlankText


class KnowledgeBaseCollectionResource(StrictContract):
    schema_version: Literal["knowledge-base-collection.v1"] = "knowledge-base-collection.v1"
    data: tuple[KnowledgeBaseResource, ...] = Field(max_length=10_000)
    summary: ManagementCollectionSummary


class KnowledgeSourceVersionResource(StrictContract):
    schema_version: Literal["knowledge-source-version.v1"] = "knowledge-source-version.v1"
    knowledge_space_id: NonBlankText
    knowledge_source_id: NonBlankText
    knowledge_source_version_id: NonBlankText
    source_kind: Literal["document", "dataset"]
    media_type: NonBlankText
    original_content_digest: Sha256Digest
    canonical_artifact_digest: Sha256Digest
    evidence_manifest_digest: Sha256Digest
    processing_lineage_digest: Sha256Digest
    evidence_unit_count: int | None = None
    dataset_revision_id: NonBlankText | None = None
    schema_revision_id: NonBlankText | None = None
    record_count: int | None = None


class KnowledgeSourceVersionSummaryResource(StrictContract):
    schema_version: Literal["knowledge-source-version-summary.v1"] = (
        "knowledge-source-version-summary.v1"
    )
    knowledge_space_id: NonBlankText
    knowledge_source_id: NonBlankText
    knowledge_source_version_id: NonBlankText
    source_kind: Literal["document", "dataset"]
    media_type: NonBlankText


class KnowledgeSourceVersionCollectionResource(StrictContract):
    schema_version: Literal["knowledge-source-version-collection.v1"] = (
        "knowledge-source-version-collection.v1"
    )
    data: tuple[KnowledgeSourceVersionSummaryResource, ...] = Field(max_length=10_000)
    summary: ManagementCollectionSummary


class PublishKnowledgeBaseReleaseRequest(StrictContract):
    knowledge_source_version_ids: tuple[NonBlankText, ...]


class KnowledgeBaseReleaseResource(StrictContract):
    schema_version: Literal["knowledge-base-release.v1"] = "knowledge-base-release.v1"
    knowledge_space_id: NonBlankText
    knowledge_base_id: NonBlankText
    knowledge_base_version_id: NonBlankText
    knowledge_base_release_id: NonBlankText
    knowledge_source_version_ids: tuple[NonBlankText, ...]
    release_manifest_digest: Sha256Digest
    state: Literal["queryable"] = "queryable"


class KnowledgeBaseReleaseSummaryResource(StrictContract):
    schema_version: Literal["knowledge-base-release-summary.v1"] = (
        "knowledge-base-release-summary.v1"
    )
    knowledge_space_id: NonBlankText
    knowledge_base_id: NonBlankText
    knowledge_base_version_id: NonBlankText
    knowledge_base_release_id: NonBlankText
    source_version_count: int = Field(ge=1, le=10_000)
    state: Literal["queryable", "deprecated", "retired", "revoked"]


class KnowledgeBaseReleaseCollectionResource(StrictContract):
    schema_version: Literal["knowledge-base-release-collection.v1"] = (
        "knowledge-base-release-collection.v1"
    )
    data: tuple[KnowledgeBaseReleaseSummaryResource, ...] = Field(max_length=10_000)
    summary: ManagementCollectionSummary


def create_management_application(
    *,
    catalog: PostgresKnowledgeCatalog,
    artifacts: ImmutableArtifactStore,
    authenticate_operator: AuthenticateKnowledgeOperator,
    document_pipeline_revision: str,
    dataset_pipeline_revision: str,
    max_upload_bytes: int,
    max_dataset_records: int,
    projection: HybridSearchProjection | None = None,
    encoder: ProjectionTextEncoder | None = None,
    ocr_extractor: DocumentOcrExtractor | None = None,
    synchronization_application: KnowledgeSourceSynchronizationApplication | None = None,
    connection_profiles: ConnectionProfileApplication | None = None,
    base_preparations: KnowledgeBasePreparationApplication | None = None,
) -> FastAPI:
    """Build a storage-opaque management surface over durable service authority."""

    def require_management_permission(
        request: Request,
        operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> None:
        # Only authenticated, server-configured grants count. No role/header/body
        # can introduce permissions and no profile operation grants Agent release.
        required = "knowledge_source.view" if request.method == "GET" else "knowledge_source.edit"
        request.state.knowledge_operator = operator
        if required not in operator.permissions:
            raise KnowledgeOperatorPermissionDenied

    application = FastAPI(
        title="Knowledge Source Service Management API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(require_management_permission)],
    )
    document_intake = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=document_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        ocr_extractor=ocr_extractor,
    )
    dataset_intake = CsvDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=dataset_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        max_records=max_dataset_records,
    )
    xlsx_dataset_intake = XlsxDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=dataset_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        max_records=max_dataset_records,
    )
    parquet_dataset_intake = ParquetDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=dataset_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        max_records=max_dataset_records,
    )
    json_dataset_intake = JsonDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=dataset_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        max_records=max_dataset_records,
    )
    releases = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
        projection=projection,
        encoder=encoder,
    )

    def audit_profile_rejection(request: Request, code: str) -> JSONResponse | None:
        operations = {
            "create_profile": "create",
            "get_profile": "get",
            "revise_profile": "revise",
            "validate_profile": "validate",
            "publish_profile": "publish",
            "profile_audit": "audit",
        }
        operation = operations.get(getattr(request.scope.get("route"), "name", ""))
        if connection_profiles is None or operation is None:
            return None
        identity = getattr(request.state, "knowledge_operator", None)
        profile_id = request.path_params.get("profile_id")
        if (
            not isinstance(profile_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", profile_id) is None
        ):
            profile_id = None
        event = ConnectionProfileRejectionEntry.model_validate(
            {
                "operator_id": None if identity is None else identity.operator_id,
                "connection_profile_id": profile_id,
                "operation": operation,
                "code": code,
                "recorded_at": datetime.now(UTC),
            }
        )
        try:
            connection_profiles.record_rejection(event)
        except ConnectionProfileError:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "connection_profile_audit_unavailable",
                    "status": 503,
                    "detail": "The rejected operation could not be audited.",
                },
                media_type="application/problem+json",
            )
        return None

    def audit_rejection(request: Request, code: str) -> JSONResponse | None:
        failure = audit_profile_rejection(request, code)
        if failure is not None:
            return failure
        operations = {
            "save_base_draft": "save_draft",
            "get_base_draft": "get_draft",
            "start_release_preparation": "start",
            "get_release_preparation": "get_preparation",
            "base_preparation_audit": "audit",
        }
        operation = operations.get(getattr(request.scope.get("route"), "name", ""))
        if base_preparations is None or operation is None:
            return None

        def safe_id(parameter: str) -> str | None:
            value = request.path_params.get(parameter)
            return (
                value
                if isinstance(value, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
                else None
            )

        identity = getattr(request.state, "knowledge_operator", None)
        operator_id = None if identity is None else identity.operator_id
        if (
            not isinstance(operator_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}", operator_id) is None
        ):
            operator_id = None
        event = BasePreparationRejectionEntry.model_validate(
            {
                "operator_id": operator_id,
                "knowledge_space_id": safe_id("knowledge_space_id"),
                "knowledge_base_id": safe_id("knowledge_base_id"),
                "release_preparation_id": safe_id("preparation_id"),
                "operation": operation,
                "code": code,
                "recorded_at": datetime.now(UTC),
            }
        )
        try:
            base_preparations.record_rejection(event)
        except BasePreparationError:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "base_preparation_audit_unavailable",
                    "status": 503,
                    "detail": "The rejected operation could not be audited.",
                },
                media_type="application/problem+json",
            )
        return None

    @application.exception_handler(ConnectionProfileError)
    def handle_connection_profile_error(
        _request: Request, error: ConnectionProfileError
    ) -> JSONResponse:
        failure = audit_rejection(_request, error.code)
        if failure is not None:
            return failure
        code = error.code
        error_status = (
            503
            if code.endswith("_unavailable")
            else 404
            if code == "connection_profile_not_found"
            else 422
            if code.startswith("connection_profile_invalid_")
            else 409
        )
        return JSONResponse(
            status_code=error_status,
            content={
                "type": "urn:knowledge-source-service:problem:connection-profile",
                "title": "Connection Profile operation failed",
                "status": error_status,
                "code": code,
                "detail": "The exact Profile operation could not be completed.",
            },
            media_type="application/problem+json",
        )

    if connection_profiles is not None:
        profiles = connection_profiles

        @application.post(
            "/v1/connection-profiles", response_model=ConnectionProfileView, status_code=201
        )
        def create_profile(
            body: ConnectionProfileDraft,
            response: Response,
            operator: KnowledgeOperator = Depends(authenticate_operator),
            idempotency_key: str = Depends(require_idempotency_key),
        ) -> ConnectionProfileView:
            view = profiles.create(
                body, operator_id=operator.operator_id, idempotency_key=idempotency_key
            )
            response.headers["Location"] = f"/v1/connection-profiles/{view.connection_profile_id}"
            return view

        @application.get(
            "/v1/connection-profiles/{profile_id}", response_model=ConnectionProfileView
        )
        def get_profile(
            profile_id: ProfileIdentifier,
            revision: int | None = Query(default=None, ge=1),
            _operator: KnowledgeOperator = Depends(authenticate_operator),
        ) -> ConnectionProfileView:
            view = profiles.get(profile_id, revision=revision)
            if view is None:
                raise ConnectionProfileError("connection_profile_not_found")
            return view

        @application.put(
            "/v1/connection-profiles/{profile_id}", response_model=ConnectionProfileView
        )
        def revise_profile(
            profile_id: ProfileIdentifier,
            body: ReviseConnectionProfileRequest,
            operator: KnowledgeOperator = Depends(authenticate_operator),
            idempotency_key: str = Depends(require_idempotency_key),
        ) -> ConnectionProfileView:
            return profiles.revise(
                profile_id,
                body.draft,
                expected_revision=body.expected_revision,
                operator_id=operator.operator_id,
                idempotency_key=idempotency_key,
            )

        @application.post(
            "/v1/connection-profiles/{profile_id}:validate", response_model=ConnectionProfileView
        )
        def validate_profile(
            profile_id: ProfileIdentifier,
            body: ConnectionProfileRevisionCommand,
            operator: KnowledgeOperator = Depends(authenticate_operator),
            idempotency_key: str = Depends(require_idempotency_key),
        ) -> ConnectionProfileView:
            return profiles.validate(
                profile_id,
                expected_revision=body.expected_revision,
                operator_id=operator.operator_id,
                idempotency_key=idempotency_key,
            )

        @application.post(
            "/v1/connection-profiles/{profile_id}:publish", response_model=ConnectionProfileView
        )
        def publish_profile(
            profile_id: ProfileIdentifier,
            body: ConnectionProfileRevisionCommand,
            operator: KnowledgeOperator = Depends(authenticate_operator),
            idempotency_key: str = Depends(require_idempotency_key),
        ) -> ConnectionProfileView:
            return profiles.publish(
                profile_id,
                expected_revision=body.expected_revision,
                operator_id=operator.operator_id,
                idempotency_key=idempotency_key,
            )

        @application.get(
            "/v1/connection-profiles/{profile_id}/audit",
            response_model=ConnectionProfileAuditCollection,
        )
        def profile_audit(
            profile_id: ProfileIdentifier,
            _operator: KnowledgeOperator = Depends(authenticate_operator),
        ) -> ConnectionProfileAuditCollection:
            if profiles.get(profile_id) is None:
                raise ConnectionProfileError("connection_profile_not_found")
            return ConnectionProfileAuditCollection(
                events=tuple(
                    ConnectionProfileAuditEntry.model_validate(asdict(event))
                    for event in profiles.audit(profile_id)
                ),
                rejections=profiles.rejections(profile_id),
            )

    @application.exception_handler(BasePreparationError)
    def handle_base_preparation_error(
        _request: Request, error: BasePreparationError
    ) -> JSONResponse:
        failure = audit_rejection(_request, error.code)
        if failure is not None:
            return failure
        code = error.code
        error_status = (
            503
            if code.endswith("_unavailable")
            else 404
            if code.endswith("_not_found")
            else 422
            if "_invalid_" in code
            else 409
        )
        return JSONResponse(
            status_code=error_status,
            content={
                "type": "urn:knowledge-source-service:problem:base-preparation",
                "title": "Base preparation operation failed",
                "status": error_status,
                "code": code,
                "detail": "The exact Base preparation operation could not be completed.",
            },
            media_type="application/problem+json",
        )

    if base_preparations is not None:
        preparations = base_preparations
        base_path = "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}"

        def require_base_scope(
            space_id: str, base_id: str, actual_space_id: str, actual_base_id: str
        ) -> None:
            if (space_id, base_id) != (actual_space_id, actual_base_id):
                raise BasePreparationError("base_scope_mismatch")

        @application.put(f"{base_path}/draft", response_model=KnowledgeBaseDraft)
        def save_base_draft(
            knowledge_space_id: BaseIdentifier,
            knowledge_base_id: BaseIdentifier,
            body: SaveKnowledgeBaseDraftRequest,
            operator: KnowledgeOperator = Depends(authenticate_operator),
            idempotency_key: str = Depends(require_idempotency_key),
        ) -> KnowledgeBaseDraft:
            require_base_scope(
                knowledge_space_id,
                knowledge_base_id,
                body.knowledge_space_id,
                body.knowledge_base_id,
            )
            return preparations.save_draft(
                body, operator_id=operator.operator_id, idempotency_key=idempotency_key
            )

        @application.get(f"{base_path}/draft", response_model=KnowledgeBaseDraft)
        def get_base_draft(
            knowledge_space_id: BaseIdentifier,
            knowledge_base_id: BaseIdentifier,
            revision: int | None = Query(default=None, ge=1),
        ) -> KnowledgeBaseDraft:
            draft = preparations.get_draft(knowledge_base_id, revision=revision)
            if draft is None:
                raise BasePreparationError("base_draft_not_found")
            require_base_scope(
                knowledge_space_id,
                knowledge_base_id,
                draft.knowledge_space_id,
                draft.knowledge_base_id,
            )
            return draft

        @application.post(
            f"{base_path}/release-preparations",
            response_model=QueuedReleasePreparation,
            status_code=202,
        )
        def start_release_preparation(
            knowledge_space_id: BaseIdentifier,
            knowledge_base_id: BaseIdentifier,
            body: StartReleasePreparationRequest,
            response: Response,
            operator: KnowledgeOperator = Depends(authenticate_operator),
            idempotency_key: str = Depends(require_idempotency_key),
        ) -> QueuedReleasePreparation:
            require_base_scope(
                knowledge_space_id,
                knowledge_base_id,
                body.knowledge_space_id,
                body.knowledge_base_id,
            )
            preparation = preparations.start(
                body, operator_id=operator.operator_id, idempotency_key=idempotency_key
            )
            response.headers["Location"] = (
                f"/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}"
                f"/release-preparations/{preparation.release_preparation_id}"
            )
            return preparation

        @application.get(
            f"{base_path}/release-preparations/{{preparation_id}}",
            response_model=ReleasePreparationResource,
        )
        def get_release_preparation(
            knowledge_space_id: BaseIdentifier,
            knowledge_base_id: BaseIdentifier,
            preparation_id: BaseIdentifier,
        ) -> ReleasePreparationResource:
            preparation = preparations.get_preparation(preparation_id)
            if preparation is None:
                raise BasePreparationError("base_preparation_not_found")
            require_base_scope(
                knowledge_space_id,
                knowledge_base_id,
                preparation.knowledge_space_id,
                preparation.knowledge_base_id,
            )
            return preparation

        @application.get(
            f"{base_path}/preparation-audit", response_model=BasePreparationAuditCollection
        )
        def base_preparation_audit(
            knowledge_space_id: BaseIdentifier,
            knowledge_base_id: BaseIdentifier,
        ) -> BasePreparationAuditCollection:
            draft = preparations.get_draft(knowledge_base_id)
            if draft is None:
                raise BasePreparationError("base_draft_not_found")
            require_base_scope(
                knowledge_space_id,
                knowledge_base_id,
                draft.knowledge_space_id,
                draft.knowledge_base_id,
            )
            return BasePreparationAuditCollection(
                events=preparations.audit(knowledge_base_id),
                rejections=preparations.rejections(knowledge_base_id),
            )

    @application.exception_handler(InvalidKnowledgeOperatorCredential)
    def handle_invalid_operator_credential(
        _request: Request,
        _error: InvalidKnowledgeOperatorCredential,
    ) -> JSONResponse:
        failure = audit_rejection(_request, "invalid_operator_credential")
        if failure is not None:
            return failure
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "type": "urn:knowledge-source-service:problem:invalid-operator-credential",
                "title": "Knowledge operator authentication failed",
                "status": 401,
                "code": "invalid_operator_credential",
                "detail": "A valid operator Bearer credential is required.",
            },
            media_type="application/problem+json",
        )
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @application.exception_handler(KnowledgeOperatorPermissionDenied)
    def handle_permission_denied(
        _request: Request, _error: KnowledgeOperatorPermissionDenied
    ) -> JSONResponse:
        failure = audit_rejection(_request, "knowledge_operator_permission_denied")
        if failure is not None:
            return failure
        return JSONResponse(
            status_code=403,
            content={
                "type": "urn:knowledge-source-service:problem:operator-permission-denied",
                "title": "Knowledge operator permission denied",
                "status": 403,
                "code": "knowledge_operator_permission_denied",
                "detail": "The authenticated operator lacks the required permission.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(KnowledgeCatalogConflict)
    def handle_catalog_conflict(
        _request: Request,
        _error: KnowledgeCatalogConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": "urn:knowledge-source-service:problem:catalog-conflict",
                "title": "Knowledge catalog conflict",
                "status": 409,
                "code": "knowledge_catalog_conflict",
                "detail": "The requested catalog identity conflicts with durable authority.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(KnowledgeSourceSynchronizationPersistenceConflict)
    def handle_synchronization_persistence_conflict(
        _request: Request,
        _error: KnowledgeSourceSynchronizationPersistenceConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": (
                    "urn:knowledge-source-service:problem:knowledge-source-synchronization-conflict"
                ),
                "title": "Knowledge Source synchronization conflict",
                "status": 409,
                "code": "knowledge_source_synchronization_conflict",
                "detail": "The synchronization conflicts with durable authority.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(KnowledgeSourceSynchronizationIdempotencyConflict)
    def handle_synchronization_idempotency_conflict(
        _request: Request,
        _error: KnowledgeSourceSynchronizationIdempotencyConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": "urn:knowledge-source-service:problem:idempotency-key-mismatch",
                "title": "Idempotency key conflict",
                "status": 409,
                "code": "idempotency_key_mismatch",
                "detail": "The Idempotency-Key is already bound to another request.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(InvalidIdempotencyKey)
    def handle_invalid_idempotency_key(
        _request: Request,
        _error: InvalidIdempotencyKey,
    ) -> JSONResponse:
        failure = audit_rejection(_request, "invalid_idempotency_key")
        if failure is not None:
            return failure
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "urn:knowledge-source-service:problem:invalid-idempotency-key",
                "title": "Invalid Idempotency-Key",
                "status": 400,
                "code": "invalid_idempotency_key",
                "detail": "A non-blank Idempotency-Key header is required.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(KnowledgeCatalogIntegrityError)
    def handle_catalog_integrity_error(
        _request: Request,
        _error: KnowledgeCatalogIntegrityError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "type": "urn:knowledge-source-service:problem:catalog-integrity",
                "title": "Knowledge catalog integrity unavailable",
                "status": 503,
                "code": "knowledge_catalog_integrity_unavailable",
                "detail": "Exact Knowledge artifact integrity could not be verified.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(RequestValidationError)
    @application.exception_handler(ValueError)
    def handle_invalid_management_request(
        _request: Request,
        _error: Exception,
    ) -> JSONResponse:
        failure = audit_rejection(_request, "invalid_management_request")
        if failure is not None:
            return failure
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "type": "urn:knowledge-source-service:problem:invalid-management-request",
                "title": "Invalid Knowledge management request",
                "status": 422,
                "code": "invalid_management_request",
                "detail": "The management request failed bounded validation.",
            },
            media_type="application/problem+json",
        )

    @application.post(
        "/v1/knowledge-spaces",
        response_model=KnowledgeSpaceResource,
        status_code=status.HTTP_201_CREATED,
    )
    def create_space(
        body: CreateKnowledgeSpaceRequest,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSpaceResource:
        catalog.create_space(body.knowledge_space_id)
        return KnowledgeSpaceResource(knowledge_space_id=body.knowledge_space_id)

    @application.get(
        "/v1/knowledge-spaces",
        response_model=KnowledgeSpaceCollectionResource,
    )
    def list_spaces(
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSpaceCollectionResource:
        data = tuple(
            KnowledgeSpaceResource(knowledge_space_id=knowledge_space_id)
            for knowledge_space_id in catalog.list_spaces()
        )
        return KnowledgeSpaceCollectionResource(
            data=data,
            summary=ManagementCollectionSummary(total=len(data)),
        )

    @application.post(
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-sources",
        response_model=KnowledgeSourceResource,
        status_code=status.HTTP_201_CREATED,
    )
    def create_source(
        knowledge_space_id: str,
        body: CreateKnowledgeSourceRequest,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSourceResource:
        catalog.create_source(
            knowledge_space_id=knowledge_space_id,
            knowledge_source_id=body.knowledge_source_id,
        )
        return KnowledgeSourceResource(
            knowledge_space_id=knowledge_space_id,
            knowledge_source_id=body.knowledge_source_id,
        )

    @application.get(
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-sources",
        response_model=KnowledgeSourceCollectionResource,
    )
    def list_sources(
        knowledge_space_id: str,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSourceCollectionResource:
        data = tuple(
            KnowledgeSourceResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
            )
            for knowledge_source_id in catalog.list_sources(knowledge_space_id)
        )
        return KnowledgeSourceCollectionResource(
            data=data,
            summary=ManagementCollectionSummary(total=len(data)),
        )

    @application.post(
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases",
        response_model=KnowledgeBaseResource,
        status_code=status.HTTP_201_CREATED,
    )
    def create_base(
        knowledge_space_id: str,
        body: CreateKnowledgeBaseRequest,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeBaseResource:
        catalog.create_base(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=body.knowledge_base_id,
        )
        return KnowledgeBaseResource(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=body.knowledge_base_id,
        )

    @application.get(
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases",
        response_model=KnowledgeBaseCollectionResource,
    )
    def list_bases(
        knowledge_space_id: str,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeBaseCollectionResource:
        data = tuple(
            KnowledgeBaseResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_base_id=knowledge_base_id,
            )
            for knowledge_base_id in catalog.list_bases(knowledge_space_id)
        )
        return KnowledgeBaseCollectionResource(
            data=data,
            summary=ManagementCollectionSummary(total=len(data)),
        )

    if synchronization_application is not None:

        @application.post(
            "/v1/knowledge-source-synchronizations",
            response_model=SourceSynchronizationResource,
            status_code=status.HTTP_202_ACCEPTED,
        )
        def create_source_synchronization(
            body: SourceSynchronizationRequest,
            response: Response,
            idempotency_key: str = Depends(require_idempotency_key),
            operator: KnowledgeOperator = Depends(authenticate_operator),
        ) -> SourceSynchronizationResource:
            outcome = synchronization_application.create(
                body,
                operator_id=operator.operator_id,
                idempotency_key=idempotency_key,
            )
            synchronization = outcome.synchronization
            if not outcome.created:
                response.status_code = status.HTTP_200_OK
            response.headers["Location"] = synchronization.links.self
            response.headers["Retry-After"] = "1"
            return synchronization

        @application.get(
            ("/v1/knowledge-source-synchronizations/{knowledge_source_synchronization_id}"),
            response_model=SourceSynchronizationResource,
        )
        def get_source_synchronization(
            knowledge_source_synchronization_id: str,
            operator: KnowledgeOperator = Depends(authenticate_operator),
        ) -> SourceSynchronizationResource | JSONResponse:
            synchronization = synchronization_application.get(
                knowledge_source_synchronization_id,
                operator_id=operator.operator_id,
            )
            if synchronization is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={
                        "type": (
                            "urn:knowledge-source-service:problem:"
                            "knowledge-source-synchronization-not-found"
                        ),
                        "title": "Knowledge Source synchronization not found",
                        "status": 404,
                        "code": "knowledge_source_synchronization_not_found",
                        "detail": ("The synchronization does not exist or is not visible."),
                    },
                    media_type="application/problem+json",
                )
            return synchronization

    @application.post(
        (
            "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-sources/"
            "{knowledge_source_id}/versions:ingest"
        ),
        response_model=KnowledgeSourceVersionResource,
        status_code=status.HTTP_201_CREATED,
    )
    async def ingest_source_version(
        knowledge_space_id: str,
        knowledge_source_id: str,
        file: Annotated[UploadFile, File()],
        field_types: Annotated[str | None, Form()] = None,
        record_path: Annotated[str | None, Form()] = None,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSourceVersionResource:
        content = await file.read(max_upload_bytes + 1)
        await file.close()
        if len(content) > max_upload_bytes:
            raise ValueError("upload exceeds admitted bound")
        media_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
        filename = file.filename or "unnamed-source"
        if media_type in {
            "application/pdf",
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            "text/html",
            "text/markdown",
            "text/plain",
            "image/jpeg",
            "image/png",
            "image/tiff",
        }:
            if field_types is not None or record_path is not None:
                raise ValueError("document intake does not accept dataset mapping")
            published = document_intake.create_source_version(
                DocumentIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    media_type=media_type,
                    content=content,
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(published.version.knowledge_source_version_id),
                source_kind="document",
                media_type=published.version.media_type,
                original_content_digest=published.original_artifact.sha256,
                canonical_artifact_digest=published.canonical_artifact.sha256,
                evidence_manifest_digest=published.evidence_manifest_artifact.sha256,
                processing_lineage_digest=published.processing_lineage_digest,
                evidence_unit_count=len(published.version.evidence_units),
            )
        if media_type == "text/csv":
            if record_path is not None:
                raise ValueError("CSV intake does not accept record_path")
            declarations = _field_types(field_types)
            published_dataset = dataset_intake.create_source_version(
                CsvDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    content=content,
                    field_types=declarations,
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(published_dataset.version.knowledge_source_version_id),
                source_kind="dataset",
                media_type="text/csv",
                original_content_digest=published_dataset.original_artifact.sha256,
                canonical_artifact_digest=published_dataset.canonical_artifact.sha256,
                evidence_manifest_digest=(published_dataset.evidence_manifest_artifact.sha256),
                processing_lineage_digest=(published_dataset.processing_lineage_digest),
                dataset_revision_id=published_dataset.version.dataset_revision_id,
                schema_revision_id=published_dataset.version.schema_revision_id,
                record_count=len(published_dataset.version.records),
            )
        if media_type == ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
            if record_path is not None:
                raise ValueError("XLSX intake does not accept record_path")
            published_xlsx = xlsx_dataset_intake.create_source_version(
                XlsxDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    content=content,
                    field_types=_field_types(field_types),
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(published_xlsx.version.knowledge_source_version_id),
                source_kind="dataset",
                media_type=published_xlsx.original_artifact.media_type,
                original_content_digest=published_xlsx.original_artifact.sha256,
                canonical_artifact_digest=published_xlsx.canonical_artifact.sha256,
                evidence_manifest_digest=(published_xlsx.evidence_manifest_artifact.sha256),
                processing_lineage_digest=(published_xlsx.processing_lineage_digest),
                dataset_revision_id=published_xlsx.version.dataset_revision_id,
                schema_revision_id=published_xlsx.version.schema_revision_id,
                record_count=len(published_xlsx.version.records),
            )
        if media_type == "application/vnd.apache.parquet":
            if record_path is not None:
                raise ValueError("Parquet intake does not accept record_path")
            published_parquet = parquet_dataset_intake.create_source_version(
                ParquetDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    content=content,
                    field_types=_field_types(field_types),
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(published_parquet.version.knowledge_source_version_id),
                source_kind="dataset",
                media_type=published_parquet.original_artifact.media_type,
                original_content_digest=published_parquet.original_artifact.sha256,
                canonical_artifact_digest=(published_parquet.canonical_artifact.sha256),
                evidence_manifest_digest=(published_parquet.evidence_manifest_artifact.sha256),
                processing_lineage_digest=(published_parquet.processing_lineage_digest),
                dataset_revision_id=published_parquet.version.dataset_revision_id,
                schema_revision_id=published_parquet.version.schema_revision_id,
                record_count=len(published_parquet.version.records),
            )
        if media_type in {"application/json", "application/x-ndjson"}:
            published_json = json_dataset_intake.create_source_version(
                JsonDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    media_type=media_type,
                    content=content,
                    record_path=_record_path(record_path),
                    field_types=_field_types(field_types),
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(published_json.version.knowledge_source_version_id),
                source_kind="dataset",
                media_type=published_json.original_artifact.media_type,
                original_content_digest=published_json.original_artifact.sha256,
                canonical_artifact_digest=published_json.canonical_artifact.sha256,
                evidence_manifest_digest=(published_json.evidence_manifest_artifact.sha256),
                processing_lineage_digest=(published_json.processing_lineage_digest),
                dataset_revision_id=published_json.version.dataset_revision_id,
                schema_revision_id=published_json.version.schema_revision_id,
                record_count=len(published_json.version.records),
            )
        raise ValueError("unsupported intake media type")

    @application.get(
        (
            "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-sources/"
            "{knowledge_source_id}/versions"
        ),
        response_model=KnowledgeSourceVersionCollectionResource,
    )
    def list_source_versions(
        knowledge_space_id: str,
        knowledge_source_id: str,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSourceVersionCollectionResource:
        data = tuple(
            KnowledgeSourceVersionSummaryResource(
                knowledge_space_id=item.knowledge_space_id,
                knowledge_source_id=item.knowledge_source_id,
                knowledge_source_version_id=item.knowledge_source_version_id,
                source_kind=item.source_kind,
                media_type=item.media_type,
            )
            for item in catalog.list_source_versions(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
            )
        )
        return KnowledgeSourceVersionCollectionResource(
            data=data,
            summary=ManagementCollectionSummary(total=len(data)),
        )

    @application.post(
        ("/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/releases"),
        response_model=KnowledgeBaseReleaseResource,
        status_code=status.HTTP_201_CREATED,
    )
    def publish_release(
        knowledge_space_id: str,
        knowledge_base_id: str,
        body: PublishKnowledgeBaseReleaseRequest,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeBaseReleaseResource:
        published = releases.publish(
            PublishKnowledgeReleaseCommand(
                knowledge_space_id=knowledge_space_id,
                knowledge_base_id=knowledge_base_id,
                knowledge_source_version_ids=body.knowledge_source_version_ids,
            )
        )
        release = published.release
        return KnowledgeBaseReleaseResource(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_version_id=release.knowledge_base_version_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
            knowledge_source_version_ids=release.knowledge_source_version_ids,
            release_manifest_digest=release.release_manifest_digest,
        )

    @application.get(
        ("/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/releases"),
        response_model=KnowledgeBaseReleaseCollectionResource,
    )
    def list_releases(
        knowledge_space_id: str,
        knowledge_base_id: str,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeBaseReleaseCollectionResource:
        data = tuple(
            KnowledgeBaseReleaseSummaryResource(
                knowledge_space_id=item.knowledge_space_id,
                knowledge_base_id=item.knowledge_base_id,
                knowledge_base_version_id=item.knowledge_base_version_id,
                knowledge_base_release_id=item.knowledge_base_release_id,
                source_version_count=item.source_version_count,
                state=item.state,
            )
            for item in catalog.list_releases(
                knowledge_space_id=knowledge_space_id,
                knowledge_base_id=knowledge_base_id,
            )
        )
        return KnowledgeBaseReleaseCollectionResource(
            data=data,
            summary=ManagementCollectionSummary(total=len(data)),
        )

    return application


def _field_types(value: str | None) -> dict[str, StructuredValueType]:
    if value is None:
        raise ValueError("CSV intake requires field_types")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("field_types must be JSON") from error
    allowed = {"string", "integer", "decimal", "boolean", "date", "datetime", "null"}
    if (
        type(payload) is not dict
        or not payload
        or any(
            type(field) is not str
            or not field
            or type(value_type) is not str
            or value_type not in allowed
            for field, value_type in payload.items()
        )
    ):
        raise ValueError("field_types declarations are invalid")
    return {field: cast(StructuredValueType, value_type) for field, value_type in payload.items()}


def _record_path(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("record_path must be JSON") from error
    if (
        type(payload) is not list
        or len(payload) > 8
        or any(type(segment) is not str or not segment.strip() for segment in payload)
    ):
        raise ValueError("record_path must be a bounded array of field names")
    return tuple(payload)
