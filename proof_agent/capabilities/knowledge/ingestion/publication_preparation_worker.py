"""Fenced private worker for expensive Hybrid publication preparation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from proof_agent.capabilities.knowledge.hybrid.publication import (
    PublicationCommit,
    PublicationConflict,
)
from proof_agent.capabilities.knowledge.hybrid.publication_jobs import (
    PublicationPreparationClaim,
    PublicationPreparationJob,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
from proof_agent.capabilities.persistence.postgres.publication_preparation_repository import (
    PublicationPreparationClaimRejectedError,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeSourceOperation,
    PreparedHybridKnowledgePublication,
)
from proof_agent.contracts._base import StrictFrozenModel


class HybridPublicationPreparer(Protocol):
    def prepare(
        self,
        *,
        source_id: str,
        validation_id: str,
        smoke_query: str,
        actor: str,
    ) -> PublicationCommit: ...


class PublicationPreparationWorkerOutcome(StrictFrozenModel):
    preparation_job_id: str
    operation_id: str
    source_id: str
    state: Literal["prepared", "failed"]
    validation_id: str | None = None
    fencing_token: int | None = None
    error_code: str | None = None


class PublicationPreparationWorker:
    """Move all model/S3/OpenSearch publication work behind one durable claim."""

    def __init__(
        self,
        *,
        jobs: Any,
        preparer: HybridPublicationPreparer,
        unit_of_work_factory: Callable[[], Any],
        worker_id: str,
        lease_seconds: int = 60,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ownership_guard: Callable[[], bool] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("publication preparation worker_id must be non-empty")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("publication preparation lease is outside its bound")
        self._jobs = jobs
        self._preparer = preparer
        self._unit_of_work_factory = unit_of_work_factory
        self._worker_id = worker_id.strip()
        self._lease_seconds = lease_seconds
        self._clock = clock
        self._ownership_guard = ownership_guard or (lambda: True)

    def run_once(self) -> PublicationPreparationWorkerOutcome | None:
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
        claim: PublicationPreparationClaim,
    ) -> PublicationPreparationWorkerOutcome:
        if not self._ownership_guard():
            raise RuntimeError("Production worker role lease was lost")
        job: PublicationPreparationJob = self._jobs.require_claim(claim)
        self._mark_running(job)
        try:
            commit = self._preparer.prepare(
                source_id=job.source_id,
                validation_id=job.validation_id,
                smoke_query=job.smoke_query,
                actor=job.created_by,
            )
            _validate_commit(job, commit)
            prepared = PreparedHybridKnowledgePublication(
                validation_id=job.validation_id,
                operation_id=job.operation_id,
                attempt_id=commit.attempt.attempt_id,
                fencing_token=commit.attempt.fencing_token,
                source_id=job.source_id,
                source_draft_version_id=job.source_draft_version_id,
                candidate_digest=commit.attempt.candidate_digest,
                generation_id=commit.attempt.generation_id,
                manifest_sha256=commit.manifest.root.root_sha256,
                staged_projection_id=stable_digest(
                    {
                        "attempt_id": commit.attempt.attempt_id,
                        "identity": commit.identity.model_dump(mode="json"),
                    }
                ),
                attestation_sha256=commit.attestation.attestation_sha256,
                smoke_result_sha256=commit.smoke_result_sha256,
                state="prepared",
                prepared_at=_timestamp(self._now()),
            )
            self._commit_success(claim, job=job, commit=commit, prepared=prepared)
            return PublicationPreparationWorkerOutcome(
                preparation_job_id=job.preparation_job_id,
                operation_id=job.operation_id,
                source_id=job.source_id,
                state="prepared",
                validation_id=prepared.validation_id,
                fencing_token=prepared.fencing_token,
            )
        except PublicationPreparationClaimRejectedError:
            raise
        except Exception as exc:
            code = (
                f"publication_{exc.code.lower()}"
                if isinstance(exc, PublicationConflict)
                else "publication_preparation_failed"
            )
            return self._commit_failure(
                claim,
                job=job,
                failure_code=code[:128],
            )

    def _mark_running(self, job: PublicationPreparationJob) -> None:
        now = self._now()
        with self._unit_of_work_factory() as uow:
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "running",
                        "stage": "publication_preparing",
                        "updated_at": _timestamp(now),
                    }
                )
            )
            uow.commit()

    def _commit_success(
        self,
        claim: PublicationPreparationClaim,
        *,
        job: PublicationPreparationJob,
        commit: PublicationCommit,
        prepared: PreparedHybridKnowledgePublication,
    ) -> None:
        now = self._now()
        with self._unit_of_work_factory() as uow:
            uow.publication_preparations.require_claim(claim)
            uow.prepared_publications.save_prepared(prepared)
            uow.publication_preparations.complete(
                claim,
                prepared_commit=commit,
            )
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "succeeded",
                        "stage": "publication_prepared",
                        "outcome_code": "publication_prepared",
                        "outcome_detail": (
                            "Publication validation and staged projection completed."
                        ),
                        "updated_at": _timestamp(now),
                        "completed_at": _timestamp(now),
                    }
                )
            )
            uow.audit.append(
                _audit_event(
                    job=job,
                    outcome=AuditOutcome.SUCCEEDED,
                    event_type="hybrid_publication.prepared",
                    occurred_at=now,
                    metadata={
                        "source_id": job.source_id,
                        "operation_id": job.operation_id,
                        "validation_id": prepared.validation_id,
                        "attempt_id": prepared.attempt_id,
                        "fencing_token": prepared.fencing_token,
                        "manifest_sha256": prepared.manifest_sha256,
                        "attestation_sha256": prepared.attestation_sha256,
                        "smoke_result_sha256": prepared.smoke_result_sha256,
                    },
                )
            )
            uow.commit()

    def _commit_failure(
        self,
        claim: PublicationPreparationClaim,
        *,
        job: PublicationPreparationJob,
        failure_code: str,
    ) -> PublicationPreparationWorkerOutcome:
        now = self._now()
        safe_reason = "Publication preparation could not be completed."
        with self._unit_of_work_factory() as uow:
            uow.publication_preparations.fail(
                claim,
                failure_code=failure_code,
                safe_reason=safe_reason,
            )
            operation = _required_operation(uow, job.operation_id)
            uow.operations.save(
                operation.model_copy(
                    update={
                        "status": "failed",
                        "stage": "publication_preparation_failed",
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
                    event_type="hybrid_publication.preparation_failed",
                    occurred_at=now,
                    metadata={
                        "source_id": job.source_id,
                        "operation_id": job.operation_id,
                        "validation_id": job.validation_id,
                        "failure_code": failure_code,
                    },
                )
            )
            uow.commit()
        return PublicationPreparationWorkerOutcome(
            preparation_job_id=job.preparation_job_id,
            operation_id=job.operation_id,
            source_id=job.source_id,
            state="failed",
            error_code=failure_code,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "publication preparation worker clock must be timezone-aware"
            )
        return value.astimezone(UTC)


def _validate_commit(
    job: PublicationPreparationJob,
    commit: PublicationCommit,
) -> None:
    attempt = commit.attempt
    if (
        attempt.source_id != job.source_id
        or attempt.source_draft_version_id != job.source_draft_version_id
        or attempt.validation_id != job.validation_id
        or attempt.fencing_token < 1
        or commit.manifest.root.source_id != job.source_id
        or commit.attestation.publication_attempt_id != attempt.attempt_id
        or commit.smoke_result_sha256 == "0" * 64
    ):
        raise PublicationConflict("PREPARED_IDENTITY_MISMATCH")


def _required_operation(uow: Any, operation_id: str) -> KnowledgeSourceOperation:
    operation: KnowledgeSourceOperation | None = uow.operations.get(operation_id)
    if operation is None:
        raise LookupError(operation_id)
    return operation


def _audit_event(
    *,
    job: PublicationPreparationJob,
    outcome: AuditOutcome,
    event_type: str,
    occurred_at: datetime,
    metadata: dict[str, object],
) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=str(
            uuid5(
                NAMESPACE_URL,
                f"proof-agent:{event_type}:{job.preparation_job_id}",
            )
        ),
        category=AuditCategory.CONFIGURATION,
        event_type=event_type,
        outcome=outcome,
        actor=AuditActorFacts(
            subject="knowledge-worker",
            identity_provider="internal-service",
            session_id=f"publication-preparation:{job.preparation_job_id}",
        ),
        occurred_at=_timestamp(occurred_at),
        target_type="publication_preparation_job",
        target_id=job.preparation_job_id,
        metadata=metadata,
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "PublicationPreparationWorker",
    "PublicationPreparationWorkerOutcome",
]
