"""Provider-neutral Knowledge Source API V1 delivery boundary."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import date
import hashlib
import json
import re
from typing import Annotated, Any, BinaryIO, Literal, Protocol, cast
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field
from starlette.responses import Response

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    MetadataProfileBindingRequiredError,
    MetadataReviewConflictError,
    MetadataReviewValidationError,
)
from proof_agent.capabilities.knowledge.hybrid.workbook import (
    WorkbookReviewConflictError,
    WorkbookValidationError,
)
from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
    KnowledgeSourceRevisionConflictError,
)
from proof_agent.contracts import (
    AuditActorFacts,
    KnowledgeSourceAuditProjection,
    KnowledgeSourceApiFieldError,
    KnowledgeSourceApiProblem,
    KnowledgeSourceActionBlocker,
    KnowledgeSourceCapabilityProjection,
    KnowledgeSourceCursorPage,
    KnowledgeSourceCursorError,
    KnowledgeSourceDetailProjection,
    KnowledgeSourceDocumentProjection,
    KnowledgeSourceListItemProjection,
    KnowledgeSourceMetadataReviewProjection,
    KnowledgeSourceMetadataProfileProjection,
    KnowledgeSourceMetadataWorkbookPreviewProjection,
    KnowledgeSourceOperation,
    KnowledgeSourcePublicationProjection,
    KnowledgeSourcePublicationValidationProjection,
    KnowledgeSourceRevisionCommand,
    Permission,
)
from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.ports.knowledge_source_operations import (
    KnowledgeSourceIdempotencyConflictError,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


class KnowledgeSourceConfigurationApplication(Protocol):
    """Provider-neutral Source configuration reads used by Dashboard."""

    def capabilities(self) -> KnowledgeSourceCapabilityProjection: ...

    def list_page(
        self,
        *,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection]: ...

    def create_source(
        self,
        *,
        source_id: str,
        name: str,
        provider: str,
        params: dict[str, object],
        actor: AuditActorFacts,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection: ...

    def detail(
        self,
        source_id: str,
        *,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection: ...

    def change_lifecycle(
        self,
        source_id: str,
        *,
        action: Literal["archive", "restore"],
        expected_revision: int,
        reason: str,
        actor: AuditActorFacts,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection: ...


class KnowledgeSourceIngestionApplication(Protocol):
    """Multipart upload command consumed by the HTTP adapter."""

    def upload_document(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation: ...

    def replace_document(
        self,
        *,
        source_id: str,
        document_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation: ...

    def retry_ingestion(
        self,
        *,
        source_id: str,
        job_id: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation: ...

    def cancel_ingestion(
        self,
        *,
        source_id: str,
        job_id: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation: ...

class KnowledgeSourceOperationsApplication(Protocol):
    """Durable operation read boundary used by polling clients."""

    def list_page(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceOperation]: ...

    def get(
        self,
        *,
        source_id: str,
        operation_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceOperation: ...


class KnowledgeSourcePublicationPreparationApplication(Protocol):
    def prepare_publication(
        self,
        *,
        source_id: str,
        smoke_query: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation: ...


class KnowledgeSourcePublicationApplication(Protocol):
    def publish(
        self,
        *,
        source_id: str,
        validation_id: str,
        expected_revision: int,
        expected_fencing_token: int,
        change_note: str,
        idempotency_key: str,
        request_sha256: str,
        context: KnowledgeSourceCommandContext,
    ) -> tuple[KnowledgeSourceOperation, bool]: ...


class KnowledgeSourceWorkspaceApplication(Protocol):
    """Bounded safe resources and business-review commands for seven tabs."""

    def documents(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceDocumentProjection]: ...

    def reviews(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceMetadataReviewProjection]: ...

    def metadata_profile(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataProfileProjection: ...

    def approve_review(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataReviewProjection: ...

    def save_review_draft(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        changes: dict[str, str | int | date | None],
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataReviewProjection: ...

    def reject_review(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataReviewProjection: ...

    def publication_validations(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationValidationProjection]: ...

    def publications(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationProjection]: ...

    def audit(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceAuditProjection]: ...


class KnowledgeSourceMetadataWorkbookApplication(Protocol):
    def generate_export(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation: ...

    def download_export(
        self,
        *,
        source_id: str,
        export_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> tuple[bytes, str]: ...

    def create_import_preview(
        self,
        *,
        source_id: str,
        export_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation: ...

    def get_import_preview(
        self,
        *,
        source_id: str,
        preview_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataWorkbookPreviewProjection: ...

    def apply_import_preview(
        self,
        *,
        source_id: str,
        preview_id: str,
        expected_preview_identity: str,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation: ...


class KnowledgeSourcePublicationPreparationRequest(StrictFrozenModel):
    """Asynchronous publication preparation command."""

    smoke_query: str = Field(min_length=1, max_length=4_096)
    expected_revision: int = Field(ge=1)


class KnowledgeSourceCreateRequest(StrictFrozenModel):
    """Capability-selected creation command with no deployment secrets."""

    source_id: str | None = Field(default=None, min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    params: dict[str, object] = Field(default_factory=dict)


class KnowledgeSourcePublicationRequest(StrictFrozenModel):
    """Short authority-only publication CAS command."""

    validation_id: str = Field(min_length=1, max_length=512)
    expected_fencing_token: int = Field(ge=1)
    change_note: str = Field(min_length=1, max_length=1_000)
    expected_revision: int = Field(ge=1)


class KnowledgeSourceReviewApprovalRequest(StrictFrozenModel):
    """Exact Metadata Review V2 approval CAS command."""

    document_id: str = Field(min_length=1, max_length=255)
    revision_id: str = Field(min_length=1, max_length=255)
    expected_review_version: int = Field(ge=1)
    expected_review_identity: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    reason: str = Field(min_length=1, max_length=2_000)


class KnowledgeSourceReviewDraftChanges(StrictFrozenModel):
    """Typed partial business metadata fields accepted by Save Draft."""

    authority: str | None = Field(default=None, min_length=1, max_length=255)
    effective_from: date | None = None
    effective_to: date | None = None
    taxonomy_id: str | None = Field(default=None, min_length=1, max_length=255)
    taxonomy_revision_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    precedence_policy_revision_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    precedence_authority_tier: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    precedence_order: int | None = Field(default=None, ge=0)


class KnowledgeSourceReviewDraftRequest(KnowledgeSourceReviewApprovalRequest):
    """Exact Metadata Review V2 Save Draft CAS command."""

    changes: KnowledgeSourceReviewDraftChanges


class KnowledgeSourceMetadataWorkbookExportRequest(StrictFrozenModel):
    revision_id: str = Field(min_length=1, max_length=255)
    expected_revision: int = Field(ge=1)


class KnowledgeSourceMetadataWorkbookApplyRequest(StrictFrozenModel):
    expected_preview_identity: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2_000)


class KnowledgeSourceLifecycleRequest(StrictFrozenModel):
    """Explicit Source CAS and trace-safe lifecycle decision reason."""

    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2_000)


class KnowledgeSourceProblemRoute(APIRoute):
    """Render every failure from this router as safe RFC 7807 JSON."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                return await original(request)
            except Exception as exc:
                return _problem_response(request, exc)

        return route_handler


