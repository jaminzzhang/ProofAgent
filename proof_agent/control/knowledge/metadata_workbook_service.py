"""Application service for the asynchronous Metadata Workbook V2 round trip."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, BinaryIO, Protocol, cast
from uuid import UUID, uuid4

from proof_agent.capabilities.knowledge.hybrid.intake import quarantine_hybrid_upload
from proof_agent.capabilities.knowledge.hybrid.metadata_workbook_jobs import (
    MetadataWorkbookJobV2,
)
from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
)
from proof_agent.control.knowledge.ingestion_service import (
    KnowledgeSourceAdmissionEffect,
    KnowledgeSourceCommandUnitOfWork,
    KnowledgeSourceIngestionService,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeSourceMetadataWorkbookPreviewProjection,
    KnowledgeSourceOperation,
    KnowledgeSourceProviderCapability,
    Permission,
)
from proof_agent.contracts.persistence import KnowledgeSourceRecord


class _SummaryReader(Protocol):
    def summary_for_source(self, source_id: str) -> Mapping[str, int]: ...


class KnowledgeSourceMetadataWorkbookService:
    """Admit exact Workbook V2 commands without mutating Source authority."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], KnowledgeSourceCommandUnitOfWork],
        provider_capability: KnowledgeSourceProviderCapability,
        summary_reader: _SummaryReader,
        knowledge: Any,
        metadata_reviews: Any,
        workbooks: Any,
        artifact_store: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._commands = KnowledgeSourceIngestionService(
            unit_of_work_factory=unit_of_work_factory,
            provider_capability=provider_capability,
            summary_reader=summary_reader,
            clock=self._clock,
        )
        self._knowledge = knowledge
        self._metadata_reviews = metadata_reviews
        self._workbooks = workbooks
        self._artifact_store = artifact_store

    def generate_export(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation:
        _require_permission(_actor_context(actor), Permission.KNOWLEDGE_SOURCE_EDIT)
        normalized_document_id = str(UUID(document_id))
        normalized_revision_id = str(UUID(revision_id))
        normalized_key = _nonblank(idempotency_key, "idempotency_key", maximum=255)
        request_sha256 = _request_sha256(
            {
                "schema_version": "metadata-workbook-export-command.v2",
                "source_id": source_id,
                "document_id": normalized_document_id,
                "revision_id": normalized_revision_id,
                "expected_revision": expected_revision,
            }
        )

        def persist_job(
            unit_of_work: KnowledgeSourceCommandUnitOfWork,
            _source_record: KnowledgeSourceRecord,
            operation: KnowledgeSourceOperation,
            admitted_at: datetime,
        ) -> None:
            workbook_uow = cast(Any, unit_of_work)
            review_set = workbook_uow.metadata_reviews.get_current_review_set(
                source_id=source_id,
                document_id=normalized_document_id,
                revision_id=normalized_revision_id,
            )
            if review_set is None:
                raise ValueError(
                    "Metadata Workbook Export requires a current Review Set"
                )
            workbook_uow.metadata_workbooks.enqueue_job(
                MetadataWorkbookJobV2(
                    job_id=str(uuid4()),
                    operation_id=operation.operation_id,
                    source_id=source_id,
                    document_id=normalized_document_id,
                    revision_id=normalized_revision_id,
                    source_revision=operation.source_revision,
                    command="generate_export",
                    resource_id=operation.operation_id,
                    request_sha256=request_sha256,
                    state="READY",
                    fencing_token=0,
                    created_by=actor.subject,
                    created_at=admitted_at,
                    updated_at=admitted_at,
                )
            )
            workbook_uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="hybrid_metadata_workbook.export_admitted",
                    target_type="metadata_workbook_export",
                    target_id=operation.operation_id,
                    occurred_at=admitted_at,
                    metadata={
                        "source_id": source_id,
                        "document_id": normalized_document_id,
                        "revision_id": normalized_revision_id,
                        "operation_id": operation.operation_id,
                    },
                )
            )

        effect = cast(KnowledgeSourceAdmissionEffect, persist_job)
        operation, _created = self._commands.admit_async_command(
            source_id=source_id,
            action="edit_metadata_workbook",
            command="generate_metadata_workbook_export",
            expected_revision=expected_revision,
            idempotency_key=normalized_key,
            request_sha256=request_sha256,
            context=_actor_context(actor),
            stage="metadata_workbook_export_queued",
            admission_effect=effect,
            advance_source_revision=False,
        )
        return operation

    def download_export(
        self,
        *,
        source_id: str,
        export_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> tuple[bytes, str]:
        _require_permission(context, Permission.KNOWLEDGE_SOURCE_EDIT)
        if self._knowledge.get_source_record(source_id) is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_not_found",
                detail="The Knowledge Source was not found.",
            )
        export = self._workbooks.get_export(
            source_id=source_id,
            export_id=export_id,
        )
        if (
            export is None
            or export.state != "available"
            or export.manifest.expires_at <= self._now()
        ):
            raise KnowledgeSourceCommandRejectedError(
                code="metadata_workbook_export_unavailable",
                detail="The Metadata Workbook Export is unavailable.",
            )
        if self._artifact_store is None:
            raise KnowledgeSourceCommandRejectedError(
                code="metadata_workbook_artifact_unavailable",
                detail="The Metadata Workbook artifact service is unavailable.",
            )
        content = self._artifact_store.get_exact(export.artifact_ref)
        if (
            len(content) != export.artifact_ref.size_bytes
            or hashlib.sha256(content).hexdigest() != export.artifact_ref.sha256
        ):
            raise KnowledgeSourceCommandRejectedError(
                code="metadata_workbook_artifact_identity_invalid",
                detail="The Metadata Workbook artifact failed integrity verification.",
            )
        filename = (
            f"{source_id}-{export.manifest.document_id}-metadata-v2.xlsx"
        )
        return content, filename

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
    ) -> KnowledgeSourceOperation:
        _require_permission(_actor_context(actor), Permission.KNOWLEDGE_SOURCE_EDIT)
        normalized_filename = _workbook_filename(filename)
        normalized_content_type = content_type.partition(";")[0].strip().lower()
        if normalized_content_type != _WORKBOOK_MEDIA_TYPE:
            raise ValueError(
                "Metadata Workbook Preview requires the official XLSX content type"
            )
        normalized_key = _nonblank(idempotency_key, "idempotency_key", maximum=255)
        export = self._workbooks.get_export(
            source_id=source_id,
            export_id=export_id,
        )
        if (
            export is None
            or export.state != "available"
            or export.manifest.expires_at <= self._now()
        ):
            raise KnowledgeSourceCommandRejectedError(
                code="metadata_workbook_export_unavailable",
                detail="The Metadata Workbook Export is unavailable.",
            )
        if self._artifact_store is None:
            raise KnowledgeSourceCommandRejectedError(
                code="metadata_workbook_artifact_unavailable",
                detail="The Metadata Workbook artifact service is unavailable.",
            )
        with quarantine_hybrid_upload(
            content,
            max_file_bytes=_MAX_WORKBOOK_FILE_BYTES,
        ) as quarantined:
            exact_content = quarantined.path.read_bytes()
            original_ref = self._artifact_store.put_immutable(
                key=(
                    "metadata-workbooks/v2/returns/"
                    f"{quarantined.sha256}/original.xlsx"
                ),
                content=exact_content,
                media_type=_WORKBOOK_MEDIA_TYPE,
            )
            content_sha256 = quarantined.sha256
            size_bytes = quarantined.size_bytes
        request_sha256 = _request_sha256(
            {
                "schema_version": "metadata-workbook-preview-command.v2",
                "source_id": source_id,
                "export_id": export_id,
                "filename": normalized_filename,
                "content_type": normalized_content_type,
                "content_sha256": content_sha256,
                "size_bytes": size_bytes,
                "expected_revision": expected_revision,
            }
        )

        def persist_job(
            unit_of_work: KnowledgeSourceCommandUnitOfWork,
            _source_record: KnowledgeSourceRecord,
            operation: KnowledgeSourceOperation,
            admitted_at: datetime,
        ) -> None:
            workbook_uow = cast(Any, unit_of_work)
            current_export = workbook_uow.metadata_workbooks.get_export(
                source_id=source_id,
                export_id=export_id,
            )
            if (
                current_export is None
                or current_export.state != "available"
                or current_export.manifest.expires_at <= admitted_at
            ):
                raise ValueError("Metadata Workbook Export became unavailable")
            workbook_uow.metadata_workbooks.enqueue_job(
                MetadataWorkbookJobV2(
                    job_id=str(uuid4()),
                    operation_id=operation.operation_id,
                    source_id=source_id,
                    document_id=current_export.manifest.document_id,
                    revision_id=current_export.manifest.revision_id,
                    source_revision=operation.source_revision,
                    command="create_preview",
                    resource_id=operation.operation_id,
                    parent_resource_id=export_id,
                    request_sha256=request_sha256,
                    original_ref=original_ref,
                    state="READY",
                    fencing_token=0,
                    created_by=actor.subject,
                    created_at=admitted_at,
                    updated_at=admitted_at,
                )
            )
            workbook_uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="hybrid_metadata_workbook.preview_admitted",
                    target_type="metadata_workbook_import_preview",
                    target_id=operation.operation_id,
                    occurred_at=admitted_at,
                    metadata={
                        "source_id": source_id,
                        "export_id": export_id,
                        "operation_id": operation.operation_id,
                        "content_sha256": original_ref.sha256,
                        "size_bytes": original_ref.size_bytes,
                    },
                )
            )

        effect = cast(KnowledgeSourceAdmissionEffect, persist_job)
        operation, _created = self._commands.admit_async_command(
            source_id=source_id,
            action="edit_metadata_workbook",
            command="create_metadata_workbook_import_preview",
            expected_revision=expected_revision,
            idempotency_key=normalized_key,
            request_sha256=request_sha256,
            context=_actor_context(actor),
            stage="metadata_workbook_preview_queued",
            admission_effect=effect,
            advance_source_revision=False,
        )
        return operation

    def get_import_preview(
        self,
        *,
        source_id: str,
        preview_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataWorkbookPreviewProjection:
        _require_permission(context, Permission.KNOWLEDGE_SOURCE_VIEW)
        if self._knowledge.get_source_record(source_id) is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_not_found",
                detail="The Knowledge Source was not found.",
            )
        authority = self._workbooks.get_preview(
            source_id=source_id,
            preview_id=preview_id,
        )
        if authority is None:
            raise KnowledgeSourceCommandRejectedError(
                code="metadata_workbook_preview_not_found",
                detail="The Metadata Workbook Import Preview was not found.",
            )
        projected_state = authority.state
        if (
            authority.expires_at <= self._now()
            and projected_state not in {"applied", "stale"}
        ):
            projected_state = "expired"
        preview = authority.preview
        report = authority.validation_report
        return KnowledgeSourceMetadataWorkbookPreviewProjection.model_validate(
            {
                "preview_id": authority.preview_id,
                "export_id": authority.export_id,
                "state": projected_state,
                "preview_identity": (
                    None if preview is None else preview.preview_identity
                ),
                "conflict_count": 0 if preview is None else preview.conflict_count,
                "field_merges": (
                    []
                    if preview is None
                    else [
                        item.model_dump(mode="json") for item in preview.field_merges
                    ]
                ),
                "override_modes": (
                    []
                    if preview is None
                    else [
                        item.model_dump(mode="json") for item in preview.override_modes
                    ]
                ),
                "validation_report": (
                    None if report is None else report.model_dump(mode="json")
                ),
                "created_at": _timestamp(authority.created_at),
                "expires_at": _timestamp(authority.expires_at),
            }
        )

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
    ) -> KnowledgeSourceOperation:
        _require_permission(_actor_context(actor), Permission.KNOWLEDGE_SOURCE_EDIT)
        normalized_identity = expected_preview_identity.strip()
        if (
            len(normalized_identity) != 64
            or any(character not in "0123456789abcdef" for character in normalized_identity)
        ):
            raise ValueError("expected_preview_identity is invalid")
        normalized_reason = _nonblank(reason, "reason", maximum=2_000)
        normalized_key = _nonblank(idempotency_key, "idempotency_key", maximum=255)
        preview = self._workbooks.get_preview(
            source_id=source_id,
            preview_id=preview_id,
        )
        if (
            preview is None
            or preview.state != "ready_to_apply"
            or preview.preview is None
            or preview.preview.preview_identity != normalized_identity
            or preview.expires_at <= self._now()
        ):
            raise KnowledgeSourceCommandRejectedError(
                code="metadata_workbook_preview_unavailable",
                detail=(
                    "The Metadata Workbook Import Preview is stale, conflicting, "
                    "expired, or already consumed."
                ),
            )
        request_sha256 = _request_sha256(
            {
                "schema_version": "metadata-workbook-apply-command.v2",
                "source_id": source_id,
                "preview_id": preview_id,
                "expected_preview_identity": normalized_identity,
                "expected_revision": expected_revision,
                "reason": normalized_reason,
            }
        )

        def persist_job(
            unit_of_work: KnowledgeSourceCommandUnitOfWork,
            _source_record: KnowledgeSourceRecord,
            operation: KnowledgeSourceOperation,
            admitted_at: datetime,
        ) -> None:
            workbook_uow = cast(Any, unit_of_work)
            current = workbook_uow.metadata_workbooks.get_preview(
                source_id=source_id,
                preview_id=preview_id,
            )
            if (
                current is None
                or current.state != "ready_to_apply"
                or current.preview is None
                or current.preview.preview_identity != normalized_identity
                or current.expires_at <= admitted_at
            ):
                raise ValueError("Metadata Workbook Preview became unavailable")
            workbook_uow.metadata_workbooks.enqueue_job(
                MetadataWorkbookJobV2(
                    job_id=str(uuid4()),
                    operation_id=operation.operation_id,
                    source_id=source_id,
                    document_id=current.preview.document_id,
                    revision_id=current.preview.revision_id,
                    source_revision=operation.source_revision,
                    command="apply_preview",
                    resource_id=preview_id,
                    request_sha256=request_sha256,
                    expected_preview_identity=normalized_identity,
                    reason=normalized_reason,
                    state="READY",
                    fencing_token=0,
                    created_by=actor.subject,
                    created_at=admitted_at,
                    updated_at=admitted_at,
                )
            )
            workbook_uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="hybrid_metadata_workbook.apply_admitted",
                    target_type="metadata_workbook_import_preview",
                    target_id=preview_id,
                    occurred_at=admitted_at,
                    metadata={
                        "source_id": source_id,
                        "preview_id": preview_id,
                        "preview_identity": normalized_identity,
                        "operation_id": operation.operation_id,
                    },
                )
            )

        effect = cast(KnowledgeSourceAdmissionEffect, persist_job)
        operation, _created = self._commands.admit_async_command(
            source_id=source_id,
            action="edit_metadata_workbook",
            command="apply_metadata_workbook_import_preview",
            expected_revision=expected_revision,
            idempotency_key=normalized_key,
            request_sha256=request_sha256,
            context=_actor_context(actor),
            stage="metadata_workbook_apply_queued",
            admission_effect=effect,
            advance_source_revision=False,
        )
        return operation

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Metadata Workbook service clock must be timezone-aware")
        return value.astimezone(UTC)


