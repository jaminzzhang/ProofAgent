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
    IntentResolution,
    ModelMessage,
    ModelRequest,
    ModelRole,
    ReActActionType,
)
from proof_agent.contracts.manifest import ModelConfig, ReActPlannerConfig


_ALLOWED_RECOMMENDED_ACTIONS = frozenset(
    {
        ReActActionType.ASK_CLARIFICATION,
        ReActActionType.PLAN_RETRIEVAL,
        ReActActionType.PROPOSE_TOOL_CALL,
    }
)


class IntentResolver(Protocol):
    def resolve(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: Mapping[str, Any] | None = None,
    ) -> IntentResolution:
        """Resolve user intent into an audit-safe structured summary."""


class DeterministicIntentResolver:
    """Deterministic intent resolver for offline demos and tests."""

    def resolve(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: Mapping[str, Any] | None = None,
    ) -> IntentResolution:
        _ = (system_prompt, context_summary, workflow_stage_context)
        normalized_question = question.lower()
        if "can this customer" in normalized_question or "claim it" in normalized_question:
            return IntentResolution(
                resolution_id="intent_clarify_1",
                user_goal="Resolve a customer-specific claim question.",
                domain_intent="customer_claim_question",
                known_facts=("The user refers to a customer or claim without identifiers.",),
                missing_fields=("customer_id", "policy_id", "claim_type"),
                ambiguities=("The referenced customer, policy, and claim type are unclear.",),
                risk_flags=(),
                confidence=0.55,
                recommended_next_action=ReActActionType.ASK_CLARIFICATION,
            )
        if "look up customer policy status" in normalized_question:
            return IntentResolution(
                resolution_id="intent_tool_1",
                user_goal="Look up a customer policy status.",
                domain_intent="customer_policy_status_lookup",
                known_facts=("The user asks for customer policy status lookup.",),
                missing_fields=(),
                ambiguities=(),
                risk_flags=("customer_data_access",),
                confidence=0.86,
                recommended_next_action=ReActActionType.PROPOSE_TOOL_CALL,
            )
        return IntentResolution(
            resolution_id="intent_retrieval_1",
            user_goal="Answer an enterprise policy question.",
            domain_intent="enterprise_policy_question",
            known_facts=("The user asks a question that should be grounded in knowledge.",),
            missing_fields=(),
            ambiguities=(),
            risk_flags=(),
            confidence=0.84,
            recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
        )


class LLMIntentResolver:
    def __init__(
        self,
        *,
        config: ReActPlannerConfig,
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

    def resolve(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: Mapping[str, Any] | None = None,
    ) -> IntentResolution:
        payload: dict[str, Any] = {
            "question": question,
            "system_prompt_summary": system_prompt,
            "context_summary": context_summary,
            "allowed_recommended_next_actions": [
                action.value for action in sorted(_ALLOWED_RECOMMENDED_ACTIONS, key=str)
            ],
        }
        if workflow_stage_context:
            payload["workflow_stage_context"] = dict(workflow_stage_context)
        request = ModelRequest(
            provider=self.model_provider.provider_name,
            model=self.model_provider.model_name,
            messages=(
                ModelMessage(role=ModelRole.SYSTEM, content=_intent_control_prompt()),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(payload, ensure_ascii=True, sort_keys=True),
                ),
            ),
            response_format="json",
            stream=False,
            metadata={"role": "intent_resolution", "question": question},
        )
        response = self.model_provider.generate(request)
        resolution = parse_model_contract(
            content=response.content,
            contract_type=IntentResolution,
            role="intent_resolution",
        )
        return _validate_intent_resolution(
            resolution,
            raw_content_length=len(response.content),
        )


def resolve_intent_resolver(config: ReActPlannerConfig) -> IntentResolver:
    if config.provider == "deterministic":
        return DeterministicIntentResolver()
    return LLMIntentResolver(config=config)


def _intent_control_prompt() -> str:
    return (
        "You are the Proof Agent Intent Resolver. "
        "Return exactly one JSON object matching IntentResolution. "
        "Summarize user intent, known facts, missing fields, ambiguities, risk flags, "
        "confidence, and a recommended_next_action. "
        "Use only allowed recommended_next_action values from the user message. "
        "Do not return raw chain-of-thought, markdown, tool calls, retrieval plans, "
        "final answers, or policy decisions."
    )


def _validate_intent_resolution(
    resolution: IntentResolution,
    *,
    raw_content_length: int,
) -> IntentResolution:
    if resolution.recommended_next_action not in _ALLOWED_RECOMMENDED_ACTIONS:
        raise ModelOutputNormalizationError(
            role="intent_resolution",
            error_code="model_output_contract_validation_failed",
            message=(
                "intent_resolution recommended_next_action must be one of "
                "ask_clarification, plan_retrieval, or propose_tool_call."
            ),
            raw_content_length=raw_content_length,
            contract_name="IntentResolution",
            violation_codes=("invalid_recommended_next_action",),
            field_paths=("recommended_next_action",),
            violation_count=1,
        )
    if (
        resolution.recommended_next_action == ReActActionType.ASK_CLARIFICATION
        and not resolution.missing_fields
    ):
        raise ModelOutputNormalizationError(
            role="intent_resolution",
            error_code="model_output_contract_validation_failed",
            message="ask_clarification intent resolution requires missing_fields.",
            raw_content_length=raw_content_length,
            contract_name="IntentResolution",
            violation_codes=("missing_required_field_for_action",),
            field_paths=("missing_fields",),
            violation_count=1,
        )
    return resolution