router = APIRouter(
    prefix="/config",
    tags=["knowledge-sources"],
    route_class=KnowledgeSourceProblemRoute,
)


def _configuration_application(
    request: Request,
) -> KnowledgeSourceConfigurationApplication:
    application = getattr(
        request.app.state,
        "knowledge_source_configuration_application",
        None,
    )
    if application is None:
        raise KnowledgeSourceCommandRejectedError(
            code="knowledge_source_configuration_unavailable",
            detail="Knowledge Source configuration is unavailable.",
        )
    return cast(KnowledgeSourceConfigurationApplication, application)


def _ingestion_application(request: Request) -> KnowledgeSourceIngestionApplication:
    application = getattr(
        request.app.state,
        "knowledge_source_ingestion_application",
        None,
    )
    if application is None:
        raise KnowledgeSourceCommandRejectedError(
            code="knowledge_source_ingestion_unavailable",
            detail="Knowledge Source ingestion is unavailable.",
        )
    return cast(KnowledgeSourceIngestionApplication, application)


def _operations_application(request: Request) -> KnowledgeSourceOperationsApplication:
    application = getattr(
        request.app.state,
        "knowledge_source_operations_application",
        None,
    )
    if application is None:
        raise KnowledgeSourceCommandRejectedError(
            code="knowledge_source_operations_unavailable",
            detail="Knowledge Source operations are unavailable.",
        )
    return cast(KnowledgeSourceOperationsApplication, application)


