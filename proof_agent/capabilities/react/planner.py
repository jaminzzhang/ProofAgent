from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, Field

from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.capabilities.models.normalization import (
    ModelOutputNormalizationError,
    parse_model_contract,
)
from proof_agent.contracts import (
    ModelMessage,
    ModelRequest,
    ModelRole,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
)
from proof_agent.contracts.manifest import ModelConfig, ReActPlannerConfig


_INITIAL_PLANNER_ACTION_TYPES = (
    ReActActionType.ASK_CLARIFICATION,
    ReActActionType.PLAN_RETRIEVAL,
    ReActActionType.PROPOSE_TOOL_CALL,
)
_INITIAL_PLANNER_ACTION_TYPE_SET = frozenset(_INITIAL_PLANNER_ACTION_TYPES)
_MAX_CANONICAL_STRING_LENGTH = 512
_V1_TOOL_PARAMETER_ALLOWLIST = {
    "customer_lookup": frozenset({"customer_id", "policy_id"}),
    "untrusted_web_search": frozenset({"query", "max_results"}),
}


class ReActPlanner(Protocol):
    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_node_context: Mapping[str, Any] | None = None,
    ) -> ReActActionProposal:
        """Propose the next governed ReAct action."""


class DeterministicReActPlanner:
    """Deterministic ReAct planner for offline demos and tests."""

    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_node_context: Mapping[str, Any] | None = None,
    ) -> ReActActionProposal:
        _ = (system_prompt, context_summary, workflow_node_context)
        normalized_question = question.lower()

        if "can this customer" in normalized_question or "claim it" in normalized_question:
            return ReActActionProposal(
                action_id="act_clarify_1",
                action_type=ReActActionType.ASK_CLARIFICATION,
                reasoning_summary=ReasoningSummary(
                    goal="Clarify the customer and claim details before governed action.",
                    observations=("The request refers to a customer or claim without identifiers.",),
                    candidate_actions=(ReActActionType.ASK_CLARIFICATION,),
                    selected_action=ReActActionType.ASK_CLARIFICATION,
                    rationale_summary="Required customer and claim context is missing.",
                    risk_flags=(),
                    required_evidence=(),
                ),
                parameters={"missing_fields": ("customer_id", "policy_id", "claim_type")},
                risk_level="low",
            )

        if "look up customer policy status" in normalized_question:
            return ReActActionProposal(
                action_id="act_tool_1",
                action_type=ReActActionType.PROPOSE_TOOL_CALL,
                reasoning_summary=ReasoningSummary(
                    goal="Check customer policy status through the governed tool path.",
                    observations=("The request asks for customer policy status lookup.",),
                    candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL,),
                    selected_action=ReActActionType.PROPOSE_TOOL_CALL,
                    rationale_summary="The status requires an approved customer lookup tool call.",
                    risk_flags=("customer_data_access",),
                    required_evidence=("customer policy status",),
                ),
                parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
                target_tool_name="customer_lookup",
                risk_level="medium",
            )

        return ReActActionProposal(
            action_id="act_retrieval_1",
            action_type=ReActActionType.PLAN_RETRIEVAL,
            reasoning_summary=ReasoningSummary(
                goal="Retrieve policy evidence before answering.",
                observations=("The request can be answered from governed knowledge evidence.",),
                candidate_actions=(ReActActionType.PLAN_RETRIEVAL,),
                selected_action=ReActActionType.PLAN_RETRIEVAL,
                rationale_summary="Relevant policy evidence is needed before final answer generation.",
                risk_flags=(),
                required_evidence=("policy evidence",),
            ),
            parameters={"query": _deterministic_query(question)},
            risk_level="low",
        )


class LLMReActPlanner:
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

    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_node_context: Mapping[str, Any] | None = None,
    ) -> ReActActionProposal:
        user_payload: dict[str, Any] = {
            "question": question,
            "system_prompt_summary": system_prompt,
            "context_summary": context_summary,
            "allowed_actions": [
                action.value
                for action in _INITIAL_PLANNER_ACTION_TYPES
            ],
        }
        if workflow_node_context:
            user_payload["workflow_node_context"] = dict(workflow_node_context)
        request = ModelRequest(
            provider=self.model_provider.provider_name,
            model=self.model_provider.model_name,
            messages=(
                ModelMessage(role=ModelRole.SYSTEM, content=_planner_control_prompt()),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        user_payload,
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                ),
            ),
            response_format="json",
            stream=False,
            metadata={"role": "react_planner", "question": question},
        )
        response = self.model_provider.generate(request)
        proposal = _parse_planner_proposal(
            content=response.content,
        )
        return _validate_planner_proposal(
            proposal,
            raw_content_length=len(response.content),
        )