def _actor_context(actor: AuditActorFacts) -> KnowledgeSourceCommandContext:
    return KnowledgeSourceCommandContext(
        operator_subject=actor.subject,
        permissions=tuple(Permission(value) for value in actor.permissions),
    )


def _require_permission(
    context: KnowledgeSourceCommandContext,
    permission: Permission,
) -> None:
    if permission not in context.permissions:
        raise KnowledgeSourceCommandRejectedError(
            code="permission_required",
            detail=f"The {permission.value} permission is required.",
        )


def _request_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _nonblank(value: str, field: str, *, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} is invalid")
    return normalized


def _workbook_filename(value: str) -> str:
    normalized = _nonblank(value, "filename", maximum=255)
    if Path(normalized).name != normalized or not normalized.lower().endswith(
        ".xlsx"
    ):
        raise ValueError("Metadata Workbook Preview requires one safe .xlsx filename")
    return normalized


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _audit_event(
    *,
    actor: AuditActorFacts,
    event_type: str,
    target_type: str,
    target_id: str,
    occurred_at: datetime,
    metadata: dict[str, object],
) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=str(uuid4()),
        category=AuditCategory.CONFIGURATION,
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        actor=actor,
        occurred_at=_timestamp(occurred_at),
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )


__all__ = ["KnowledgeSourceMetadataWorkbookService"]


_WORKBOOK_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_MAX_WORKBOOK_FILE_BYTES = 10 * 1024 * 1024
