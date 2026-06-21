from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.capabilities.models.normalization import (
    ModelOutputNormalizationError,
    parse_model_contract,
)
from proof_agent.capabilities.react.planner import _deterministic_query
from proof_agent.contracts import (
    BusinessFlowCandidatePack,
    BusinessFlowSkillPackDefinition,
    BusinessFlowSkillPackRecommendation,
    BusinessFlowSkillPackRecommendationType,
    IntentResolution,
    IntentResolutionResult,
    ModelMessage,
    ModelRequest,
    ModelRole,
    ReActActionType,
    RetrievalQueryItem,
)
from proof_agent.contracts.manifest import ModelConfig, ReActPlannerConfig


_ALLOWED_RECOMMENDED_ACTIONS = frozenset(
    {
        ReActActionType.ASK_CLARIFICATION,
        ReActActionType.PLAN_RETRIEVAL,
        ReActActionType.PROPOSE_TOOL_CALL,
    }
)
_INTENT_REQUIRED_FIELDS = (
    "resolution_id",
    "user_goal",
    "domain_intent",
    "known_facts",
    "missing_fields",
    "ambiguities",
    "risk_flags",
    "confidence",
    "recommended_next_action",
    "retrieval_query_set",
)


class IntentResolver(Protocol):
    def resolve(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: Mapping[str, Any] | None = None,
        business_flow_skill_packs: tuple[BusinessFlowSkillPackDefinition, ...] = (),
    ) -> IntentResolutionResult:
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
        business_flow_skill_packs: tuple[BusinessFlowSkillPackDefinition, ...] = (),
    ) -> IntentResolutionResult:
        _ = (system_prompt, context_summary, workflow_stage_context)
        normalized_question = question.lower()
        if "can this customer" in normalized_question or "claim it" in normalized_question:
            resolution = IntentResolution(
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
            return IntentResolutionResult(
                intent_resolution=resolution,
                business_flow_skill_pack_recommendation=(
                    _deterministic_business_flow_recommendation(
                        resolution,
                        business_flow_skill_packs,
                    )
                ),
            )
        if "look up customer policy status" in normalized_question:
            resolution = IntentResolution(
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
            return IntentResolutionResult(
                intent_resolution=resolution,
                business_flow_skill_pack_recommendation=(
                    _deterministic_business_flow_recommendation(
                        resolution,
                        business_flow_skill_packs,
                    )
                ),
            )
        resolution = IntentResolution(
            resolution_id="intent_retrieval_1",
            user_goal="Answer an enterprise policy question.",
            domain_intent="enterprise_policy_question",
            known_facts=("The user asks a question that should be grounded in knowledge.",),
            missing_fields=(),
            ambiguities=(),
            risk_flags=(),
            confidence=0.84,
            recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
            retrieval_query_set=(
                RetrievalQueryItem(
                    query=_deterministic_query(question),
                    intent_angle="primary_policy_question",
                    required=True,
                    reason="The user asks a knowledge-backed enterprise policy question.",
                ),
            ),
        )
        return IntentResolutionResult(
            intent_resolution=resolution,
            business_flow_skill_pack_recommendation=(
                _deterministic_business_flow_recommendation(
                    resolution,
                    business_flow_skill_packs,
                )
            ),
        )


class LLMIntentResolver:
    def __init__(
        self,
        *,
        config: ReActPlannerConfig,
        model_provider: ModelProvider | None = None,
        max_queries: int = 3,
    ) -> None:
        if max_queries < 1 or max_queries > 5:
            raise ValueError("max_queries must be between 1 and 5")
        self.config = config
        self.max_queries = max_queries
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
        business_flow_skill_packs: tuple[BusinessFlowSkillPackDefinition, ...] = (),
    ) -> IntentResolutionResult:
        business_flow_routing = _business_flow_skill_pack_routing_payload(
            business_flow_skill_packs
        )
        payload: dict[str, Any] = {
            "question": question,
            "system_prompt_summary": system_prompt,
            "context_summary": context_summary,
            "required_output_contract": _intent_required_output_contract(
                include_business_flow_recommendation=bool(business_flow_routing)
            ),
            "retrieval_query_set_budget": {
                "max_queries": self.max_queries,
                "required_when": (
                    "recommended_next_action is plan_retrieval and missing_fields is empty"
                ),
                "allowed_item_fields": ["query", "intent_angle", "required", "reason"],
                "forbidden_item_fields": [
                    "source_id",
                    "provider",
                    "filters",
                    "top_k",
                    "scope_id",
                ],
            },
            "allowed_recommended_next_actions": [
                action.value for action in sorted(_ALLOWED_RECOMMENDED_ACTIONS, key=str)
            ],
        }
        if workflow_stage_context:
            payload["workflow_stage_context"] = dict(workflow_stage_context)
        if business_flow_routing:
            payload["business_flow_skill_pack_routing"] = business_flow_routing
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
        try:
            return _parse_and_validate_intent_resolution_result(
                response.content,
                max_queries=self.max_queries,
                require_business_flow_recommendation=bool(business_flow_routing),
            )
        except ModelOutputNormalizationError as exc:
            repair_request = _intent_repair_request(
                provider=self.model_provider.provider_name,
                model=self.model_provider.model_name,
                question=question,
                original_payload=payload,
                previous_content=response.content,
                error=exc,
            )
        repair_response = self.model_provider.generate(repair_request)
        return _parse_and_validate_intent_resolution_result(
            repair_response.content,
            max_queries=self.max_queries,
            require_business_flow_recommendation=bool(business_flow_routing),
        )


def _intent_required_output_contract(
    *,
    include_business_flow_recommendation: bool,
) -> dict[str, Any]:
    intent_contract = {
        "name": "IntentResolution",
        "required_fields": list(_INTENT_REQUIRED_FIELDS),
        "field_types": {
            "resolution_id": "string",
            "user_goal": "string",
            "domain_intent": "string",
            "known_facts": "array of strings",
            "missing_fields": "array of strings",
            "ambiguities": "array of strings",
            "risk_flags": "array of strings",
            "confidence": "number between 0 and 1",
            "recommended_next_action": "one of allowed_recommended_next_actions",
            "retrieval_query_set": (
                "array of RetrievalQueryItem objects with query, "
                "intent_angle, required, and reason"
            ),
        },
        "example": {
            "resolution_id": "intent_1",
            "user_goal": "Understand the user's insurance knowledge request.",
            "domain_intent": "public_insurance_knowledge_query",
            "known_facts": ["The user asks for an insurance product explanation."],
            "missing_fields": [],
            "ambiguities": [],
            "risk_flags": [],
            "confidence": 0.82,
            "recommended_next_action": "plan_retrieval",
            "retrieval_query_set": [
                {
                    "query": "insurance product explanation",
                    "intent_angle": "primary_policy_question",
                    "required": True,
                    "reason": "The user asks for a knowledge-backed explanation.",
                }
            ],
        },
    }
    if not include_business_flow_recommendation:
        return intent_contract
    return {
        "name": "IntentResolutionResult",
        "required_fields": [
            "intent_resolution",
            "business_flow_skill_pack_recommendation",
        ],
        "field_types": {
            "intent_resolution": "IntentResolution object",
            "business_flow_skill_pack_recommendation": (
                "BusinessFlowSkillPackRecommendation object with recommendation_type "
                "single_pack, no_pack, or ambiguous; top-level route confidence; "
                "candidate_packs sorted by confidence descending; candidate pack_id, "
                "confidence, and reason"
            ),
        },
        "intent_resolution_contract": intent_contract,
    }


def _business_flow_skill_pack_routing_payload(
    skill_packs: tuple[BusinessFlowSkillPackDefinition, ...],
) -> dict[str, Any] | None:
    if not skill_packs:
        return None
    return {
        "required": True,
        "instruction": (
            "Recommend a Business Flow Skill Pack from candidate_packs, return no_pack "
            "when none fits, or ambiguous when multiple business flows are materially "
            "needed. Do not execute or apply any pack content."
        ),
        "candidate_packs": [
            {
                "pack_id": pack.id,
                "label": pack.label,
                "description": pack.description,
                "intent_patterns": list(pack.intent_patterns),
                "intent_taxonomy_refs": list(pack.intent_taxonomy_refs),
                "admission": {
                    "min_confidence": pack.admission.min_confidence,
                    "require_authorization_context": (
                        pack.admission.require_authorization_context
                    ),
                },
            }
            for pack in skill_packs
        ],
        "allowed_recommendation_types": [
            BusinessFlowSkillPackRecommendationType.SINGLE_PACK.value,
            BusinessFlowSkillPackRecommendationType.NO_PACK.value,
            BusinessFlowSkillPackRecommendationType.AMBIGUOUS.value,
        ],
    }


def _parse_and_validate_intent_resolution_result(
    content: str,
    *,
    max_queries: int,
    require_business_flow_recommendation: bool,
) -> IntentResolutionResult:
    if '"intent_resolution"' in content:
        result = parse_model_contract(
            content=content,
            contract_type=IntentResolutionResult,
            role="intent_resolution",
        )
    else:
        result = IntentResolutionResult(
            intent_resolution=parse_model_contract(
                content=content,
                contract_type=IntentResolution,
                role="intent_resolution",
            )
        )
    return _validate_intent_resolution_result(
        result,
        raw_content_length=len(content),
        max_queries=max_queries,
        require_business_flow_recommendation=require_business_flow_recommendation,
    )


def _intent_repair_request(
    *,
    provider: str,
    model: str,
    question: str,
    original_payload: Mapping[str, Any],
    previous_content: str,
    error: ModelOutputNormalizationError,
) -> ModelRequest:
    previous_json, previous_parse_error = _json_or_parse_error(previous_content)
    repair_payload: dict[str, Any] = {
        "question": question,
        "instruction": (
            "Repair the previous intent_resolution output. Return only one JSON object "
            "matching the required_output_contract. Preserve the user's meaning; do not "
            "answer the user."
        ),
        "required_output_contract": original_payload["required_output_contract"],
        "allowed_recommended_next_actions": original_payload[
            "allowed_recommended_next_actions"
        ],
        "validation_error": {
            "error_code": error.error_code,
            "contract_name": error.contract_name,
            "field_paths": list(error.field_paths),
            "violation_codes": list(error.violation_codes),
            "violation_count": error.violation_count,
        },
        "previous_response_json": previous_json,
        "previous_response_parse_error_code": previous_parse_error,
    }
    if "workflow_stage_context" in original_payload:
        repair_payload["workflow_stage_context"] = original_payload[
            "workflow_stage_context"
        ]
    return ModelRequest(
        provider=provider,
        model=model,
        messages=(
            ModelMessage(role=ModelRole.SYSTEM, content=_intent_repair_prompt()),
            ModelMessage(
                role=ModelRole.USER,
                content=json.dumps(repair_payload, ensure_ascii=True, sort_keys=True),
            ),
        ),
        response_format="json",
        stream=False,
        metadata={
            "role": "intent_resolution",
            "question": question,
            "repair_attempt": 1,
        },
    )


def _json_or_parse_error(content: str) -> tuple[Any | None, str | None]:
    try:
        return json.loads(content.strip()), None
    except json.JSONDecodeError:
        return None, "model_output_json_parse_failed"


def _intent_repair_prompt() -> str:
    return (
        "You are repairing a Proof Agent intent resolution JSON object. "
        "Return exactly one JSON object with every required field present. "
        "Do not include markdown, explanations, final answers, tool calls, or chain-of-thought."
    )


def resolve_intent_resolver(
    config: ReActPlannerConfig,
    *,
    max_queries: int = 3,
) -> IntentResolver:
    if config.provider == "deterministic":
        return DeterministicIntentResolver()
    return LLMIntentResolver(config=config, max_queries=max_queries)


def _intent_control_prompt() -> str:
    return (
        "You are the Proof Agent Intent Resolver. "
        "Return exactly one JSON object matching the required output contract. "
        "When the contract is IntentResolution, include all required fields: "
        f"{', '.join(_INTENT_REQUIRED_FIELDS)}. "
        "When the contract is IntentResolutionResult, return intent_resolution plus an "
        "independent business_flow_skill_pack_recommendation. "
        "Summarize user intent, known facts, missing fields, ambiguities, risk flags, "
        "confidence, and a recommended_next_action. "
        "Use only allowed recommended_next_action values from the user message. "
        "When the recommended_next_action is plan_retrieval and no missing_fields "
        "block retrieval, include a bounded non-executing retrieval_query_set. "
        "Do not return raw chain-of-thought, markdown, tool calls, executable retrieval "
        "plans, final answers, or policy decisions."
    )


def _deterministic_business_flow_recommendation(
    resolution: IntentResolution,
    skill_packs: tuple[BusinessFlowSkillPackDefinition, ...],
) -> BusinessFlowSkillPackRecommendation | None:
    if not skill_packs:
        return None
    if len(skill_packs) == 1:
        return BusinessFlowSkillPackRecommendation(
            recommendation_id=f"bfsp_rec_{resolution.resolution_id}",
            intent_resolution_id=resolution.resolution_id,
            recommendation_type=BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
            confidence=resolution.confidence,
            reason="Deterministic resolver selected the only published Business Flow Skill Pack.",
            candidate_packs=(
                BusinessFlowCandidatePack(
                    pack_id=skill_packs[0].id,
                    confidence=resolution.confidence,
                    reason="Only published Business Flow Skill Pack.",
                ),
            ),
        )
    return BusinessFlowSkillPackRecommendation(
        recommendation_id=f"bfsp_rec_{resolution.resolution_id}",
        intent_resolution_id=resolution.resolution_id,
        recommendation_type=BusinessFlowSkillPackRecommendationType.AMBIGUOUS,
        confidence=resolution.confidence,
        reason="Deterministic resolver found multiple published Business Flow Skill Packs.",
        candidate_packs=tuple(
            BusinessFlowCandidatePack(
                pack_id=pack.id,
                confidence=resolution.confidence,
                reason="Published Business Flow Skill Pack candidate.",
            )
            for pack in skill_packs
        ),
        requires_task_split=True,
    )


def _validate_intent_resolution_result(
    result: IntentResolutionResult,
    *,
    raw_content_length: int,
    max_queries: int,
    require_business_flow_recommendation: bool,
) -> IntentResolutionResult:
    _validate_intent_resolution(
        result.intent_resolution,
        raw_content_length=raw_content_length,
        max_queries=max_queries,
    )
    recommendation = result.business_flow_skill_pack_recommendation
    if require_business_flow_recommendation and recommendation is None:
        raise ModelOutputNormalizationError(
            role="intent_resolution",
            error_code="model_output_contract_validation_failed",
            message=(
                "intent_resolution result requires "
                "business_flow_skill_pack_recommendation when Business Flow Skill "
                "Packs are provided."
            ),
            raw_content_length=raw_content_length,
            contract_name="IntentResolutionResult",
            violation_codes=("business_flow_recommendation_required",),
            field_paths=("business_flow_skill_pack_recommendation",),
            violation_count=1,
        )
    if (
        recommendation is not None
        and recommendation.intent_resolution_id != result.intent_resolution.resolution_id
    ):
        raise ModelOutputNormalizationError(
            role="intent_resolution",
            error_code="model_output_contract_validation_failed",
            message=(
                "business_flow_skill_pack_recommendation.intent_resolution_id must "
                "match intent_resolution.resolution_id."
            ),
            raw_content_length=raw_content_length,
            contract_name="IntentResolutionResult",
            violation_codes=("business_flow_recommendation_intent_mismatch",),
            field_paths=("business_flow_skill_pack_recommendation.intent_resolution_id",),
            violation_count=1,
        )
    return result


def _validate_intent_resolution(
    resolution: IntentResolution,
    *,
    raw_content_length: int,
    max_queries: int,
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
    if len(resolution.retrieval_query_set) > max_queries:
        raise ModelOutputNormalizationError(
            role="intent_resolution",
            error_code="model_output_contract_validation_failed",
            message="intent_resolution retrieval_query_set exceeds max_queries.",
            raw_content_length=raw_content_length,
            contract_name="IntentResolution",
            violation_codes=("retrieval_query_set_over_budget",),
            field_paths=("retrieval_query_set",),
            violation_count=1,
        )
    if (
        resolution.recommended_next_action == ReActActionType.PLAN_RETRIEVAL
        and not resolution.missing_fields
        and not resolution.retrieval_query_set
    ):
        raise ModelOutputNormalizationError(
            role="intent_resolution",
            error_code="model_output_contract_validation_failed",
            message=(
                "plan_retrieval intent resolution without blocking missing_fields "
                "requires retrieval_query_set."
            ),
            raw_content_length=raw_content_length,
            contract_name="IntentResolution",
            violation_codes=("retrieval_query_set_required",),
            field_paths=("retrieval_query_set",),
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
