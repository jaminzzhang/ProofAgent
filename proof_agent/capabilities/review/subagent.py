from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.capabilities.models.normalization import (
    ModelOutputNormalizationError,
    parse_model_contract,
)
from proof_agent.contracts import (
    EnforcementPoint,
    ModelMessage,
    ModelRequest,
    ModelRole,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReviewDecision,
    ReviewSubagentConfig,
    allowed_review_decisions_for,
)
from proof_agent.contracts.manifest import ModelConfig


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


class LLMHarnessReviewSubagent:
    def __init__(
        self,
        *,
        config: ReviewSubagentConfig,
        model_provider: ModelProvider | None = None,
    ) -> None:
        self.config = config
        self.model_provider = model_provider or resolve_provider(
            ModelConfig(
                provider=config.provider,
                name=config.name,
                params=config.params,
            )
        )

    def review(
        self,
        *,
        enforcement_point: EnforcementPoint,
        action: ReActActionProposal,
        context: Mapping[str, Any],
    ) -> ReviewDecision:
        point = EnforcementPoint(enforcement_point)
        allowed_decisions = allowed_review_decisions_for(point)
        request = ModelRequest(
            provider=self.model_provider.provider_name,
            model=self.model_provider.model_name,
            messages=(
                ModelMessage(role=ModelRole.SYSTEM, content=_review_control_prompt()),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        {
                            "enforcement_point": point.value,
                            "action": action.model_dump(
                                mode="json",
                                warnings=False,
                                fallback=_json_contract_fallback,
                            ),
                            "context": dict(context),
                            "allowed_decisions": [
                                decision.value
                                for decision in PolicyDecisionType
                                if decision in allowed_decisions
                            ],
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                ),
            ),
            max_output_tokens=self.config.max_output_tokens,
            timeout_seconds=int(self.config.timeout_seconds),
            response_format="json",
            stream=False,
            metadata={
                "role": "harness_review",
                "enforcement_point": point.value,
                "subject_action_id": action.action_id,
            },
        )
        response = self.model_provider.generate(request)
        decision = parse_model_contract(
            content=response.content,
            contract_type=ReviewDecision,
            role="harness_review",
        )
        if (
            decision.enforcement_point != point
            or decision.subject_action_id != action.action_id
        ):
            raise ModelOutputNormalizationError(
                role="harness_review",
                error_code="model_output_contract_validation_failed",
                message="Model review output was not bound to the current review request.",
                raw_content_length=len(response.content),
            )
        if decision.suggested_decision not in allowed_decisions:
            raise ModelOutputNormalizationError(
                role="harness_review",
                error_code="model_output_contract_validation_failed",
                message=(
                    "suggested_decision is not allowed for the current "
                    "enforcement point."
                ),
                raw_content_length=len(response.content),
            )
        return decision


def _json_contract_fallback(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_contract_fallback(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_json_contract_fallback(item) for item in value]
    return value


def _review_control_prompt() -> str:
    return (
        "You are the Proof Agent LLM Harness Review Subagent. "
        "Return exactly one JSON object matching ReviewDecision. "
        "Your decision is advisory only; PolicyEngine remains the final authority. "
        "Do not generate final user answers, chain-of-thought, markdown commentary, or tool results. "
        "Use fail-closed reasoning when the action or context is unsafe or underspecified."
    )


def resolve_review_subagent(config: ReviewSubagentConfig) -> HarnessReviewSubagent:
    if config.provider == "deterministic":
        return DeterministicHarnessReviewSubagent()
    return LLMHarnessReviewSubagent(config=config)
