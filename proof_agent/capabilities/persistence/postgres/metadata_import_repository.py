"""PostgreSQL queue authority for fenced metadata workbook imports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping

from proof_agent.capabilities.knowledge.hybrid.metadata_import_jobs import (
    MetadataImportJob,
    MetadataImportJobClaim,
)
from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    hybrid_metadata_import_jobs,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


class MetadataImportConflictError(RuntimeError):
    """A durable import identity is already bound to different work."""


class MetadataImportClaimRejectedError(RuntimeError):
    """A metadata import lease or fencing token is stale."""


class PostgresMetadataImportRepository:
    """Lease metadata import work with PostgreSQL row locks and fences."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connection_source = connection_source
        self._clock = clock

    def enqueue(self, job: MetadataImportJob) -> MetadataImportJob:
        if job.state != "READY" or job.fencing_token != 0:
            raise ValueError("new metadata import jobs must be unfenced and ready")
        values = _values(job)
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(
                postgres_insert(hybrid_metadata_import_jobs)
                .values(**values)
                .on_conflict_do_nothing()
                .returning(hybrid_metadata_import_jobs.c.import_job_id)
            ).scalar_one_or_none()
            if inserted is None:
                existing = connection.execute(
                    sa.select(hybrid_metadata_import_jobs).where(
                        sa.or_(
                            hybrid_metadata_import_jobs.c.import_job_id
                            == UUID(job.import_job_id),
                            hybrid_metadata_import_jobs.c.operation_id
                            == job.operation_id,
                        )
                    )
                ).mappings().one_or_none()
                if existing is None or _job(existing) != job:
                    raise MetadataImportConflictError(
                        "metadata import identity already exists"
                    )
        persisted = self.get(job.import_job_id)
        if persisted is None:
            raise RuntimeError("metadata import job disappeared after admission")
        return persisted

    def get(self, import_job_id: str) -> MetadataImportJob | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(hybrid_metadata_import_jobs).where(
                    hybrid_metadata_import_jobs.c.import_job_id
                    == UUID(import_job_id)
                )
            ).mappings().one_or_none()
        return None if row is None else _job(row)

    def get_for_operation(self, operation_id: str) -> MetadataImportJob | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(hybrid_metadata_import_jobs).where(
                    hybrid_metadata_import_jobs.c.operation_id == operation_id
                )
            ).mappings().one_or_none()
        return None if row is None else _job(row)

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> MetadataImportJobClaim | None:
        if not worker_id.strip() or len(worker_id) > 512:
            raise ValueError("metadata import worker_id is invalid")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("metadata import lease is outside its bound")
        now = self._now()
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(hybrid_metadata_import_jobs)
                .where(
                    sa.or_(
                        hybrid_metadata_import_jobs.c.state == "READY",
                        sa.and_(
                            hybrid_metadata_import_jobs.c.state == "CLAIMED",
                            hybrid_metadata_import_jobs.c.lease_expires_at <= now,
                        ),
                    )
                )
                .order_by(
                    hybrid_metadata_import_jobs.c.created_at,
                    hybrid_metadata_import_jobs.c.import_job_id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            ).mappings().one_or_none()
            if row is None:
                return None
            token = int(row["fencing_token"]) + 1
            expires = now + timedelta(seconds=lease_seconds)
            changed = connection.execute(
                sa.update(hybrid_metadata_import_jobs)
                .where(
                    hybrid_metadata_import_jobs.c.import_job_id
                    == row["import_job_id"],
                    hybrid_metadata_import_jobs.c.fencing_token
                    == row["fencing_token"],
                )
                .values(
                    state="CLAIMED",
                    fencing_token=token,
                    worker_id=worker_id,
                    claimed_at=now,
                    lease_expires_at=expires,
                    failure_code=None,
                    safe_reason=None,
                    updated_at=now,
                )
            )
            if changed.rowcount != 1:
                raise MetadataImportClaimRejectedError(
                    "metadata import claim lost its fence"
                )
        return MetadataImportJobClaim(
            import_job_id=str(row["import_job_id"]),
            operation_id=str(row["operation_id"]),
            worker_id=worker_id,
            fencing_token=token,
            claimed_at=now,
            lease_expires_at=expires,
        )

    def require_claim(self, claim: MetadataImportJobClaim) -> MetadataImportJob:
        now = self._now()
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(hybrid_metadata_import_jobs).where(
                    hybrid_metadata_import_jobs.c.import_job_id
                    == UUID(claim.import_job_id),
                    hybrid_metadata_import_jobs.c.operation_id == claim.operation_id,
                    hybrid_metadata_import_jobs.c.state == "CLAIMED",
                    hybrid_metadata_import_jobs.c.worker_id == claim.worker_id,
                    hybrid_metadata_import_jobs.c.fencing_token
                    == claim.fencing_token,
                    hybrid_metadata_import_jobs.c.lease_expires_at > now,
                )
            ).mappings().one_or_none()
        if row is None:
            raise MetadataImportClaimRejectedError(
                "metadata import claim is stale or expired"
            )
        return _job(row)

    def complete(
        self,
        claim: MetadataImportJobClaim,
        *,
        result_import_id: str,
    ) -> MetadataImportJob:
        if not result_import_id.strip() or len(result_import_id) > 512:
            raise ValueError("metadata import result identity is invalid")
        return self._transition(
            claim,
            state="COMPLETED",
            result_import_id=result_import_id,
        )

    def fail(
        self,
        claim: MetadataImportJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> MetadataImportJob:
        if not failure_code.strip() or len(failure_code) > 128:
            raise ValueError("metadata import failure code is invalid")
        if not safe_reason.strip() or len(safe_reason) > 1_000:
            raise ValueError("metadata import safe reason is invalid")
        return self._transition(
            claim,
            state="FAILED",
            failure_code=failure_code,
            safe_reason=safe_reason,
        )

    def _transition(
        self,
        claim: MetadataImportJobClaim,
        *,
        state: str,
        **values: object,
    ) -> MetadataImportJob:
        now = self._now()
        with write_connection(self._connection_source) as connection:
            changed = connection.execute(
                sa.update(hybrid_metadata_import_jobs)
                .where(
                    hybrid_metadata_import_jobs.c.import_job_id
                    == UUID(claim.import_job_id),
                    hybrid_metadata_import_jobs.c.operation_id == claim.operation_id,
                    hybrid_metadata_import_jobs.c.state == "CLAIMED",
                    hybrid_metadata_import_jobs.c.worker_id == claim.worker_id,
                    hybrid_metadata_import_jobs.c.fencing_token
                    == claim.fencing_token,
                    hybrid_metadata_import_jobs.c.lease_expires_at > now,
                )
                .values(
                    state=state,
                    worker_id=None,
                    claimed_at=None,
                    lease_expires_at=None,
                    updated_at=now,
                    completed_at=now,
                    **values,
                )
            )
            if changed.rowcount != 1:
                raise MetadataImportClaimRejectedError(
                    "metadata import claim is stale"
                )
        persisted = self.get(claim.import_job_id)
        if persisted is None:
            raise RuntimeError("metadata import job disappeared after transition")
        return persisted

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metadata import clock must be timezone-aware")
        return value


def _values(job: MetadataImportJob) -> dict[str, object]:
    return {
        "import_job_id": UUID(job.import_job_id),
        "operation_id": job.operation_id,
        "source_id": job.source_id,
        "document_id": UUID(job.document_id),
        "revision_id": UUID(job.revision_id),
        "source_revision": job.source_revision,
        "request_sha256": job.request_sha256,
        "filename": job.filename,
        "original_ref_json": model_json(job.original_ref),
        "content_sha256": job.content_sha256,
        "state": job.state,
        "fencing_token": job.fencing_token,
        "worker_id": job.worker_id,
        "claimed_at": job.claimed_at,
        "lease_expires_at": job.lease_expires_at,
        "failure_code": job.failure_code,
        "safe_reason": job.safe_reason,
        "result_import_id": job.result_import_id,
        "created_by": job.created_by,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
    }


def _job(row: RowMapping) -> MetadataImportJob:
    state = cast(
        Literal["READY", "CLAIMED", "COMPLETED", "FAILED"],
        str(row["state"]),
    )
    return MetadataImportJob(
        import_job_id=str(row["import_job_id"]),
        operation_id=str(row["operation_id"]),
        source_id=str(row["source_id"]),
        document_id=str(row["document_id"]),
        revision_id=str(row["revision_id"]),
        source_revision=int(row["source_revision"]),
        request_sha256=str(row["request_sha256"]),
        filename=str(row["filename"]),
        original_ref=ExactArtifactRef.model_validate(row["original_ref_json"]),
        content_sha256=str(row["content_sha256"]),
        state=state,
        fencing_token=int(row["fencing_token"]),
        worker_id=None if row["worker_id"] is None else str(row["worker_id"]),
        claimed_at=row["claimed_at"],
        lease_expires_at=row["lease_expires_at"],
        failure_code=(
            None if row["failure_code"] is None else str(row["failure_code"])
        ),
        safe_reason=None if row["safe_reason"] is None else str(row["safe_reason"]),
        result_import_id=(
            None
            if row["result_import_id"] is None
            else str(row["result_import_id"])
        ),
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


__all__ = [
    "MetadataImportClaimRejectedError",
    "MetadataImportConflictError",
    "PostgresMetadataImportRepository",
]
