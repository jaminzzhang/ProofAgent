"""PostgreSQL queue authority for fenced publication preparation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping

from proof_agent.capabilities.knowledge.hybrid.publication import PublicationCommit
from proof_agent.capabilities.knowledge.hybrid.publication_jobs import (
    PublicationPreparationClaim,
    PublicationPreparationJob,
)
from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    hybrid_publication_preparation_jobs,
)


class PublicationPreparationConflictError(RuntimeError):
    pass


class PublicationPreparationClaimRejectedError(RuntimeError):
    pass


class PostgresPublicationPreparationRepository:
    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connection_source = connection_source
        self._clock = clock

    def enqueue(
        self,
        job: PublicationPreparationJob,
    ) -> PublicationPreparationJob:
        if job.state != "READY" or job.fencing_token != 0:
            raise ValueError("new publication preparation jobs must be ready")
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(
                postgres_insert(hybrid_publication_preparation_jobs)
                .values(**_values(job))
                .on_conflict_do_nothing()
                .returning(
                    hybrid_publication_preparation_jobs.c.preparation_job_id
                )
            ).scalar_one_or_none()
            if inserted is None:
                row = connection.execute(
                    sa.select(hybrid_publication_preparation_jobs).where(
                        sa.or_(
                            hybrid_publication_preparation_jobs.c.preparation_job_id
                            == UUID(job.preparation_job_id),
                            hybrid_publication_preparation_jobs.c.operation_id
                            == job.operation_id,
                            hybrid_publication_preparation_jobs.c.validation_id
                            == job.validation_id,
                        )
                    )
                ).mappings().one_or_none()
                if row is None or _job(row) != job:
                    raise PublicationPreparationConflictError(
                        "publication preparation identity already exists"
                    )
        persisted = self.get(job.preparation_job_id)
        if persisted is None:
            raise RuntimeError(
                "publication preparation job disappeared after admission"
            )
        return persisted

    def get(
        self,
        preparation_job_id: str,
    ) -> PublicationPreparationJob | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(hybrid_publication_preparation_jobs).where(
                    hybrid_publication_preparation_jobs.c.preparation_job_id
                    == UUID(preparation_job_id)
                )
            ).mappings().one_or_none()
        return None if row is None else _job(row)

    def get_for_validation(
        self,
        validation_id: str,
    ) -> PublicationPreparationJob | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(hybrid_publication_preparation_jobs).where(
                    hybrid_publication_preparation_jobs.c.validation_id
                    == validation_id
                )
            ).mappings().one_or_none()
        return None if row is None else _job(row)

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> PublicationPreparationClaim | None:
        if not worker_id.strip() or len(worker_id) > 512:
            raise ValueError("publication preparation worker_id is invalid")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("publication preparation lease is outside its bound")
        now = self._now()
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(hybrid_publication_preparation_jobs)
                .where(
                    sa.or_(
                        hybrid_publication_preparation_jobs.c.state == "READY",
                        sa.and_(
                            hybrid_publication_preparation_jobs.c.state
                            == "CLAIMED",
                            hybrid_publication_preparation_jobs.c.lease_expires_at
                            <= now,
                        ),
                    )
                )
                .order_by(
                    hybrid_publication_preparation_jobs.c.created_at,
                    hybrid_publication_preparation_jobs.c.preparation_job_id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            ).mappings().one_or_none()
            if row is None:
                return None
            token = int(row["fencing_token"]) + 1
            expires = now + timedelta(seconds=lease_seconds)
            changed = connection.execute(
                sa.update(hybrid_publication_preparation_jobs)
                .where(
                    hybrid_publication_preparation_jobs.c.preparation_job_id
                    == row["preparation_job_id"],
                    hybrid_publication_preparation_jobs.c.fencing_token
                    == row["fencing_token"],
                )
                .values(
                    state="CLAIMED",
                    fencing_token=token,
                    worker_id=worker_id,
                    claimed_at=now,
                    lease_expires_at=expires,
                    updated_at=now,
                )
            )
            if changed.rowcount != 1:
                raise PublicationPreparationClaimRejectedError(
                    "publication preparation claim lost its fence"
                )
        return PublicationPreparationClaim(
            preparation_job_id=str(row["preparation_job_id"]),
            operation_id=str(row["operation_id"]),
            worker_id=worker_id,
            fencing_token=token,
            claimed_at=now,
            lease_expires_at=expires,
        )

    def require_claim(
        self,
        claim: PublicationPreparationClaim,
    ) -> PublicationPreparationJob:
        now = self._now()
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(hybrid_publication_preparation_jobs).where(
                    hybrid_publication_preparation_jobs.c.preparation_job_id
                    == UUID(claim.preparation_job_id),
                    hybrid_publication_preparation_jobs.c.operation_id
                    == claim.operation_id,
                    hybrid_publication_preparation_jobs.c.state == "CLAIMED",
                    hybrid_publication_preparation_jobs.c.worker_id
                    == claim.worker_id,
                    hybrid_publication_preparation_jobs.c.fencing_token
                    == claim.fencing_token,
                    hybrid_publication_preparation_jobs.c.lease_expires_at > now,
                )
            ).mappings().one_or_none()
        if row is None:
            raise PublicationPreparationClaimRejectedError(
                "publication preparation claim is stale or expired"
            )
        return _job(row)

    def complete(
        self,
        claim: PublicationPreparationClaim,
        *,
        prepared_commit: PublicationCommit,
    ) -> PublicationPreparationJob:
        return self._transition(
            claim,
            state="PREPARED",
            prepared_commit_json=model_json(prepared_commit),
        )

    def fail(
        self,
        claim: PublicationPreparationClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> PublicationPreparationJob:
        if not failure_code.strip() or len(failure_code) > 128:
            raise ValueError("publication preparation failure code is invalid")
        if not safe_reason.strip() or len(safe_reason) > 1_000:
            raise ValueError("publication preparation safe reason is invalid")
        return self._transition(
            claim,
            state="FAILED",
            failure_code=failure_code,
            safe_reason=safe_reason,
        )

    def invalidate_source(
        self,
        source_id: str,
        *,
        invalidated_at: datetime,
    ) -> int:
        """Fence queued, claimed, or prepared work after Source authority changes."""

        timestamp = invalidated_at.astimezone(UTC)
        with write_connection(self._connection_source) as connection:
            changed = connection.execute(
                sa.update(hybrid_publication_preparation_jobs)
                .where(
                    hybrid_publication_preparation_jobs.c.source_id == source_id,
                    hybrid_publication_preparation_jobs.c.state.in_(
                        ("READY", "CLAIMED", "PREPARED")
                    ),
                )
                .values(
                    state="FAILED",
                    worker_id=None,
                    claimed_at=None,
                    lease_expires_at=None,
                    prepared_commit_json=sa.null(),
                    failure_code="publication_source_changed",
                    safe_reason=(
                        "Source metadata changed after publication preparation."
                    ),
                    updated_at=timestamp,
                    completed_at=timestamp,
                )
            )
        return int(changed.rowcount or 0)

    def _transition(
        self,
        claim: PublicationPreparationClaim,
        *,
        state: str,
        **values: object,
    ) -> PublicationPreparationJob:
        now = self._now()
        with write_connection(self._connection_source) as connection:
            changed = connection.execute(
                sa.update(hybrid_publication_preparation_jobs)
                .where(
                    hybrid_publication_preparation_jobs.c.preparation_job_id
                    == UUID(claim.preparation_job_id),
                    hybrid_publication_preparation_jobs.c.operation_id
                    == claim.operation_id,
                    hybrid_publication_preparation_jobs.c.state == "CLAIMED",
                    hybrid_publication_preparation_jobs.c.worker_id
                    == claim.worker_id,
                    hybrid_publication_preparation_jobs.c.fencing_token
                    == claim.fencing_token,
                    hybrid_publication_preparation_jobs.c.lease_expires_at > now,
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
                raise PublicationPreparationClaimRejectedError(
                    "publication preparation claim is stale"
                )
        persisted = self.get(claim.preparation_job_id)
        if persisted is None:
            raise RuntimeError(
                "publication preparation job disappeared after transition"
            )
        return persisted

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "publication preparation clock must be timezone-aware"
            )
        return value


def _values(job: PublicationPreparationJob) -> dict[str, object]:
    return {
        "preparation_job_id": UUID(job.preparation_job_id),
        "operation_id": job.operation_id,
        "validation_id": job.validation_id,
        "source_id": job.source_id,
        "source_revision": job.source_revision,
        "source_draft_version_id": job.source_draft_version_id,
        "smoke_query": job.smoke_query,
        "state": job.state,
        "fencing_token": job.fencing_token,
        "worker_id": job.worker_id,
        "claimed_at": job.claimed_at,
        "lease_expires_at": job.lease_expires_at,
        "prepared_commit_json": (
            sa.null()
            if job.prepared_commit is None
            else model_json(job.prepared_commit)
        ),
        "failure_code": job.failure_code,
        "safe_reason": job.safe_reason,
        "created_by": job.created_by,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
    }


def _job(row: RowMapping) -> PublicationPreparationJob:
    state = cast(
        Literal["READY", "CLAIMED", "PREPARED", "FAILED"],
        str(row["state"]),
    )
    payload = row["prepared_commit_json"]
    return PublicationPreparationJob(
        preparation_job_id=str(row["preparation_job_id"]),
        operation_id=str(row["operation_id"]),
        validation_id=str(row["validation_id"]),
        source_id=str(row["source_id"]),
        source_revision=int(row["source_revision"]),
        source_draft_version_id=str(row["source_draft_version_id"]),
        smoke_query=str(row["smoke_query"]),
        state=state,
        fencing_token=int(row["fencing_token"]),
        worker_id=None if row["worker_id"] is None else str(row["worker_id"]),
        claimed_at=row["claimed_at"],
        lease_expires_at=row["lease_expires_at"],
        prepared_commit=(
            None
            if payload is None
            else PublicationCommit.model_validate_json(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
        ),
        failure_code=(
            None if row["failure_code"] is None else str(row["failure_code"])
        ),
        safe_reason=None if row["safe_reason"] is None else str(row["safe_reason"]),
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


__all__ = [
    "PostgresPublicationPreparationRepository",
    "PublicationPreparationClaimRejectedError",
    "PublicationPreparationConflictError",
]
