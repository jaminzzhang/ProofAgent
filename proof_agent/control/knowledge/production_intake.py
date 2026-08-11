"""Production Hybrid PDF admission behind exact storage and transactional authorities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Protocol
from uuid import UUID, uuid4

from proof_agent.capabilities.knowledge.hybrid.intake import (
    preflight_hybrid_pdf,
    quarantine_hybrid_upload,
)
from proof_agent.capabilities.knowledge.hybrid.ports import KnowledgeArtifactStore
from proof_agent.capabilities.knowledge.ingestion.contracts import HybridIntakeLimits
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridPrivateParserBuildConfig,
    hybrid_build_request_sha256,
)
from proof_agent.control.knowledge.application import KnowledgeSourceCommandContext
from proof_agent.control.knowledge.ingestion_service import (
    KnowledgeSourceAdmissionEffect,
    KnowledgeSourceIngestionService,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeSource,
    KnowledgeSourceIntakeCapability,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
    KnowledgeSourceProviderCapability,
    KnowledgeSourceProviderReadiness,
    Permission,
)


class HybridIntakeKnowledgeRepository(Protocol):
    def get_knowledge_source(self, source_id: str) -> KnowledgeSource | None: ...

    def resolve_version(self, asset_id: str, *, version_id: str | None = None) -> Any: ...


class HybridIntakeIngestionRepository(Protocol):
    def enqueue(
        self,
        request: HybridArtifactBuildRequest,
        *,
        operation_id: str | None = None,
        filename: str = "document.pdf",
        uploaded_by: str = "system",
        replacement: bool = False,
    ) -> Any: ...

    def list_active_records_for_source(self, source_id: str) -> tuple[Any, ...]: ...

    def get_record(self, job_id: str) -> Any | None: ...

    def get_document_candidate(
        self,
        *,
        source_id: str,
        document_id: str,
    ) -> Any | None: ...

    def get_result(self, job_id: str) -> Any | None: ...

    def manual_retry(
        self,
        *,
        job_id: str,
        requested_by: str,
        operation_id: str | None = None,
        touch_source: bool = True,
    ) -> Any: ...

    def request_cancel(
        self,
        *,
        job_id: str,
        requested_by: str,
        touch_source: bool = True,
    ) -> Any: ...


class HybridStreamingArtifactStore(KnowledgeArtifactStore, Protocol):
    def put_immutable_stream(
        self,
        *,
        key: str,
        content: BinaryIO,
        media_type: str,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> Any: ...


class HybridIntakeUnitOfWork(Protocol):
    knowledge: Any
    hybrid_ingestion: Any
    audit: Any
    operations: Any

    def __enter__(self) -> "HybridIntakeUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


@dataclass(frozen=True)
class HybridPdfAdmission:
    source: KnowledgeSource
    request: HybridArtifactBuildRequest
    filename: str
    page_count: int
    uploaded_by: str
    created_at: str


class HybridKnowledgeSourceSummaryReader:
    def __init__(self, ingestion: HybridIntakeIngestionRepository) -> None:
        self._ingestion = ingestion

    def summary_for_source(self, source_id: str) -> Mapping[str, int]:
        records = self._ingestion.list_active_records_for_source(source_id)
        return {
            "documents": len({item.build_request.document_id for item in records}),
            "ready": sum(item.job.state == "COMPLETED" for item in records),
            "review_required": sum(
                item.job.state == "REVIEW_REQUIRED" for item in records
            ),
            "retryable_ingestion": sum(
                item.job.state == "CANCELLED"
                or (
                    item.job.state == "FAILED"
                    and item.job.failure_classification == "recoverable_exhausted"
                )
                for item in records
            ),
            "cancellable_ingestion": sum(
                item.job.state
                in {"READY", "LEASED", "RETRY_SCHEDULED"}
                for item in records
            ),
            "replacement_required": sum(
                item.job.state == "FAILED"
                and item.job.failure_classification == "non_recoverable"
                for item in records
            ),
        }


def hybrid_knowledge_source_provider_capability(
    *,
    readiness_revision: str | None = None,
) -> KnowledgeSourceProviderCapability:
    """Return the sanitized API capability for the composed Hybrid provider."""

    limits = HybridIntakeLimits()
    return KnowledgeSourceProviderCapability(
        provider="hybrid_index",
        creation_supported=True,
        intake=KnowledgeSourceIntakeCapability(
            content_types=("application/pdf",),
            max_file_bytes=limits.max_file_bytes,
            max_batch_files=1,
            max_source_documents=limits.max_source_documents,
        ),
        features=(
            "documents",
            "document_revisions",
            "metadata_workbook_v2",
            "metadata_reviews",
            "publication",
            "operations",
            "audit",
        ),
        readiness=KnowledgeSourceProviderReadiness(
            state="ready",
            revision=readiness_revision,
        ),
    )


class ProductionHybridKnowledgeIntakeService:
    """Admit safe PDFs without making local files or environment secrets authoritative."""

    def __init__(
        self,
        *,
        knowledge: HybridIntakeKnowledgeRepository,
        ingestion: HybridIntakeIngestionRepository,
        unit_of_work_factory: Callable[[], HybridIntakeUnitOfWork],
        artifact_store: HybridStreamingArtifactStore,
        build_config: HybridPrivateParserBuildConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._knowledge = knowledge
        self._ingestion = ingestion
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_store = artifact_store
        self._build_config = build_config
        self._clock = clock
        self._commands = KnowledgeSourceIngestionService(
            unit_of_work_factory=unit_of_work_factory,
            provider_capability=hybrid_knowledge_source_provider_capability(),
            summary_reader=HybridKnowledgeSourceSummaryReader(ingestion),
            clock=clock,
        )

    def create_source(
        self,
        *,
        source_id: str,
        name: str,
        params: Mapping[str, object],
        actor: AuditActorFacts,
    ) -> KnowledgeSource:
        normalized_name = _nonblank(name, "name", maximum=255)
        limits = HybridIntakeLimits.model_validate(dict(params), strict=True)
        now = _timestamp(self._clock())
        source = KnowledgeSource(
            source_id=_safe_source_id(source_id),
            name=normalized_name,
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params=limits.model_dump(mode="json"),
            source_draft_version_id=str(uuid4()),
            created_at=now,
            updated_at=now,
        )
        with self._unit_of_work_factory() as uow:
            uow.knowledge.save_source(source, expected_revision=0)
            uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="knowledge_source.created",
                    target_type="knowledge_source",
                    target_id=source.source_id,
                    occurred_at=now,
                    metadata={"provider": "hybrid_index"},
                )
            )
            uow.commit()
        return source

    def admit_pdf(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        actor: AuditActorFacts,
    ) -> HybridPdfAdmission:
        if type(content) is not bytes:
            raise ValueError("Hybrid Index PDF content must be exact bytes")
        return self.admit_pdf_stream(
            source_id=source_id,
            filename=filename,
            content_type=content_type,
            content=BytesIO(content),
            actor=actor,
        )

    def admit_pdf_stream(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        actor: AuditActorFacts,
    ) -> HybridPdfAdmission:
        source = self._knowledge.get_knowledge_source(source_id)
        if (
            source is None
            or source.provider != "hybrid_index"
            or source.lifecycle_state is not KnowledgeSourceLifecycleState.ACTIVE
        ):
            raise KeyError(source_id)
        limits = HybridIntakeLimits.model_validate(dict(source.params), strict=True)
        normalized_filename = _pdf_filename(filename)
        normalized_content_type = content_type.partition(";")[0].strip().lower()
        if normalized_content_type != "application/pdf":
            raise ValueError("Hybrid Index uploads require application/pdf")
        with quarantine_hybrid_upload(
            content,
            max_file_bytes=limits.max_file_bytes,
        ) as quarantined:
            preflight = preflight_hybrid_pdf(quarantined.path, limits=limits)
            if (
                preflight.source_size_bytes != quarantined.size_bytes
                or preflight.source_sha256 != quarantined.sha256
            ):
                raise ValueError("Hybrid PDF preflight identity diverged from upload quarantine")

            job_id = str(uuid4())
            document_id = str(uuid4())
            revision_id = str(uuid4())
            request_identity = f"{source.source_id}:{document_id}:{revision_id}"
            intake_identity = hashlib.sha256(
                _canonical_json(
                    {
                        "source_id": source.source_id,
                        "document_id": document_id,
                        "revision_id": revision_id,
                        "source_sha256": preflight.source_sha256,
                        "parser_revision": self._build_config.parser_revision,
                        "model_digests": self._build_config.model_digests,
                        "configuration_sha256": self._build_config.configuration_sha256,
                    }
                )
            ).hexdigest()
            with quarantined.path.open("rb") as exact_stream:
                original_ref = self._artifact_store.put_immutable_stream(
                    key=f"hybrid/{preflight.source_sha256}/{intake_identity}/original.pdf",
                    content=exact_stream,
                    media_type="application/pdf",
                    expected_sha256=preflight.source_sha256,
                    expected_size_bytes=preflight.source_size_bytes,
                )
        request = HybridArtifactBuildRequest(
            job_id=job_id,
            request_identity=request_identity,
            source_id=source.source_id,
            document_id=document_id,
            revision_id=revision_id,
            original_ref=original_ref,
            page_numbers=tuple(range(1, preflight.page_count + 1)),
            parser_revision=self._build_config.parser_revision,
            model_digests=self._build_config.model_digests,
            configuration_sha256=self._build_config.configuration_sha256,
        )
        request = request.model_copy(
            update={"request_sha256": hybrid_build_request_sha256(request)}
        )

        current_version = self._knowledge.resolve_version(source.source_id)
        if current_version is None:
            raise KeyError(source.source_id)
        now = _timestamp(self._clock())
        updated_source = source.model_copy(
            update={
                "updated_at": now,
            }
        )
        with self._unit_of_work_factory() as uow:
            uow.knowledge.save_source(
                updated_source,
                expected_revision=current_version.revision,
            )
            uow.hybrid_ingestion.enqueue(
                request,
                filename=normalized_filename,
                uploaded_by=actor.subject,
            )
            uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="hybrid_pdf.admitted",
                    target_type="hybrid_ingestion_job",
                    target_id=job_id,
                    occurred_at=now,
                    metadata={
                        "source_id": source.source_id,
                        "document_id": document_id,
                        "revision_id": revision_id,
                        "page_count": preflight.page_count,
                        "size_bytes": preflight.source_size_bytes,
                        "content_sha256": preflight.source_sha256,
                    },
                )
            )
            uow.commit()
        return HybridPdfAdmission(
            source=updated_source,
            request=request,
            filename=normalized_filename,
            page_count=preflight.page_count,
            uploaded_by=actor.subject,
            created_at=now,
        )

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
    ) -> KnowledgeSourceOperation:
        """Admit one new stable document through the V1 command authority."""

        return self._admit_pdf_command(
            source_id=source_id,
            document_id=None,
            filename=filename,
            content_type=content_type,
            content=content,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

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
    ) -> KnowledgeSourceOperation:
        """Admit an immutable revision for one existing stable document."""

        return self._admit_pdf_command(
            source_id=source_id,
            document_id=str(UUID(document_id)),
            filename=filename,
            content_type=content_type,
            content=content,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def _admit_pdf_command(
        self,
        *,
        source_id: str,
        document_id: str | None,
        filename: str,
        content_type: str,
        content: BinaryIO,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation:
        source = self._knowledge.get_knowledge_source(source_id)
        if (
            source is None
            or source.provider != "hybrid_index"
            or source.lifecycle_state is not KnowledgeSourceLifecycleState.ACTIVE
        ):
            raise KeyError(source_id)
        limits = HybridIntakeLimits.model_validate(dict(source.params), strict=True)
        normalized_filename = _pdf_filename(filename)
        normalized_content_type = content_type.partition(";")[0].strip().lower()
        if normalized_content_type != "application/pdf":
            raise ValueError("Hybrid Index uploads require application/pdf")
        normalized_idempotency_key = _nonblank(
            idempotency_key,
            "idempotency_key",
            maximum=255,
        )
        command = "upload_document" if document_id is None else "replace_document"
        with quarantine_hybrid_upload(
            content,
            max_file_bytes=limits.max_file_bytes,
        ) as quarantined:
            preflight = preflight_hybrid_pdf(quarantined.path, limits=limits)
            if (
                preflight.source_size_bytes != quarantined.size_bytes
                or preflight.source_sha256 != quarantined.sha256
            ):
                raise ValueError(
                    "Hybrid PDF preflight identity diverged from upload quarantine"
                )
            request_sha256 = hashlib.sha256(
                _canonical_json(
                    {
                        "schema_version": "hybrid-intake-command.v1",
                        "command": command,
                        "source_id": source.source_id,
                        "document_id": document_id,
                        "filename": normalized_filename,
                        "content_type": normalized_content_type,
                        "content_sha256": preflight.source_sha256,
                        "size_bytes": preflight.source_size_bytes,
                        "expected_revision": expected_revision,
                        "parser_revision": self._build_config.parser_revision,
                        "model_digests": self._build_config.model_digests,
                        "configuration_sha256": self._build_config.configuration_sha256,
                    }
                )
            ).hexdigest()
            with quarantined.path.open("rb") as exact_stream:
                original_ref = self._artifact_store.put_immutable_stream(
                    key=(
                        f"hybrid/{preflight.source_sha256}/"
                        f"{request_sha256}/original.pdf"
                    ),
                    content=exact_stream,
                    media_type="application/pdf",
                    expected_sha256=preflight.source_sha256,
                    expected_size_bytes=preflight.source_size_bytes,
                )

        admitted_document_id = document_id or str(uuid4())
        revision_id = str(uuid4())
        job_id = str(uuid4())
        request_identity = (
            f"{source.source_id}:{admitted_document_id}:{revision_id}"
        )
        build_request = HybridArtifactBuildRequest(
            job_id=job_id,
            request_identity=request_identity,
            source_id=source.source_id,
            document_id=admitted_document_id,
            revision_id=revision_id,
            original_ref=original_ref,
            page_numbers=tuple(range(1, preflight.page_count + 1)),
            parser_revision=self._build_config.parser_revision,
            model_digests=self._build_config.model_digests,
            configuration_sha256=self._build_config.configuration_sha256,
        )
        build_request = build_request.model_copy(
            update={"request_sha256": hybrid_build_request_sha256(build_request)}
        )

        def persist_work(
            unit_of_work: Any,
            source_record: Any,
            operation: KnowledgeSourceOperation,
            admitted_at: datetime,
        ) -> None:
            del source_record
            unit_of_work.hybrid_ingestion.enqueue(
                build_request,
                operation_id=operation.operation_id,
                filename=normalized_filename,
                uploaded_by=actor.subject,
                replacement=document_id is not None,
            )
            unit_of_work.audit.append(
                _audit_event(
                    actor=actor,
                    event_type=f"hybrid_pdf.{command}.admitted",
                    target_type="hybrid_ingestion_job",
                    target_id=job_id,
                    occurred_at=_timestamp(admitted_at),
                    metadata={
                        "source_id": source.source_id,
                        "document_id": admitted_document_id,
                        "revision_id": revision_id,
                        "operation_id": operation.operation_id,
                        "page_count": preflight.page_count,
                        "size_bytes": preflight.source_size_bytes,
                        "content_sha256": preflight.source_sha256,
                    },
                )
            )

        admission_effect: KnowledgeSourceAdmissionEffect = persist_work
        operation, _created = self._commands.admit_async_command(
            source_id=source.source_id,
            action=command,
            command=command,
            expected_revision=expected_revision,
            idempotency_key=normalized_idempotency_key,
            request_sha256=request_sha256,
            context=KnowledgeSourceCommandContext(
                operator_subject=actor.subject,
                permissions=tuple(Permission(value) for value in actor.permissions),
            ),
            stage="ingestion_queued",
            admission_effect=admission_effect,
        )
        return operation

    def retry_ingestion(
        self,
        *,
        source_id: str,
        job_id: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation:
        return self._admit_job_command(
            source_id=source_id,
            job_id=job_id,
            command="retry_ingestion",
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def cancel_ingestion(
        self,
        *,
        source_id: str,
        job_id: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation:
        return self._admit_job_command(
            source_id=source_id,
            job_id=job_id,
            command="cancel_ingestion",
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def _admit_job_command(
        self,
        *,
        source_id: str,
        job_id: str,
        command: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation:
        record = self._ingestion.get_record(job_id)
        if record is None or record.build_request.source_id != source_id:
            raise KeyError(job_id)
        request_sha256 = hashlib.sha256(
            _canonical_json(
                {
                    "schema_version": "hybrid-job-command.v1",
                    "command": command,
                    "source_id": source_id,
                    "job_id": job_id,
                    "expected_revision": expected_revision,
                }
            )
        ).hexdigest()

        def persist_command(
            unit_of_work: Any,
            source_record: Any,
            operation: KnowledgeSourceOperation,
            admitted_at: datetime,
        ) -> None:
            del source_record
            if command == "retry_ingestion":
                unit_of_work.hybrid_ingestion.manual_retry(
                    job_id=job_id,
                    requested_by=actor.subject,
                    operation_id=operation.operation_id,
                    touch_source=False,
                )
            else:
                unit_of_work.hybrid_ingestion.request_cancel(
                    job_id=job_id,
                    requested_by=actor.subject,
                    touch_source=False,
                )
                unit_of_work.operations.save(
                    operation.model_copy(
                        update={
                            "status": "succeeded",
                            "stage": "cancellation_requested",
                            "outcome_code": "cancellation_requested",
                            "outcome_detail": (
                                "The ingestion cancellation request was accepted."
                            ),
                            "updated_at": _timestamp(admitted_at),
                            "completed_at": _timestamp(admitted_at),
                        }
                    )
                )
            unit_of_work.audit.append(
                _audit_event(
                    actor=actor,
                    event_type=f"hybrid_ingestion.{command}.admitted",
                    target_type="hybrid_ingestion_job",
                    target_id=job_id,
                    occurred_at=_timestamp(admitted_at),
                    metadata={
                        "source_id": source_id,
                        "operation_id": operation.operation_id,
                    },
                )
            )

        admission_effect: KnowledgeSourceAdmissionEffect = persist_command
        operation, _created = self._commands.admit_async_command(
            source_id=source_id,
            action=command,
            command=command,
            expected_revision=expected_revision,
            idempotency_key=_nonblank(
                idempotency_key,
                "idempotency_key",
                maximum=255,
            ),
            request_sha256=request_sha256,
            context=KnowledgeSourceCommandContext(
                operator_subject=actor.subject,
                permissions=tuple(Permission(value) for value in actor.permissions),
            ),
            stage="retry_queued" if command == "retry_ingestion" else "cancellation_queued",
            admission_effect=admission_effect,
        )
        return operation


def _audit_event(
    *,
    actor: AuditActorFacts,
    event_type: str,
    target_type: str,
    target_id: str,
    occurred_at: str,
    metadata: Mapping[str, object],
) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=str(uuid4()),
        category=AuditCategory.CONFIGURATION,
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        actor=actor,
        occurred_at=occurred_at,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )


def _safe_source_id(value: str) -> str:
    normalized = _nonblank(value, "source_id", maximum=128)
    if not normalized[0].isalnum() or any(
        not (character.isalnum() or character in "_-") for character in normalized
    ):
        raise ValueError("source_id contains unsupported characters")
    return normalized


def _pdf_filename(value: str) -> str:
    normalized = _nonblank(value, "filename", maximum=255)
    if Path(normalized).name != normalized or not normalized.lower().endswith(".pdf"):
        raise ValueError("Hybrid Index uploads require one safe .pdf filename")
    return normalized


def _nonblank(value: str, field: str, *, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _timestamp(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("Hybrid intake clock must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


__all__ = [
    "HybridKnowledgeSourceSummaryReader",
    "HybridPdfAdmission",
    "ProductionHybridKnowledgeIntakeService",
    "hybrid_knowledge_source_provider_capability",
]
