"""Production-only Hybrid Knowledge intake and lifecycle API."""

from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from proof_agent.capabilities.knowledge.hybrid.publication import PublicationConflict
from proof_agent.capabilities.knowledge.hybrid.rule_units import project_rule_units
from proof_agent.capabilities.knowledge.hybrid.workbook import (
    DEFAULT_WORKBOOK_IMPORT_LIMITS,
    WORKBOOK_MEDIA_TYPE,
    InsuranceMetadataDraftInput,
    InsuranceMetadataReview,
    WorkbookImportRecord,
    WorkbookImportRowIdentity,
    WorkbookKnownAnchor,
    WorkbookReviewConflictError,
    WorkbookValidationError,
    create_workbook_only_review,
    import_metadata_workbook,
    reconcile_metadata_drafts,
)
from proof_agent.capabilities.knowledge.ingestion.contracts import HybridIntakeLimits
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildResult,
    HybridInsuranceMetadataArtifact,
)
from proof_agent.capabilities.persistence.postgres.hybrid_ingestion_repository import (
    HybridIngestionRecord,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeArtifactBuildSpec,
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeSource,
    Permission,
    QuarantinedKnowledgeUpload,
)
from proof_agent.contracts.hybrid_documents import StructuredKnowledgeDocumentArtifact
from proof_agent.contracts.persistence import PersistenceConflictError
from proof_agent.control.knowledge.production_intake import (
    ProductionHybridKnowledgeIntakeService,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


router = APIRouter(prefix="/config/knowledge-sources", tags=["production-knowledge"])


class ProductionKnowledgeRepository(Protocol):
    def get_knowledge_source(self, source_id: str) -> KnowledgeSource | None: ...

    def list_knowledge_sources(self) -> tuple[KnowledgeSource, ...]: ...


class ProductionHybridIngestionRepository(Protocol):
    def get_record(self, job_id: str) -> HybridIngestionRecord | None: ...

    def list_records_for_source(self, source_id: str) -> tuple[HybridIngestionRecord, ...]: ...

    def get_result(self, job_id: str) -> HybridArtifactBuildResult | None: ...


class ProductionMetadataReviewRepository(Protocol):
    def list_page(self, source_id: str, **kwargs: Any) -> Any: ...

    def get(self, source_id: str, review_id: str) -> InsuranceMetadataReview | None: ...


class KnowledgeSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocumentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)


class KnowledgeDocumentBatchUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[KnowledgeDocumentUploadRequest] = Field(min_length=1, max_length=50)


class KnowledgeMetadataWorkbookImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    document_id: str = Field(min_length=1, max_length=255)
    revision_id: str = Field(min_length=1, max_length=255)


class KnowledgeMetadataReviewResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_review_version: int = Field(ge=1)
    expected_review_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2_000)
    corrections: dict[str, str | int | None] = Field(default_factory=dict)


class KnowledgeSourcePublicationValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smoke_query: str = Field(min_length=1, max_length=4_096)


class KnowledgeSourcePublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_id: str = Field(min_length=1, max_length=512)
    change_note: str = Field(min_length=1, max_length=2_000)


