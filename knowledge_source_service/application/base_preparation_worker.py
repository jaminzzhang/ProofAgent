"""Trusted Worker lease operations; no builds, artifact publication or process loop."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
import re
from typing import Protocol

from pydantic import ValidationError

from knowledge_source_service.contracts.base_preparations import (
    KnowledgeBaseVersion,
    FailedReleasePreparation,
    PreparationWorkerAuditEntry,
    ReadyReleasePreparation,
)
from knowledge_source_service.domain.base_preparations import (
    BasePreparationError,
    PreparationClaim,
    validate_prepared_candidate,
)
from knowledge_source_service.domain.publications import PreparedKnowledgeBaseRelease
from knowledge_source_service.ports.base_preparations import (
    BasePreparationRepository,
    BasePreparationTransaction,
)


class ReleasePreparationBuilder(Protocol):
    def build(self, base_version: KnowledgeBaseVersion) -> PreparedKnowledgeBaseRelease: ...


class BasePreparationExecutor:
    """Execute at most one Preparation with server-owned build policy."""

    def __init__(
        self,
        *,
        worker: BasePreparationWorker,
        builder: ReleasePreparationBuilder,
        candidate_ttl: timedelta,
    ) -> None:
        if not isinstance(candidate_ttl, timedelta) or candidate_ttl <= timedelta(0):
            raise BasePreparationError("base_preparation_invalid_candidate_ttl")
        self._worker = worker
        self._builder = builder
        self._candidate_ttl = candidate_ttl

    def run_once(self) -> ReadyReleasePreparation | FailedReleasePreparation | None:
        return self._worker.run_next(
            builder=self._builder,
            candidate_ttl=self._candidate_ttl,
        )


class BasePreparationWorker:
    def __init__(
        self, *, repository: BasePreparationRepository, worker_id: str, lease_duration: timedelta
    ) -> None:
        if (
            not isinstance(worker_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", worker_id) is None
        ):
            raise BasePreparationError("base_preparation_invalid_worker")
        if not isinstance(lease_duration, timedelta) or not (
            timedelta(0) < lease_duration <= timedelta(hours=1)
        ):
            raise BasePreparationError("base_preparation_invalid_lease_duration")
        self._repository = repository
        self._worker_id = worker_id
        self._lease_duration = lease_duration

    def claim_next(self) -> PreparationClaim | None:
        with self._transaction() as transaction:
            return transaction.claim_next(self._worker_id, self._lease_duration)

    def renew(self, claim: PreparationClaim) -> PreparationClaim:
        try:
            claim = PreparationClaim.model_validate(claim.model_dump(mode="python"))
        except (ValidationError, AttributeError, TypeError):
            raise BasePreparationError("base_preparation_invalid_claim") from None
        if claim.worker_id != self._worker_id:
            raise BasePreparationError("base_preparation_stale_claim")
        with self._transaction() as transaction:
            return transaction.renew_claim(claim, self._lease_duration)

    def run_next(
        self, *, builder: ReleasePreparationBuilder, candidate_ttl: timedelta
    ) -> ReadyReleasePreparation | FailedReleasePreparation | None:
        if not isinstance(candidate_ttl, timedelta) or candidate_ttl <= timedelta(0):
            raise BasePreparationError("base_preparation_invalid_candidate_ttl")
        claim = self.claim_next()
        if claim is None:
            return None
        try:
            candidate = builder.build(claim.admission.base_version)
        except Exception:
            with self._transaction() as transaction:
                return transaction.fail_claim(claim, "base_preparation_build_failed")
        try:
            if not isinstance(candidate, PreparedKnowledgeBaseRelease):
                raise TypeError
            validate_prepared_candidate(claim.admission, candidate)
        except (BasePreparationError, AttributeError, TypeError, ValueError):
            with self._transaction() as transaction:
                return transaction.fail_claim(claim, "base_preparation_invalid_candidate")
        with self._transaction() as transaction:
            return transaction.complete_claim(claim, candidate, candidate_ttl)

    def audit(self, base_id: str) -> tuple[PreparationWorkerAuditEntry, ...]:
        with self._transaction() as transaction:
            return transaction.worker_audit(base_id)

    @contextmanager
    def _transaction(self) -> Iterator[BasePreparationTransaction]:
        try:
            with self._repository.transaction() as transaction:
                yield transaction
        except BasePreparationError:
            raise
        except Exception:
            raise BasePreparationError("base_preparation_worker_unavailable") from None
