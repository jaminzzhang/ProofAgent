"""Private Knowledge Worker for controlled metadata workbook imports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import ValidationError

from proof_agent.capabilities.knowledge.hybrid.metadata_import_jobs import (
    MetadataImportJob,
    MetadataImportJobClaim,
)
from proof_agent.capabilities.knowledge.hybrid.ports import KnowledgeArtifactStore
from proof_agent.capabilities.knowledge.hybrid.rule_units import project_rule_units
from proof_agent.capabilities.knowledge.hybrid.workbook import (
    WorkbookImportRecord,
    WorkbookImportRowIdentity,
    WorkbookKnownAnchor,
    WorkbookValidationError,
    create_metadata_review_for_row,
    import_metadata_workbook,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildResult,
    HybridInsuranceMetadataArtifact,
)
from proof_agent.capabilities.persistence.postgres.metadata_import_repository import (
    MetadataImportClaimRejectedError,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeSourceOperation,
)
from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.hybrid_documents import (
    StructuredKnowledgeDocumentArtifact,
)


class MetadataImportJobRepository(Protocol):
    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> MetadataImportJobClaim | None: ...

    def require_claim(self, claim: MetadataImportJobClaim) -> MetadataImportJob: ...


class MetadataImportWorkerOutcome(StrictFrozenModel):
    import_job_id: str
    operation_id: str
    source_id: str
    state: Literal["completed", "failed"]
    result_import_id: str | None = None
    error_code: str | None = None


class MetadataWorkbookImportWorker:
    """Validate one staged XLSX and atomically materialize its review batch."""

    def __init__(
        self,
        *,
        jobs: MetadataImportJobRepository,
        ingestion: Any,
        unit_of_work_factory: Callable[[], Any],
        artifact_store: KnowledgeArtifactStore,
        worker_id: str,
        lease_seconds: int = 60,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ownership_guard: Callable[[], bool] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("metadata import worker_id must be non-empty")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("metadata import lease is outside its bound")
        self._jobs = jobs
        self._ingestion = ingestion
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_store = artifact_store
        self._worker_id = worker_id.strip()
        self._lease_seconds = lease_seconds
        self._clock = clock
        self._ownership_guard = ownership_guard or (lambda: True)

    def run_once(self) -> MetadataImportWorkerOutcome | None:
        if not self._ownership_guard():
            return None
        claim = self._jobs.claim_next(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return None
        return self.process_claim(claim)

    def process_claim(
        self,
        claim: MetadataImportJobClaim,
    ) -> MetadataImportWorkerOutcome:
        if not self._ownership_guard():
            raise RuntimeError("Production worker role lease was lost")
        job = self._jobs.require_claim(claim)
        self._mark_running(job)
        try:
            result = _require_completed_candidate(
                self._ingestion,
                source_id=job.source_id,
                document_id=job.document_id,
                revision_id=job.revision_id,
            )
            original = self._artifact_store.get_exact(job.original_ref)
            _verify_exact_bytes(job.original_ref.sha256, job.original_ref.size_bytes, original)
            canonical = StructuredKnowledgeDocumentArtifact.model_validate_json(
                self._artifact_store.get_exact(result.canonical_ref)
            )
            metadata = HybridInsuranceMetadataArtifact.model_validate_json(
                self._artifact_store.get_exact(result.insurance_metadata_ref)
            )
            _validate_build_artifacts(result, canonical, metadata)
            drafts = project_rule_units(
                canonical,
                document_defaults=metadata.document_defaults,
                source_id=job.source_id,
            )
            if not drafts:
                raise WorkbookValidationError(
                    "completed build has no canonical Rule Unit anchors"
                )
            by_anchor = {draft.canonical_anchor: draft for draft in drafts}
            if len(by_anchor) != len(drafts):
                raise WorkbookValidationError(
                    "completed build contains duplicate canonical anchors"
                )
            pdf_by_anchor = {
                draft.canonical_anchor: draft for draft in metadata.pdf_drafts
            }
            if (
                len(pdf_by_anchor) != len(metadata.pdf_drafts)
                or not set(pdf_by_anchor).issubset(by_anchor)
            ):
                raise WorkbookValidationError(
                    "PDF metadata drafts diverge from canonical anchors"
                )
            imported = import_metadata_workbook(
                original,
                known_anchors=tuple(
                    WorkbookKnownAnchor(
                        source_id=job.source_id,
                        document_id=job.document_id,
                        revision_id=job.revision_id,
                        canonical_anchor=draft.canonical_anchor,
                    )
                    for draft in drafts
                ),
                artifact_store=self._artifact_store,
            )
            now = self._now()
            import_record = WorkbookImportRecord(
                import_id=imported.import_id,
                template_revision=imported.template_revision,
                source_id=job.source_id,
                document_id=job.document_id,
                revision_id=job.revision_id,
                created_by=job.created_by,
                created_at=now,
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
                create_metadata_review_for_row(
                    row=row,
                    import_record=import_record,
                    pdf_draft=pdf_by_anchor.get(row.canonical_anchor),
                    citation_uri=_citation_for_anchor(
                        by_anchor,
                        row.canonical_anchor,
                    ),
                )
                for row in imported.rows
            )
            self._commit_success(
                claim,
                job=job,
                result=result,
                import_record=import_record,
                reviews=reviews,
                completed_at=now,
            )
            return MetadataImportWorkerOutcome(
                import_job_id=job.import_job_id,
                operation_id=job.operation_id,
                source_id=job.source_id,
                state="completed",
                result_import_id=import_record.import_id,
            )
        except MetadataImportClaimRejectedError:
            raise
        except (WorkbookValidationError, ValidationError, ValueError, KeyError, LookupError):
            return self._commit_failure(
                claim,
                job=job,
                failure_code="metadata_workbook_invalid",
                safe_reason="The metadata workbook failed controlled validation.",
            )
        except Exception:
            return self._commit_failure(
                claim,
                job=job,
                failure_code="metadata_import_failed",
                safe_reason="The metadata workbook import could not be completed.",
            )

    def _mark_running(self, job: MetadataImportJob) -> None:
        now = self._now()
        with self._unit_of_work_factory() as uow:
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "running",
                        "stage": "metadata_validation",
                        "updated_at": _timestamp(now),
                    }
                )
            )
            uow.commit()

    def _commit_success(
        self,
        claim: MetadataImportJobClaim,
        *,
        job: MetadataImportJob,
        result: HybridArtifactBuildResult,
        import_record: WorkbookImportRecord,
        reviews: tuple[Any, ...],
        completed_at: datetime,
    ) -> None:
        with self._unit_of_work_factory() as uow:
            uow.metadata_imports.require_claim(claim)
            current_result = _require_completed_candidate(
                uow.hybrid_ingestion,
                source_id=job.source_id,
                document_id=job.document_id,
                revision_id=job.revision_id,
            )
            if current_result != result:
                raise WorkbookValidationError(
                    "Hybrid build changed before metadata review commit"
                )
            uow.metadata_reviews.put_many(reviews)
            source_record = uow.knowledge.get_source_record(job.source_id)
            if source_record is None:
                raise LookupError(job.source_id)
            source_version = uow.knowledge.save_source(
                source_record.source.model_copy(
                    update={
                        "source_draft_version_id": str(uuid4()),
                        "updated_at": _next_source_timestamp(
                            source_record.source.updated_at,
                            completed_at,
                        ),
                    }
                ),
                expected_revision=source_record.revision,
            )
            uow.metadata_imports.complete(
                claim,
                result_import_id=import_record.import_id,
            )
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "succeeded",
                        "stage": "metadata_import_completed",
                        "source_revision": source_version.revision,
                        "outcome_code": "metadata_import_completed",
                        "outcome_detail": (
                            f"Validated {len(reviews)} metadata review row(s)."
                        ),
                        "updated_at": _timestamp(completed_at),
                        "completed_at": _timestamp(completed_at),
                    }
                )
            )
            uow.audit.append(
                _audit_event(
                    job=job,
                    outcome=AuditOutcome.SUCCEEDED,
                    event_type="hybrid_metadata_workbook.imported",
                    occurred_at=completed_at,
                    metadata={
                        "source_id": job.source_id,
                        "document_id": job.document_id,
                        "revision_id": job.revision_id,
                        "operation_id": job.operation_id,
                        "import_id": import_record.import_id,
                        "row_count": len(reviews),
                        "content_sha256": job.content_sha256,
                    },
                )
            )
            uow.commit()

    def _commit_failure(
        self,
        claim: MetadataImportJobClaim,
        *,
        job: MetadataImportJob,
        failure_code: str,
        safe_reason: str,
    ) -> MetadataImportWorkerOutcome:
        now = self._now()
        with self._unit_of_work_factory() as uow:
            uow.metadata_imports.fail(
                claim,
                failure_code=failure_code,
                safe_reason=safe_reason,
            )
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "failed",
                        "stage": "metadata_import_failed",
                        "outcome_code": failure_code,
                        "outcome_detail": safe_reason,
                        "updated_at": _timestamp(now),
                        "completed_at": _timestamp(now),
                    }
                )
            )
            uow.audit.append(
                _audit_event(
                    job=job,
                    outcome=AuditOutcome.FAILED,
                    event_type="hybrid_metadata_workbook.import_failed",
                    occurred_at=now,
                    metadata={
                        "source_id": job.source_id,
                        "document_id": job.document_id,
                        "revision_id": job.revision_id,
                        "operation_id": job.operation_id,
                        "failure_code": failure_code,
                    },
                )
            )
            uow.commit()
        return MetadataImportWorkerOutcome(
            import_job_id=job.import_job_id,
            operation_id=job.operation_id,
            source_id=job.source_id,
            state="failed",
            error_code=failure_code,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metadata import worker clock must be timezone-aware")
        return value.astimezone(UTC)


def _required_operation(uow: Any, operation_id: str) -> KnowledgeSourceOperation:
    operation: KnowledgeSourceOperation | None = uow.operations.get(operation_id)
    if operation is None:
        raise LookupError(operation_id)
    return operation


def _require_completed_candidate(
    ingestion: Any,
    *,
    source_id: str,
    document_id: str,
    revision_id: str,
) -> HybridArtifactBuildResult:
    candidate = ingestion.get_document_candidate(
        source_id=source_id,
        document_id=document_id,
    )
    if (
        candidate is None
        or candidate.candidate_revision_id != revision_id
        or candidate.pending_revision_id is not None
    ):
        raise WorkbookValidationError(
            "metadata import revision is no longer the selected candidate"
        )
    records = tuple(
        record
        for record in ingestion.list_records_for_source(source_id)
        if record.build_request.document_id == document_id
        and record.build_request.revision_id == revision_id
        and record.job.state == "COMPLETED"
    )
    if len(records) != 1:
        raise WorkbookValidationError(
            "metadata import requires one completed exact build"
        )
    result: HybridArtifactBuildResult | None = ingestion.get_result(
        records[0].build_request.job_id
    )
    if result is None:
        raise WorkbookValidationError(
            "metadata import completed build result is unavailable"
        )
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
        raise WorkbookValidationError(
            "completed Hybrid build artifacts diverge from authority"
        )


def _citation_for_anchor(
    indexed: dict[str, Any],
    canonical_anchor: str | None,
) -> str:
    if canonical_anchor is None or canonical_anchor not in indexed:
        raise WorkbookValidationError(
            "workbook row has no governed canonical anchor"
        )
    return str(indexed[canonical_anchor].citation_uri)


def _verify_exact_bytes(expected_sha256: str, expected_size: int, content: bytes) -> None:
    if (
        len(content) != expected_size
        or hashlib.sha256(content).hexdigest() != expected_sha256
    ):
        raise WorkbookValidationError("metadata workbook artifact identity mismatch")


def _audit_event(
    *,
    job: MetadataImportJob,
    outcome: AuditOutcome,
    event_type: str,
    occurred_at: datetime,
    metadata: dict[str, object],
) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=str(
            uuid5(
                NAMESPACE_URL,
                f"proof-agent:{event_type}:{job.import_job_id}",
            )
        ),
        category=AuditCategory.CONFIGURATION,
        event_type=event_type,
        outcome=outcome,
        actor=AuditActorFacts(
            subject="knowledge-worker",
            identity_provider="internal-service",
            session_id=f"metadata-import:{job.import_job_id}",
        ),
        occurred_at=_timestamp(occurred_at),
        target_type="metadata_import_job",
        target_id=job.import_job_id,
        metadata=metadata,
    )


def _next_source_timestamp(current: str, now: datetime) -> str:
    current_value = datetime.fromisoformat(current.replace("Z", "+00:00"))
    if current_value.tzinfo is None or current_value.utcoffset() is None:
        raise ValueError("Knowledge Source updated_at must be timezone-aware")
    return _timestamp(max(now, current_value + timedelta(microseconds=1)))


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["MetadataImportWorkerOutcome", "MetadataWorkbookImportWorker"]
