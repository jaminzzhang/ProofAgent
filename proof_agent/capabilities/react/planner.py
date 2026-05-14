from __future__ import annotations

from typing import Protocol

from proof_agent.contracts import ReActActionProposal, ReActActionType, ReasoningSummary
from proof_agent.contracts.manifest import ReActPlannerConfig
from proof_agent.errors import ProofAgentError


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


def _deterministic_query(question: str) -> str:
    if question == "What is the reimbursement rule for travel meals?":
        return "travel meals reimbursement rule"
    return question


def resolve_react_planner(config: ReActPlannerConfig) -> ReActPlanner:
    if config.provider == "deterministic":
        return DeterministicReActPlanner()

    raise ProofAgentError(
        "PA_REACT_001",
        f"Unsupported ReAct planner provider: {config.provider}",
        "Set react.planner.provider to 'deterministic' or install a supported ReAct planner provider.",
    )
