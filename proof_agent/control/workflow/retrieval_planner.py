"""RetrievalPlanner for multi-round agentic retrieval (ADR-0015)."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from proof_agent.contracts import ModelMessage, ModelRequest, ModelRole
from proof_agent.contracts.evidence import EvidenceChunk


if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class RetrievalRound:
    """Single round of retrieval with query, candidates, evaluation, and action."""

    round_id: str
    query: str
    candidates: tuple[EvidenceChunk, ...]
    evaluation: dict[str, Any]
    action: str
    reason: str


@dataclass(frozen=True)
class RetrievalResult:
    """Result of multi-round agentic retrieval."""

    evidence: tuple[EvidenceChunk, ...]
    total_rounds: int
    final_action: str
    rounds: tuple[RetrievalRound, ...]


class KnowledgeProviderProtocol(Protocol):
    """Protocol for knowledge provider."""

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        """Retrieve evidence for query."""
        ...


class ModelProtocol(Protocol):
    """Protocol for LLM model."""

    def generate(self, request: Any) -> Any:
        """Generate response for prompt."""
        ...


class RetrievalPlanner:
    """Multi-round agentic retrieval planner (ADR-0015).

    Drives iterative retrieval cycles:
    1. Analyze question and plan retrieval
    2. Execute retrieval via KnowledgeProvider
    3. Evaluate evidence sufficiency
    4. Decide next action: rewrite/sufficient/abort

    Termination conditions:
    - LLM soft judgment: sufficient or abort
    - Hard limit: max_rounds reached

    Error handling:
    - Fail-closed: return accumulated evidence on any error
    """

    def __init__(
        self,
        knowledge_provider: KnowledgeProviderProtocol,
        planner_model: ModelProtocol,
        evaluator_model: ModelProtocol,
        max_rounds: int = 3,
    ):
        """Initialize retrieval planner.

        Args:
            knowledge_provider: Provider for retrieval
            planner_model: LLM for planning and query rewriting
            evaluator_model: LLM for evidence evaluation
            max_rounds: Maximum retrieval rounds (hard limit)
        """
        self.knowledge_provider = knowledge_provider
        self.planner_model = planner_model
        self.evaluator_model = evaluator_model
        self.max_rounds = max_rounds

    def plan_and_retrieve(self, question: str) -> RetrievalResult:
        """Execute multi-round agentic retrieval.

        Args:
            question: Original question to answer

        Returns:
            RetrievalResult with accumulated evidence and round history
        """
        rounds: list[RetrievalRound] = []
        all_evidence: list[EvidenceChunk] = []
        current_query = question
        round_num = 0

        while round_num < self.max_rounds:
            round_num += 1
            round_id = f"round_{round_num:02d}_{uuid.uuid4().hex[:8]}"

            # Execute retrieval
            try:
                candidates = tuple(self.knowledge_provider.retrieve(current_query))
            except Exception:
                # Provider failure: return accumulated evidence
                return RetrievalResult(
                    evidence=tuple(all_evidence),
                    total_rounds=round_num,
                    final_action="provider_failure",
                    rounds=tuple(rounds),
                )

            all_evidence.extend(candidates)

            # Evaluate evidence sufficiency
            try:
                evaluation_prompt = self._build_evaluation_prompt(question, all_evidence)
                evaluation_response = self._generate_text(self.evaluator_model, evaluation_prompt)
                evaluation = json.loads(evaluation_response)
            except Exception:
                # Evaluator failure: return accumulated evidence
                return RetrievalResult(
                    evidence=tuple(all_evidence),
                    total_rounds=round_num,
                    final_action="evaluator_failure",
                    rounds=tuple(rounds),
                )

            # Generate action plan
            try:
                action_prompt = self._build_action_prompt(
                    question, current_query, candidates, evaluation
                )
                action_response = self._generate_text(self.planner_model, action_prompt)
                action_plan = json.loads(action_response)
                action = action_plan.get("action", "sufficient")
                reason = action_plan.get("reason", "")
                new_query = action_plan.get("new_query", "")
            except Exception:
                # Planner failure: return accumulated evidence
                return RetrievalResult(
                    evidence=tuple(all_evidence),
                    total_rounds=round_num,
                    final_action="planner_failure",
                    rounds=tuple(rounds),
                )

            # Record round
            round_record = RetrievalRound(
                round_id=round_id,
                query=current_query,
                candidates=tuple(candidates),
                evaluation=evaluation,
                action=action,
                reason=reason,
            )
            rounds.append(round_record)

            # Check termination conditions
            if action == "sufficient":
                return RetrievalResult(
                    evidence=tuple(all_evidence),
                    total_rounds=round_num,
                    final_action="sufficient",
                    rounds=tuple(rounds),
                )
            elif action == "abort":
                return RetrievalResult(
                    evidence=tuple(all_evidence),
                    total_rounds=round_num,
                    final_action="abort",
                    rounds=tuple(rounds),
                )
            elif action == "rewrite":
                current_query = new_query
            else:
                # Unknown action: treat as sufficient
                return RetrievalResult(
                    evidence=tuple(all_evidence),
                    total_rounds=round_num,
                    final_action="sufficient",
                    rounds=tuple(rounds),
                )

        # Max rounds reached
        return RetrievalResult(
            evidence=tuple(all_evidence),
            total_rounds=round_num,
            final_action="max_rounds_reached",
            rounds=tuple(rounds),
        )

    def _build_evaluation_prompt(
        self, question: str, evidence: list[EvidenceChunk]
    ) -> str:
        """Build prompt for evidence evaluation.

        Args:
            question: Original question
            evidence: Accumulated evidence so far

        Returns:
            Evaluation prompt for evaluator_model
        """
        evidence_text = "\n".join(
            f"- [{i+1}] {chunk.content[:200]}..." for i, chunk in enumerate(evidence)
        )

        return f"""Evaluate whether the following evidence is sufficient to answer the question.

