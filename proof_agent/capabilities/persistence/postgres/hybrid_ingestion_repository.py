from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.knowledge.ingestion.contracts import HybridIntakeLimits
from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
    write_connection,
)

from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridKnowledgeJob,
    HybridKnowledgeJobClaim,
    HybridKnowledgeJobRequest,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridArtifactBuildResult,
    HybridInsuranceMetadataArtifact,
    hybrid_build_request_sha256,
    validate_hybrid_artifact_build_result,
)
from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    InsuranceMetadataReviewSet,
    create_insurance_metadata_review_set,
)
from proof_agent.capabilities.knowledge.hybrid.rule_units import project_rule_units
from proof_agent.capabilities.persistence.postgres.schema import (
    hybrid_document_candidates,
    hybrid_ingestion_jobs,
    knowledge_sources,
)
from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_ingestion_attempt_repository import (
    PostgresKnowledgeIngestionAttemptRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_repository import (
    PostgresKnowledgeSourceOperationRepository,
)
from proof_agent.capabilities.persistence.postgres.metadata_review_repository import (
    PostgresInsuranceMetadataReviewRepository,
)
from proof_agent.contracts.agent_configuration import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
)
from proof_agent.contracts.hybrid_documents import StructuredKnowledgeDocumentArtifact
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.contracts.knowledge_operations import KnowledgeIngestionAttempt


class HybridIngestionConflictError(RuntimeError):
    pass


class HybridIngestionClaimRejectedError(RuntimeError):
    pass


class HybridIngestionCancellationRejectedError(RuntimeError):
    pass


class HybridIngestionRetryRejectedError(RuntimeError):
    pass


class ExactHybridReviewArtifactReader(Protocol):
    def get_exact(self, ref: ExactArtifactRef) -> bytes: ...


@dataclass(frozen=True)
class HybridIngestionRecord:
    job: HybridKnowledgeJob
    build_request: HybridArtifactBuildRequest
    filename: str
    uploaded_by: str


@dataclass(frozen=True)
class HybridDocumentCandidate:
    source_id: str
    document_id: str
    candidate_revision_id: str | None
    pending_revision_id: str | None
    updated_at: datetime


