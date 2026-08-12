from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from knowledge_source_service.adapters.postgres.knowledge_queries import (
    KnowledgeQueryPersistenceConflict,
    PostgresKnowledgeQueryRepository,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.application.knowledge_queries import (
    KnowledgeQueryApplication,
    KnowledgeServiceClient,
)
from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
    KnowledgeServiceProblem,
)
from knowledge_source_service.domain.knowledge_queries import StaleKnowledgeQueryClaim
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission


pytestmark = pytest.mark.postgres_integration


class AllowingAuthorizer:
    def authorize(
        self, *, client_id: str, request: CreateKnowledgeQueryRequest
    ) -> KnowledgeQueryAdmission:
        return KnowledgeQueryAdmission(
            knowledge_space_id="space-durable",
            client_grant_id=f"grant-{client_id}",
            effective_access_scope_digest=f"sha256:{'a' * 64}",
        )


def test_postgres_repository_rebuilds_the_complete_admitted_query(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    first_repository = PostgresKnowledgeQueryRepository.from_dsn(kss_postgres_dsn)
    application = KnowledgeQueryApplication(
        repository=first_repository,
        authorizer=AllowingAuthorizer(),
        clock=lambda: datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        id_factory=lambda: "query-durable-1",
    )
    request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": "release-durable-1",
            "question": "理赔规则是什么？",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1000,
                "max_duration_ms": 5000,
            },
            "deadline_at": "2026-08-12T09:01:00Z",
        }
    )
    created = application.create(
        request,
        client=KnowledgeServiceClient(client_id="proof-agent-client"),
        idempotency_key="run-1:retrieval-1:attempt-1",
    )
    first_repository.close()

    rebuilt_repository = PostgresKnowledgeQueryRepository.from_dsn(kss_postgres_dsn)
    rebuilt = rebuilt_repository.get("query-durable-1")
    replay = rebuilt_repository.get_by_idempotency(
        client_id="proof-agent-client",
        idempotency_key="run-1:retrieval-1:attempt-1",
    )
    rebuilt_repository.close()

    assert rebuilt is not None
    assert rebuilt.query == created.query
    assert rebuilt.request == request
    assert rebuilt.client_id == "proof-agent-client"
    assert rebuilt.admission == KnowledgeQueryAdmission(
        knowledge_space_id="space-durable",
        client_grant_id="grant-proof-agent-client",
        effective_access_scope_digest=f"sha256:{'a' * 64}",
    )
    assert replay == rebuilt


