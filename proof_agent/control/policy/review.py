from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.contracts import (
    EnforcementPoint,
    PolicyDecision,
    PolicyDecisionType,
    ReviewDecision,
)

ALLOWED_REVIEW_DECISIONS: dict[EnforcementPoint, frozenset[PolicyDecisionType]] = {
    EnforcementPoint.BEFORE_RETRIEVAL_PLAN: frozenset(
        {
            PolicyDecisionType.ALLOW,
            PolicyDecisionType.DENY,
            PolicyDecisionType.ESCALATE,
        }
    ),
    EnforcementPoint.BEFORE_RETRIEVAL_STEP: frozenset(
        {
            PolicyDecisionType.ALLOW,
            PolicyDecisionType.DENY,
            PolicyDecisionType.ESCALATE,
        }
    ),
    EnforcementPoint.BEFORE_TOOL_CALL: frozenset(
        {
            PolicyDecisionType.ALLOW,
            PolicyDecisionType.DENY,
            PolicyDecisionType.REQUIRE_APPROVAL,
            PolicyDecisionType.ESCALATE,
        }
    ),
    EnforcementPoint.BEFORE_MODEL_CALL: frozenset(
        {
            PolicyDecisionType.ALLOW,
            PolicyDecisionType.DENY,
            PolicyDecisionType.ESCALATE,
        }
    ),
}

_STRICTNESS: dict[PolicyDecisionType, int] = {
    PolicyDecisionType.ALLOW: 0,
    PolicyDecisionType.REQUIRE_APPROVAL: 1,
    PolicyDecisionType.ESCALATE: 2,
    PolicyDecisionType.DENY: 3,
}


def is_review_decision_allowed(
    enforcement_point: EnforcementPoint,
    decision: PolicyDecisionType,
) -> bool:
    return decision in ALLOWED_REVIEW_DECISIONS.get(enforcement_point, frozenset())


def is_stricter_than(
    candidate: PolicyDecisionType,
    baseline: PolicyDecisionType,
) -> bool:
    return _STRICTNESS[candidate] > _STRICTNESS[baseline]


def fail_closed_decision_type(
    enforcement_point: EnforcementPoint,
    context: Mapping[str, Any],
) -> PolicyDecisionType:
    if enforcement_point == EnforcementPoint.BEFORE_TOOL_CALL:
        return PolicyDecisionType.REQUIRE_APPROVAL
    if enforcement_point == EnforcementPoint.BEFORE_MODEL_CALL:
        return PolicyDecisionType.DENY
    if enforcement_point in {
        EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        EnforcementPoint.BEFORE_RETRIEVAL_STEP,
    }:
        fallback = context.get("review_fallback_decision")
        if fallback is not None:
            try:
                fallback_decision = PolicyDecisionType(fallback)
            except ValueError:
                return PolicyDecisionType.DENY
            if is_review_decision_allowed(enforcement_point, fallback_decision):
                return fallback_decision
        return PolicyDecisionType.DENY
    return PolicyDecisionType.DENY


def fail_closed_policy_decision(
    enforcement_point: EnforcementPoint,
    context: Mapping[str, Any],
    *,
    trace_event_id: str,
    error_code: str,
) -> PolicyDecision:
    decision = fail_closed_decision_type(enforcement_point, context)
    return PolicyDecision(
        decision=decision,
        enforcement_point=enforcement_point,
        reason=f"Review output was invalid; failed closed with {decision.value}.",
        policy_rule_id=f"auto_review.{enforcement_point.value}.fail_closed",
        metadata=dict(context),
        trace_event_id=trace_event_id,
    )


def review_event_metadata(
    *,
    review_decision: ReviewDecision | None,
    final_decision: PolicyDecision,
    used_review: bool,
    overridden: bool = False,
    error_code: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "used_review": used_review,
        "final_decision": final_decision.decision.value,
        "overridden": overridden,
    }
    if review_decision is not None:
        event.update(
            {
                "review_id": review_decision.review_id,
                "review_enforcement_point": review_decision.enforcement_point.value,
                "suggested_decision": review_decision.suggested_decision.value,
                "subject_action_id": review_decision.subject_action_id,
                "review_confidence": review_decision.confidence,
            }
        )
    if error_code is not None:
        event["error_code"] = error_code
    return event
