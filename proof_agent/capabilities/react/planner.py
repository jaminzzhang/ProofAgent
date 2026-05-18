from __future__ import annotations

import json
from typing import Protocol

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


class ReActPlanner(Protocol):
    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
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
    ) -> ReActActionProposal:
        _ = (system_prompt, context_summary)
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
    ) -> ReActActionProposal:
        request = ModelRequest(
            provider=self.model_provider.provider_name,
            model=self.model_provider.model_name,
            messages=(
                ModelMessage(role=ModelRole.SYSTEM, content=_planner_control_prompt()),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        {
                            "question": question,
                            "system_prompt_summary": system_prompt,
                            "context_summary": context_summary,
                            "allowed_actions": [
                                action.value
                                for action in _INITIAL_PLANNER_ACTION_TYPES
                            ],
                        },
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
        proposal = parse_model_contract(
            content=response.content,
            contract_type=ReActActionProposal,
            role="react_planner",
        )
        return _validate_planner_proposal(proposal)


def _planner_control_prompt() -> str:
    return (
        "You are the Proof Agent LLM ReAct Planner. "
        "Return exactly one JSON object matching ReActActionProposal. "
        "Use only allowed action_type values supplied in the user message. "
        "Do not return chain-of-thought, markdown commentary, tool results, or natural language. "
        "A proposed action is not approved and cannot execute until Harness policy admits it."
    )


def _validate_planner_proposal(
    proposal: ReActActionProposal,
) -> ReActActionProposal:
    if proposal.action_type not in _INITIAL_PLANNER_ACTION_TYPE_SET:
        raise _planner_semantic_error(
            f"unsupported initial planner action: {proposal.action_type.value}."
        )

    if proposal.reasoning_summary.selected_action != proposal.action_type:
        raise _planner_semantic_error(
            "selected_action must match action_type."
        )

    if proposal.action_type not in proposal.reasoning_summary.candidate_actions:
        raise _planner_semantic_error(
            "action_type must appear in candidate_actions."
        )

    if (
        proposal.action_type == ReActActionType.PLAN_RETRIEVAL
        and not proposal.parameters.get("query")
    ):
        raise _planner_semantic_error("plan_retrieval requires parameters.query.")

    if (
        proposal.action_type == ReActActionType.PROPOSE_TOOL_CALL
        and not proposal.target_tool_name
    ):
        raise _planner_semantic_error("propose_tool_call requires target_tool_name.")

    if (
        proposal.action_type == ReActActionType.ASK_CLARIFICATION
        and not proposal.parameters.get("missing_fields")
    ):
        raise _planner_semantic_error(
            "ask_clarification requires parameters.missing_fields."
        )

    return proposal


def _planner_semantic_error(message: str) -> ModelOutputNormalizationError:
    return ModelOutputNormalizationError(
        role="react_planner",
        error_code="model_output_contract_validation_failed",
        message=message,
        raw_content_length=0,
    )


def _deterministic_query(question: str) -> str:
    if question == "What is the reimbursement rule for travel meals?":
        return "travel meals reimbursement rule"
    return question


def resolve_react_planner(config: ReActPlannerConfig) -> ReActPlanner:
    if config.provider == "deterministic":
        return DeterministicReActPlanner()
    return LLMReActPlanner(config=config)
