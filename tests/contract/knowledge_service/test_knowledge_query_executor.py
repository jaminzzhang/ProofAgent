from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import threading
from typing import Any

from fastapi import Request
from fastapi.testclient import TestClient

from knowledge_source_service.adapters.memory.knowledge_queries import (
    InMemoryKnowledgeQueryRepository,
)
from knowledge_source_service.application.knowledge_queries import (
    KnowledgeQueryApplication,
    KnowledgeServiceClient,
)
from knowledge_source_service.application.query_executor import KnowledgeQueryExecutor
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.contracts.results import KnowledgeQueryResult
from knowledge_source_service.delivery.http import create_application
from knowledge_source_service.ports.retrieval import (
    AdmittedKnowledgeQuery,
    KnowledgeRetrievalEngine,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _result_payload() -> dict[str, Any]:
    return {
        "schema_version": "knowledge-query-result.v1",
        "evidence_groups": [
            {
                "evidence_group_id": "relevance-group-1",
                "group_type": "relevance_ranked",
                "ordering": {"kind": "relevance", "final_rank_field": "fused_rank"},
                "candidate_evidence": [],
            }
        ],
        "query_plan_summary": {
            "plan_revision": 1,
            "planned_lanes": ["lexical"],
            "structured_query_count": 0,
            "plan_digest": _digest("a"),
        },
        "execution_summary": {
            "strategy": "single_pass",
            "rounds": 1,
            "stop_reason": "single_pass_complete",
            "degraded": False,
            "budget_usage": {
                "rounds": 1,
                "model_calls": 0,
                "candidates": 0,
                "model_tokens": 0,
                "duration_ms": 8_000,
            },
        },
        "retrieval_lineage": {
            "knowledge_base_release_id": "release-opaque-id",
            "release_manifest_digest": _digest("b"),
            "access_scope_digest": _digest("c"),
            "plan_revision_digests": [_digest("d")],
        },
    }


class StaticRetrievalEngine:
    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        assert query.request.question == "理赔规则是什么？"
        assert query.request.knowledge_base_release_id == "release-opaque-id"
        return KnowledgeQueryResult.model_validate(_result_payload())


class FailingRetrievalEngine:
    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        raise RuntimeError(
            "postgresql://internal-user:secret@authority/"
            f"{query.request.knowledge_base_release_id}"
        )


class CountingRetrievalEngine:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        self.calls += 1
        return KnowledgeQueryResult.model_validate(_result_payload())


class CallbackRetrievalEngine:
    def __init__(self) -> None:
        self.on_retrieve: Callable[[], None] | None = None

    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        assert self.on_retrieve is not None
        self.on_retrieve()
        return KnowledgeQueryResult.model_validate(_result_payload())


class CapturingRetrievalEngine:
    def __init__(self) -> None:
        self.received: Any = None

    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        self.received = query
        return KnowledgeQueryResult.model_validate(_result_payload())


class RenewalObservingRepository(InMemoryKnowledgeQueryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.renewed = threading.Event()
        self.renewal_count = 0

    def renew_claim(
        self,
        claim: Any,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> None:
        super().renew_claim(claim, now=now, lease_duration=lease_duration)
        self.renewal_count += 1
        self.renewed.set()


class LeaseAwareRetrievalEngine:
    def __init__(
        self,
        *,
        repository: RenewalObservingRepository,
        contender_at: datetime,
    ) -> None:
        self._repository = repository
        self._contender_at = contender_at
        self.contender_claim: Any = "not-attempted"

    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        assert self._repository.renewed.wait(timeout=0.5)
        self.contender_claim = self._repository.claim_next_queued(
            worker_id="worker-contender",
            now=self._contender_at,
            lease_duration=timedelta(milliseconds=90),
        )
        return KnowledgeQueryResult.model_validate(_result_payload())


def _authenticate(_request: Request) -> KnowledgeServiceClient:
    return KnowledgeServiceClient(client_id="agent-client-1")


class AllowingTestAuthorizer:
    def authorize(
        self, *, client_id: str, request: CreateKnowledgeQueryRequest
    ) -> KnowledgeQueryAdmission:
        return KnowledgeQueryAdmission(
            knowledge_space_id="space-test",
            client_grant_id=f"grant-{client_id}",
            effective_access_scope_digest=f"sha256:{'a' * 64}",
        )


def _executor_clock() -> datetime:
    return datetime(2026, 8, 11, 10, 29, 18, tzinfo=UTC)


def _runtime(
    retrieval_engine: KnowledgeRetrievalEngine,
    *,
    executor_clock: Callable[[], datetime] = _executor_clock,
    executor_trace_id_factory: Callable[[], str] = lambda: "trace-executor-1",
    application_clock: Callable[[], datetime] | None = None,
    repository: InMemoryKnowledgeQueryRepository | None = None,
    lease_duration: timedelta = timedelta(minutes=1),
) -> tuple[TestClient, KnowledgeQueryExecutor]:
    repository = repository or InMemoryKnowledgeQueryRepository()

    def create_clock() -> datetime:
        return datetime(2026, 8, 11, 10, 29, 10, tzinfo=UTC)

    query_application = KnowledgeQueryApplication(
        repository=repository,
        authorizer=AllowingTestAuthorizer(),
        clock=application_clock or create_clock,
        id_factory=lambda: "query-1",
    )
    client = TestClient(
        create_application(
            query_application=query_application,
            authenticate_client=_authenticate,
            trace_id_factory=lambda: "trace-1",
            release_identity="kss-test-release",
            readiness_probe=lambda: {
                "postgresql": True,
                "object_storage": True,
                "search": True,
            },
        )
    )
    executor = KnowledgeQueryExecutor(
        repository=repository,
        retrieval_engine=retrieval_engine,
        clock=executor_clock,
        result_retention=timedelta(days=1),
        trace_id_factory=executor_trace_id_factory,
        worker_id="worker-test-1",
        lease_duration=lease_duration,
    )
    return client, executor


def _create_query(client: TestClient) -> Any:
    return client.post(
        "/v1/knowledge-queries",
        headers={"Idempotency-Key": "attempt-1"},
        json={
            "knowledge_base_release_id": "release-opaque-id",
            "question": "理赔规则是什么？",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1_000,
                "max_duration_ms": 10_000,
            },
            "deadline_at": "2026-08-11T10:30:00Z",
        },
    )


def test_executor_completes_one_queued_query_with_a_typed_result() -> None:
    client, executor = _runtime(StaticRetrievalEngine())
    create_response = _create_query(client)

    worked = executor.run_once()
    get_response = client.get(create_response.headers["location"])

    assert worked is True
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["state"] == "succeeded"
    assert body["started_at"] == "2026-08-11T10:29:18Z"
    assert body["completed_at"] == "2026-08-11T10:29:18Z"
    assert body["result_availability"] == "available"
    assert body["result_expires_at"] == "2026-08-12T10:29:18Z"
    assert body["result"] == _result_payload()


def test_executor_renews_the_fenced_lease_during_long_retrieval() -> None:
    base = datetime(2026, 8, 11, 10, 29, 18, tzinfo=UTC)
    clock_values = iter(
        (
            base,
            base + timedelta(milliseconds=60),
            base + timedelta(milliseconds=70),
        )
    )
    repository = RenewalObservingRepository()
    retrieval_engine = LeaseAwareRetrievalEngine(
        repository=repository,
        contender_at=base + timedelta(milliseconds=100),
    )
    client, executor = _runtime(
        retrieval_engine,
        executor_clock=lambda: next(clock_values),
        repository=repository,
        lease_duration=timedelta(milliseconds=90),
    )
    created = _create_query(client)

    worked = executor.run_once()

    assert worked is True
    assert repository.renewal_count == 1
    assert retrieval_engine.contender_claim is None
    assert client.get(created.headers["location"]).json()["state"] == "succeeded"


def test_result_content_is_not_exposed_after_its_retention_deadline() -> None:
    application_now = [datetime(2026, 8, 11, 10, 29, 10, tzinfo=UTC)]
    client, executor = _runtime(
        StaticRetrievalEngine(),
        application_clock=lambda: application_now[0],
    )
    created = _create_query(client)
    executor.run_once()
    application_now[0] = datetime(2026, 8, 12, 10, 29, 18, tzinfo=UTC)

    expired_view = client.get(created.headers["location"])

    assert expired_view.status_code == 200
    assert expired_view.json()["state"] == "succeeded"
    assert expired_view.json()["result_availability"] == "expired"
    assert expired_view.json()["result"] is None


def test_executor_passes_frozen_admission_context_to_retrieval() -> None:
    retrieval_engine = CapturingRetrievalEngine()
    client, executor = _runtime(retrieval_engine)
    _create_query(client)

    executor.run_once()

    assert retrieval_engine.received.request.knowledge_base_release_id == "release-opaque-id"
    assert retrieval_engine.received.admission.knowledge_space_id == "space-test"
    assert retrieval_engine.received.admission.client_grant_id == "grant-agent-client-1"
    assert retrieval_engine.received.admission.effective_access_scope_digest == (
        f"sha256:{'a' * 64}"
    )


def test_executor_records_an_unexpected_retrieval_failure_without_leaking_it() -> None:
    client, executor = _runtime(
        FailingRetrievalEngine(),
        executor_trace_id_factory=lambda: "trace-executor-failure-1",
    )
    create_response = _create_query(client)

    worked = executor.run_once()
    get_response = client.get(create_response.headers["location"])

    assert worked is True
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["state"] == "failed"
    assert body["started_at"] == "2026-08-11T10:29:18Z"
    assert body["completed_at"] == "2026-08-11T10:29:18Z"
    assert body["result_availability"] == "unavailable"
    assert body["result"] is None
    assert body["result_expires_at"] is None
    assert body["problem"] == {
        "type": "urn:knowledge-source-service:problem:knowledge-query-execution-failed",
        "title": "Knowledge Query execution failed",
        "status": 500,
        "code": "KNOWLEDGE_QUERY_EXECUTION_FAILED",
        "detail": "The Knowledge Query could not be completed.",
        "trace_id": "trace-executor-failure-1",
        "retryable": False,
        "blockers": [],
    }
    assert "secret" not in str(body)


def test_executor_expires_queued_work_before_calling_retrieval_after_deadline() -> None:
    retrieval_engine = CountingRetrievalEngine()
    client, executor = _runtime(
        retrieval_engine,
        executor_clock=lambda: datetime(2026, 8, 11, 10, 30, 0, tzinfo=UTC),
        executor_trace_id_factory=lambda: "trace-executor-deadline-1",
    )
    create_response = _create_query(client)

    worked = executor.run_once()
    get_response = client.get(create_response.headers["location"])

    assert worked is True
    assert retrieval_engine.calls == 0
    body = get_response.json()
    assert body["state"] == "expired"
    assert body["started_at"] is None
    assert body["completed_at"] == "2026-08-11T10:30:00Z"
    assert body["result_availability"] == "unavailable"
    assert body["problem"] == {
        "type": "urn:knowledge-source-service:problem:knowledge-query-deadline-elapsed",
        "title": "Knowledge Query deadline elapsed",
        "status": 408,
        "code": "knowledge_query_deadline_elapsed",
        "detail": "The Knowledge Query deadline elapsed before completion.",
        "trace_id": "trace-executor-deadline-1",
        "retryable": False,
        "blockers": [],
    }


def test_executor_discards_a_result_that_finishes_at_the_absolute_deadline() -> None:
    retrieval_engine = CountingRetrievalEngine()
    clock_values = iter(
        (
            datetime(2026, 8, 11, 10, 29, 59, tzinfo=UTC),
            datetime(2026, 8, 11, 10, 30, 0, tzinfo=UTC),
        )
    )
    client, executor = _runtime(
        retrieval_engine,
        executor_clock=lambda: next(clock_values),
        executor_trace_id_factory=lambda: "trace-executor-late-result-1",
    )
    create_response = _create_query(client)

    worked = executor.run_once()
    get_response = client.get(create_response.headers["location"])

    assert worked is True
    assert retrieval_engine.calls == 1
    body = get_response.json()
    assert body["state"] == "expired"
    assert body["started_at"] == "2026-08-11T10:29:59Z"
    assert body["completed_at"] == "2026-08-11T10:30:00Z"
    assert body["result_availability"] == "unavailable"
    assert body["result"] is None
    assert body["problem"]["trace_id"] == "trace-executor-late-result-1"
    assert body["problem"]["code"] == "knowledge_query_deadline_elapsed"


def test_executor_cannot_commit_success_after_running_query_is_cancelled() -> None:
    retrieval_engine = CallbackRetrievalEngine()
    client, executor = _runtime(retrieval_engine)
    create_response = _create_query(client)
    cancel_responses: list[Any] = []
    retrieval_engine.on_retrieve = lambda: cancel_responses.append(
        client.post(f"{create_response.headers['location']}:cancel")
    )

    worked = executor.run_once()
    get_response = client.get(create_response.headers["location"])

    assert worked is True
    assert cancel_responses[0].status_code == 200
    assert cancel_responses[0].json()["state"] == "cancelled"
    body = get_response.json()
    assert body["state"] == "cancelled"
    assert body["cancel_requested_at"] == "2026-08-11T10:29:10Z"
    assert body["result_availability"] == "unavailable"
    assert body["result"] is None


def test_cancel_cannot_rewrite_a_succeeded_query_terminal_state() -> None:
    client, executor = _runtime(StaticRetrievalEngine())
    create_response = _create_query(client)
    executor.run_once()

    cancel_response = client.post(f"{create_response.headers['location']}:cancel")
    get_response = client.get(create_response.headers["location"])

    assert cancel_response.status_code == 409
    assert cancel_response.headers["content-type"].startswith("application/problem+json")
    assert cancel_response.json() == {
        "type": "urn:knowledge-source-service:problem:knowledge-query-terminal-state-conflict",
        "title": "Knowledge Query terminal state conflict",
        "status": 409,
        "code": "knowledge_query_terminal_state_conflict",
        "detail": "A terminal Knowledge Query cannot be cancelled.",
        "trace_id": "trace-1",
        "retryable": False,
        "blockers": [],
    }
    assert get_response.json()["state"] == "succeeded"
    assert get_response.json()["result_availability"] == "available"
