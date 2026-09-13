"""Required-query evidence coverage, never answer-semantic verification."""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    ObservationRecord,
    ObservationTruthArtifact,
    ReActActionType,
    ReActActionProposal,
    ReasoningSummary,
    RetrievalObservationTruth,
)
from proof_agent.control.workflow.controlled_react.artifact_binding import (
    require_bound_observation_truth,
)
from proof_agent.errors import ProofAgentError
from proof_agent.control.validators.answer_facts import answer_fact_repair_options
from proof_agent.control.knowledge.performance_analysis import is_performance_comparison, missing_performance_coverage


@dataclass(frozen=True)
class RequiredRetrieval:
    requirement_id: str
    query: str


@dataclass(frozen=True)
class RetrievalRequirementProgress:
    requirement: RequiredRetrieval
    attempted: bool
    supporting_truth_refs: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalTaskCompletion:
    requirements: tuple[RetrievalRequirementProgress, ...]
    missing_answer_requirements: tuple[str, ...] = ()
    supplementary: tuple[RequiredRetrieval, ...] = ()

    @property
    def complete(self) -> bool:
        return bool(self.requirements) and all(
            row.supporting_truth_refs for row in self.requirements
        ) and not self.missing_answer_requirements

    @property
    def pending(self) -> tuple[RequiredRetrieval, ...]:
        required = tuple(row.requirement for row in self.requirements if not row.attempted)
        if required or any(not row.supporting_truth_refs for row in self.requirements):
            return required
        return self.supplementary if self.missing_answer_requirements else ()

    @property
    def unmet_count(self) -> int:
        return sum(not row.supporting_truth_refs for row in self.requirements)


def completion_projection(
    completion: RetrievalTaskCompletion | None, *, reason: str | None = None
) -> dict[str, Any]:
    rows = completion.requirements if completion else ()
    complete = bool(completion and completion.complete)
    aliases = {
        "required_retrieval_complete": "requirements_satisfied",
        "required_retrieval_pending": "requirements_pending",
    }
    reason = (
        aliases.get(reason, reason)
        if reason
        else ("requirements_satisfied" if complete else "requirements_pending")
    )
    if reason not in {
        "requirements_satisfied",
        "requirements_pending",
        "requirements_unsatisfied",
        "plan_budget_exhausted",
        "observation_no_progress",
        "business_flow_admission_failed",
        "policy_denied",
        "tool_scope_denied",
        "review_denied",
        "planner_refused",
        "unresolved_subgoals",
        "clarification_required",
    }:
        reason = "planner_refused"
    return {
        "schema_version": "retrieval-task-completion.v1",
        "status": "not_applicable"
        if completion is None
        else ("complete" if complete else "incomplete"),
        "reason": "not_applicable" if completion is None else reason,
        "required_count": len(rows),
        **({"missing_answer_requirements": list(completion.missing_answer_requirements)}
           if completion and completion.missing_answer_requirements else {}),
        "completed_count": sum(bool(row.supporting_truth_refs) for row in rows),
        "unmet_requirement_ids": [
            row.requirement.requirement_id for row in rows if not row.supporting_truth_refs
        ],
        "proofs": [
            {
                "requirement_id": row.requirement.requirement_id,
                "truth_refs": list(row.supporting_truth_refs),
            }
            for row in rows
            if row.supporting_truth_refs
        ],
    }


def incomplete_refusal(proposal: ReActActionProposal, *, reason: str) -> ReActActionProposal:
    return proposal.model_copy(
        update={
            "action_type": ReActActionType.REFUSE,
            "parameters": {"refusal_reason": reason},
            "target_tool_name": None,
            "reasoning_summary": proposal.reasoning_summary.model_copy(
                update={
                    "selected_action": ReActActionType.REFUSE,
                    "rationale_summary": "The retrieval completion gate does not permit a final answer.",
                }
            ),
        }
    )


def required_retrievals(intent: Mapping[str, Any] | None) -> tuple[RequiredRetrieval, ...]:
    if intent is None:
        return ()
    items = intent.get("retrieval_query_set", ())
    if not isinstance(items, (tuple, list)) or len(items) > 5:
        raise _invalid_requirement()
    required: dict[str, RequiredRetrieval] = {}
    for item in items:
        if not isinstance(item, Mapping) or type(item.get("required")) is not bool:
            raise _invalid_requirement()
        query = item.get("query")
        if not isinstance(query, str) or not query.strip():
            raise _invalid_requirement()
        if item["required"]:
            query = query.strip()
            required.setdefault(
                query, RequiredRetrieval("rq_" + sha256(query.encode()).hexdigest(), query)
            )
    return tuple(required.values())


