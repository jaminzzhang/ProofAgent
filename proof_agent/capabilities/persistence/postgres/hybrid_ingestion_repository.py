from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import UUID

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
    hybrid_build_request_sha256,
    validate_hybrid_artifact_build_result,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    hybrid_ingestion_jobs,
    knowledge_sources,
)
from proof_agent.contracts.agent_configuration import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
)


class HybridIngestionConflictError(RuntimeError):
    pass


class HybridIngestionClaimRejectedError(RuntimeError):
    pass


@dataclass(frozen=True)
class HybridIngestionRecord:
    job: HybridKnowledgeJob
    build_request: HybridArtifactBuildRequest
    filename: str
    uploaded_by: str


class PostgresHybridIngestionRepository:
    """Fenced PostgreSQL queue and result authority for private PDF parsing."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connection_source = connection_source
        self._clock = clock or (lambda: datetime.now(UTC))

    def enqueue(
        self,
        request: HybridArtifactBuildRequest,
        *,
        filename: str = "document.pdf",
        uploaded_by: str = "system",
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
            limits = HybridIntakeLimits.model_validate(dict(source.params), strict=True)
            source_job_count = int(
                connection.execute(
                    select(func.count())
                    .select_from(hybrid_ingestion_jobs)
                    .where(hybrid_ingestion_jobs.c.source_id == request.source_id)
                ).scalar_one()
            )
            if source_job_count >= limits.max_source_documents:
                raise ValueError("Hybrid Knowledge Source document limit has been reached")
            inserted = connection.execute(
                postgres_insert(hybrid_ingestion_jobs)
                .values(**values)
                .on_conflict_do_nothing()
                .returning(hybrid_ingestion_jobs.c.job_id)
            ).scalar_one_or_none()
            if inserted is None:
                raise HybridIngestionConflictError("Hybrid ingestion identity conflict")
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
        return None if payload is None else HybridArtifactBuildResult.model_validate(payload)

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
            token = int(row["fencing_token"]) + 1
            lease_expires_at = now + timedelta(seconds=lease_seconds)
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
                    safe_reason=None,
                    updated_at=now,
                )
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
        return claim.model_copy(update={"lease_expires_at": expires})

    def commit_artifact_build(
        self,
        claim: HybridKnowledgeJobClaim,
        result: HybridArtifactBuildResult,
    ) -> HybridKnowledgeJob:
        request = self.load_build_request(claim)
        validate_hybrid_artifact_build_result(request, result)
        return self._transition(
            claim,
            state="COMPLETED",
            result_json=result.model_dump(mode="json"),
            completed=True,
        )

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
            )
            if changed.rowcount != 1:
                raise HybridIngestionClaimRejectedError("Hybrid ingestion claim is stale")
        job = self.get(claim.job_id)
        if job is None:
            raise RuntimeError("Hybrid ingestion job disappeared after transition")
        return job

    def _require_claim(self, claim: HybridKnowledgeJobClaim) -> Any:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_ingestion_jobs).where(
                    hybrid_ingestion_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_ingestion_jobs.c.state == "CLAIMED",
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


def _build_request(payload: Any, retry_count: int) -> HybridArtifactBuildRequest:
    return HybridArtifactBuildRequest.model_validate_json(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    ).model_copy(
        update={"auto_retry_count": retry_count}
    )


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
    return HybridKnowledgeJob(
        request=_scheduler_request(request),
        state=row["state"],
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
    )


def _record_from_row(row: Any) -> HybridIngestionRecord:
    request = _build_request(row["request_json"], int(row["auto_retry_count"]))
    return HybridIngestionRecord(
        job=_job_from_row(row),
        build_request=request,
        filename=str(row["filename"]),
        uploaded_by=str(row["uploaded_by"]),
    )


__all__ = [
    "HybridIngestionClaimRejectedError",
    "HybridIngestionConflictError",
    "HybridIngestionRecord",
    "PostgresHybridIngestionRepository",
]