Question: {question}

Evidence:
{evidence_text}

Respond in JSON format:
{{"sufficient": true/false, "reason": "explanation"}}

Consider:
- Does the evidence directly address the question?
- Is there enough detail to provide a complete answer?
- Are there any gaps or contradictions?
"""

    def _build_action_prompt(
        self,
        question: str,
        current_query: str,
        candidates: tuple[EvidenceChunk, ...],
        evaluation: dict[str, Any],
    ) -> str:
        """Build prompt for action planning.

        Args:
            question: Original question
            current_query: Current retrieval query
            candidates: Evidence from current round
            evaluation: Evidence sufficiency evaluation

        Returns:
            Action planning prompt for planner_model
        """
        candidates_text = "\n".join(
            f"- {chunk.content[:150]}..." for chunk in candidates
        )

        return f"""Based on the retrieval results and evaluation, decide the next action.

Original Question: {question}
Current Query: {current_query}

Retrieved Evidence:
{candidates_text}

Evaluation: {json.dumps(evaluation)}

Choose one action:
1. "sufficient" - Evidence is adequate, stop retrieval
2. "abort" - Evidence is inadequate and unlikely to improve, stop retrieval
3. "rewrite" - Try a different query to find better evidence

Respond in JSON format:
{{"action": "sufficient|abort|rewrite", "reason": "explanation", "new_query": "new query if rewrite"}}

Guidelines:
- If evaluation.sufficient is true, choose "sufficient"
- If no evidence was found and query seems reasonable, choose "abort"
- If evidence is partial or off-topic, choose "rewrite" with a more specific query
"""

    def _generate_text(self, model: ModelProtocol, prompt: str) -> str:
        """Call either a simple test model or a governed ModelProvider and return text."""

        provider_name = getattr(model, "provider_name", None)
        model_name = getattr(model, "model_name", None)
        if isinstance(provider_name, str) and isinstance(model_name, str):
            response = model.generate(
                ModelRequest(
                    messages=(ModelMessage(role=ModelRole.USER, content=prompt),),
                    provider=provider_name,
                    model=model_name,
                    response_format="json",
                )
            )
        else:
            response = model.generate(prompt)
        if isinstance(response, str):
            return response
        content = getattr(response, "content", None)
        if isinstance(content, str):
            return content
        return str(response)
