"""Narrow control interface for bounded Agentic retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class AgenticRetrievalObservation:
    """Content-free retrieval metadata exposed to a planner/evaluator."""

    retrieval_round: int
    question: str
    knowledge_base_release_id: str
    access_scope_digest: str
    candidate_count: int
    candidate_evidence_ids: tuple[str, ...]
    remaining_rounds: int
    remaining_model_calls: int
    remaining_model_tokens: int
    remaining_duration_ms: int

    def __post_init__(self) -> None:
        if self.remaining_duration_ms < 1:
            raise ValueError("remaining_duration_ms must be positive")


@dataclass(frozen=True)
class AgenticRetrievalDecision:
    """One bounded control signal; never an answer or Admission decision."""

    action: Literal["continue", "complete", "abort"]
    revised_question: str | None
    model_tokens_used: int

    def __post_init__(self) -> None:
        if self.model_tokens_used < 0:
            raise ValueError("model_tokens_used cannot be negative")
        if self.action == "continue" and (
            self.revised_question is None or not self.revised_question.strip()
        ):
            raise ValueError("continue requires a non-blank revised_question")
        if self.action != "continue" and self.revised_question is not None:
            raise ValueError("only continue may supply a revised_question")


class AgenticRetrievalController(Protocol):
    """Choose a retrieval control action from content-free observations."""

    def decide(self, observation: AgenticRetrievalObservation) -> AgenticRetrievalDecision: ...