def test_postgres_claim_uses_a_lease_and_rejects_a_stale_fencing_token(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    repository = PostgresKnowledgeQueryRepository.from_dsn(kss_postgres_dsn)
    application = KnowledgeQueryApplication(
        repository=repository,
        authorizer=AllowingAuthorizer(),
        clock=lambda: datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        id_factory=lambda: "query-leased-1",
    )
    request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": "release-durable-1",
            "question": "理赔规则是什么？",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1000,
                "max_duration_ms": 5000,
            },
            "deadline_at": "2026-08-12T09:05:00Z",
        }
    )
    application.create(
        request,
        client=KnowledgeServiceClient(client_id="proof-agent-client"),
        idempotency_key="run-lease:retrieval-1:attempt-1",
    )

    first = repository.claim_next_queued(
        worker_id="worker-a",
        now=datetime(2026, 8, 12, 9, 0, 1, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    blocked = repository.claim_next_queued(
        worker_id="worker-b",
        now=datetime(2026, 8, 12, 9, 0, 20, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    takeover = repository.claim_next_queued(
        worker_id="worker-b",
        now=datetime(2026, 8, 12, 9, 0, 32, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )

    assert first is not None
    assert blocked is None
    assert takeover is not None
    assert first.fencing_token == 1
    assert takeover.fencing_token == 2

    first_running = replace(
        first.record,
        query=first.record.query.model_copy(
            update={
                "state": "running",
                "started_at": datetime(2026, 8, 12, 9, 0, 1, tzinfo=UTC),
            }
        ),
    )
    with pytest.raises(StaleKnowledgeQueryClaim):
        repository.save_claim(first, first_running)

    takeover_running = replace(
        takeover.record,
        query=takeover.record.query.model_copy(
            update={
                "state": "running",
                "started_at": datetime(2026, 8, 12, 9, 0, 32, tzinfo=UTC),
            }
        ),
    )
    repository.save_claim(takeover, takeover_running)

    persisted = repository.get("query-leased-1")
    repository.close()
    assert persisted is not None
    assert persisted.query.state == "running"
    assert persisted.query.started_at == datetime(2026, 8, 12, 9, 0, 32, tzinfo=UTC)


def test_postgres_running_claim_can_renew_its_lease_without_changing_the_fence(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    repository = PostgresKnowledgeQueryRepository.from_dsn(kss_postgres_dsn)
    application = KnowledgeQueryApplication(
        repository=repository,
        authorizer=AllowingAuthorizer(),
        clock=lambda: datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        id_factory=lambda: "query-renewed-1",
    )
    application.create(
        CreateKnowledgeQueryRequest.model_validate(
            {
                "knowledge_base_release_id": "release-durable-1",
                "question": "理赔规则是什么？",
                "execution_budget": {
                    "max_rounds": 1,
                    "max_model_calls": 1,
                    "max_candidates": 20,
                    "max_model_tokens": 1000,
                    "max_duration_ms": 120_000,
                },
                "deadline_at": "2026-08-12T09:05:00Z",
            }
        ),
        client=KnowledgeServiceClient(client_id="proof-agent-client"),
        idempotency_key="run-renewed:retrieval-1:attempt-1",
    )
    claim = repository.claim_next_queued(
        worker_id="worker-a",
        now=datetime(2026, 8, 12, 9, 0, 1, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    assert claim is not None
    repository.save_claim(
        claim,
        replace(
            claim.record,
            query=claim.record.query.model_copy(
                update={
                    "state": "running",
                    "started_at": datetime(2026, 8, 12, 9, 0, 1, tzinfo=UTC),
                }
            ),
        ),
    )

    repository.renew_claim(
        claim,
        now=datetime(2026, 8, 12, 9, 0, 20, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    blocked = repository.claim_next_queued(
        worker_id="worker-b",
        now=datetime(2026, 8, 12, 9, 0, 32, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    takeover = repository.claim_next_queued(
        worker_id="worker-b",
        now=datetime(2026, 8, 12, 9, 0, 51, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )

    assert blocked is None
    assert takeover is not None
    assert takeover.fencing_token == claim.fencing_token + 1
    with pytest.raises(StaleKnowledgeQueryClaim):
        repository.renew_claim(
            claim,
            now=datetime(2026, 8, 12, 9, 0, 52, tzinfo=UTC),
            lease_duration=timedelta(seconds=30),
        )
    repository.close()


def test_postgres_state_version_prevents_stale_cancel_from_overwriting_terminal_state(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    repository = PostgresKnowledgeQueryRepository.from_dsn(kss_postgres_dsn)
    application = KnowledgeQueryApplication(
        repository=repository,
        authorizer=AllowingAuthorizer(),
        clock=lambda: datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        id_factory=lambda: "query-cas-1",
    )
    request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": "release-durable-1",
            "question": "理赔规则是什么？",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1000,
                "max_duration_ms": 5000,
            },
            "deadline_at": "2026-08-12T09:05:00Z",
        }
    )
    application.create(
        request,
        client=KnowledgeServiceClient(client_id="proof-agent-client"),
        idempotency_key="run-cas:retrieval-1:attempt-1",
    )
    claim = repository.claim_next_queued(
        worker_id="worker-a",
        now=datetime(2026, 8, 12, 9, 0, 1, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    assert claim is not None
    running = replace(
        claim.record,
        query=claim.record.query.model_copy(
            update={
                "state": "running",
                "started_at": datetime(2026, 8, 12, 9, 0, 1, tzinfo=UTC),
            }
        ),
    )
    repository.save_claim(claim, running)
    stale_cancel_base = repository.get("query-cas-1")
    assert stale_cancel_base is not None

    failed = replace(
        stale_cancel_base,
        query=stale_cancel_base.query.model_copy(
            update={
                "state": "failed",
                "completed_at": datetime(2026, 8, 12, 9, 0, 2, tzinfo=UTC),
                "result_availability": "unavailable",
                "problem": KnowledgeServiceProblem(
                    type="urn:test:failed",
                    title="Execution failed",
                    status=500,
                    code="execution_failed",
                    detail="Execution failed safely.",
                    trace_id="trace-cas-1",
                    retryable=False,
                ),
            }
        ),
    )
    repository.save_claim(claim, failed)

    stale_cancelled = replace(
        stale_cancel_base,
        query=stale_cancel_base.query.model_copy(
            update={
                "state": "cancelled",
                "cancel_requested_at": datetime(2026, 8, 12, 9, 0, 2, tzinfo=UTC),
                "completed_at": datetime(2026, 8, 12, 9, 0, 2, tzinfo=UTC),
                "result_availability": "unavailable",
            }
        ),
    )
    with pytest.raises(KnowledgeQueryPersistenceConflict):
        repository.add(stale_cancelled)

    persisted = repository.get("query-cas-1")
    repository.close()
    assert persisted is not None
    assert persisted.query.state == "failed"