@router.get("")
def list_knowledge_sources(
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    sources = _knowledge_repository(request).list_knowledge_sources()
    data = [_source_payload(request, source) for source in sources]
    return {"data": data, "meta": {"total": len(data)}}


@router.post("", status_code=201)
def create_knowledge_source(
    body: KnowledgeSourceCreateRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    if body.provider != "hybrid_index":
        raise HTTPException(status_code=400, detail="production_requires_hybrid_index")
    source_id = body.source_id or f"ks_{uuid4().hex}"
    try:
        source = _intake_service(request).create_source(
            source_id=source_id,
            name=body.name,
            params=body.params,
            actor=_audit_actor(request, identity),
        )
    except PersistenceConflictError as exc:
        raise HTTPException(status_code=409, detail="knowledge_source_conflict") from exc
    except (ProofAgentError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _source_payload(request, source)


@router.get("/{source_id}")
def get_knowledge_source(
    source_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    return _source_payload(request, _require_source(request, source_id))


@router.get("/{source_id}/documents")
def list_knowledge_documents(
    source_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    _require_source(request, source_id)
    documents = [
        _document_projection(record)
        for record in _ingestion_repository(request).list_records_for_source(source_id)
    ]
    return {
        "data": [item.model_dump(mode="json") for item in documents],
        "meta": {"total": len(documents)},
    }


@router.post("/{source_id}/documents", status_code=202)
def upload_knowledge_document(
    source_id: str,
    body: KnowledgeDocumentUploadRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    source = _require_source(request, source_id)
    content = _decode_upload(body.content_base64, _limits(source).max_file_bytes)
    try:
        admission = _intake_service(request).admit_pdf(
            source_id=source_id,
            filename=body.filename,
            content_type=body.content_type,
            content=content,
            actor=_audit_actor(request, identity),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge_source_not_found") from exc
    except PersistenceConflictError as exc:
        raise HTTPException(status_code=409, detail="knowledge_source_changed") from exc
    except ProofAgentError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _admission_upload_projection(admission).model_dump(mode="json")


@router.post("/{source_id}/documents/batch", status_code=202)
def upload_knowledge_documents(
    source_id: str,
    body: KnowledgeDocumentBatchUploadRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    source = _require_source(request, source_id)
    limits = _limits(source)
    if len(body.documents) > limits.max_batch_files:
        raise HTTPException(status_code=400, detail="hybrid_batch_limit_exceeded")
    admitted: list[QuarantinedKnowledgeUpload] = []
    for item in body.documents:
        content = _decode_upload(item.content_base64, limits.max_file_bytes)
        try:
            result = _intake_service(request).admit_pdf(
                source_id=source_id,
                filename=item.filename,
                content_type=item.content_type,
                content=content,
                actor=_audit_actor(request, identity),
            )
        except PersistenceConflictError as exc:
            raise HTTPException(status_code=409, detail="knowledge_source_changed") from exc
        except (ProofAgentError, ValueError) as exc:
            detail = exc.message if isinstance(exc, ProofAgentError) else str(exc)
            raise HTTPException(status_code=400, detail=detail) from exc
        admitted.append(_admission_upload_projection(result))
    return {
        "data": [item.model_dump(mode="json") for item in admitted],
        "meta": {"total": len(admitted)},
    }


@router.get("/{source_id}/ingestion-jobs")
def list_knowledge_ingestion_jobs(
    source_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    _require_source(request, source_id)
    jobs = [
        _job_projection(record)
        for record in _ingestion_repository(request).list_records_for_source(source_id)
    ]
    return {
        "data": [item.model_dump(mode="json") for item in jobs],
        "meta": {"total": len(jobs)},
    }


@router.get("/{source_id}/ingestion-jobs/{job_id}")
def get_knowledge_ingestion_job(
    source_id: str,
    job_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    record = _ingestion_repository(request).get_record(job_id)
    if record is None or record.build_request.source_id != source_id:
        raise HTTPException(status_code=404, detail="knowledge_ingestion_job_not_found")
    return _job_projection(record).model_dump(mode="json")


@router.post("/{source_id}/metadata-workbooks/import")
def import_metadata_workbook_for_source(
    source_id: str,
    body: KnowledgeMetadataWorkbookImportRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    _require_source(request, source_id)
    if not body.filename.casefold().endswith(".xlsx") or body.content_type != WORKBOOK_MEDIA_TYPE:
        raise HTTPException(status_code=400, detail="metadata_workbook_envelope_invalid")
    content = _decode_upload(
        body.content_base64,
        DEFAULT_WORKBOOK_IMPORT_LIMITS.max_file_bytes,
    )
    try:
        result = _completed_build(
            request,
            source_id=source_id,
            document_id=body.document_id,
            revision_id=body.revision_id,
        )
        artifacts = _artifact_store(request)
        canonical = StructuredKnowledgeDocumentArtifact.model_validate_json(
            artifacts.get_exact(result.canonical_ref)
        )
        metadata = HybridInsuranceMetadataArtifact.model_validate_json(
            artifacts.get_exact(result.insurance_metadata_ref)
        )
        _validate_build_artifacts(result, canonical, metadata)
        drafts = project_rule_units(
            canonical,
            document_defaults=metadata.document_defaults,
            source_id=source_id,
        )
        if not drafts:
            raise WorkbookValidationError("completed build has no canonical Rule Unit anchors")
        by_anchor = {draft.canonical_anchor: draft for draft in drafts}
        if len(by_anchor) != len(drafts):
            raise WorkbookValidationError("completed build contains duplicate canonical anchors")
        pdf_by_anchor = {draft.canonical_anchor: draft for draft in metadata.pdf_drafts}
        if len(pdf_by_anchor) != len(metadata.pdf_drafts) or not set(pdf_by_anchor).issubset(
            by_anchor
        ):
            raise WorkbookValidationError("PDF metadata drafts diverge from canonical anchors")
        imported = import_metadata_workbook(
            content,
            known_anchors=tuple(
                WorkbookKnownAnchor(
                    source_id=source_id,
                    document_id=result.document_id,
                    revision_id=result.revision_id,
                    canonical_anchor=draft.canonical_anchor,
                )
                for draft in drafts
            ),
            artifact_store=artifacts,
        )
        import_record = WorkbookImportRecord(
            import_id=imported.import_id,
            template_revision=imported.template_revision,
            source_id=source_id,
            document_id=result.document_id,
            revision_id=result.revision_id,
            created_by=identity.operator_id,
            created_at=datetime.now(UTC),
            original_ref=imported.original_ref,
            normalized_ref=imported.normalized_ref,
            rows=tuple(
                WorkbookImportRowIdentity(
                    row_number=row.row_number,
                    source_id=row.source_id,
                    document_id=row.document_id,
                    revision_id=row.revision_id,
                    canonical_anchor=row.canonical_anchor,
                    metadata_draft_id=row.metadata.metadata_draft_id,
                )
                for row in imported.rows
            ),
        )
        reviews = tuple(
            _review_for_row(
                row=row,
                import_record=import_record,
                pdf_draft=pdf_by_anchor.get(row.canonical_anchor),
                citation_uri=_citation_for_anchor(by_anchor, row.canonical_anchor),
            )
            for row in imported.rows
        )
        repository = _metadata_reviews(request)
        replayed = all(
            repository.get(source_id, review.review_id) == review for review in reviews
        )
        with _configuration_uow(request) as uow:
            persisted = uow.metadata_reviews.put_many(reviews)
            _append_audit_once(
                uow,
                _audit_record(
                    request,
                    identity,
                    audit_id=str(
                        uuid5(
                            NAMESPACE_URL,
                            f"proof-agent:metadata-import:{source_id}:{imported.import_id}",
                        )
                    ),
                    event_type="hybrid_metadata_workbook.imported",
                    target_type="metadata_workbook_import",
                    target_id=imported.import_id,
                    metadata={
                        "source_id": source_id,
                        "document_id": result.document_id,
                        "revision_id": result.revision_id,
                        "row_count": len(imported.rows),
                        "content_sha256": imported.original_sha256,
                    },
                ),
            )
            uow.commit()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="completed_hybrid_build_not_found") from exc
    except (ValidationError, WorkbookValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkbookReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    page = _metadata_reviews(request).list_page(
        source_id,
        limit=100,
        import_id=imported.import_id,
    )
    return {
        "import_id": imported.import_id,
        "template_revision": imported.template_revision,
        "row_count": len(imported.rows),
        "replayed": replayed,
        "original_ref": imported.original_ref.model_dump(mode="json"),
        "normalized_ref": imported.normalized_ref.model_dump(mode="json"),
        "reviews": [item.model_dump(mode="json") for item in persisted],
        "meta": _review_page_meta(page),
    }


@router.get("/{source_id}/metadata-reviews")
def list_metadata_reviews(
    source_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    state: str | None = Query(default=None),
    import_id: str | None = Query(default=None),
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    _require_source(request, source_id)
    try:
        page = _metadata_reviews(request).list_page(
            source_id,
            limit=limit,
            cursor=cursor,
            state=state,
            import_id=import_id,
        )
    except WorkbookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "data": [item.model_dump(mode="json") for item in page.items],
        "meta": _review_page_meta(page),
    }


@router.get("/{source_id}/metadata-reviews/{review_id}")
def get_metadata_review(
    source_id: str,
    review_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    review = _metadata_reviews(request).get(source_id, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="metadata_review_not_found")
    return review.model_dump(mode="json")


@router.post("/{source_id}/metadata-reviews/{review_id}/{action}")
def resolve_metadata_review(
    source_id: str,
    review_id: str,
    action: str,
    body: KnowledgeMetadataReviewResolutionRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    if action not in {"approve", "correct", "reject"}:
        raise HTTPException(status_code=404, detail="metadata_review_action_not_found")
    permission = (
        Permission.KNOWLEDGE_SOURCE_EDIT
        if action == "correct"
        else Permission.KNOWLEDGE_SOURCE_PUBLISH
    )
    require_operator_permission(identity, permission)
    try:
        with _configuration_uow(request) as uow:
            updated = uow.metadata_reviews.resolve(
                source_id=source_id,
                review_id=review_id,
                expected_review_version=body.expected_review_version,
                expected_review_identity=body.expected_review_identity,
                action=action,
                actor=identity.operator_id,
                reason=body.reason,
                corrections=body.corrections,
            )
            uow.audit.append(
                _audit_record(
                    request,
                    identity,
                    event_type=f"hybrid_metadata_review.{action}",
                    target_type="metadata_review",
                    target_id=review_id,
                    metadata={
                        "source_id": source_id,
                        "review_version": updated.review_version,
                        "review_identity": updated.review_identity,
                    },
                )
            )
            uow.commit()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="metadata_review_not_found") from exc
    except WorkbookReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkbookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return cast(dict[str, object], updated.model_dump(mode="json"))


@router.post("/{source_id}/publication/validate")
def validate_publication(
    source_id: str,
    body: KnowledgeSourcePublicationValidationRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_PUBLISH)
    _require_source(request, source_id)
    try:
        validation = _publication_api(request).validate(
            source_id=source_id,
            smoke_query=body.smoke_query,
            actor=identity.operator_id,
        )
    except PublicationConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    return cast(dict[str, object], validation.model_dump(mode="json"))


@router.post("/{source_id}/publication/publish")
def publish_source(
    source_id: str,
    body: KnowledgeSourcePublicationRequest,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_PUBLISH)
    _require_source(request, source_id)
    try:
        publication = _publication_api(request).publish(
            source_id=source_id,
            validation_id=body.validation_id,
            change_note=body.change_note,
            actor=identity.operator_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="publication_validation_not_found") from exc
    except PublicationConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    return cast(dict[str, object], publication.model_dump(mode="json"))


@router.get("/{source_id}/publication-validations")
def list_publication_validations(
    source_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    values = tuple(_publication_api(request).list_validations(source_id))
    return {"data": [item.model_dump(mode="json") for item in values], "meta": {"total": len(values)}}


@router.get("/{source_id}/publications")
def list_publications(
    source_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    values = tuple(_publication_api(request).list_publications(source_id))
    return {"data": [item.model_dump(mode="json") for item in values], "meta": {"total": len(values)}}


def _source_payload(request: Request, source: KnowledgeSource) -> dict[str, object]:
    records = _ingestion_repository(request).list_records_for_source(source.source_id)
    payload = cast(dict[str, object], source.model_dump(mode="json"))
    payload["document_count"] = len(records)
    payload["ready_document_count"] = sum(
        record.job.state == "COMPLETED" for record in records
    )
    payload["publication_count"] = 0
    return payload


def _document_projection(record: HybridIngestionRecord) -> KnowledgeDocument:
    request = record.build_request
    state = _public_state(record.job.state)
    created_at = _timestamp(record.job.created_at)
    updated_at = _timestamp(record.job.updated_at)
    return KnowledgeDocument(
        document_id=request.document_id,
        source_id=request.source_id,
        revision_id=request.revision_id,
        filename=record.filename,
        content_type="application/pdf",
        content_hash=request.original_ref.sha256,
        size_bytes=request.original_ref.size_bytes,
        state=state,
        storage_path=f"managed://hybrid/{request.document_id}/revisions/{request.revision_id}",
        ingestion_job_id=request.job_id,
        artifact_path=(
            f"managed://hybrid/{request.document_id}/artifacts"
            if record.job.state == "COMPLETED"
            else None
        ),
        error_code=record.job.failure_code,
        error_message=record.job.safe_reason,
        created_at=created_at,
        updated_at=updated_at,
    )


def _job_projection(record: HybridIngestionRecord) -> KnowledgeIngestionJob:
    request = record.build_request
    model_identity = hashlib.sha256("\n".join(request.model_digests).encode()).hexdigest()
    return KnowledgeIngestionJob(
        job_id=request.job_id,
        source_id=request.source_id,
        document_id=request.document_id,
        revision_id=request.revision_id,
        state=_public_state(record.job.state),
        attempt_count=record.job.fencing_token,
        auto_retry_count=record.job.auto_retry_count,
        max_auto_retries=record.job.max_auto_retries,
        ingestion_config_fingerprint=request.configuration_sha256,
        artifact_build_spec=KnowledgeArtifactBuildSpec(
            provider="hybrid_index",
            engine_name="private_hybrid_parser",
            engine_version=request.parser_revision,
            parser_fingerprint_identity=model_identity,
            content_hash=request.original_ref.sha256,
            parsed_text_sha256="pending" if record.job.state != "COMPLETED" else "managed",
        ),
        artifact_path=(
            f"managed://hybrid/{request.document_id}/artifacts"
            if record.job.state == "COMPLETED"
            else None
        ),
        completed_at=(
            _timestamp(record.job.completed_at) if record.job.completed_at is not None else None
        ),
        error_code=record.job.failure_code,
        error_message=record.job.safe_reason,
        last_error_code=record.job.failure_code,
        last_error_message=record.job.safe_reason,
        last_failure_classification=record.job.failure_classification,
        next_attempt_at=(
            _timestamp(record.job.next_attempt_at)
            if record.job.next_attempt_at is not None
            else None
        ),
        created_at=_timestamp(record.job.created_at),
        updated_at=_timestamp(record.job.updated_at),
    )


def _admission_upload_projection(admission: Any) -> QuarantinedKnowledgeUpload:
    request = admission.request
    return QuarantinedKnowledgeUpload(
        upload_id=request.job_id,
        source_id=request.source_id,
        filename=admission.filename,
        content_type="application/pdf",
        size_bytes=request.original_ref.size_bytes,
        storage_path=f"managed://hybrid/{request.document_id}/revisions/{request.revision_id}",
        state="accepted",
        completed_at=admission.created_at,
        promoted_document_id=request.document_id,
        promoted_revision_id=request.revision_id,
        ingestion_job_id=request.job_id,
        created_at=admission.created_at,
        updated_at=admission.created_at,
    )


def _public_state(state: str) -> str:
    return {
        "READY": "queued",
        "CLAIMED": "processing",
        "RETRY_SCHEDULED": "retry_scheduled",
        "REVIEW_REQUIRED": "review_required",
        "COMPLETED": "ready",
        "FAILED": "failed",
    }[state]


def _decode_upload(value: str, maximum_bytes: int) -> bytes:
    maximum_encoded = ((maximum_bytes + 2) // 3) * 4
    if len(value) > maximum_encoded:
        raise HTTPException(status_code=400, detail="hybrid_upload_envelope_too_large")
    try:
        content = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_base64") from exc
    if not content or len(content) > maximum_bytes:
        raise HTTPException(status_code=400, detail="hybrid_upload_size_invalid")
    return content


def _limits(source: KnowledgeSource) -> HybridIntakeLimits:
    try:
        return HybridIntakeLimits.model_validate(dict(source.params), strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="hybrid_source_limits_invalid") from exc


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


def _require_source(request: Request, source_id: str) -> KnowledgeSource:
    source = _knowledge_repository(request).get_knowledge_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="knowledge_source_not_found")
    return source


def _intake_service(request: Request) -> ProductionHybridKnowledgeIntakeService:
    service = getattr(request.app.state, "production_hybrid_intake_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="hybrid_intake_unavailable")
    return cast(ProductionHybridKnowledgeIntakeService, service)


def _knowledge_repository(request: Request) -> ProductionKnowledgeRepository:
    repository = getattr(request.app.state, "production_knowledge_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="knowledge_repository_unavailable")
    return cast(ProductionKnowledgeRepository, repository)


def _ingestion_repository(request: Request) -> ProductionHybridIngestionRepository:
    repository = getattr(request.app.state, "production_hybrid_ingestion_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="hybrid_ingestion_unavailable")
    return cast(ProductionHybridIngestionRepository, repository)


def _metadata_reviews(request: Request) -> ProductionMetadataReviewRepository:
    repository = getattr(request.app.state, "production_metadata_review_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="metadata_review_repository_unavailable")
    return cast(ProductionMetadataReviewRepository, repository)


def _publication_api(request: Request) -> Any:
    publication = getattr(request.app.state, "production_hybrid_publication_api", None)
    if publication is None:
        raise HTTPException(status_code=503, detail="hybrid_publication_unavailable")
    return publication


def _artifact_store(request: Request) -> Any:
    store = getattr(request.app.state, "production_hybrid_artifact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="hybrid_artifact_store_unavailable")
    return store


def _configuration_uow(request: Request) -> Any:
    factory = getattr(request.app.state, "production_configuration_uow_factory", None)
    if not callable(factory):
        raise HTTPException(status_code=503, detail="configuration_uow_unavailable")
    return factory()


def _completed_build(
    request: Request,
    *,
    source_id: str,
    document_id: str,
    revision_id: str,
) -> HybridArtifactBuildResult:
    repository = _ingestion_repository(request)
    matches = tuple(
        record
        for record in repository.list_records_for_source(source_id)
        if record.build_request.document_id == document_id
        and record.build_request.revision_id == revision_id
        and record.job.state == "COMPLETED"
    )
    if len(matches) != 1:
        raise KeyError((source_id, document_id, revision_id))
    result = repository.get_result(matches[0].build_request.job_id)
    if result is None:
        raise KeyError((source_id, document_id, revision_id))
    return result


def _validate_build_artifacts(
    result: HybridArtifactBuildResult,
    canonical: StructuredKnowledgeDocumentArtifact,
    metadata: HybridInsuranceMetadataArtifact,
) -> None:
    if (
        canonical.document_id != result.document_id
        or canonical.revision_id != result.revision_id
        or canonical.original_sha256 != result.original_ref.sha256
        or canonical.build_identity != result.build_identity
        or metadata.source_id != result.source_id
        or metadata.document_id != result.document_id
        or metadata.revision_id != result.revision_id
        or metadata.structured_build_id != result.build_id
        or metadata.original_sha256 != result.original_ref.sha256
    ):
        raise WorkbookValidationError("completed Hybrid build artifacts diverge from authority")


def _review_for_row(
    *,
    row: Any,
    import_record: WorkbookImportRecord,
    pdf_draft: InsuranceMetadataDraftInput | None,
    citation_uri: str,
) -> InsuranceMetadataReview:
    workbook_draft = _workbook_row_draft(row)
    if pdf_draft is None:
        return create_workbook_only_review(
            workbook_draft,
            import_record=import_record,
            row=row,
            citation_uri=citation_uri,
        )
    return reconcile_metadata_drafts(
        pdf_draft,
        workbook_draft,
        import_record=import_record,
        row=row,
    )


def _workbook_row_draft(row: Any) -> InsuranceMetadataDraftInput:
    applicability = row.metadata.applicability
    precedence = row.metadata.precedence
    if applicability is None or precedence is None or row.metadata.authority is None:
        raise WorkbookValidationError("workbook row is missing governed metadata")
    return InsuranceMetadataDraftInput(
        metadata_draft_id=row.metadata.metadata_draft_id,
        origin="workbook",
        source_id=row.source_id,
        document_id=row.document_id,
        revision_id=row.revision_id,
        canonical_anchor=row.canonical_anchor,
        authority=row.metadata.authority,
        effective_from=row.metadata.effective_from,
        effective_to=row.metadata.effective_to,
        taxonomy_id=applicability.taxonomy_id,
        taxonomy_revision_id=applicability.taxonomy_revision_id,
        precedence_policy_revision_id=precedence.policy_revision_id,
        precedence_authority_tier=precedence.authority_tier,
        precedence_order=precedence.order,
    )


def _review_page_meta(page: Any) -> dict[str, object]:
    return {
        "total": page.total,
        "unresolved": page.summary.unresolved,
        "next_cursor": page.next_cursor,
        "summary": page.summary.model_dump(mode="json"),
    }


def _audit_record(
    request: Request,
    identity: OperatorIdentityContext,
    *,
    event_type: str,
    target_type: str,
    target_id: str,
    metadata: dict[str, object],
    audit_id: str | None = None,
) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=audit_id or str(uuid4()),
        category=AuditCategory.CONFIGURATION,
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        actor=_audit_actor(request, identity),
        occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )


def _append_audit_once(uow: Any, event: AuditMetadataRecord) -> None:
    existing = uow.audit.get(event.audit_id)
    if existing is None:
        uow.audit.append(event)
        return
    if (
        existing.event_type != event.event_type
        or existing.target_type != event.target_type
        or existing.target_id != event.target_id
        or existing.metadata != event.metadata
    ):
        raise WorkbookReviewConflictError("metadata import audit identity already exists")


def _citation_for_anchor(
    indexed: dict[str, Any],
    canonical_anchor: str | None,
) -> str:
    if canonical_anchor is None or canonical_anchor not in indexed:
        raise WorkbookValidationError("workbook row has no governed canonical anchor")
    return cast(str, indexed[canonical_anchor].citation_uri)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = ["router"]