def _publication_preparation_application(
    request: Request,
) -> KnowledgeSourcePublicationPreparationApplication:
    application = getattr(
        request.app.state,
        "knowledge_source_publication_preparation_application",
        None,
    )
    if application is None:
        raise KnowledgeSourceCommandRejectedError(
            code="knowledge_source_publication_unavailable",
            detail="Knowledge Source publication preparation is unavailable.",
        )
    return cast(KnowledgeSourcePublicationPreparationApplication, application)


def _publication_application(
    request: Request,
) -> KnowledgeSourcePublicationApplication:
    application = getattr(
        request.app.state,
        "knowledge_source_publication_application",
        None,
    )
    if application is None:
        raise KnowledgeSourceCommandRejectedError(
            code="knowledge_source_publication_unavailable",
            detail="Knowledge Source publication is unavailable.",
        )
    return cast(KnowledgeSourcePublicationApplication, application)


def _workspace_application(request: Request) -> KnowledgeSourceWorkspaceApplication:
    application = getattr(
        request.app.state,
        "knowledge_source_workspace_application",
        None,
    )
    if application is None:
        raise KnowledgeSourceCommandRejectedError(
            code="knowledge_source_workspace_unavailable",
            detail="Knowledge Source workspace resources are unavailable.",
        )
    return cast(KnowledgeSourceWorkspaceApplication, application)


def _metadata_workbook_application(
    request: Request,
) -> KnowledgeSourceMetadataWorkbookApplication:
    application = getattr(
        request.app.state,
        "knowledge_source_metadata_workbook_application",
        None,
    )
    if application is None:
        raise KnowledgeSourceCommandRejectedError(
            code="knowledge_source_metadata_workbook_unavailable",
            detail="Knowledge Source Metadata Workbook is unavailable.",
        )
    return cast(KnowledgeSourceMetadataWorkbookApplication, application)


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


def _command_context(identity: OperatorIdentityContext) -> KnowledgeSourceCommandContext:
    return KnowledgeSourceCommandContext(
        operator_subject=identity.operator_id,
        permissions=tuple(sorted(identity.permissions, key=lambda item: item.value)),
        permission_mapping_version_id=identity.permission_mapping_version_id,
        permission_epoch=identity.permission_epoch,
    )


