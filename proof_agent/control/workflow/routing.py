from __future__ import annotations

from proof_agent.contracts import PolicyDecision, PolicyDecisionType


def route_policy_decision(decision: PolicyDecision) -> str:
    if decision.decision == PolicyDecisionType.ALLOW:
        return "continue"
    if decision.decision == PolicyDecisionType.REQUIRE_APPROVAL:
        return "approval"
    if decision.decision == PolicyDecisionType.ESCALATE:
        return "escalate"
    return "stop"