class PostgresHybridIngestionRepository:
    """Fenced PostgreSQL queue and result authority for private PDF parsing."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        clock: Callable[[], datetime] | None = None,
        artifact_store: ExactHybridReviewArtifactReader | None = None,
    ) -> None:
        self._connection_source = connection_source
        self._clock = clock or (lambda: datetime.now(UTC))
        self._artifact_store = artifact_store
        self._reference_profile_source_ids: frozenset[str] = frozenset()
        self._reference_profile_source_ids_configured = False

    def configure_artifact_store(
        self, artifact_store: ExactHybridReviewArtifactReader
    ) -> None:
        """Bind the exact reader once when composing the production worker."""

        if self._artifact_store is not None and self._artifact_store is not artifact_store:
            raise ValueError("Hybrid ingestion artifact reader is already configured")
        self._artifact_store = artifact_store

    def configure_reference_profile_source_ids(
        self, source_ids: tuple[str, ...]
    ) -> None:
        """Allow reference-only Profiles for an explicit local-environment allowlist."""

        if any(not source_id.strip() for source_id in source_ids):
            raise ValueError("Reference Profile Source IDs must be non-empty")
        resolved = frozenset(source_id.strip() for source_id in source_ids)
        if (
            self._reference_profile_source_ids_configured
            and resolved != self._reference_profile_source_ids
        ):
            raise ValueError("Reference Profile Source IDs are already configured")
        self._reference_profile_source_ids = resolved
        self._reference_profile_source_ids_configured = True

    def _metadata_profile_requires_production(self, source_id: str) -> bool:
        return source_id not in self._reference_profile_source_ids

    def enqueue(
        self,
        request: HybridArtifactBuildRequest,
        *,
        operation_id: str | None = None,
        filename: str = "document.pdf",
        uploaded_by: str = "system",
        replacement: bool = False,
    ) -> HybridKnowledgeJob:
        if request.request_sha256 != hybrid_build_request_sha256(request):
            raise ValueError("Hybrid ingestion request digest does not match its payload")
        if (
            not filename.strip()
            or len(filename) > 255
            or not filename.lower().endswith(".pdf")
            or not uploaded_by.strip()
            or len(uploaded_by) > 512
        ):
            raise ValueError("Hybrid ingestion intake metadata is invalid")
        now = self._now()
        values = {
            "job_id": UUID(request.job_id),
            "operation_id": operation_id,
            "idempotency_key": request.job_id,
            "source_id": request.source_id,
            "document_id": UUID(request.document_id),
            "revision_id": UUID(request.revision_id),
            "request_identity": request.request_identity,
            "request_sha256": request.request_sha256,
            "request_json": request.model_dump(mode="json"),
            "filename": filename.strip(),
            "uploaded_by": uploaded_by.strip(),
            "state": "READY",
            "fencing_token": 0,
            "auto_retry_count": 0,
            "max_auto_retries": request.max_auto_retries,
            "next_attempt_initiation": "automatic",
            "created_at": now,
            "updated_at": now,
        }
        with write_connection(self._connection_source) as connection:
            source_payload = connection.execute(
                select(knowledge_sources.c.configuration_json)
                .where(knowledge_sources.c.source_id == request.source_id)
                .with_for_update()
            ).scalar_one_or_none()
            source = (
                None
                if source_payload is None
                else KnowledgeSource.model_validate(source_payload)
            )
            if (
                source is None
                or source.provider != "hybrid_index"
                or source.lifecycle_state is not KnowledgeSourceLifecycleState.ACTIVE
            ):
                raise ValueError("Hybrid ingestion requires an active Hybrid Knowledge Source")
            existing_row = connection.execute(
                select(hybrid_ingestion_jobs).where(
                    hybrid_ingestion_jobs.c.job_id == UUID(request.job_id)
                )
            ).mappings().one_or_none()
            if existing_row is not None:
                existing = _job_from_row(existing_row)
                if existing.request.request_sha256 == request.request_sha256:
                    return existing
                raise HybridIngestionConflictError("Hybrid ingestion identity conflict")
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:document_scope, 0))"
                ),
                {"document_scope": f"{request.source_id}\x1f{request.document_id}"},
            )
            candidate_row = connection.execute(
                select(hybrid_document_candidates)
                .where(
                    hybrid_document_candidates.c.source_id == request.source_id,
                    hybrid_document_candidates.c.document_id
                    == UUID(request.document_id),
                )
                .with_for_update()
            ).mappings().one_or_none()
            if replacement and candidate_row is None:
                raise LookupError("Hybrid replacement document was not found")
            if not replacement and candidate_row is not None:
                raise HybridIngestionConflictError(
                    "Hybrid document identity already exists"
                )
            if (
                candidate_row is not None
                and candidate_row["pending_revision_id"] is not None
            ):
                raise HybridIngestionConflictError(
                    "Hybrid document already has a pending revision"
                )
            limits = HybridIntakeLimits.model_validate(dict(source.params), strict=True)
            source_document_count = int(
                connection.execute(
                    select(func.count())
                    .select_from(hybrid_document_candidates)
                    .where(
                        hybrid_document_candidates.c.source_id == request.source_id
                    )
                ).scalar_one()
            )
            if (
                candidate_row is None
                and source_document_count >= limits.max_source_documents
            ):
                raise ValueError("Hybrid Knowledge Source document limit has been reached")
            inserted = connection.execute(
                postgres_insert(hybrid_ingestion_jobs)
                .values(**values)
                .on_conflict_do_nothing()
                .returning(hybrid_ingestion_jobs.c.job_id)
            ).scalar_one_or_none()
            if inserted is None:
                raise HybridIngestionConflictError("Hybrid ingestion identity conflict")
            if candidate_row is None:
                connection.execute(
                    sa.insert(hybrid_document_candidates).values(
                        source_id=request.source_id,
                        document_id=UUID(request.document_id),
                        candidate_revision_id=None,
                        pending_revision_id=UUID(request.revision_id),
                        updated_at=now,
                    )
                )
            else:
                changed = connection.execute(
                    update(hybrid_document_candidates)
                    .where(
                        hybrid_document_candidates.c.source_id == request.source_id,
                        hybrid_document_candidates.c.document_id
                        == UUID(request.document_id),
                        hybrid_document_candidates.c.pending_revision_id.is_(None),
                    )
                    .values(
                        pending_revision_id=UUID(request.revision_id),
                        updated_at=now,
                    )
                )
                if changed.rowcount != 1:
                    raise HybridIngestionConflictError(
                        "Hybrid document already has a pending revision"
                    )
        created = self.get(request.job_id)
        if created is None:
            raise RuntimeError("Hybrid ingestion job disappeared after admission")
        return created

    def get(self, job_id: str) -> HybridKnowledgeJob | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_ingestion_jobs).where(
                    hybrid_ingestion_jobs.c.job_id == UUID(job_id)
                )
            ).mappings().one_or_none()
        return None if row is None else _job_from_row(row)

    def get_result(self, job_id: str) -> HybridArtifactBuildResult | None:
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                select(hybrid_ingestion_jobs.c.result_json).where(
                    hybrid_ingestion_jobs.c.job_id == UUID(job_id)
                )
            ).scalar_one_or_none()
        return (
            None
            if payload is None
            else HybridArtifactBuildResult.model_validate_json(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
        )

    def get_document_candidate(
        self,
        *,
        source_id: str,
        document_id: str,
    ) -> HybridDocumentCandidate | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_document_candidates).where(
                    hybrid_document_candidates.c.source_id == source_id,
                    hybrid_document_candidates.c.document_id == UUID(document_id),
                )
            ).mappings().one_or_none()
        return None if row is None else _candidate_from_row(row)

    def list_candidate_records_for_source(
        self,
        source_id: str,
    ) -> tuple[HybridIngestionRecord, ...]:
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(
                select(hybrid_ingestion_jobs)
                .join(
                    hybrid_document_candidates,
                    sa.and_(
                        hybrid_document_candidates.c.source_id
                        == hybrid_ingestion_jobs.c.source_id,
                        hybrid_document_candidates.c.document_id
                        == hybrid_ingestion_jobs.c.document_id,
                        hybrid_document_candidates.c.candidate_revision_id
                        == hybrid_ingestion_jobs.c.revision_id,
                    ),
                )
                .where(hybrid_document_candidates.c.source_id == source_id)
                .order_by(hybrid_document_candidates.c.document_id)
            ).mappings()
        return tuple(_record_from_row(row) for row in rows)

    def request_cancel(
        self,
        *,
        job_id: str,
        requested_by: str,
        touch_source: bool = True,
    ) -> HybridKnowledgeJob:
        if not requested_by.strip() or len(requested_by) > 512:
            raise ValueError("Hybrid ingestion cancellation actor is invalid")
        now = self._now()
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_ingestion_jobs)
                .where(hybrid_ingestion_jobs.c.job_id == UUID(job_id))
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise LookupError("Hybrid ingestion job was not found")
            if row["state"] in {"CANCEL_REQUESTED", "CANCELLED"}:
                existing = _job_from_row(row)
                if existing.cancel_requested_by != requested_by:
                    raise HybridIngestionCancellationRejectedError(
                        "Hybrid ingestion cancellation actor does not match"
                    )
                return existing
            common = {
                "cancel_requested_at": now,
                "cancel_requested_by": requested_by,
                "updated_at": now,
            }
            if row["state"] in {"READY", "RETRY_SCHEDULED"}:
                values = {
                    **common,
                    "state": "CANCELLED",
                    "worker_id": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "next_attempt_at": None,
                    "cancelled_at": now,
                    "completed_at": now,
                }
            elif row["state"] == "CLAIMED":
                values = {**common, "state": "CANCEL_REQUESTED"}
            else:
                raise HybridIngestionCancellationRejectedError(
                    "Hybrid ingestion job is not cancellable"
                )
            connection.execute(
                update(hybrid_ingestion_jobs)
                .where(
                    hybrid_ingestion_jobs.c.job_id == UUID(job_id),
                    hybrid_ingestion_jobs.c.state == row["state"],
                    hybrid_ingestion_jobs.c.fencing_token == row["fencing_token"],
                )
                .values(**values)
            )
            if values["state"] == "CANCELLED":
                self._clear_pending_revision(
                    connection,
                    source_id=str(row["source_id"]),
                    document_id=row["document_id"],
                    revision_id=row["revision_id"],
                    now=now,
                )
            if touch_source:
                self._touch_source_revision(
                    connection,
                    source_id=str(row["source_id"]),
                    now=now,
                )
            self._sync_operation(
                connection,
                operation_id=(
                    None if row["operation_id"] is None else str(row["operation_id"])
                ),
                source_id=str(row["source_id"]),
                status=(
                    "cancelled"
                    if values["state"] == "CANCELLED"
                    else "cancel_requested"
                ),
                stage=(
                    "ingestion_cancelled"
                    if values["state"] == "CANCELLED"
                    else "ingestion_cancellation_requested"
                ),
                outcome_code=(
                    "hybrid_ingestion_cancelled"
                    if values["state"] == "CANCELLED"
                    else None
                ),
                outcome_detail=(
                    "Hybrid document ingestion was cancelled."
                    if values["state"] == "CANCELLED"
                    else None
                ),
                now=now,
                terminal=values["state"] == "CANCELLED",
            )
        cancelled = self.get(job_id)
        if cancelled is None:
            raise RuntimeError("Hybrid ingestion job disappeared after cancellation")
        return cancelled

    def cancellation_requested(self, claim: HybridKnowledgeJobClaim) -> bool:
        with read_connection(self._connection_source) as connection:
            state = connection.execute(
                select(hybrid_ingestion_jobs.c.state).where(
                    hybrid_ingestion_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_ingestion_jobs.c.worker_id == claim.worker_id,
                    hybrid_ingestion_jobs.c.fencing_token == claim.fencing_token,
                )
            ).scalar_one_or_none()
        if state is None:
            raise HybridIngestionClaimRejectedError("Hybrid ingestion claim is stale")
        if state == "CANCEL_REQUESTED":
            return True
        if state != "CLAIMED":
            raise HybridIngestionClaimRejectedError("Hybrid ingestion claim is stale")
        return False

    def acknowledge_cancellation(
        self,
        claim: HybridKnowledgeJobClaim,
    ) -> HybridKnowledgeJob:
        now = self._now()
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_ingestion_jobs)
                .where(
                    hybrid_ingestion_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_ingestion_jobs.c.state == "CANCEL_REQUESTED",
                    hybrid_ingestion_jobs.c.worker_id == claim.worker_id,
                    hybrid_ingestion_jobs.c.fencing_token == claim.fencing_token,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise HybridIngestionClaimRejectedError(
                    "Hybrid ingestion cancellation fence is stale"
                )
            changed = connection.execute(
                update(hybrid_ingestion_jobs)
                .where(
                    hybrid_ingestion_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_ingestion_jobs.c.state == "CANCEL_REQUESTED",
                    hybrid_ingestion_jobs.c.worker_id == claim.worker_id,
                    hybrid_ingestion_jobs.c.fencing_token == claim.fencing_token,
                )
                .values(
                    state="CANCELLED",
                    worker_id=None,
                    claimed_at=None,
                    lease_expires_at=None,
                    next_attempt_at=None,
                    updated_at=now,
                    cancelled_at=now,
                    completed_at=now,
                )
            )
            if changed.rowcount != 1:
                raise HybridIngestionClaimRejectedError(
                    "Hybrid ingestion cancellation fence is stale"
                )
            PostgresKnowledgeIngestionAttemptRepository(connection).transition_running(
                job_id=claim.job_id,
                fencing_token=claim.fencing_token,
                state="cancelled",
                completed_at=now,
            )
            self._clear_pending_revision(
                connection,
                source_id=str(row["source_id"]),
                document_id=row["document_id"],
                revision_id=row["revision_id"],
                now=now,
            )
            self._touch_source_revision(
                connection,
                source_id=str(row["source_id"]),
                now=now,
            )
            self._sync_operation(
                connection,
                operation_id=(
                    None if row["operation_id"] is None else str(row["operation_id"])
                ),
                source_id=str(row["source_id"]),
                status="cancelled",
                stage="ingestion_cancelled",
                outcome_code="hybrid_ingestion_cancelled",
                outcome_detail="Hybrid document ingestion was cancelled.",
                now=now,
                terminal=True,
            )
        cancelled = self.get(claim.job_id)
        if cancelled is None:
            raise RuntimeError("Hybrid ingestion job disappeared after cancellation")
        return cancelled

    def manual_retry(
        self,
        *,
        job_id: str,
        requested_by: str,
        operation_id: str | None = None,
        touch_source: bool = True,
    ) -> HybridKnowledgeJob:
        if not requested_by.strip() or len(requested_by) > 512:
            raise ValueError("Hybrid ingestion retry actor is invalid")
        now = self._now()
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_ingestion_jobs)
                .where(hybrid_ingestion_jobs.c.job_id == UUID(job_id))
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise LookupError("Hybrid ingestion job was not found")
            retryable = row["state"] == "CANCELLED" or (
                row["state"] == "FAILED"
                and row["failure_classification"] == "recoverable_exhausted"
            )
            if not retryable:
                raise HybridIngestionRetryRejectedError(
                    "Hybrid ingestion job requires replacement or is not retryable"
                )
            candidate = connection.execute(
                select(hybrid_document_candidates)
                .where(
                    hybrid_document_candidates.c.source_id == row["source_id"],
                    hybrid_document_candidates.c.document_id == row["document_id"],
                )
                .with_for_update()
            ).mappings().one_or_none()
            if candidate is None:
                connection.execute(
                    sa.insert(hybrid_document_candidates).values(
                        source_id=row["source_id"],
                        document_id=row["document_id"],
                        candidate_revision_id=None,
                        pending_revision_id=row["revision_id"],
                        updated_at=now,
                    )
                )
            elif candidate["pending_revision_id"] is None:
                connection.execute(
                    update(hybrid_document_candidates)
                    .where(
                        hybrid_document_candidates.c.source_id == row["source_id"],
                        hybrid_document_candidates.c.document_id == row["document_id"],
                    )
                    .values(
                        pending_revision_id=row["revision_id"],
                        updated_at=now,
                    )
                )
            else:
                raise HybridIngestionRetryRejectedError(
                    "Hybrid document already has pending work"
                )
            connection.execute(
                update(hybrid_ingestion_jobs)
                .where(
                    hybrid_ingestion_jobs.c.job_id == UUID(job_id),
                    hybrid_ingestion_jobs.c.state == row["state"],
                    hybrid_ingestion_jobs.c.fencing_token == row["fencing_token"],
                )
                .values(
                    operation_id=operation_id or row["operation_id"],
                    state="READY",
                    worker_id=None,
                    claimed_at=None,
                    lease_expires_at=None,
                    auto_retry_count=0,
                    next_attempt_initiation="manual",
                    next_attempt_at=None,
                    safe_reason=None,
                    failure_code=None,
                    failure_classification=None,
                    completed_at=None,
                    cancel_requested_at=None,
                    cancel_requested_by=None,
                    cancelled_at=None,
                    updated_at=now,
                )
            )
            if touch_source:
                self._touch_source_revision(
                    connection,
                    source_id=str(row["source_id"]),
                    now=now,
                )
        retried = self.get(job_id)
        if retried is None:
            raise RuntimeError("Hybrid ingestion job disappeared after manual retry")
        return retried

    def list_for_source(self, source_id: str) -> tuple[HybridKnowledgeJob, ...]:
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(
                select(hybrid_ingestion_jobs)
                .where(hybrid_ingestion_jobs.c.source_id == source_id)
                .order_by(hybrid_ingestion_jobs.c.created_at, hybrid_ingestion_jobs.c.job_id)
            ).mappings()
        return tuple(_job_from_row(row) for row in rows)

    def get_record(self, job_id: str) -> HybridIngestionRecord | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_ingestion_jobs).where(
                    hybrid_ingestion_jobs.c.job_id == UUID(job_id)
                )
            ).mappings().one_or_none()
        return None if row is None else _record_from_row(row)

    def list_records_for_source(self, source_id: str) -> tuple[HybridIngestionRecord, ...]:
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(
                select(hybrid_ingestion_jobs)
                .where(hybrid_ingestion_jobs.c.source_id == source_id)
                .order_by(hybrid_ingestion_jobs.c.created_at, hybrid_ingestion_jobs.c.job_id)
            ).mappings()
        return tuple(_record_from_row(row) for row in rows)

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> HybridKnowledgeJobClaim | None:
        if not worker_id.strip() or not 1 <= lease_seconds <= 300:
            raise ValueError("Hybrid ingestion claim parameters are invalid")
        now = self._now()
        with write_connection(self._connection_source) as connection:
            eligible = or_(
                hybrid_ingestion_jobs.c.state == "READY",
                and_(
                    hybrid_ingestion_jobs.c.state == "RETRY_SCHEDULED",
                    hybrid_ingestion_jobs.c.next_attempt_at <= now,
                ),
                and_(
                    hybrid_ingestion_jobs.c.state == "CLAIMED",
                    hybrid_ingestion_jobs.c.lease_expires_at <= now,
                ),
            )
            row = connection.execute(
                select(hybrid_ingestion_jobs)
                .where(eligible)
                .order_by(hybrid_ingestion_jobs.c.created_at, hybrid_ingestion_jobs.c.job_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).mappings().one_or_none()
            if row is None:
                return None
            attempts = PostgresKnowledgeIngestionAttemptRepository(connection)
            if row["state"] == "CLAIMED":
                attempts.transition_running(
                    job_id=str(row["job_id"]),
                    fencing_token=int(row["fencing_token"]),
                    state="failed",
                    completed_at=now,
                    failure_code="PA_HYBRID_LEASE_EXPIRED",
                    failure_classification="recoverable",
                    outcome_detail="The prior worker lease expired.",
                )
            token = int(row["fencing_token"]) + 1
            lease_expires_at = now + timedelta(seconds=lease_seconds)
            attempt_number = attempts.next_attempt_number(str(row["job_id"]))
            raw_initiation = row["next_attempt_initiation"]
            if raw_initiation not in {"automatic", "manual"}:
                raise RuntimeError("Hybrid ingestion attempt initiation is invalid")
            initiation = cast(Literal["automatic", "manual"], raw_initiation)
            connection.execute(
                update(hybrid_ingestion_jobs)
                .where(hybrid_ingestion_jobs.c.job_id == row["job_id"])
                .values(
                    state="CLAIMED",
                    fencing_token=token,
                    worker_id=worker_id,
                    claimed_at=now,
                    lease_expires_at=lease_expires_at,
                    next_attempt_at=None,
                    next_attempt_initiation="automatic",
                    safe_reason=None,
                    updated_at=now,
                )
            )
            attempts.append(
                KnowledgeIngestionAttempt(
                    attempt_id=str(uuid4()),
                    job_id=str(row["job_id"]),
                    attempt_number=attempt_number,
                    initiation=initiation,
                    state="running",
                    fencing_token=token,
                    worker_id=worker_id,
                    started_at=_timestamp(now),
                    updated_at=_timestamp(now),
                )
            )
            self._touch_source_revision(
                connection,
                source_id=str(row["source_id"]),
                now=now,
            )
            self._sync_operation(
                connection,
                operation_id=(
                    None if row["operation_id"] is None else str(row["operation_id"])
                ),
                source_id=str(row["source_id"]),
                status="running",
                stage="ingestion_processing",
                outcome_code=None,
                outcome_detail=None,
                now=now,
                terminal=False,
            )
        request = _build_request(row["request_json"], int(row["auto_retry_count"]))
        return HybridKnowledgeJobClaim(
            job_id=str(row["job_id"]),
            request=_scheduler_request(request),
            worker_id=worker_id,
            fencing_token=token,
            claimed_at=now,
            lease_expires_at=lease_expires_at,
        )

    def load_build_request(self, claim: HybridKnowledgeJobClaim) -> HybridArtifactBuildRequest:
        row = self._require_claim(claim)
        return _build_request(row["request_json"], int(row["auto_retry_count"]))

    def renew_claim(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        lease_seconds: int,
    ) -> HybridKnowledgeJobClaim:
        if not 1 <= lease_seconds <= 300:
            raise ValueError("Hybrid ingestion lease is outside its bound")
        now = self._now()
        expires = now + timedelta(seconds=lease_seconds)
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(
                update(hybrid_ingestion_jobs)
                .where(
                    hybrid_ingestion_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_ingestion_jobs.c.state == "CLAIMED",
                    hybrid_ingestion_jobs.c.worker_id == claim.worker_id,
                    hybrid_ingestion_jobs.c.fencing_token == claim.fencing_token,
                    hybrid_ingestion_jobs.c.lease_expires_at > now,
                )
                .values(lease_expires_at=expires, updated_at=now)
            )
            if updated.rowcount != 1:
                raise HybridIngestionClaimRejectedError("Hybrid ingestion claim is stale")
            PostgresKnowledgeIngestionAttemptRepository(connection).touch_running(
                job_id=claim.job_id,
                fencing_token=claim.fencing_token,
                updated_at=now,
            )
        return claim.model_copy(update={"lease_expires_at": expires})

    def commit_artifact_build(
        self,
        claim: HybridKnowledgeJobClaim,
        result: HybridArtifactBuildResult,
    ) -> HybridKnowledgeJob:
        request = self.load_build_request(claim)
        validate_hybrid_artifact_build_result(request, result)
        review_set = self._materialize_review_set(result)
        now = self._now()
        with write_connection(self._connection_source) as connection:
            changed = connection.execute(
                update(hybrid_ingestion_jobs)
                .where(
                    hybrid_ingestion_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_ingestion_jobs.c.state == "CLAIMED",
                    hybrid_ingestion_jobs.c.worker_id == claim.worker_id,
                    hybrid_ingestion_jobs.c.fencing_token == claim.fencing_token,
                )
                .values(
                    state="COMPLETED",
                    worker_id=None,
                    claimed_at=None,
                    lease_expires_at=None,
                    updated_at=now,
                    completed_at=now,
                    result_json=result.model_dump(mode="json"),
                )
            )
            if changed.rowcount != 1:
                raise HybridIngestionClaimRejectedError("Hybrid ingestion claim is stale")
            PostgresKnowledgeIngestionAttemptRepository(connection).transition_running(
                job_id=claim.job_id,
                fencing_token=claim.fencing_token,
                state="succeeded",
                completed_at=now,
            )
            selected = connection.execute(
                update(hybrid_document_candidates)
                .where(
                    hybrid_document_candidates.c.source_id == request.source_id,
                    hybrid_document_candidates.c.document_id
                    == UUID(request.document_id),
                    hybrid_document_candidates.c.pending_revision_id
                    == UUID(request.revision_id),
                )
                .values(
                    candidate_revision_id=UUID(request.revision_id),
                    pending_revision_id=None,
                    updated_at=now,
                )
            )
            if selected.rowcount != 1:
                raise HybridIngestionClaimRejectedError(
                    "Hybrid ingestion candidate selection is stale"
                )
            PostgresInsuranceMetadataReviewRepository(
                connection,
                clock=lambda: now,
            ).put_review_set(review_set)
            self._touch_source_revision(
                connection,
                source_id=request.source_id,
                now=now,
                advance_draft=True,
            )
            self._sync_operation(
                connection,
                operation_id=self._operation_id_for_job(connection, claim.job_id),
                source_id=request.source_id,
                status="succeeded",
                stage="ingestion_completed",
                outcome_code="hybrid_ingestion_completed",
                outcome_detail="Hybrid document ingestion completed.",
                now=now,
                terminal=True,
            )
        completed = self.get(claim.job_id)
        if completed is None:
            raise RuntimeError("Hybrid ingestion job disappeared after completion")
        return completed

    def _materialize_review_set(
        self,
        result: HybridArtifactBuildResult,
    ) -> InsuranceMetadataReviewSet:
        if self._artifact_store is None:
            raise ValueError(
                "Hybrid ingestion requires an exact artifact reader for Metadata Review V2"
            )
        canonical = StructuredKnowledgeDocumentArtifact.model_validate_json(
            self._exact_json(result.canonical_ref)
        )
        metadata = HybridInsuranceMetadataArtifact.model_validate_json(
            self._exact_json(result.insurance_metadata_ref)
        )
        if (
            canonical.document_id != result.document_id
            or canonical.revision_id != result.revision_id
            or canonical.build_identity != result.build_identity
            or metadata.source_id != result.source_id
            or metadata.document_id != result.document_id
            or metadata.revision_id != result.revision_id
            or metadata.structured_build_id != result.build_id
            or metadata.original_sha256 != result.original_ref.sha256
        ):
            raise ValueError("Hybrid review artifacts do not match the committed build")
        profile = PostgresInsuranceMetadataReviewRepository(
            self._connection_source,
            clock=self._clock,
        ).get_bound_profile(
            result.source_id,
            production=self._metadata_profile_requires_production(result.source_id),
        )
        rule_units = project_rule_units(
            canonical,
            document_defaults=metadata.document_defaults,
            source_id=result.source_id,
        )
        return create_insurance_metadata_review_set(
            source_id=result.source_id,
            structured_build_id=result.build_id,
            profile=profile,
            document_default=metadata.document_defaults,
            parser_proposals=metadata.pdf_drafts,
            canonical_anchors=(unit.canonical_anchor for unit in rule_units),
        )

    def _exact_json(self, ref: ExactArtifactRef) -> bytes:
        if ref.media_type != "application/json":
            raise ValueError("Hybrid review artifact must be application/json")
        assert self._artifact_store is not None
        content = self._artifact_store.get_exact(ref)
        if (
            len(content) != ref.size_bytes
            or hashlib.sha256(content).hexdigest() != ref.sha256
        ):
            raise ValueError("Hybrid review artifact failed exact read-back validation")
        return content

    def schedule_retry(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        auto_retry_count: int,
        safe_error: str,
    ) -> HybridKnowledgeJob:
        return self._transition(
            claim,
            state="RETRY_SCHEDULED",
            auto_retry_count=auto_retry_count,
            next_attempt_at=self._now() + timedelta(seconds=5),
            next_attempt_initiation="automatic",
            safe_reason=safe_error,
        )

    def require_review(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        safe_reason: str,
    ) -> HybridKnowledgeJob:
        return self._transition(
            claim,
            state="REVIEW_REQUIRED",
            safe_reason=safe_reason,
        )

    def fail_integrity(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> HybridKnowledgeJob:
        return self._transition(
            claim,
            state="FAILED",
            failure_code=failure_code,
            failure_classification="non_recoverable",
            safe_reason=safe_reason,
            completed=True,
        )

    def fail_retries_exhausted(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> HybridKnowledgeJob:
        return self._transition(
            claim,
            state="FAILED",
            failure_code=failure_code,
            failure_classification="recoverable_exhausted",
            safe_reason=safe_reason,
            completed=True,
        )

    def _transition(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        state: str,
        completed: bool = False,
        **values: Any,
    ) -> HybridKnowledgeJob:
        now = self._now()
        update_values = {
            "state": state,
            "worker_id": None,
            "claimed_at": None,
            "lease_expires_at": None,
            "updated_at": now,
            "completed_at": now if completed else None,
            **values,
        }
        with write_connection(self._connection_source) as connection:
            changed = connection.execute(
                update(hybrid_ingestion_jobs)
                .where(
                    hybrid_ingestion_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_ingestion_jobs.c.state == "CLAIMED",
                    hybrid_ingestion_jobs.c.worker_id == claim.worker_id,
                    hybrid_ingestion_jobs.c.fencing_token == claim.fencing_token,
                )
                .values(**update_values)
                .returning(
                    hybrid_ingestion_jobs.c.operation_id,
                    hybrid_ingestion_jobs.c.source_id,
                    hybrid_ingestion_jobs.c.document_id,
                    hybrid_ingestion_jobs.c.revision_id,
                )
            ).mappings().one_or_none()
            if changed is None:
                raise HybridIngestionClaimRejectedError("Hybrid ingestion claim is stale")
            attempts = PostgresKnowledgeIngestionAttemptRepository(connection)
            if state == "RETRY_SCHEDULED":
                attempts.transition_running(
                    job_id=claim.job_id,
                    fencing_token=claim.fencing_token,
                    state="failed",
                    completed_at=now,
                    failure_code="PA_HYBRID_TRANSIENT",
                    failure_classification="recoverable",
                    outcome_detail=str(values["safe_reason"]),
                )
            elif state == "REVIEW_REQUIRED":
                attempts.transition_running(
                    job_id=claim.job_id,
                    fencing_token=claim.fencing_token,
                    state="failed",
                    completed_at=now,
                    failure_code="PA_HYBRID_REVIEW_REQUIRED",
                    failure_classification="review_required",
                    outcome_detail=str(values["safe_reason"]),
                )
            elif state == "FAILED":
                raw_classification = values["failure_classification"]
                if raw_classification not in {
                    "recoverable",
                    "recoverable_exhausted",
                    "review_required",
                    "non_recoverable",
                }:
                    raise RuntimeError(
                        "Hybrid ingestion failure classification is invalid"
                    )
                classification = cast(
                    Literal[
                        "recoverable",
                        "recoverable_exhausted",
                        "review_required",
                        "non_recoverable",
                    ],
                    raw_classification,
                )
                attempts.transition_running(
                    job_id=claim.job_id,
                    fencing_token=claim.fencing_token,
                    state="failed",
                    completed_at=now,
                    failure_code=str(values["failure_code"]),
                    failure_classification=classification,
                    outcome_detail=str(values["safe_reason"]),
                )
            if completed and state == "FAILED":
                self._clear_pending_revision(
                    connection,
                    source_id=str(changed["source_id"]),
                    document_id=changed["document_id"],
                    revision_id=changed["revision_id"],
                    now=now,
                )
            self._touch_source_revision(
                connection,
                source_id=str(changed["source_id"]),
                now=now,
            )
            self._sync_operation(
                connection,
                operation_id=(
                    None
                    if changed["operation_id"] is None
                    else str(changed["operation_id"])
                ),
                source_id=str(changed["source_id"]),
                now=now,
                **_operation_projection_for_job_state(
                    state=state,
                    safe_reason=(
                        None
                        if values.get("safe_reason") is None
                        else str(values["safe_reason"])
                    ),
                    failure_code=(
                        None
                        if values.get("failure_code") is None
                        else str(values["failure_code"])
                    ),
                ),
            )
        job = self.get(claim.job_id)
        if job is None:
            raise RuntimeError("Hybrid ingestion job disappeared after transition")
        return job

    def _require_claim(self, claim: HybridKnowledgeJobClaim) -> Any:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_ingestion_jobs).where(
                    hybrid_ingestion_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_ingestion_jobs.c.state.in_(
                        ("CLAIMED", "CANCEL_REQUESTED")
                    ),
                    hybrid_ingestion_jobs.c.worker_id == claim.worker_id,
                    hybrid_ingestion_jobs.c.fencing_token == claim.fencing_token,
                )
            ).mappings().one_or_none()
        if row is None:
            raise HybridIngestionClaimRejectedError("Hybrid ingestion claim is stale")
        return row

    def _now(self) -> datetime:
        value = self._clock()
        if value.utcoffset() is None:
            raise ValueError("Hybrid ingestion clock must be timezone-aware")
        return value

    @staticmethod
    def _operation_id_for_job(connection: Any, job_id: str) -> str | None:
        value = connection.execute(
            select(hybrid_ingestion_jobs.c.operation_id).where(
                hybrid_ingestion_jobs.c.job_id == UUID(job_id)
            )
        ).scalar_one()
        return None if value is None else str(value)

    @staticmethod
    def _sync_operation(
        connection: Any,
        *,
        operation_id: str | None,
        source_id: str,
        status: Literal[
            "queued",
            "running",
            "cancel_requested",
            "succeeded",
            "failed",
            "cancelled",
        ],
        stage: str,
        outcome_code: str | None,
        outcome_detail: str | None,
        now: datetime,
        terminal: bool,
    ) -> None:
        if operation_id is None:
            return
        operations = PostgresKnowledgeSourceOperationRepository(connection)
        operation = operations.get(operation_id)
        if operation is None or operation.source_id != source_id:
            raise HybridIngestionClaimRejectedError(
                "Hybrid ingestion operation authority is missing or mismatched"
            )
        source_record = PostgresKnowledgeAssetRepository(connection).get_source_record(source_id)
        if source_record is None:
            raise HybridIngestionClaimRejectedError(
                "Hybrid ingestion source disappeared"
            )
        timestamp = _timestamp(now)
        operations.save(
            operation.model_copy(
                update={
                    "status": status,
                    "stage": stage,
                    "source_revision": source_record.revision,
                    "outcome_code": outcome_code,
                    "outcome_detail": outcome_detail,
                    "updated_at": timestamp,
                    "completed_at": timestamp if terminal else None,
                }
            )
        )

    @staticmethod
    def _touch_source_revision(
        connection: Any,
        *,
        source_id: str,
        now: datetime,
        advance_draft: bool = False,
    ) -> None:
        knowledge = PostgresKnowledgeAssetRepository(connection)
        source_record = knowledge.get_source_record(source_id)
        if source_record is None:
            raise HybridIngestionClaimRejectedError(
                "Hybrid ingestion source disappeared"
            )
        current_updated_at = datetime.fromisoformat(
            source_record.source.updated_at.replace("Z", "+00:00")
        )
        advanced_at = max(now, current_updated_at + timedelta(microseconds=1))
        updates: dict[str, object] = {"updated_at": _timestamp(advanced_at)}
        if advance_draft:
            updates["source_draft_version_id"] = str(uuid4())
        knowledge.save_source(
            source_record.source.model_copy(update=updates),
            expected_revision=source_record.revision,
        )

    @staticmethod
    def _clear_pending_revision(
        connection: Any,
        *,
        source_id: str,
        document_id: UUID,
        revision_id: UUID,
        now: datetime,
    ) -> None:
        candidate = connection.execute(
            select(hybrid_document_candidates)
            .where(
                hybrid_document_candidates.c.source_id == source_id,
                hybrid_document_candidates.c.document_id == document_id,
                hybrid_document_candidates.c.pending_revision_id == revision_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        if candidate is None:
            raise HybridIngestionClaimRejectedError(
                "Hybrid ingestion pending revision is stale"
            )
        if candidate["candidate_revision_id"] is None:
            connection.execute(
                sa.delete(hybrid_document_candidates).where(
                    hybrid_document_candidates.c.source_id == source_id,
                    hybrid_document_candidates.c.document_id == document_id,
                )
            )
            return
        connection.execute(
            update(hybrid_document_candidates)
            .where(
                hybrid_document_candidates.c.source_id == source_id,
                hybrid_document_candidates.c.document_id == document_id,
                hybrid_document_candidates.c.pending_revision_id == revision_id,
            )
            .values(pending_revision_id=None, updated_at=now)
        )


def _build_request(payload: Any, retry_count: int) -> HybridArtifactBuildRequest:
    return HybridArtifactBuildRequest.model_validate_json(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    ).model_copy(
        update={"auto_retry_count": retry_count}
    )


def _operation_projection_for_job_state(
    *,
    state: str,
    safe_reason: str | None,
    failure_code: str | None,
) -> dict[str, Any]:
    if state == "RETRY_SCHEDULED":
        return {
            "status": "queued",
            "stage": "ingestion_retry_scheduled",
            "outcome_code": None,
            "outcome_detail": safe_reason,
            "terminal": False,
        }
    if state == "REVIEW_REQUIRED":
        return {
            "status": "succeeded",
            "stage": "ingestion_review_required",
            "outcome_code": "hybrid_ingestion_review_required",
            "outcome_detail": safe_reason,
            "terminal": True,
        }
    if state == "FAILED":
        codes = {
            "PA_HYBRID_WORKER_INTEGRITY": "hybrid_ingestion_integrity_failed",
            "PA_HYBRID_RETRY_EXHAUSTED": "hybrid_ingestion_retries_exhausted",
        }
        return {
            "status": "failed",
            "stage": "ingestion_failed",
            "outcome_code": codes.get(
                failure_code or "",
                "hybrid_ingestion_failed",
            ),
            "outcome_detail": safe_reason,
            "terminal": True,
        }
    raise RuntimeError("Hybrid ingestion operation projection state is invalid")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _scheduler_request(request: HybridArtifactBuildRequest) -> HybridKnowledgeJobRequest:
    return HybridKnowledgeJobRequest(
        job_id=request.job_id,
        idempotency_key=request.job_id,
        request_identity=request.request_identity,
        request_sha256=request.request_sha256,
        kind="parse",
    )


def _job_from_row(row: Any) -> HybridKnowledgeJob:
    request = _build_request(row["request_json"], int(row["auto_retry_count"]))
    raw_state = "LEASED" if row["state"] == "CLAIMED" else row["state"]
    if raw_state not in {
        "READY",
        "LEASED",
        "RETRY_SCHEDULED",
        "CANCEL_REQUESTED",
        "REVIEW_REQUIRED",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    }:
        raise RuntimeError("Hybrid ingestion job state is invalid")
    state = cast(
        Literal[
            "READY",
            "LEASED",
            "RETRY_SCHEDULED",
            "CANCEL_REQUESTED",
            "REVIEW_REQUIRED",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        ],
        raw_state,
    )
    return HybridKnowledgeJob(
        request=_scheduler_request(request),
        state=state,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        fencing_token=int(row["fencing_token"]),
        auto_retry_count=int(row["auto_retry_count"]),
        max_auto_retries=int(row["max_auto_retries"]),
        next_attempt_at=row["next_attempt_at"],
        safe_reason=row["safe_reason"],
        completed_at=row["completed_at"],
        failure_code=row["failure_code"],
        failure_classification=row["failure_classification"],
        cancel_requested_at=row["cancel_requested_at"],
        cancel_requested_by=row["cancel_requested_by"],
        cancelled_at=row["cancelled_at"],
    )


def _record_from_row(row: Any) -> HybridIngestionRecord:
    request = _build_request(row["request_json"], int(row["auto_retry_count"]))
    return HybridIngestionRecord(
        job=_job_from_row(row),
        build_request=request,
        filename=str(row["filename"]),
        uploaded_by=str(row["uploaded_by"]),
    )


def _candidate_from_row(row: Any) -> HybridDocumentCandidate:
    return HybridDocumentCandidate(
        source_id=str(row["source_id"]),
        document_id=str(row["document_id"]),
        candidate_revision_id=(
            None
            if row["candidate_revision_id"] is None
            else str(row["candidate_revision_id"])
        ),
        pending_revision_id=(
            None
            if row["pending_revision_id"] is None
            else str(row["pending_revision_id"])
        ),
        updated_at=row["updated_at"],
    )


__all__ = [
    "HybridDocumentCandidate",
    "HybridIngestionClaimRejectedError",
    "HybridIngestionCancellationRejectedError",
    "HybridIngestionConflictError",
    "HybridIngestionRecord",
    "HybridIngestionRetryRejectedError",
    "PostgresHybridIngestionRepository",
]
