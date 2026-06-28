from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.capabilities.review import HarnessReviewSubagent
from proof_agent.contracts import (
    EnforcementPoint,
    IntentResolution,
    PolicyDecision,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReviewDecision,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.policy.review import fail_closed_policy_decision
from proof_agent.control.workflow.harness_helpers import emit_policy_decision
from proof_agent.observability.audit.trace import TraceWriter


def emit_reasoning_summary(trace: TraceWriter, proposal: ReActActionProposal) -> None:
    """Emit an audit-safe reasoning summary without raw chain-of-thought."""

    summary = proposal.reasoning_summary
    trace.emit(
        "reasoning_summary",
        status="ok",
        payload={
            "action_id": proposal.action_id,
            "goal": summary.goal,
            "observations": list(summary.observations),
            "candidate_actions": [action.value for action in summary.candidate_actions],
            "selected_action": summary.selected_action.value,
            "rationale_summary": summary.rationale_summary,
            "risk_flags": list(summary.risk_flags),
            "required_evidence": list(summary.required_evidence),
        },
    )


def emit_intent_resolution(
    trace: TraceWriter,
    resolution: IntentResolution,
    *,
    max_queries: int = 3,
    stage_id: str = "intent_resolution",
) -> None:
    """Emit an audit-safe intent summary without raw chain-of-thought."""

    query_set = _retrieval_query_set_payload(resolution)
    trace.emit(
        "intent_resolution",
        status="ok",
        payload={
            "resolution_id": resolution.resolution_id,
            "user_goal": resolution.user_goal,
            "domain_intent": resolution.domain_intent,
            "known_facts": list(resolution.known_facts),
            "missing_fields": list(resolution.missing_fields),
            "ambiguities": list(resolution.ambiguities),
            "risk_flags": list(resolution.risk_flags),
            "confidence": resolution.confidence,
            "recommended_next_action": resolution.recommended_next_action.value,
            "retrieval_query_set": query_set,
            "stage_id": stage_id,
        },
    )
    trace.emit(
        "retrieval_query_set",
        status="ok",
        payload={
            "intent_resolution_id": resolution.resolution_id,
            "query_count": len(query_set),
            "max_queries": max_queries,
            "queries": query_set,
            "recommended_next_action": resolution.recommended_next_action.value,
            "validation_status": "passed",
            "stage_id": stage_id,
        },
    )


def emit_action_proposal(trace: TraceWriter, proposal: ReActActionProposal) -> None:
    """Emit the proposed governed action using JSON-serializable fields."""

    trace.emit(
        "action_proposal",
        status="ok",
        payload={
            "action_id": proposal.action_id,
            "action_type": proposal.action_type.value,
            "parameters": _jsonable(dict(proposal.parameters)),
            "target_tool_name": proposal.target_tool_name,
            "risk_level": proposal.risk_level,
        },
    )


def _retrieval_query_set_payload(resolution: IntentResolution) -> list[dict[str, Any]]:
    return [
        {
            "query": item.query,
            "intent_angle": item.intent_angle,
            "required": item.required,
            "reason": item.reason,
        }
        for item in resolution.retrieval_query_set
    ]


def review_action(
    *,
    trace: TraceWriter,
    policy: PolicyEngine,
    enforcement_point: EnforcementPoint,
    context: Mapping[str, Any],
    proposal: ReActActionProposal,
    auto_review_enabled: bool,
    review_subagent: HarnessReviewSubagent | None,
    low_risk_fast_path_enabled: bool = True,
    trace_event_id: str = "",
) -> tuple[PolicyDecision, dict[str, Any]]:
    """Review a ReAct action, fail closed on reviewer errors, then emit policy."""

    point = EnforcementPoint(enforcement_point)
    fast_path_reason = _low_risk_fast_path_reason(
        point=point,
        context=context,
        proposal=proposal,
        enabled=low_risk_fast_path_enabled,
        auto_review_enabled=auto_review_enabled,
        review_subagent=review_subagent,
    )
    trace.emit(
        "review_requested",
        status="ok" if auto_review_enabled and review_subagent is not None else "blocked",
        payload={
            "action_id": proposal.action_id,
            "action_type": proposal.action_type.value,
            "enforcement_point": point.value,
            "auto_review_enabled": auto_review_enabled,
            "reviewer_available": review_subagent is not None,
            "low_risk_fast_path_enabled": low_risk_fast_path_enabled,
            "fast_path_candidate": fast_path_reason is not None,
        },
    )

    review_decision: ReviewDecision | None = None
    if fast_path_reason is not None:
        deterministic_decision = policy.evaluate(
            point,
            context,
            trace_event_id=trace_event_id,
        )
        if deterministic_decision.decision is PolicyDecisionType.ALLOW:
            review_event = {
                "used_review": False,
                "final_decision": deterministic_decision.decision.value,
                "overridden": False,
                "review_enforcement_point": point.value,
                "subject_action_id": proposal.action_id,
                "fast_path_reason": fast_path_reason,
            }
            trace.emit("review_decision", status="ok", payload=_jsonable(review_event))
            emit_policy_decision(trace, deterministic_decision)
            return deterministic_decision, review_event

    if auto_review_enabled and review_subagent is not None:
        try:
            review_decision = review_subagent.review(
                enforcement_point=point,
                action=proposal,
                context=context,
            )
        except ModelOutputNormalizationError as exc:
            final_decision = fail_closed_policy_decision(
                point,
                context,
                trace_event_id=trace_event_id,
                error_code=exc.error_code,
            )
            review_event = {
                "used_review": False,
                "final_decision": final_decision.decision.value,
                "overridden": False,
                "error_code": exc.error_code,
                "error_class": exc.__class__.__name__,
                "subject_action_id": proposal.action_id,
            }
            trace.emit(
                "model_output_normalization_failed",
                status="blocked",
                payload={
                    "role": exc.role,
                    "error_code": exc.error_code,
                    "raw_content_length": exc.raw_content_length,
                    "subject_action_id": proposal.action_id,
                    "enforcement_point": point.value,
                },
            )
            trace.emit("review_error", status="error", payload=review_event)
            emit_policy_decision(trace, final_decision)
            return final_decision, review_event
        except Exception as exc:
            final_decision = fail_closed_policy_decision(
                point,
                context,
                trace_event_id=trace_event_id,
                error_code="review_subagent_error",
            )
            review_event = {
                "used_review": False,
                "final_decision": final_decision.decision.value,
                "overridden": False,
                "error_code": "review_subagent_error",
                "error_class": exc.__class__.__name__,
                "subject_action_id": proposal.action_id,
            }
            trace.emit("review_error", status="error", payload=review_event)
            emit_policy_decision(trace, final_decision)
            return final_decision, review_event

    final_decision, review_event = policy.evaluate_with_review(
        point,
        context,
        review_decision=review_decision,
        trace_event_id=trace_event_id,
    )
    trace.emit(
        "review_decision",
        status="ok" if final_decision.decision is PolicyDecisionType.ALLOW else "blocked",
        payload=_jsonable(review_event),
    )
    if review_event.get("overridden"):
        trace.emit("review_overridden", status="blocked", payload=_jsonable(review_event))
    emit_policy_decision(trace, final_decision)
    return final_decision, review_event


def _low_risk_fast_path_reason(
    *,
    point: EnforcementPoint,
    context: Mapping[str, Any],
    proposal: ReActActionProposal,
    enabled: bool,
    auto_review_enabled: bool,
    review_subagent: HarnessReviewSubagent | None,
) -> str | None:
    if not enabled or not auto_review_enabled or review_subagent is None:
        return None
    if proposal.risk_level != "low":
        return None
    if (
        point is EnforcementPoint.BEFORE_RETRIEVAL_PLAN
        and proposal.action_type is ReActActionType.PLAN_RETRIEVAL
    ):
        return "low_risk_policy_allow"
    if (
        point is EnforcementPoint.BEFORE_RETRIEVAL_STEP
        and proposal.action_type is ReActActionType.RUN_RETRIEVAL_STEP
    ):
        return "low_risk_policy_allow"
    if (
        point is EnforcementPoint.BEFORE_MODEL_CALL
        and proposal.action_type is ReActActionType.GENERATE_FINAL_ANSWER
        and _positive_int(context.get("accepted_evidence_count")) > 0
        and bool(context.get("citations_present"))
    ):
        return "low_risk_policy_allow"
    return None


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def clarification_message(proposal: ReActActionProposal) -> str:
    missing_fields = proposal.parameters.get("missing_fields")
    if missing_fields:
        fields = ", ".join(str(field) for field in missing_fields)
        return f"Please provide the missing details before I can continue: {fields}."
    return "Please provide the missing details before I can continue."


def should_stop_for_step_budget(step_count: int, max_steps: int) -> bool:
    return step_count >= max_steps


def should_stop_for_plan_budget(plan_rounds: int, max_plan_rounds: int) -> bool:
    """Return True when the Controlled ReAct Loop must stop for the plan budget.

    Counts Plan Rounds (``plan`` invocations); ``max_plan_rounds`` is the
    dual-axis budget that guards thinking divergence (ADR-0032).
    """

    return plan_rounds >= max_plan_rounds


# Actions the plan stage may legitimately choose from when unrestricted. The
# synthetic actions (RUN_RETRIEVAL_STEP, STOP, ESCALATE) are produced by stage
# behavior or routing, never emitted by the planner, so they are excluded.
_PLAN_ELIGIBLE_ACTIONS: frozenset[ReActActionType] = frozenset(
    {
        ReActActionType.PLAN_RETRIEVAL,
        ReActActionType.PROPOSE_TOOL_CALL,
        ReActActionType.GENERATE_FINAL_ANSWER,
        ReActActionType.ASK_CLARIFICATION,
        ReActActionType.REFUSE,
    }
)

# Converged eligible set: once saturation or repetition fires, plan may only
# answer with what it has or refuse. Observation actions are removed so the
# loop cannot keep gathering without progress.
_TERMINAL_NARROWED_ACTIONS: frozenset[ReActActionType] = frozenset(
    {ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE}
)

_ANSWER_READY_ACTIONS: frozenset[ReActActionType] = frozenset(
    {ReActActionType.GENERATE_FINAL_ANSWER}
)

_ANSWER_READY_CLARIFICATION_BLOCKER_ACTIONS: frozenset[ReActActionType] = frozenset(
    {ReActActionType.ASK_CLARIFICATION, ReActActionType.REFUSE}
)

_ANSWER_READY_CLARIFICATION_BLOCKER_CODES: frozenset[str] = frozenset(
    {"unresolved_subgoal", "variant_conflict"}
)

_ANSWER_READY_HARD_BLOCKER_CODES: frozenset[str] = frozenset(
    {
        "no_accepted_evidence",
        "policy_denied",
        "evidence_relevance_failed",
        "citation_binding_impossible",
    }
)

# Eligible set when the plan budget is exhausted: the loop must end, and the
# only honest terminal action is refuse (no evidence synthesis is possible).
_REFUSE_ONLY_ACTIONS: frozenset[ReActActionType] = frozenset({ReActActionType.REFUSE})

_EVIDENCE_SATURATION_WINDOW = 2
_ACTION_REPETITION_WINDOW = 2


def compute_eligible_action_set(
    *,
    plan_rounds: int,
    max_plan_rounds: int,
    action_history: list[Mapping[str, Any]],
    evidence_trajectory: list[int],
    observations: list[Mapping[str, Any]] | None = None,
    answer_ready_blockers: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[frozenset[ReActActionType], str | None]:
    """Deterministically narrow the plan eligible action set (ADR-0032).

    Pure function over control state, no LLM call. Returns the eligible action
    set for the upcoming plan round and the convergence signal that fired
    (``None`` when unrestricted). Signal precedence is, strictest first:
    plan-budget exhaustion, action repetition, evidence saturation.
    """

    if should_stop_for_plan_budget(plan_rounds, max_plan_rounds):
        return _REFUSE_ONLY_ACTIONS, "plan_budget_exhausted"

    if _detect_answer_ready(observations or []):
        if answer_ready_blockers:
            return _answer_ready_blocked_actions(answer_ready_blockers), "answer_ready_blocked"
        return _ANSWER_READY_ACTIONS, "answer_ready"

    if _detect_action_repetition(action_history):
        return _TERMINAL_NARROWED_ACTIONS, "action_repetition"

    if _detect_evidence_saturation(evidence_trajectory):
        return _TERMINAL_NARROWED_ACTIONS, "evidence_saturation"

    return _PLAN_ELIGIBLE_ACTIONS, None


def _answer_ready_blocked_actions(
    blockers: Sequence[Mapping[str, Any]],
) -> frozenset[ReActActionType]:
    codes = {
        str(blocker.get("code") or "").strip()
        for blocker in blockers
        if isinstance(blocker, Mapping)
    }
    if codes and codes <= _ANSWER_READY_CLARIFICATION_BLOCKER_CODES:
        return _ANSWER_READY_CLARIFICATION_BLOCKER_ACTIONS
    if codes & _ANSWER_READY_HARD_BLOCKER_CODES:
        return _REFUSE_ONLY_ACTIONS
    return _REFUSE_ONLY_ACTIONS


def should_block_duplicate_observation_action(
    proposal: ReActActionProposal,
    *,
    action_history: list[Mapping[str, Any]],
    observations: list[Mapping[str, Any]],
) -> bool:
    if proposal.action_type not in {
        ReActActionType.PLAN_RETRIEVAL,
        ReActActionType.PROPOSE_TOOL_CALL,
    }:
        return False
    current = _action_fingerprint(
        {"action_type": proposal.action_type.value, "parameters": dict(proposal.parameters)}
    )
    if not any(_action_fingerprint(entry) == current for entry in action_history):
        return False
    return not _latest_observation_has_unresolved_subgoals(observations)


def build_retrieval_observation_record(
    *,
    action_id: str,
    action_type: ReActActionType,
    plan_round: int,
    accepted_before: int,
    accepted_after: int,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    new_count = max(accepted_after - accepted_before, 0)
    citations = [
        str(item["citation"])
        for item in evidence
        if isinstance(item.get("citation"), str) and item["citation"].strip()
    ]
    sources = [
        str(item["source"])
        for item in evidence
        if isinstance(item.get("source"), str) and item["source"].strip()
    ]
    return {
        "observation_id": f"obs_{plan_round}_{action_id}",
        "action_id": action_id,
        "action_type": action_type.value,
        "round": plan_round,
        "truth_ref": "evidence",
        "summary": {
            "accepted_evidence_count": accepted_after,
            "new_evidence_count": new_count,
            "citation_count": len(citations),
        },
        "accepted_evidence_count": accepted_after,
        "new_evidence_count": new_count,
        "unresolved_subgoals": [],
        "source_refs": sources,
        "citation_refs": citations,
    }


def _detect_answer_ready(observations: list[Mapping[str, Any]]) -> bool:
    if not observations:
        return False
    latest = observations[-1]
    if int(latest.get("accepted_evidence_count") or 0) <= 0:
        return False
    return not _latest_observation_has_unresolved_subgoals(observations)


def _latest_observation_has_unresolved_subgoals(
    observations: list[Mapping[str, Any]],
) -> bool:
    if not observations:
        return False
    unresolved = observations[-1].get("unresolved_subgoals") or []
    return len(list(unresolved)) > 0


def _detect_evidence_saturation(evidence_trajectory: list[int]) -> bool:
    """True when accepted evidence did not grow across the saturation window."""

    if len(evidence_trajectory) <= _EVIDENCE_SATURATION_WINDOW:
        return False
    window = evidence_trajectory[-(_EVIDENCE_SATURATION_WINDOW + 1) :]
    baseline = window[0]
    return all(count <= baseline for count in window[1:])


def _detect_action_repetition(action_history: list[Mapping[str, Any]]) -> bool:
    """True when the most recent two rounds chose the same action and parameters."""

    if len(action_history) < _ACTION_REPETITION_WINDOW:
        return False
    recent = action_history[-_ACTION_REPETITION_WINDOW:]
    return _action_fingerprint(recent[0]) == _action_fingerprint(recent[1])


def _action_fingerprint(entry: Mapping[str, Any]) -> tuple[Any, Any]:
    parameters = entry.get("parameters", {})
    normalized = tuple(sorted(parameters.items(), key=lambda item: str(item[0])))
    return entry.get("action_type"), normalized


# Convergence signals that indicate the loop cannot make further progress and
# must end. Under these signals the Action Constraint default is REFUSE.
_DIVERGENCE_SIGNALS: frozenset[str] = frozenset({"plan_budget_exhausted"})


@dataclass(frozen=True)
class ActionRewrite:
    """Trace-safe record of an Action Constraint rewrite (ADR-0032 Layer 2)."""

    original_action_type: ReActActionType
    constrained_to: ReActActionType
    reason: str
    eligible_set: tuple[ReActActionType, ...]


def constrain_action(
    proposal: ReActActionProposal,
    eligible_set: frozenset[ReActActionType],
    *,
    convergence_signal: str | None,
) -> tuple[ReActActionProposal, ActionRewrite | None]:
    """Return the proposal unchanged when in-set, otherwise rewrite it (ADR-0032).

    Layer 2 eligibility enforcement: a provider-neutral, deterministic rewrite.
    The default for an out-of-set action follows the convergence context and
    must itself be in the eligible set. Divergence signals prefer REFUSE;
    ordinary convergence prefers GENERATE_FINAL_ANSWER when available.
    """

    if proposal.action_type in eligible_set:
        return proposal, None

    if convergence_signal in _DIVERGENCE_SIGNALS and ReActActionType.REFUSE in eligible_set:
        default = ReActActionType.REFUSE
    elif ReActActionType.GENERATE_FINAL_ANSWER in eligible_set:
        default = ReActActionType.GENERATE_FINAL_ANSWER
    elif ReActActionType.REFUSE in eligible_set:
        default = ReActActionType.REFUSE
    elif ReActActionType.ASK_CLARIFICATION in eligible_set:
        default = ReActActionType.ASK_CLARIFICATION
    else:
        default = sorted(eligible_set, key=lambda action: action.value)[0]
    constrained = proposal.model_copy(update={"action_type": default})
    rewrite = ActionRewrite(
        original_action_type=proposal.action_type,
        constrained_to=default,
        reason="outside_eligible_set",
        eligible_set=tuple(sorted(eligible_set, key=lambda action: action.value)),
    )
    return constrained, rewrite


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
