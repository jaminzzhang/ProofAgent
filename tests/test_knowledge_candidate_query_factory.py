from __future__ import annotations

from datetime import UTC, datetime, timedelta

from proof_agent.control.knowledge.candidate_request import (
    BoundKnowledgeCandidateQueryFactory,
)
from proof_agent.contracts.knowledge_candidates import KnowledgeCandidateExecutionBudget


def test_bound_factory_freezes_release_and_stabilizes_semantic_attempt_identity() -> None:
    factory = BoundKnowledgeCandidateQueryFactory(
        knowledge_base_release_id="release-published-agent-v1",
        execution_budget=KnowledgeCandidateExecutionBudget(
            max_rounds=3,
            max_model_calls=4,
            max_candidates=50,
            max_model_tokens=2000,
            max_duration_ms=5000,
        ),
        deadline_after=timedelta(seconds=10),
        clock=lambda: datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        access_assertion_factory=lambda run_id: f"signed-context:{run_id}",
    )

    first = factory.build(
        run_id="run-1",
        retrieval_action_id="action-retrieve-1",
        semantic_attempt="plan-round-1",
        question="理赔增长原因",
        strategy="agentic",
    )
    replay = factory.build(
        run_id="run-1",
        retrieval_action_id="action-retrieve-1",
        semantic_attempt="plan-round-1",
        question="理赔增长原因",
        strategy="agentic",
    )
    next_attempt = factory.build(
        run_id="run-1",
        retrieval_action_id="action-retrieve-1",
        semantic_attempt="plan-round-2",
        question="理赔增长原因",
        strategy="agentic",
    )

    assert first == replay
    assert first.idempotency_key != next_attempt.idempotency_key
    assert first.idempotency_key.startswith("knowledge-query:v1:sha256:")
    assert first.knowledge_base_release_id == "release-published-agent-v1"
    assert first.strategy == "agentic"
    assert first.deadline_at == datetime(2026, 8, 12, 9, 0, 10, tzinfo=UTC)
    assert first.access_narrowing_context is not None
    assert first.access_narrowing_context.assertion_token == "signed-context:run-1"
