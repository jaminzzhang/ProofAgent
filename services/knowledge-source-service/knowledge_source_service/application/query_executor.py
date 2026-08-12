"""Application loop for executing admitted Knowledge Queries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
import threading

from knowledge_source_service.contracts.knowledge_query import (
    KnowledgeQuery,
    KnowledgeServiceProblem,
)
from knowledge_source_service.contracts.results import KnowledgeQueryResult
from knowledge_source_service.domain.knowledge_queries import KnowledgeQueryRecord
from knowledge_source_service.domain.knowledge_queries import (
    KnowledgeQueryClaim,
    StaleKnowledgeQueryClaim,
)
from knowledge_source_service.ports.knowledge_queries import KnowledgeQueryRepository
from knowledge_source_service.ports.retrieval import (
    AdmittedKnowledgeQuery,
    KnowledgeRetrievalEngine,
)


class KnowledgeQueryExecutor:
    """Move one queued Query through the real retrieval seam to success."""

    def __init__(
        self,
        *,
        repository: KnowledgeQueryRepository,
        retrieval_engine: KnowledgeRetrievalEngine,
        clock: Callable[[], datetime],
        result_retention: timedelta,
        trace_id_factory: Callable[[], str],
        worker_id: str,
        lease_duration: timedelta,
    ) -> None:
        self._repository = repository
        self._retrieval_engine = retrieval_engine
        self._clock = clock
        self._result_retention = result_retention
        self._trace_id_factory = trace_id_factory
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._worker_id = worker_id
        self._lease_duration = lease_duration

    def run_once(self) -> bool:
        """Execute at most one queued Query and report whether work was found."""

        started_at = self._clock()
        claim = self._repository.claim_next_queued(
            worker_id=self._worker_id,
            now=started_at,
            lease_duration=self._lease_duration,
        )
        if claim is None:
            return False
        record = claim.record

        if record.request.deadline_at <= started_at:
            self._record_expired(
                claim,
                record,
                record.query,
                completed_at=started_at,
            )
            return True

        running = _validated_transition(
            record.query,
            state="running",
            started_at=started_at,
        )
        if not self._save_claim(claim, replace(record, query=running)):
            return True

        heartbeat = _KnowledgeQueryLeaseHeartbeat(
            repository=self._repository,
            claim=claim,
            clock=self._clock,
            lease_duration=self._lease_duration,
        )
        result: KnowledgeQueryResult | None = None
        execution_failed = False
        heartbeat.start()
        try:
            result = self._retrieval_engine.retrieve(
                AdmittedKnowledgeQuery(
                    request=record.request,
                    admission=record.admission,
                )
            )
        except Exception:
            execution_failed = True
        finally:
            heartbeat.stop()

        if heartbeat.claim_lost:
            return True
        if execution_failed:
            if not self._execution_is_still_running(record.query.knowledge_query_id):
                return True
            completed_at = self._clock()
            failed = _validated_transition(
                running,
                state="failed",
                completed_at=completed_at,
                result_availability="unavailable",
                problem=_unexpected_execution_problem(self._trace_id_factory()),
            )
            self._save_claim(claim, replace(record, query=failed))
            return True

        if result is None:
            raise RuntimeError("retrieval engine returned no typed result")
        if not self._execution_is_still_running(record.query.knowledge_query_id):
            return True
        completed_at = self._clock()
        if record.request.deadline_at <= completed_at:
            self._record_expired(claim, record, running, completed_at=completed_at)
            return True

        succeeded = _validated_transition(
            running,
            state="succeeded",
            completed_at=completed_at,
            result_availability="available",
            result_expires_at=completed_at + self._result_retention,
            result=result,
        )
        self._save_claim(claim, replace(record, query=succeeded))
        return True

    def _record_expired(
        self,
        claim: KnowledgeQueryClaim,
        record: KnowledgeQueryRecord,
        current: KnowledgeQuery,
        *,
        completed_at: datetime,
    ) -> None:
        expired = _validated_transition(
            current,
            state="expired",
            completed_at=completed_at,
            result_availability="unavailable",
            problem=_deadline_elapsed_problem(self._trace_id_factory()),
        )
        self._save_claim(claim, replace(record, query=expired))

    def _save_claim(
        self,
        claim: KnowledgeQueryClaim,
        record: KnowledgeQueryRecord,
    ) -> bool:
        try:
            self._repository.save_claim(claim, record)
        except StaleKnowledgeQueryClaim:
            return False
        return True

    def _execution_is_still_running(self, knowledge_query_id: str) -> bool:
        current = self._repository.get(knowledge_query_id)
        return current is not None and current.query.state == "running"


class _KnowledgeQueryLeaseHeartbeat:
    """Renew one fenced claim while its synchronous retrieval call is active."""

    def __init__(
        self,
        *,
        repository: KnowledgeQueryRepository,
        claim: KnowledgeQueryClaim,
        clock: Callable[[], datetime],
        lease_duration: timedelta,
    ) -> None:
        self._repository = repository
        self._claim = claim
        self._clock = clock
        self._lease_duration = lease_duration
        self._interval_seconds = lease_duration.total_seconds() / 3
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="knowledge-query-lease-heartbeat",
            daemon=True,
        )

    @property
    def claim_lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=min(max(self._interval_seconds, 0.1), 5.0))
        if self._thread.is_alive():
            self._lost.set()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                self._repository.renew_claim(
                    self._claim,
                    now=self._clock(),
                    lease_duration=self._lease_duration,
                )
            except Exception:
                self._lost.set()
                return


def _validated_transition(query: KnowledgeQuery, **changes: object) -> KnowledgeQuery:
    payload = query.model_dump(mode="python")
    payload.update(changes)
    return KnowledgeQuery.model_validate(payload)


def _unexpected_execution_problem(trace_id: str) -> KnowledgeServiceProblem:
    return KnowledgeServiceProblem(
        type="urn:knowledge-source-service:problem:knowledge-query-execution-failed",
        title="Knowledge Query execution failed",
        status=500,
        code="KNOWLEDGE_QUERY_EXECUTION_FAILED",
        detail="The Knowledge Query could not be completed.",
        trace_id=trace_id,
        retryable=False,
    )


def _deadline_elapsed_problem(trace_id: str) -> KnowledgeServiceProblem:
    return KnowledgeServiceProblem(
        type="urn:knowledge-source-service:problem:knowledge-query-deadline-elapsed",
        title="Knowledge Query deadline elapsed",
        status=408,
        code="knowledge_query_deadline_elapsed",
        detail="The Knowledge Query deadline elapsed before completion.",
        trace_id=trace_id,
        retryable=False,
    )
