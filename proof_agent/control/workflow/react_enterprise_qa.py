from __future__ import annotations

from collections.abc import Mapping
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


def emit_intent_resolution(trace: TraceWriter, resolution: IntentResolution) -> None:
    """Emit an audit-safe intent summary without raw chain-of-thought."""

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


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
