"""Bounded Agentic orchestration that cannot expand retrieval authority."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

from knowledge_source_service.contracts.results import KnowledgeQueryResult
from knowledge_source_service.domain.identities import sha256_json
from knowledge_source_service.ports.agentic import (
    AgenticRetrievalController,
    AgenticRetrievalDecision,
    AgenticRetrievalObservation,
)
from knowledge_source_service.ports.retrieval import (
    AdmittedKnowledgeQuery,
    KnowledgeRetrievalEngine,
)


class AgenticRetrievalBudgetViolation(RuntimeError):
    """A controller reported usage outside the remaining hard budget."""


class AgenticControllerUnavailable(RuntimeError):
    """Agentic was explicitly requested without an admitted controller."""


class UnavailableAgenticRetrievalController:
    """Fail closed while leaving single-pass execution available."""

    def decide(
        self,
        observation: AgenticRetrievalObservation,
    ) -> AgenticRetrievalDecision:
        del observation
        raise AgenticControllerUnavailable(
            "Agentic retrieval controller is not configured"
        )


class BoundedAgenticKnowledgeRetrievalEngine:
    """Run query reformulation only inside one frozen admitted Query scope."""

    def __init__(
        self,
        *,
        single_pass_engine: KnowledgeRetrievalEngine,
        controller: AgenticRetrievalController,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._single_pass_engine = single_pass_engine
        self._controller = controller
        self._monotonic_clock = monotonic_clock

    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        if query.request.strategy == "single_pass":
            return self._single_pass_engine.retrieve(query)

        budget = query.request.execution_budget
        started = self._monotonic_clock()
        current_question = query.request.question
        model_calls = 0
        model_tokens = 0
        round_payloads: list[dict[str, Any]] = []
        stop_reason = "budget_exhausted"

        for retrieval_round in range(1, budget.max_rounds + 1):
            if _elapsed_ms(self._monotonic_clock(), started) >= budget.max_duration_ms:
                break
            round_request = query.request.model_copy(
                update={
                    "question": current_question,
                    "strategy": "single_pass",
                }
            )
            round_result = self._single_pass_engine.retrieve(
                AdmittedKnowledgeQuery(
                    request=round_request,
                    admission=query.admission,
                )
            )
            round_payload = _label_round(round_result, retrieval_round)
            round_payloads.append(round_payload)
            merged_groups = _merge_groups(
                round_payloads,
                max_candidates=budget.max_candidates,
            )
            candidate_ids = _candidate_ids(merged_groups)

            if model_calls >= budget.max_model_calls:
                break
            elapsed_ms = _elapsed_ms(self._monotonic_clock(), started)
            if elapsed_ms >= budget.max_duration_ms:
                break
            remaining_tokens = budget.max_model_tokens - model_tokens
            observation = AgenticRetrievalObservation(
                retrieval_round=retrieval_round,
                question=current_question,
                knowledge_base_release_id=query.request.knowledge_base_release_id,
                access_scope_digest=query.admission.effective_access_scope_digest,
                candidate_count=len(candidate_ids),
                candidate_evidence_ids=candidate_ids,
                remaining_rounds=budget.max_rounds - retrieval_round,
                remaining_model_calls=budget.max_model_calls - model_calls,
                remaining_model_tokens=remaining_tokens,
                remaining_duration_ms=budget.max_duration_ms - elapsed_ms,
            )
            decision = self._controller.decide(observation)
            model_calls += 1
            if decision.model_tokens_used > remaining_tokens:
                raise AgenticRetrievalBudgetViolation(
                    "agentic controller exceeded the remaining model token budget"
                )
            model_tokens += decision.model_tokens_used

            if _elapsed_ms(self._monotonic_clock(), started) >= budget.max_duration_ms:
                break

            if decision.action == "complete":
                stop_reason = "coverage_complete"
                break
            if decision.action == "abort":
                stop_reason = "no_candidates" if not candidate_ids else "coverage_complete"
                break
            if retrieval_round == budget.max_rounds:
                break
            assert decision.revised_question is not None
            current_question = decision.revised_question.strip()

        if not round_payloads:
            raise AgenticRetrievalBudgetViolation(
                "agentic retrieval duration budget elapsed before the first round"
            )
        return _compose_result(
            round_payloads=round_payloads,
            max_candidates=budget.max_candidates,
            stop_reason=stop_reason,
            model_calls=model_calls,
            model_tokens=model_tokens,
            duration_ms=min(
                _elapsed_ms(self._monotonic_clock(), started),
                budget.max_duration_ms,
            ),
        )


def _label_round(result: KnowledgeQueryResult, retrieval_round: int) -> dict[str, Any]:
    payload = result.model_dump(mode="json")
    payload["query_plan_summary"]["plan_revision"] = retrieval_round
    for group in payload["evidence_groups"]:
        for candidate in group["candidate_evidence"]:
            candidate["retrieval_lineage"]["retrieval_round"] = retrieval_round
            candidate["retrieval_lineage"]["plan_revision"] = retrieval_round
    return payload


def _merge_groups(
    round_payloads: list[dict[str, Any]],
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    group_order = ("relevance_ranked", "structured")
    merged: list[dict[str, Any]] = []
    remaining = max_candidates
    for group_type in group_order:
        templates = [
            group
            for payload in round_payloads
            for group in payload["evidence_groups"]
            if group["group_type"] == group_type
        ]
        if not templates:
            continue
        candidates_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
        for group in templates:
            for candidate in group["candidate_evidence"]:
                identity = (
                    candidate["knowledge_source_version_id"],
                    candidate["evidence_unit_id"],
                )
                candidates_by_identity[identity] = candidate
        candidates = list(candidates_by_identity.values())[:remaining]
        remaining -= len(candidates)
        for rank, candidate in enumerate(candidates, start=1):
            if group_type == "relevance_ranked":
                candidate["ranking"]["fused_rank"] = rank
            else:
                candidate["ranking"]["structured_order"] = rank
        template = dict(templates[-1])
        template["candidate_evidence"] = candidates
        merged.append(template)
    return merged


def _candidate_ids(groups: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        candidate["candidate_evidence_id"]
        for group in groups
        for candidate in group["candidate_evidence"]
    )


def _compose_result(
    *,
    round_payloads: list[dict[str, Any]],
    max_candidates: int,
    stop_reason: str,
    model_calls: int,
    model_tokens: int,
    duration_ms: int,
) -> KnowledgeQueryResult:
    groups = _merge_groups(round_payloads, max_candidates=max_candidates)
    plan_digests = tuple(
        payload["query_plan_summary"]["plan_digest"] for payload in round_payloads
    )
    lanes = tuple(
        lane
        for lane in ("lexical", "sparse", "dense", "structured")
        if any(
            lane in payload["query_plan_summary"]["planned_lanes"]
            for payload in round_payloads
        )
    )
    candidate_count = sum(len(group["candidate_evidence"]) for group in groups)
    latest = round_payloads[-1]
    return KnowledgeQueryResult.model_validate(
        {
            "schema_version": "knowledge-query-result.v1",
            "evidence_groups": groups,
            "query_plan_summary": {
                "plan_revision": len(round_payloads),
                "planned_lanes": lanes,
                "structured_query_count": sum(
                    payload["query_plan_summary"]["structured_query_count"]
                    for payload in round_payloads
                ),
                "plan_digest": sha256_json(
                    {
                        "schema": "agentic-knowledge-query-plan.v1",
                        "plan_revision_digests": plan_digests,
                    }
                ),
            },
            "execution_summary": {
                "strategy": "agentic",
                "rounds": len(round_payloads),
                "stop_reason": stop_reason,
                "degraded": any(
                    payload["execution_summary"]["degraded"]
                    for payload in round_payloads
                ),
                "budget_usage": {
                    "rounds": len(round_payloads),
                    "model_calls": model_calls,
                    "candidates": candidate_count,
                    "model_tokens": model_tokens,
                    "duration_ms": duration_ms,
                },
            },
            "retrieval_lineage": {
                **latest["retrieval_lineage"],
                "plan_revision_digests": plan_digests,
            },
        }
    )


def _elapsed_ms(now: float, started: float) -> int:
    return max(0, int((now - started) * 1000))