def _planner_control_prompt() -> str:
    return (
        "You are the Proof Agent LLM ReAct Planner. "
        "Return exactly one JSON object matching ReActActionProposal. "
        "If you use a compact form, return action_type plus parameters; params is accepted as an alias for parameters. "
        "Use only allowed action_type values supplied in the user message. "
        "Do not return chain-of-thought, markdown commentary, tool results, or natural language. "
        "A proposed action is not approved and cannot execute until Harness policy admits it. "
        "When action_type is plan_retrieval, set parameters.query to the original question verbatim. "
        "Do not summarize, shorten, translate, or rephrase the question. "
        "Preserve the original language, key terms, and full phrasing exactly as provided."
    )


class _CompactPlannerProposal(BaseModel):
    action_type: ReActActionType
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    params: Mapping[str, Any] = Field(default_factory=dict)
    target_tool_name: str | None = None


def _parse_planner_proposal(*, content: str) -> ReActActionProposal:
    try:
        return parse_model_contract(
            content=content,
            contract_type=ReActActionProposal,
            role="react_planner",
        )
    except ModelOutputNormalizationError as exc:
        if exc.error_code != "model_output_contract_validation_failed":
            raise
    compact = parse_model_contract(
        content=content,
        contract_type=_CompactPlannerProposal,
        role="react_planner",
    )
    parameters = compact.parameters or compact.params
    action_type = compact.action_type
    target_tool_name = compact.target_tool_name
    if (
        action_type == ReActActionType.PROPOSE_TOOL_CALL
        and target_tool_name is None
        and _is_non_empty_string(parameters.get("query"))
    ):
        action_type = ReActActionType.PLAN_RETRIEVAL
        parameters = {"query": parameters["query"]}
    if (
        action_type == ReActActionType.PROPOSE_TOOL_CALL
        and target_tool_name is None
        and isinstance(parameters.get("arguments"), Mapping)
        and _is_non_empty_string(parameters["arguments"].get("query"))
    ):
        action_type = ReActActionType.PLAN_RETRIEVAL
        parameters = {"query": parameters["arguments"]["query"]}
    if (
        action_type == ReActActionType.PLAN_RETRIEVAL
        and not _is_non_empty_string(parameters.get("query"))
        and _is_non_empty_string(parameters.get("plan"))
    ):
        parameters = {"query": parameters["plan"]}
    return ReActActionProposal(
        action_id="act_llm_compact_1",
        action_type=action_type,
        reasoning_summary=_safe_reasoning_summary(action_type),
        parameters=parameters,
        target_tool_name=target_tool_name,
        risk_level="medium"
        if action_type == ReActActionType.PROPOSE_TOOL_CALL
        else "low",
    )


def _validate_planner_proposal(
    proposal: ReActActionProposal,
    *,
    raw_content_length: int,
) -> ReActActionProposal:
    if proposal.action_type not in _INITIAL_PLANNER_ACTION_TYPE_SET:
        raise _planner_semantic_error(
            f"unsupported initial planner action: {proposal.action_type.value}.",
            raw_content_length=raw_content_length,
        )

    if proposal.reasoning_summary.selected_action != proposal.action_type:
        raise _planner_semantic_error(
            "selected_action must match action_type.",
            raw_content_length=raw_content_length,
        )

    if proposal.action_type not in proposal.reasoning_summary.candidate_actions:
        raise _planner_semantic_error(
            "action_type must appear in candidate_actions.",
            raw_content_length=raw_content_length,
        )

    if (
        proposal.action_type == ReActActionType.PLAN_RETRIEVAL
        and not _is_non_empty_string(proposal.parameters.get("query"))
    ):
        raise _planner_semantic_error(
            "plan_retrieval requires parameters.query.",
            raw_content_length=raw_content_length,
        )

    if (
        proposal.action_type == ReActActionType.PROPOSE_TOOL_CALL
        and not _is_non_empty_string(proposal.target_tool_name)
    ):
        raise _planner_semantic_error(
            "propose_tool_call requires target_tool_name.",
            raw_content_length=raw_content_length,
        )

    if (
        proposal.action_type == ReActActionType.ASK_CLARIFICATION
        and not _is_non_empty_string_sequence(
            proposal.parameters.get("missing_fields")
        )
    ):
        raise _planner_semantic_error(
            "ask_clarification requires parameters.missing_fields.",
            raw_content_length=raw_content_length,
        )

    return _canonicalize_planner_proposal(
        proposal,
        raw_content_length=raw_content_length,
    )


