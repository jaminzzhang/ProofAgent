"""Knowledge Worker for fenced Metadata Workbook V2 commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
from typing import Any, Literal, Protocol

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    InsuranceMetadataProfileRevision,
    InsuranceMetadataReviewSet,
    MetadataReviewConflictError,
    MetadataReviewValidationError,
)
from proof_agent.capabilities.knowledge.hybrid.metadata_workbook import (
    MetadataWorkbookExportAuthorityV2,
    MetadataWorkbookValidationError,
    MetadataWorkbookValidationIssueV2,
    MetadataWorkbookValidationReportV2,
    WorkbookRuleUnitInventoryItem,
    create_metadata_workbook_import_preview_v2,
    generate_metadata_workbook_v2,
)
from proof_agent.capabilities.knowledge.hybrid.metadata_workbook_jobs import (
    MetadataWorkbookJobClaimV2,
    MetadataWorkbookJobV2,
)
from proof_agent.capabilities.knowledge.hybrid.ports import KnowledgeArtifactStore
from proof_agent.capabilities.knowledge.hybrid.rule_units import project_rule_units
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildResult,
    HybridInsuranceMetadataArtifact,
)
from proof_agent.capabilities.persistence.postgres.metadata_workbook_repository import (
    MetadataWorkbookAuthorityConflictError,
    MetadataWorkbookJobClaimRejectedError,
)
from proof_agent.contracts import KnowledgeSourceOperation
from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.hybrid_documents import StructuredKnowledgeDocumentArtifact


WORKBOOK_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


class MetadataWorkbookJobAuthority(Protocol):
    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> MetadataWorkbookJobClaimV2 | None: ...

    def require_job_claim(
        self,
        claim: MetadataWorkbookJobClaimV2,
    ) -> MetadataWorkbookJobV2: ...


class MetadataWorkbookReviewReader(Protocol):
    def get_current_review_set(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> InsuranceMetadataReviewSet | None: ...

    def get_bound_profile(
        self,
        source_id: str,
        *,
        production: bool = False,
    ) -> InsuranceMetadataProfileRevision: ...


class MetadataWorkbookInventoryReader(Protocol):
    def rule_units(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> tuple[WorkbookRuleUnitInventoryItem, ...]: ...


class ProductionMetadataWorkbookInventoryReader:
    """Project a bounded Workbook inventory from one exact completed Hybrid build."""

    def __init__(self, *, ingestion: Any, artifact_store: KnowledgeArtifactStore) -> None:
        self._ingestion = ingestion
        self._artifact_store = artifact_store

    def rule_units(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> tuple[WorkbookRuleUnitInventoryItem, ...]:
        result = _require_completed_build(
            self._ingestion,
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
        )
        canonical = StructuredKnowledgeDocumentArtifact.model_validate_json(
            _exact_artifact(self._artifact_store, result.canonical_ref)
        )
        metadata = HybridInsuranceMetadataArtifact.model_validate_json(
            _exact_artifact(self._artifact_store, result.insurance_metadata_ref)
        )
        _require_matching_build(result, canonical, metadata)
        projected = project_rule_units(
            canonical,
            document_defaults=metadata.document_defaults,
            source_id=source_id,
        )
        if len(projected) > 10_000:
            raise MetadataWorkbookValidationError(
                "metadata_review_capacity_exceeded"
            )
        anchors = tuple(item.canonical_anchor for item in projected)
        if len(anchors) != len(set(anchors)):
            raise MetadataWorkbookValidationError(
                "metadata_workbook_duplicate_canonical_anchor"
            )
        return tuple(
            WorkbookRuleUnitInventoryItem(
                canonical_anchor=item.canonical_anchor,
                citation_uri=str(item.citation_uri),
                safe_preview=item.content[:512],
            )
            for item in projected
        )


class MetadataWorkbookWorkerOutcomeV2(StrictFrozenModel):
    job_id: str
    operation_id: str
    source_id: str
    command: Literal["generate_export", "create_preview", "apply_preview"]
    state: Literal["completed", "failed"]
    resource_id: str
    error_code: str | None = None


class MetadataWorkbookV2Worker:
    """Execute one exact Workbook command and commit through one fenced UoW."""

    def __init__(
        self,
        *,
        jobs: MetadataWorkbookJobAuthority,
        reviews: MetadataWorkbookReviewReader,
        workbooks: Any,
        inventory: MetadataWorkbookInventoryReader,
        unit_of_work_factory: Callable[[], Any],
        artifact_store: KnowledgeArtifactStore,
        environment_id: str,
        worker_id: str,
        lease_seconds: int = 60,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ownership_guard: Callable[[], bool] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("Metadata Workbook worker_id must be nonblank")
        if not environment_id.strip():
            raise ValueError("Metadata Workbook environment_id must be nonblank")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("Metadata Workbook lease is outside its bound")
        self._jobs = jobs
        self._reviews = reviews
        self._workbooks = workbooks
        self._inventory = inventory
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_store = artifact_store
        self._environment_id = environment_id.strip()
        self._worker_id = worker_id.strip()
        self._lease_seconds = lease_seconds
        self._clock = clock
        self._ownership_guard = ownership_guard or (lambda: True)

    def run_once(self) -> MetadataWorkbookWorkerOutcomeV2 | None:
        if not self._ownership_guard():
            return None
        claim = self._jobs.claim_next_job(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return None
        return self.process_claim(claim)

    def process_claim(
        self,
        claim: MetadataWorkbookJobClaimV2,
    ) -> MetadataWorkbookWorkerOutcomeV2:
        if not self._ownership_guard():
            raise RuntimeError("Production worker role lease was lost")
        job = self._jobs.require_job_claim(claim)
        self._mark_running(job)
        try:
            if job.command == "generate_export":
                self._generate_export(claim, job)
            elif job.command == "create_preview":
                self._create_preview(claim, job)
            else:
                self._apply_preview(claim, job)
            return MetadataWorkbookWorkerOutcomeV2(
                job_id=job.job_id,
                operation_id=job.operation_id,
                source_id=job.source_id,
                command=job.command,
                state="completed",
                resource_id=job.resource_id,
            )
        except MetadataWorkbookJobClaimRejectedError:
            raise
        except (
            MetadataWorkbookAuthorityConflictError,
            MetadataReviewConflictError,
            MetadataReviewValidationError,
            MetadataWorkbookValidationError,
            ValueError,
            KeyError,
            LookupError,
        ):
            return self._fail(
                claim,
                job,
                code="metadata_workbook_command_rejected",
                detail="The Metadata Workbook command failed controlled validation.",
            )
        except Exception:
            return self._fail(
                claim,
                job,
                code="metadata_workbook_command_failed",
                detail="The Metadata Workbook command could not be completed.",
            )

    def _generate_export(
        self,
        claim: MetadataWorkbookJobClaimV2,
        job: MetadataWorkbookJobV2,
    ) -> None:
        current = self._current_review_set(job)
        profile = self._reviews.get_bound_profile(job.source_id, production=True)
        rule_units = self._inventory.rule_units(
            source_id=job.source_id,
            document_id=job.document_id,
            revision_id=job.revision_id,
        )
        now = self._now()
        exported = generate_metadata_workbook_v2(
            export_id=job.resource_id,
            environment_id=self._environment_id,
            review_set=current,
            profile=profile,
            rule_units=rule_units,
            exported_at=now,
            expires_at=now + timedelta(days=30),
        )
        artifact_ref = self._artifact_store.put_immutable(
            key=f"metadata-workbooks/v2/{job.resource_id}/export.xlsx",
            content=exported.content,
            media_type=WORKBOOK_MEDIA_TYPE,
        )
        exact = self._artifact_store.get_exact(artifact_ref)
        _require_exact_artifact(artifact_ref.sha256, artifact_ref.size_bytes, exact)
        with self._unit_of_work_factory() as uow:
            uow.metadata_workbooks.require_job_claim(claim)
            persisted = uow.metadata_reviews.get_current_review_set(
                source_id=job.source_id,
                document_id=job.document_id,
                revision_id=job.revision_id,
            )
            if persisted != current:
                raise MetadataReviewConflictError(
                    "Metadata Review Set changed during Workbook Export"
                )
            uow.metadata_workbooks.put_export(
                exported.manifest,
                artifact_ref=artifact_ref,
                actor=job.created_by,
            )
            uow.metadata_workbooks.complete_job(claim, completed_at=now)
            self._complete_operation(
                uow,
                job,
                stage="metadata_workbook_export_completed",
                outcome_code="metadata_workbook_export_completed",
                detail="Metadata Workbook V2 Export is ready to download.",
                completed_at=now,
            )
            uow.commit()

    def _create_preview(
        self,
        claim: MetadataWorkbookJobClaimV2,
        job: MetadataWorkbookJobV2,
    ) -> None:
        if job.parent_resource_id is None or job.original_ref is None:
            raise MetadataReviewValidationError(
                "Metadata Workbook Preview job inputs are incomplete"
            )
        export = self._workbooks.get_export(
            source_id=job.source_id,
            export_id=job.parent_resource_id,
        )
        if export is None or export.state != "available":
            raise MetadataWorkbookAuthorityConflictError(
                "Metadata Workbook Export is unavailable"
            )
        returned = self._artifact_store.get_exact(job.original_ref)
        _require_exact_artifact(
            job.original_ref.sha256,
            job.original_ref.size_bytes,
            returned,
        )
        current = self._current_review_set(job)
        profile = self._reviews.get_bound_profile(job.source_id, production=True)
        now = self._now()
        try:
            preview = create_metadata_workbook_import_preview_v2(
                preview_id=job.resource_id,
                export_manifest=export.manifest,
                returned_content=returned,
                current_review_set=current,
                profile=profile,
                previewed_at=now,
            )
        except MetadataWorkbookValidationError as exc:
            self._commit_validation_report(claim, job, export, exc, completed_at=now)
            return
        with self._unit_of_work_factory() as uow:
            uow.metadata_workbooks.require_job_claim(claim)
            uow.metadata_workbooks.put_preview(
                preview,
                original_ref=job.original_ref,
                actor=job.created_by,
                expires_at=now + timedelta(days=30),
            )
            uow.metadata_workbooks.complete_job(claim, completed_at=now)
            self._complete_operation(
                uow,
                job,
                stage="metadata_workbook_preview_completed",
                outcome_code="metadata_workbook_preview_completed",
                detail=(
                    "Metadata Workbook Preview contains conflicts."
                    if preview.state == "conflicts"
                    else "Metadata Workbook Preview is ready to apply."
                ),
                completed_at=now,
            )
            uow.commit()

    def _commit_validation_report(
        self,
        claim: MetadataWorkbookJobClaimV2,
        job: MetadataWorkbookJobV2,
        export: MetadataWorkbookExportAuthorityV2,
        error: MetadataWorkbookValidationError,
        *,
        completed_at: datetime,
    ) -> None:
        if job.original_ref is None:
            raise MetadataReviewValidationError(
                "Metadata Workbook validation report has no original artifact"
            )
        code = _validation_code(error)
        report = MetadataWorkbookValidationReportV2(
            total_error_count=1,
            errors=(
                MetadataWorkbookValidationIssueV2(
                    code=code,
                    suggested_action_key=f"metadata_workbook.action.{code}",
                ),
            ),
        )
        with self._unit_of_work_factory() as uow:
            uow.metadata_workbooks.require_job_claim(claim)
            uow.metadata_workbooks.put_validation_report(
                source_id=job.source_id,
                export_id=export.manifest.export_id,
                preview_id=job.resource_id,
                original_ref=job.original_ref,
                report=report,
                actor=job.created_by,
                created_at=completed_at,
                expires_at=completed_at + timedelta(days=30),
            )
            uow.metadata_workbooks.complete_job(claim, completed_at=completed_at)
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "failed",
                        "stage": "metadata_workbook_preview_validation_failed",
                        "outcome_code": (
                            "metadata_workbook_preview_validation_failed"
                        ),
                        "outcome_detail": (
                            "Metadata Workbook validation completed with a safe report."
                        ),
                        "updated_at": _timestamp(completed_at),
                        "completed_at": _timestamp(completed_at),
                    }
                )
            )
            uow.commit()

    def _apply_preview(
        self,
        claim: MetadataWorkbookJobClaimV2,
        job: MetadataWorkbookJobV2,
    ) -> None:
        if job.expected_preview_identity is None or job.reason is None:
            raise MetadataReviewValidationError(
                "Metadata Workbook Apply job inputs are incomplete"
            )
        now = self._now()
        with self._unit_of_work_factory() as uow:
            uow.metadata_workbooks.require_job_claim(claim)
            committed = uow.metadata_workbooks.apply_preview(
                source_id=job.source_id,
                preview_id=job.resource_id,
                expected_preview_identity=job.expected_preview_identity,
                expected_source_revision=job.source_revision,
                actor=job.created_by,
                reason=job.reason,
                applied_at=now,
            )
            uow.metadata_workbooks.complete_job(claim, completed_at=now)
            self._complete_operation(
                uow,
                job,
                stage="metadata_workbook_apply_completed",
                outcome_code="metadata_workbook_apply_completed",
                detail="Metadata Workbook Preview was applied atomically.",
                completed_at=now,
                source_revision=committed.source_revision,
            )
            uow.commit()

    def _current_review_set(
        self,
        job: MetadataWorkbookJobV2,
    ) -> InsuranceMetadataReviewSet:
        current = self._reviews.get_current_review_set(
            source_id=job.source_id,
            document_id=job.document_id,
            revision_id=job.revision_id,
        )
        if current is None:
            raise MetadataReviewValidationError(
                "Metadata Workbook command requires a current Review Set"
            )
        return current

    def _mark_running(self, job: MetadataWorkbookJobV2) -> None:
        now = self._now()
        with self._unit_of_work_factory() as uow:
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "running",
                        "stage": f"metadata_workbook_{job.command}_running",
                        "updated_at": _timestamp(now),
                    }
                )
            )
            uow.commit()

    def _complete_operation(
        self,
        uow: Any,
        job: MetadataWorkbookJobV2,
        *,
        stage: str,
        outcome_code: str,
        detail: str,
        completed_at: datetime,
        source_revision: int | None = None,
    ) -> None:
        operation = _required_operation(uow, job.operation_id)
        uow.operations.save(
            operation.model_copy(
                update={
                    "status": "succeeded",
                    "stage": stage,
                    "source_revision": source_revision or operation.source_revision,
                    "outcome_code": outcome_code,
                    "outcome_detail": detail,
                    "updated_at": _timestamp(completed_at),
                    "completed_at": _timestamp(completed_at),
                }
            )
        )

    def _fail(
        self,
        claim: MetadataWorkbookJobClaimV2,
        job: MetadataWorkbookJobV2,
        *,
        code: str,
        detail: str,
    ) -> MetadataWorkbookWorkerOutcomeV2:
        now = self._now()
        with self._unit_of_work_factory() as uow:
            uow.metadata_workbooks.fail_job(
                claim,
                failure_code=code,
                safe_reason=detail,
                completed_at=now,
            )
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "failed",
                        "stage": "metadata_workbook_command_failed",
                        "outcome_code": code,
                        "outcome_detail": detail,
                        "updated_at": _timestamp(now),
                        "completed_at": _timestamp(now),
                    }
                )
            )
            uow.commit()
        return MetadataWorkbookWorkerOutcomeV2(
            job_id=job.job_id,
            operation_id=job.operation_id,
            source_id=job.source_id,
            command=job.command,
            state="failed",
            resource_id=job.resource_id,
            error_code=code,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Metadata Workbook worker clock must be timezone-aware")
        return value.astimezone(UTC)


def _required_operation(uow: Any, operation_id: str) -> KnowledgeSourceOperation:
    operation: KnowledgeSourceOperation | None = uow.operations.get(operation_id)
    if operation is None:
        raise LookupError(operation_id)
    return operation


def _require_completed_build(
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
        raise MetadataWorkbookValidationError(
            "metadata_workbook_revision_not_current_candidate"
        )
    records = tuple(
        record
        for record in ingestion.list_records_for_source(source_id)
        if record.build_request.document_id == document_id
        and record.build_request.revision_id == revision_id
        and record.job.state == "COMPLETED"
    )
    if len(records) != 1:
        raise MetadataWorkbookValidationError(
            "metadata_workbook_completed_build_ambiguous"
        )
    result = ingestion.get_result(records[0].build_request.job_id)
    if result is None:
        raise MetadataWorkbookValidationError(
            "metadata_workbook_completed_build_unavailable"
        )
    if not isinstance(result, HybridArtifactBuildResult):
        raise MetadataWorkbookValidationError(
            "metadata_workbook_completed_build_invalid"
        )
    return result


def _exact_artifact(
    artifact_store: KnowledgeArtifactStore,
    ref: Any,
) -> bytes:
    if ref.media_type != "application/json":
        raise MetadataWorkbookValidationError(
            "metadata_workbook_build_artifact_media_type_invalid"
        )
    content = artifact_store.get_exact(ref)
    _require_exact_artifact(ref.sha256, ref.size_bytes, content)
    return content


def _require_matching_build(
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
        raise MetadataWorkbookValidationError(
            "metadata_workbook_build_artifact_identity_invalid"
        )


def _require_exact_artifact(expected_sha256: str, expected_size: int, content: bytes) -> None:
    if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise MetadataWorkbookValidationError("metadata_workbook_artifact_identity_invalid")


def _validation_code(error: MetadataWorkbookValidationError) -> str:
    value = str(error).strip()
    if not value.startswith("metadata_workbook_") or not value.replace("_", "").isalnum():
        return "metadata_workbook_invalid"
    return value[:128]


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "MetadataWorkbookV2Worker",
    "MetadataWorkbookWorkerOutcomeV2",
    "ProductionMetadataWorkbookInventoryReader",
]