@router.get(
    "/knowledge-source-capabilities",
    response_model=KnowledgeSourceCapabilityProjection,
)
def get_knowledge_source_capabilities(
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceCapabilityProjection:
    del identity
    return _configuration_application(request).capabilities()


@router.get(
    "/knowledge-sources",
    response_model=KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection],
)
def list_knowledge_sources(
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=4_096)] = None,
) -> KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection]:
    return _configuration_application(request).list_page(
        context=_command_context(identity),
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/knowledge-sources",
    response_model=KnowledgeSourceDetailProjection,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_source(
    body: KnowledgeSourceCreateRequest,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceDetailProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _configuration_application(request).create_source(
        source_id=body.source_id or f"ks_{uuid4().hex}",
        name=body.name,
        provider=body.provider,
        params=body.params,
        actor=_audit_actor(request, identity),
        context=_command_context(identity),
    )


@router.get(
    "/knowledge-sources/{source_id}",
    response_model=KnowledgeSourceDetailProjection,
)
def get_knowledge_source(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceDetailProjection:
    return _configuration_application(request).detail(
        source_id,
        context=_command_context(identity),
    )


def _change_knowledge_source_lifecycle(
    action: Literal["archive", "restore"],
    body: KnowledgeSourceLifecycleRequest,
    request: Request,
    source_id: str,
    identity: OperatorIdentityContext,
) -> KnowledgeSourceDetailProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_ARCHIVE)
    return _configuration_application(request).change_lifecycle(
        source_id,
        action=action,
        expected_revision=body.expected_revision,
        reason=body.reason,
        actor=_audit_actor(request, identity),
        context=_command_context(identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/archive",
    response_model=KnowledgeSourceDetailProjection,
)
def archive_knowledge_source(
    body: KnowledgeSourceLifecycleRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceDetailProjection:
    return _change_knowledge_source_lifecycle(
        "archive",
        body,
        request,
        source_id,
        identity,
    )


@router.post(
    "/knowledge-sources/{source_id}/restore",
    response_model=KnowledgeSourceDetailProjection,
)
def restore_knowledge_source(
    body: KnowledgeSourceLifecycleRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceDetailProjection:
    return _change_knowledge_source_lifecycle(
        "restore",
        body,
        request,
        source_id,
        identity,
    )


@router.get(
    "/knowledge-sources/{source_id}/documents",
    response_model=KnowledgeSourceCursorPage[KnowledgeSourceDocumentProjection],
)
def list_knowledge_source_documents(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=4_096)] = None,
) -> KnowledgeSourceCursorPage[KnowledgeSourceDocumentProjection]:
    return _workspace_application(request).documents(
        source_id=source_id,
        context=_command_context(identity),
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/knowledge-sources/{source_id}/metadata-reviews",
    response_model=KnowledgeSourceCursorPage[KnowledgeSourceMetadataReviewProjection],
)
def list_knowledge_source_metadata_reviews(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=4_096)] = None,
) -> KnowledgeSourceCursorPage[KnowledgeSourceMetadataReviewProjection]:
    return _workspace_application(request).reviews(
        source_id=source_id,
        context=_command_context(identity),
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/knowledge-sources/{source_id}/metadata-profile",
    response_model=KnowledgeSourceMetadataProfileProjection,
)
def get_knowledge_source_metadata_profile(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceMetadataProfileProjection:
    return _workspace_application(request).metadata_profile(
        source_id=source_id,
        context=_command_context(identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/metadata-reviews/{review_id}/approve",
    response_model=KnowledgeSourceMetadataReviewProjection,
)
def approve_knowledge_source_metadata_review(
    body: KnowledgeSourceReviewApprovalRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    review_id: Annotated[str, Path(min_length=1, max_length=512)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceMetadataReviewProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_REVIEW)
    return _workspace_application(request).approve_review(
        source_id=source_id,
        document_id=body.document_id,
        revision_id=body.revision_id,
        review_id=review_id,
        expected_review_version=body.expected_review_version,
        expected_review_identity=body.expected_review_identity,
        actor=identity.operator_id,
        reason=body.reason,
        context=_command_context(identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/metadata-reviews/{review_id}/draft",
    response_model=KnowledgeSourceMetadataReviewProjection,
)
def save_knowledge_source_metadata_review_draft(
    body: KnowledgeSourceReviewDraftRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    review_id: Annotated[str, Path(min_length=1, max_length=512)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceMetadataReviewProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    changes = body.changes.model_dump(include=body.changes.model_fields_set)
    return _workspace_application(request).save_review_draft(
        source_id=source_id,
        document_id=body.document_id,
        revision_id=body.revision_id,
        review_id=review_id,
        expected_review_version=body.expected_review_version,
        expected_review_identity=body.expected_review_identity,
        actor=identity.operator_id,
        reason=body.reason,
        changes=changes,
        context=_command_context(identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/metadata-reviews/{review_id}/reject",
    response_model=KnowledgeSourceMetadataReviewProjection,
)
def reject_knowledge_source_metadata_review(
    body: KnowledgeSourceReviewApprovalRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    review_id: Annotated[str, Path(min_length=1, max_length=512)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceMetadataReviewProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_REVIEW)
    return _workspace_application(request).reject_review(
        source_id=source_id,
        document_id=body.document_id,
        revision_id=body.revision_id,
        review_id=review_id,
        expected_review_version=body.expected_review_version,
        expected_review_identity=body.expected_review_identity,
        actor=identity.operator_id,
        reason=body.reason,
        context=_command_context(identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/documents/{document_id}/metadata-workbook-exports",
    response_model=KnowledgeSourceOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_knowledge_source_metadata_workbook_export(
    body: KnowledgeSourceMetadataWorkbookExportRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    document_id: Annotated[str, Path(min_length=1, max_length=255)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _metadata_workbook_application(request).generate_export(
        source_id=source_id,
        document_id=document_id,
        revision_id=body.revision_id,
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
        actor=_audit_actor(request, identity),
    )


@router.get(
    "/knowledge-sources/{source_id}/metadata-workbook-exports/{export_id}/content",
)
def download_knowledge_source_metadata_workbook_export(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    export_id: Annotated[str, Path(min_length=1, max_length=512)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> Response:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    content, filename = _metadata_workbook_application(request).download_export(
        source_id=source_id,
        export_id=export_id,
        context=_command_context(identity),
    )
    safe_filename = quote(filename, safe="-._")
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/knowledge-sources/{source_id}/metadata-workbook-import-previews",
    response_model=KnowledgeSourceOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_knowledge_source_metadata_workbook_import_preview(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    export_id: Annotated[str, Form(min_length=1, max_length=512)],
    expected_revision: Annotated[int, Form(ge=1)],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="metadata_workbook_filename_required",
        )
    return _metadata_workbook_application(request).create_import_preview(
        source_id=source_id,
        export_id=export_id,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        content=file.file,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        actor=_audit_actor(request, identity),
    )


@router.get(
    "/knowledge-sources/{source_id}/metadata-workbook-import-previews/{preview_id}",
    response_model=KnowledgeSourceMetadataWorkbookPreviewProjection,
)
def get_knowledge_source_metadata_workbook_import_preview(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    preview_id: Annotated[str, Path(min_length=1, max_length=512)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceMetadataWorkbookPreviewProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    return _metadata_workbook_application(request).get_import_preview(
        source_id=source_id,
        preview_id=preview_id,
        context=_command_context(identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/metadata-workbook-import-previews/{preview_id}/apply",
    response_model=KnowledgeSourceOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def apply_knowledge_source_metadata_workbook_import_preview(
    body: KnowledgeSourceMetadataWorkbookApplyRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    preview_id: Annotated[str, Path(min_length=1, max_length=512)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _metadata_workbook_application(request).apply_import_preview(
        source_id=source_id,
        preview_id=preview_id,
        expected_preview_identity=body.expected_preview_identity,
        expected_revision=body.expected_revision,
        reason=body.reason,
        idempotency_key=idempotency_key,
        actor=_audit_actor(request, identity),
    )


@router.get(
    "/knowledge-sources/{source_id}/publication-validations",
    response_model=KnowledgeSourceCursorPage[
        KnowledgeSourcePublicationValidationProjection
    ],
)
def list_knowledge_source_publication_validations(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=4_096)] = None,
) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationValidationProjection]:
    return _workspace_application(request).publication_validations(
        source_id=source_id,
        context=_command_context(identity),
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/knowledge-sources/{source_id}/publications",
    response_model=KnowledgeSourceCursorPage[KnowledgeSourcePublicationProjection],
)
def list_knowledge_source_publications(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=4_096)] = None,
) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationProjection]:
    return _workspace_application(request).publications(
        source_id=source_id,
        context=_command_context(identity),
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/knowledge-sources/{source_id}/audit",
    response_model=KnowledgeSourceCursorPage[KnowledgeSourceAuditProjection],
)
def list_knowledge_source_audit(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=4_096)] = None,
) -> KnowledgeSourceCursorPage[KnowledgeSourceAuditProjection]:
    return _workspace_application(request).audit(
        source_id=source_id,
        context=_command_context(identity),
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/knowledge-sources/{source_id}/operations",
    response_model=KnowledgeSourceCursorPage[KnowledgeSourceOperation],
)
def list_knowledge_source_operations(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=4_096)] = None,
) -> KnowledgeSourceCursorPage[KnowledgeSourceOperation]:
    return _operations_application(request).list_page(
        source_id=source_id,
        context=_command_context(identity),
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/knowledge-sources/{source_id}/operations/{operation_id}",
    response_model=KnowledgeSourceOperation,
)
def get_knowledge_source_operation(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    operation_id: Annotated[str, Path(min_length=1, max_length=255)],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    return _operations_application(request).get(
        source_id=source_id,
        operation_id=operation_id,
        context=_command_context(identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/publication-validations",
    response_model=KnowledgeSourceOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def prepare_knowledge_source_publication(
    body: KnowledgeSourcePublicationPreparationRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_PUBLISH)
    return _publication_preparation_application(request).prepare_publication(
        source_id=source_id,
        smoke_query=body.smoke_query,
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
        actor=_audit_actor(request, identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/publications",
    response_model=KnowledgeSourceOperation,
)
def publish_knowledge_source(
    body: KnowledgeSourcePublicationRequest,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_PUBLISH)
    request_sha256 = hashlib.sha256(
        json.dumps(
            {
                "schema_version": "knowledge-source-publication-command.v1",
                "source_id": source_id,
                **body.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    operation, _created = _publication_application(request).publish(
        source_id=source_id,
        validation_id=body.validation_id,
        expected_revision=body.expected_revision,
        expected_fencing_token=body.expected_fencing_token,
        change_note=body.change_note,
        idempotency_key=idempotency_key,
        request_sha256=request_sha256,
        context=_command_context(identity),
    )
    return operation


@router.post(
    "/knowledge-sources/{source_id}/documents",
    response_model=KnowledgeSourceOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_document(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    file: Annotated[UploadFile, File()],
    expected_revision: Annotated[int, Form(ge=1)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    """Admit one bounded multipart file without exposing artifact locators."""

    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="knowledge_document_filename_required",
        )
    return _ingestion_application(request).upload_document(
        source_id=source_id,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        content=file.file,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        actor=_audit_actor(request, identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/documents/{document_id}/revisions",
    response_model=KnowledgeSourceOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def replace_document(
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    document_id: Annotated[UUID, Path()],
    file: Annotated[UploadFile, File()],
    expected_revision: Annotated[int, Form(ge=1)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    """Admit one explicit immutable replacement revision."""

    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="knowledge_document_filename_required",
        )
    return _ingestion_application(request).replace_document(
        source_id=source_id,
        document_id=str(document_id),
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        content=file.file,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        actor=_audit_actor(request, identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/ingestion-jobs/{job_id}/retry",
    response_model=KnowledgeSourceOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_ingestion(
    body: KnowledgeSourceRevisionCommand,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    job_id: Annotated[str, Path(min_length=1, max_length=255)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _ingestion_application(request).retry_ingestion(
        source_id=source_id,
        job_id=job_id,
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
        actor=_audit_actor(request, identity),
    )


@router.post(
    "/knowledge-sources/{source_id}/ingestion-jobs/{job_id}/cancel",
    response_model=KnowledgeSourceOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_ingestion(
    body: KnowledgeSourceRevisionCommand,
    request: Request,
    source_id: Annotated[str, Path(min_length=1, max_length=255)],
    job_id: Annotated[str, Path(min_length=1, max_length=255)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeSourceOperation:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _ingestion_application(request).cancel_ingestion(
        source_id=source_id,
        job_id=job_id,
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
        actor=_audit_actor(request, identity),
    )


def _problem_response(request: Request, exc: Exception) -> JSONResponse:
    status_code = 500
    code = "knowledge_source_internal_error"
    title = "Knowledge Source request failed"
    detail = "The Knowledge Source request could not be completed."
    retryable = False
    current_revision: int | None = None
    blockers: tuple[KnowledgeSourceActionBlocker, ...] = ()
    field_errors: tuple[KnowledgeSourceApiFieldError, ...] = ()
    problem_name = "knowledge-source-error"

    if isinstance(exc, RequestValidationError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = "knowledge_source_request_invalid"
        title = "Knowledge Source request invalid"
        detail = "One or more request fields are invalid."
        problem_name = "knowledge-source-validation"
        field_errors = tuple(
            KnowledgeSourceApiFieldError(
                location=tuple(str(item) for item in error["loc"]),
                code=_safe_error_code(str(error["type"])),
                detail="The field value is invalid.",
            )
            for error in exc.errors()
        )
    elif isinstance(exc, KnowledgeSourceRevisionConflictError):
        status_code = status.HTTP_409_CONFLICT
        code = "knowledge_source_revision_conflict"
        title = "Knowledge Source conflict"
        detail = "The Knowledge Source changed after this view was loaded."
        current_revision = exc.current_revision
        problem_name = "knowledge-source-conflict"
    elif isinstance(exc, KnowledgeSourceIdempotencyConflictError):
        status_code = status.HTTP_409_CONFLICT
        code = "idempotency_key_mismatch"
        title = "Idempotency key conflict"
        detail = "The Idempotency-Key was already used for a different request."
        problem_name = "knowledge-source-conflict"
    elif isinstance(exc, KnowledgeSourceCursorError):
        status_code = status.HTTP_400_BAD_REQUEST
        code = "knowledge_source_cursor_invalid"
        title = "Knowledge Source cursor invalid"
        detail = "The cursor is invalid or expired; restart from the first page."
        problem_name = "knowledge-source-cursor"
    elif isinstance(exc, WorkbookReviewConflictError | MetadataReviewConflictError):
        status_code = status.HTTP_409_CONFLICT
        code = "knowledge_source_review_conflict"
        title = "Knowledge Source review conflict"
        detail = "The metadata review changed after this view was loaded."
        problem_name = "knowledge-source-conflict"
    elif isinstance(exc, MetadataProfileBindingRequiredError):
        status_code = status.HTTP_409_CONFLICT
        code = "metadata_profile_binding_required"
        title = "Metadata Profile binding required"
        detail = (
            "Bind a published Metadata Profile before reviewing this Knowledge Source."
        )
        problem_name = "knowledge-source-prerequisite"
    elif isinstance(exc, WorkbookValidationError | MetadataReviewValidationError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = "knowledge_source_review_invalid"
        title = "Knowledge Source review invalid"
        detail = "The metadata review request is invalid."
        problem_name = "knowledge-source-validation"
    elif (
        isinstance(exc, ProofAgentError)
        and exc.code.startswith("PA_HYBRID_INTAKE_")
    ):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = _safe_error_code(exc.code)
        title = "Hybrid Knowledge document rejected"
        detail = exc.message
        problem_name = "knowledge-source-validation"
    elif isinstance(exc, KnowledgeSourceCommandRejectedError):
        code = exc.code
        detail = exc.detail
        blockers = exc.blockers
        if code in {
            "knowledge_source_not_found",
            "knowledge_source_operation_not_found",
        }:
            status_code = status.HTTP_404_NOT_FOUND
            title = "Knowledge Source resource not found"
            problem_name = "knowledge-source-not-found"
        elif code == "permission_required":
            status_code = status.HTTP_403_FORBIDDEN
            title = "Knowledge Source permission required"
            problem_name = "knowledge-source-forbidden"
        elif code.endswith("_unavailable"):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            title = "Knowledge Source service unavailable"
            retryable = True
            problem_name = "knowledge-source-unavailable"
        else:
            status_code = status.HTTP_409_CONFLICT
            title = "Knowledge Source command rejected"
            problem_name = "knowledge-source-conflict"
    elif isinstance(exc, HTTPException):
        status_code = exc.status_code
        code = {
            401: "authentication_required",
            403: "permission_required",
            404: "knowledge_source_not_found",
            409: "knowledge_source_conflict",
            422: "knowledge_source_request_invalid",
        }.get(status_code, "knowledge_source_request_rejected")
        title = {
            401: "Authentication required",
            403: "Knowledge Source permission required",
            404: "Knowledge Source resource not found",
            409: "Knowledge Source conflict",
            422: "Knowledge Source request invalid",
        }.get(status_code, "Knowledge Source request rejected")
        detail = (
            exc.detail
            if isinstance(exc.detail, str) and len(exc.detail) <= 2_000
            else "The Knowledge Source request was rejected."
        )
        problem_name = "knowledge-source-request"
    elif isinstance(exc, KeyError):
        status_code = status.HTTP_404_NOT_FOUND
        code = "knowledge_source_resource_not_found"
        title = "Knowledge Source resource not found"
        detail = "The requested Knowledge Source resource was not found."
        problem_name = "knowledge-source-not-found"
    elif isinstance(exc, ValueError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = "knowledge_source_request_invalid"
        title = "Knowledge Source request invalid"
        detail = "One or more request fields are invalid."
        problem_name = "knowledge-source-validation"

    problem = KnowledgeSourceApiProblem(
        type=f"urn:proof-agent:problem:{problem_name}",
        title=title,
        status=status_code,
        code=code,
        detail=detail,
        trace_id=_trace_id(request),
        retryable=retryable,
        current_revision=current_revision,
        field_errors=field_errors,
        blockers=blockers,
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )


def _trace_id(request: Request) -> str:
    value = getattr(request.state, "trace_id", None)
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,255}", value):
        return value
    return f"trace_{uuid4().hex}"


def _safe_error_code(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return (normalized or "invalid")[:128]


__all__ = [
    "KnowledgeSourceConfigurationApplication",
    "KnowledgeSourceIngestionApplication",
    "KnowledgeSourceOperationsApplication",
    "KnowledgeSourceProblemRoute",
    "KnowledgeSourceMetadataWorkbookApplication",
    "KnowledgeSourcePublicationApplication",
    "KnowledgeSourcePublicationPreparationApplication",
    "KnowledgeSourceWorkspaceApplication",
    "router",
]
