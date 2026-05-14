from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from proof_agent.contracts import (
    EnforcementPoint,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReviewDecision,
    ReviewSubagentConfig,
)
from proof_agent.errors import ProofAgentError


class HarnessReviewSubagent(Protocol):
    """Review adapter used by the Harness before policy finalization."""

    def review(
        self,
        *,
        enforcement_point: EnforcementPoint,
        action: ReActActionProposal,
        context: Mapping[str, Any],
    ) -> ReviewDecision:
        """Return an advisory review decision for one proposed ReAct action."""


class DeterministicHarnessReviewSubagent:
    """Offline review implementation for deterministic tests and demos."""

    def review(
        self,
        *,
        enforcement_point: EnforcementPoint,
        action: ReActActionProposal,
        context: Mapping[str, Any],
    ) -> ReviewDecision:
        point = EnforcementPoint(enforcement_point)
        decision = self._suggest_decision(point, action, context)
        return ReviewDecision(
            review_id=f"review.{action.action_id}.{point.value}",
            enforcement_point=point,
            suggested_decision=decision,
            reason=self._reason(point, action, decision),
            confidence=self._confidence(decision),
            risk_flags=tuple(action.reasoning_summary.risk_flags),
            subject_action_id=action.action_id,
            metadata={
                "provider": "deterministic",
                "action_type": action.action_type.value,
                "risk_level": action.risk_level,
                "target_tool_name": action.target_tool_name,
            },
        )

    def _suggest_decision(
        self,
        point: EnforcementPoint,
        action: ReActActionProposal,
        context: Mapping[str, Any],
    ) -> PolicyDecisionType:
        if (
            point == EnforcementPoint.BEFORE_RETRIEVAL_PLAN
            and action.action_type == ReActActionType.PLAN_RETRIEVAL
        ):
            return PolicyDecisionType.ALLOW
        if (
            point == EnforcementPoint.BEFORE_RETRIEVAL_STEP
            and action.action_type == ReActActionType.RUN_RETRIEVAL_STEP
        ):
            return PolicyDecisionType.ALLOW
        if (
            point == EnforcementPoint.BEFORE_TOOL_CALL
            and action.action_type == ReActActionType.PROPOSE_TOOL_CALL
            and action.risk_level == "medium"
        ):
            return PolicyDecisionType.REQUIRE_APPROVAL
        if (
            point == EnforcementPoint.BEFORE_MODEL_CALL
            and action.action_type == ReActActionType.GENERATE_FINAL_ANSWER
            and int(context.get("accepted_evidence_count", 0)) > 0
        ):
            return PolicyDecisionType.ALLOW
        return PolicyDecisionType.DENY

    def _reason(
        self,
        point: EnforcementPoint,
        action: ReActActionProposal,
        decision: PolicyDecisionType,
    ) -> str:
        if decision == PolicyDecisionType.ALLOW:
            return f"Deterministic review allows {action.action_type.value} at {point.value}."
        if decision == PolicyDecisionType.REQUIRE_APPROVAL:
            return (
                "Deterministic review requires approval for medium-risk tool access."
            )
        return f"Deterministic review denies unsupported action at {point.value}."

    def _confidence(self, decision: PolicyDecisionType) -> float:
        if decision == PolicyDecisionType.ALLOW:
            return 0.9
        if decision == PolicyDecisionType.REQUIRE_APPROVAL:
            return 0.95
        return 0.85


def resolve_review_subagent(config: ReviewSubagentConfig) -> HarnessReviewSubagent:
    if config.provider == "deterministic":
        return DeterministicHarnessReviewSubagent()
    raise ProofAgentError(
        "PA_MODEL_001",
        f"Unsupported review subagent provider '{config.provider}'.",
        "Set review.subagent.provider to 'deterministic' or add a registered review provider.",
    )
