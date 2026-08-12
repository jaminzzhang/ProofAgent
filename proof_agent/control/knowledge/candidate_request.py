"""Build exact Knowledge Candidate Queries from a Published Agent binding."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Literal, Protocol

from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateAccessContext,
    KnowledgeCandidateExecutionBudget,
    KnowledgeCandidateQuery,
    KnowledgeCandidateQueryConstraints,
)


class KnowledgeCandidateQueryFactory(Protocol):
    def build(
        self,
        *,
        run_id: str,
        retrieval_action_id: str,
        semantic_attempt: str,
        question: str,
        strategy: Literal["single_step", "single_pass", "agentic"],
    ) -> KnowledgeCandidateQuery: ...


@dataclass(frozen=True)
class BoundKnowledgeCandidateQueryFactory:
    """Freeze one Published Agent Version to one exact Knowledge Base Release."""

    knowledge_base_release_id: str
    execution_budget: KnowledgeCandidateExecutionBudget
    deadline_after: timedelta
    clock: Callable[[], datetime]
    access_assertion_factory: Callable[[str], str] | None = None
    query_constraints: KnowledgeCandidateQueryConstraints = field(
        default_factory=KnowledgeCandidateQueryConstraints
    )

    def __post_init__(self) -> None:
        if not self.knowledge_base_release_id.strip():
            raise ValueError("knowledge_base_release_id must be non-blank")
        if self.deadline_after <= timedelta(0):
            raise ValueError("deadline_after must be positive")

    def build(
        self,
        *,
        run_id: str,
        retrieval_action_id: str,
        semantic_attempt: str,
        question: str,
        strategy: Literal["single_step", "single_pass", "agentic"],
    ) -> KnowledgeCandidateQuery:
        idempotency_key = _idempotency_key(
            run_id=run_id,
            retrieval_action_id=retrieval_action_id,
            semantic_attempt=semantic_attempt,
            knowledge_base_release_id=self.knowledge_base_release_id,
        )
        assertion_token = (
            self.access_assertion_factory(run_id)
            if self.access_assertion_factory is not None
            else None
        )
        return KnowledgeCandidateQuery(
            idempotency_key=idempotency_key,
            knowledge_base_release_id=self.knowledge_base_release_id,
            question=question,
            strategy="agentic" if strategy == "agentic" else "single_pass",
            query_constraints=self.query_constraints,
            access_narrowing_context=(
                KnowledgeCandidateAccessContext(assertion_token=assertion_token)
                if assertion_token is not None
                else None
            ),
            execution_budget=self.execution_budget,
            deadline_at=self.clock() + self.deadline_after,
        )


def _idempotency_key(
    *,
    run_id: str,
    retrieval_action_id: str,
    semantic_attempt: str,
    knowledge_base_release_id: str,
) -> str:
    canonical = json.dumps(
        {
            "contract": "knowledge-query.v1",
            "run_id": run_id,
            "retrieval_action_id": retrieval_action_id,
            "semantic_attempt": semantic_attempt,
            "knowledge_base_release_id": knowledge_base_release_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"knowledge-query:v1:sha256:{sha256(canonical.encode()).hexdigest()}"