def assess_retrieval_completion(
    *,
    run_id: str,
    requirements: tuple[RequiredRetrieval, ...],
    records: tuple[ObservationRecord, ...],
    truths: tuple[ObservationTruthArtifact, ...],
    question: str = "",
    optional_queries: tuple[str, ...] = (),
) -> RetrievalTaskCompletion:
    attempted: set[str] = set()
    support: dict[str, list[str]] = {}
    evidence: list[EvidenceChunk] = []
    for record, truth in zip(records, truths, strict=True):
        binding = require_bound_observation_truth(truth)
        if (
            binding.run_id != run_id
            or record.truth_ref != binding.reference
            or record.observation_id != truth.observation_id
            or record.action_id != truth.action_id
        ):
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "Retrieval completion evidence identity is invalid.",
                "Restart the run with its own immutable observation artifacts.",
            )
        if (
            not isinstance(truth, RetrievalObservationTruth)
            or record.action_type is not ReActActionType.PLAN_RETRIEVAL
        ):
            continue
        query = truth.admission_metadata.get("query")
        if not isinstance(query, str) or not query.strip():
            continue
        query = query.strip()
        attempted.add(query)
        evidence.extend(chunk for chunk in truth.accepted_evidence
            if chunk.status is EvidenceStatus.ACCEPTED and chunk.source in record.source_refs
            and chunk.citation in record.citation_refs and chunk.citation in truth.citation_refs)
        if any(
            chunk.status is EvidenceStatus.ACCEPTED
            and chunk.source.strip()
            and chunk.source in record.source_refs
            and chunk.citation
            and chunk.citation.strip()
            and chunk.citation in truth.citation_refs
            and chunk.citation in record.citation_refs
            for chunk in truth.accepted_evidence
        ):
            support.setdefault(query, []).append(binding.reference)
    missing = missing_performance_coverage(question, "\n".join(
        option["statement"] for option in answer_fact_repair_options(tuple(evidence)))) if is_performance_comparison(question) else ()
    if is_performance_comparison(question):
        from proof_agent.control.knowledge.business_assessment import assessment_gaps
        missing = tuple(dict.fromkeys((*missing, *assessment_gaps(tuple(evidence)))))
    # A finite query family, independent of model proposals and observed wording.
    # Every query still goes through the ordinary policy, binding and run budgets.
    supplement_queries = (*optional_queries[:3],
        question[:150] + " 实际报告期 各业务营运利润 新业务价值率 净息差 下降 亏损 减值")
    supplementary = tuple(RequiredRetrieval("rq_" + sha256(q.encode()).hexdigest(), q)
        for q in dict.fromkeys(supplement_queries) if q and q not in attempted) if missing else ()
    return RetrievalTaskCompletion(
        tuple(
            RetrievalRequirementProgress(
                requirement,
                requirement.query in attempted,
                tuple(dict.fromkeys(support.get(requirement.query, []))),
            )
            for requirement in requirements
        ),
        missing_answer_requirements=missing,
        supplementary=supplementary,
    )


def _invalid_requirement() -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        "Required retrieval specification is invalid.",
        "Use the validated bounded Intent Resolution query set.",
    )


def pending_retrieval_action(
    proposal: ReActActionProposal, requirement: RequiredRetrieval, *, plan_round: int
) -> ReActActionProposal:
    return ReActActionProposal(
        action_id=f"act_required_{plan_round + 1}_{requirement.requirement_id[3:19]}",
        action_type=ReActActionType.PLAN_RETRIEVAL,
        parameters={"query": requirement.query},
        risk_level=proposal.risk_level,
        reasoning_summary=ReasoningSummary(
            goal="Complete the required retrieval evidence.",
            observations=("A required query has no verified evidence.",),
            candidate_actions=(ReActActionType.PLAN_RETRIEVAL, ReActActionType.REFUSE),
            selected_action=ReActActionType.PLAN_RETRIEVAL,
            rationale_summary="Retrieve the pending requirement before finalizing.",
            risk_flags=proposal.reasoning_summary.risk_flags,
            required_evidence=(requirement.requirement_id,),
        ),
    )
