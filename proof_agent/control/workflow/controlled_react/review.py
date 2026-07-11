from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.capabilities.review import HarnessReviewSubagent
from proof_agent.contracts import (
    EnforcementPoint,
    PolicyDecision,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReviewDecision,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.policy.review import fail_closed_policy_decision
from proof_agent.control.workflow.harness_helpers import emit_policy_decision
from proof_agent.observability.audit.trace import TraceEmitter


def review_action(
    *,
    trace: TraceEmitter,
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


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