def _canonicalize_planner_proposal(
    proposal: ReActActionProposal,
    *,
    raw_content_length: int,
) -> ReActActionProposal:
    action_type = proposal.action_type
    if action_type == ReActActionType.PLAN_RETRIEVAL:
        return ReActActionProposal(
            action_id="act_llm_retrieval_1",
            action_type=action_type,
            reasoning_summary=_safe_reasoning_summary(action_type),
            parameters={
                "query": _canonical_string(
                    proposal.parameters["query"],
                    field_name="parameters.query",
                    raw_content_length=raw_content_length,
                )
            },
            risk_level="low",
        )
    if action_type == ReActActionType.ASK_CLARIFICATION:
        missing_fields = tuple(
            _canonical_string(
                field,
                field_name="parameters.missing_fields",
                raw_content_length=raw_content_length,
            )
            for field in proposal.parameters["missing_fields"]
        )
        return ReActActionProposal(
            action_id="act_llm_clarification_1",
            action_type=action_type,
            reasoning_summary=_safe_reasoning_summary(action_type),
            parameters={"missing_fields": missing_fields},
            risk_level="low",
        )

    target_tool_name = _canonical_string(
        proposal.target_tool_name,
        field_name="target_tool_name",
        raw_content_length=raw_content_length,
    )
    allowed_parameters = _V1_TOOL_PARAMETER_ALLOWLIST.get(target_tool_name)
    if allowed_parameters is None:
        raise _planner_semantic_error(
            "propose_tool_call target_tool_name is not supported.",
            raw_content_length=raw_content_length,
        )
    tool_parameters: dict[str, str] = {
        key: _canonical_string(
            proposal.parameters[key],
            field_name=f"parameters.{key}",
            raw_content_length=raw_content_length,
        )
        for key in sorted(allowed_parameters)
        if key in proposal.parameters
    }
    if not tool_parameters:
        raise _planner_semantic_error(
            "propose_tool_call requires supported tool parameters.",
            raw_content_length=raw_content_length,
        )
    return ReActActionProposal(
        action_id="act_llm_tool_1",
        action_type=action_type,
        reasoning_summary=_safe_reasoning_summary(action_type),
        parameters=tool_parameters,
        target_tool_name=target_tool_name,
        risk_level="medium",
    )


def _canonical_string(
    value: object,
    *,
    field_name: str,
    raw_content_length: int,
) -> str:
    if not isinstance(value, str):
        raise _planner_semantic_error(
            f"{field_name} must be a string.",
            raw_content_length=raw_content_length,
        )
    canonical = value.strip()
    if not canonical:
        raise _planner_semantic_error(
            f"{field_name} must not be empty.",
            raw_content_length=raw_content_length,
        )
    if len(canonical) > _MAX_CANONICAL_STRING_LENGTH:
        raise _planner_semantic_error(
            f"{field_name} exceeded the safe string length limit.",
            raw_content_length=raw_content_length,
        )
    return canonical


def _safe_reasoning_summary(action_type: ReActActionType) -> ReasoningSummary:
    if action_type == ReActActionType.PLAN_RETRIEVAL:
        return ReasoningSummary(
            goal="Plan a governed retrieval step before answering.",
            observations=("The request needs policy evidence before a final answer.",),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="Retrieve evidence through the configured knowledge provider.",
            risk_flags=(),
            required_evidence=("policy evidence",),
        )
    if action_type == ReActActionType.ASK_CLARIFICATION:
        return ReasoningSummary(
            goal="Request missing details before continuing.",
            observations=("Required fields are missing from the request.",),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="Ask for the missing fields before any governed action.",
            risk_flags=(),
            required_evidence=(),
        )
    return ReasoningSummary(
        goal="Propose a governed tool call for policy review.",
        observations=("The request may need a manifest-declared tool.",),
        candidate_actions=(action_type,),
        selected_action=action_type,
        rationale_summary="The tool proposal must pass policy and approval checks before execution.",
        risk_flags=("customer_data_access",),
        required_evidence=(),
    )


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_non_empty_string_sequence(value: object) -> bool:
    return (
        isinstance(value, list | tuple)
        and bool(value)
        and all(_is_non_empty_string(item) for item in value)
    )


def _planner_semantic_error(
    message: str,
    *,
    raw_content_length: int,
) -> ModelOutputNormalizationError:
    return ModelOutputNormalizationError(
        role="react_planner",
        error_code="model_output_contract_validation_failed",
        message=message,
        raw_content_length=raw_content_length,
    )


def _deterministic_query(question: str) -> str:
    if question == "What is the reimbursement rule for travel meals?":
        return "travel meals reimbursement rule"
    if question == "住院理赔需要哪些材料？":
        return "inpatient claim reimbursement required documents"
    if question == "What does deductible mean in inpatient reimbursement coverage?":
        return "deductible out of pocket before reimbursement"
    if question == "How should I understand the waiting period clause in a health insurance policy?":
        return "waiting period policy starts benefits"
    if question == "住院医疗险里的免赔额和等待期是什么意思？":
        return "deductible waiting period policy terms reimbursement"
    if question == "What happens after I submit an inpatient reimbursement claim?":
        return "claim review documents status after submit"
    if question == "What documents should I prepare to improve my claim approval odds?":
        return "claim documents preparation review approval likelihood"
    return question


def resolve_react_planner(config: ReActPlannerConfig) -> ReActPlanner:
    if config.provider == "deterministic":
        return DeterministicReActPlanner()
    return LLMReActPlanner(config=config)
