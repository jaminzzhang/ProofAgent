import pytest

from proof_agent.capabilities.react import DeterministicReActPlanner, resolve_react_planner
from proof_agent.contracts import ReActActionType, ReActPlannerConfig
from proof_agent.errors import ProofAgentError


def test_deterministic_planner_plans_retrieval_for_travel_meals() -> None:
    planner = DeterministicReActPlanner()

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meals reimbursement rule"
    assert proposal.reasoning_summary.selected_action == ReActActionType.PLAN_RETRIEVAL


def test_deterministic_planner_asks_clarification_for_underspecified_claim() -> None:
    planner = DeterministicReActPlanner()

    proposal = planner.plan(
        question="Can this customer claim it?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.ASK_CLARIFICATION
    assert "missing_fields" in proposal.parameters


def test_deterministic_planner_proposes_governed_customer_policy_tool_call() -> None:
    planner = DeterministicReActPlanner()

    proposal = planner.plan(
        question="Please look up customer policy status.",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PROPOSE_TOOL_CALL
    assert proposal.target_tool_name == "customer_lookup"
    assert proposal.risk_level == "medium"
    assert proposal.parameters["customer_id"] == "CUST-001"
    assert proposal.parameters["policy_id"] == "POL-001"


def test_unsupported_react_planner_provider_raises_actionable_error() -> None:
    config = ReActPlannerConfig(provider="unsupported", name="planner")

    with pytest.raises(ProofAgentError) as exc:
        resolve_react_planner(config)

    assert exc.value.code == "PA_REACT_001"
