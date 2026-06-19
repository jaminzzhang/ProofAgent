"""Controlled ReAct Loop control-unit and scaffold tests (ADR-0032 / ADR-0033).

These tests cover the pure control functions (plan budget, Convergence Check,
Action Constraint), the graph routing edges that close the loop, and the
``MockLLMSequenceProvider`` scaffold (ADR-0033 V2) that makes loop behaviour
testable under a scripted sequence of planner proposals.

End-to-end loop tests live in ``tests/test_workflow_react_enterprise_qa.py``.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from proof_agent.capabilities.react.planner import ReActPlanner
from proof_agent.contracts import (
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
)
from proof_agent.control.workflow.react_enterprise_qa import (
    compute_eligible_action_set,
    constrain_action,
    should_stop_for_plan_budget,
)
from proof_agent.runtime.react_graph import (
    loop_route_after_plan,
    loop_route_after_retrieval,
    loop_route_after_tool,
)


def _proposal(action_type: ReActActionType, *, action_id: str = "act_test") -> ReActActionProposal:
    return ReActActionProposal(
        action_id=action_id,
        action_type=action_type,
        reasoning_summary=ReasoningSummary(
            goal="Test proposal.",
            observations=(),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="test",
            risk_flags=(),
            required_evidence=(),
        ),
        parameters={},
        risk_level="low",
    )


class MockLLMSequencePlanner:
    """Scripted ReAct planner returning a fixed sequence of proposals.

    Matches the existing in-test ``FakeXxxProvider`` convention (list + clamp to
    last element when exhausted). Implements ``ReActPlanner``.
    """

    def __init__(self, proposals: list[ReActActionProposal]) -> None:
        self._proposals = list(proposals)
        self.calls: list[str] = []

    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: Mapping[str, Any] | None = None,
    ) -> ReActActionProposal:
        _ = (system_prompt, context_summary, workflow_stage_context)
        self.calls.append(question)
        index = min(len(self.calls) - 1, len(self._proposals) - 1)
        return self._proposals[index]


def test_mock_llm_sequence_planner_returns_proposals_in_order() -> None:
    """RED (slice 0): the scaffold dequeues proposals in order and clamps at the end."""

    planner: ReActPlanner = MockLLMSequencePlanner(
        [
            _proposal(ReActActionType.PLAN_RETRIEVAL, action_id="act_round_1"),
            _proposal(ReActActionType.GENERATE_FINAL_ANSWER, action_id="act_round_2"),
        ]
    )

    first = planner.plan(question="q", system_prompt="s", context_summary="c")
    second = planner.plan(question="q", system_prompt="s", context_summary="c")
    third = planner.plan(question="q", system_prompt="s", context_summary="c")

    assert first.action_id == "act_round_1"
    assert first.action_type is ReActActionType.PLAN_RETRIEVAL
    assert second.action_id == "act_round_2"
    assert second.action_type is ReActActionType.GENERATE_FINAL_ANSWER
    # Exhausted sequence clamps to the last proposal rather than raising.
    assert third.action_id == "act_round_2"
    assert len(planner.calls) == 3


@pytest.mark.parametrize(
    "plan_rounds, max_plan_rounds, expected",
    [
        (0, 4, False),
        (3, 4, False),
        (4, 4, True),
        (5, 4, True),
        (0, 0, True),
    ],
)
def test_should_stop_for_plan_budget(
    plan_rounds: int, max_plan_rounds: int, expected: bool
) -> None:
    """RED (slice 1): plan budget stops the loop once rounds reach the cap."""

    assert should_stop_for_plan_budget(plan_rounds, max_plan_rounds) is expected


def test_compute_eligible_action_set_unrestricted_when_no_signal() -> None:
    """RED (slice 2): no convergence signal returns the full plan-eligible set."""

    eligible, signal = compute_eligible_action_set(
        plan_rounds=1,
        max_plan_rounds=4,
        action_history=[],
        evidence_trajectory=[2],
    )

    assert signal is None
    assert eligible == frozenset(
        {
            ReActActionType.PLAN_RETRIEVAL,
            ReActActionType.PROPOSE_TOOL_CALL,
            ReActActionType.GENERATE_FINAL_ANSWER,
            ReActActionType.ASK_CLARIFICATION,
            ReActActionType.REFUSE,
        }
    )


def test_compute_eligible_action_set_evidence_saturation_narrows_to_terminal() -> None:
    """RED (slice 2): evidence not growing for two rounds narrows to answer/refuse."""

    eligible, signal = compute_eligible_action_set(
        plan_rounds=3,
        max_plan_rounds=4,
        action_history=[
            {"action_type": "propose_tool_call", "parameters": {"customer_id": "C1"}},
            {"action_type": "plan_retrieval", "parameters": {"query": "q1"}},
            {"action_type": "plan_retrieval", "parameters": {"query": "q2"}},
        ],
        evidence_trajectory=[2, 2, 2],
    )

    assert signal == "evidence_saturation"
    assert eligible == frozenset({ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE})


def test_compute_eligible_action_set_action_repetition_narrows_to_terminal() -> None:
    """RED (slice 2): same action twice in a row narrows to answer/refuse."""

    eligible, signal = compute_eligible_action_set(
        plan_rounds=3,
        max_plan_rounds=4,
        action_history=[
            {"action_type": "propose_tool_call", "parameters": {"customer_id": "C1"}},
            {"action_type": "propose_tool_call", "parameters": {"customer_id": "C1"}},
        ],
        evidence_trajectory=[0, 1],
    )

    assert signal == "action_repetition"
    assert eligible == frozenset({ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE})


def test_compute_eligible_action_set_hard_budget_forces_refuse() -> None:
    """RED (slice 2): plan budget exhausted forces refuse-only eligible set."""

    eligible, signal = compute_eligible_action_set(
        plan_rounds=4,
        max_plan_rounds=4,
        action_history=[],
        evidence_trajectory=[],
    )

    assert signal == "plan_budget_exhausted"
    assert eligible == frozenset({ReActActionType.REFUSE})


def test_constrain_action_keeps_in_set_proposal_unchanged() -> None:
    """RED (slice 3): a proposal inside the eligible set passes through untouched."""

    proposal = _proposal(ReActActionType.PLAN_RETRIEVAL)
    eligible = frozenset({ReActActionType.PLAN_RETRIEVAL, ReActActionType.GENERATE_FINAL_ANSWER})

    constrained, rewritten = constrain_action(proposal, eligible, convergence_signal=None)

    assert constrained is proposal
    assert rewritten is None


def test_constrain_action_rewrites_to_generate_in_convergence_context() -> None:
    """RED (slice 3): out-of-set proposal under saturation/repetition becomes GENERATE."""

    proposal = _proposal(ReActActionType.PLAN_RETRIEVAL)
    eligible = frozenset({ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE})

    constrained, rewritten = constrain_action(
        proposal, eligible, convergence_signal="evidence_saturation"
    )

    assert constrained.action_type is ReActActionType.GENERATE_FINAL_ANSWER
    assert rewritten is not None
    assert rewritten.original_action_type is ReActActionType.PLAN_RETRIEVAL
    assert rewritten.constrained_to is ReActActionType.GENERATE_FINAL_ANSWER
    assert rewritten.reason == "outside_eligible_set"


def test_constrain_action_rewrites_to_refuse_in_divergence_context() -> None:
    """RED (slice 3): out-of-set proposal under budget exhaustion becomes REFUSE."""

    proposal = _proposal(ReActActionType.PLAN_RETRIEVAL)
    eligible = frozenset({ReActActionType.REFUSE})

    constrained, rewritten = constrain_action(
        proposal, eligible, convergence_signal="plan_budget_exhausted"
    )

    assert constrained.action_type is ReActActionType.REFUSE
    assert rewritten is not None
    assert rewritten.constrained_to is ReActActionType.REFUSE


def test_constrain_action_rewrites_to_generate_when_no_signal() -> None:
    """RED (slice 3): out-of-set proposal with no signal defaults to GENERATE."""

    proposal = _proposal(ReActActionType.PROPOSE_TOOL_CALL)
    eligible = frozenset({ReActActionType.GENERATE_FINAL_ANSWER})

    constrained, rewritten = constrain_action(proposal, eligible, convergence_signal=None)

    assert constrained.action_type is ReActActionType.GENERATE_FINAL_ANSWER
    assert rewritten is not None


def _state_with_action(action_type: ReActActionType) -> dict[str, Any]:
    return {
        "action": {
            "action_id": "act_test",
            "action_type": action_type.value,
            "reasoning_summary": {
                "goal": "test",
                "observations": [],
                "candidate_actions": [action_type.value],
                "selected_action": action_type.value,
                "rationale_summary": "test",
                "risk_flags": [],
                "required_evidence": [],
            },
            "parameters": {},
            "risk_level": "low",
        }
    }


def test_loop_route_after_plan_generates_routes_to_model() -> None:
    """RED (slice 4): GENERATE_FINAL_ANSWER routes to model (terminal synthesis)."""

    state = _state_with_action(ReActActionType.GENERATE_FINAL_ANSWER)

    assert loop_route_after_plan(state) == "model"


def test_loop_route_after_plan_refuse_routes_to_end() -> None:
    """RED (slice 4): REFUSE routes to end."""

    state = _state_with_action(ReActActionType.REFUSE)

    assert loop_route_after_plan(state) == "end"


def test_loop_route_after_plan_observation_actions_route_to_review() -> None:
    """RED (slice 4): observation actions route to their review nodes, not back to plan."""

    assert (
        loop_route_after_plan(_state_with_action(ReActActionType.PLAN_RETRIEVAL))
        == "review_retrieval_plan"
    )
    assert (
        loop_route_after_plan(_state_with_action(ReActActionType.PROPOSE_TOOL_CALL))
        == "review_tool"
    )
    assert loop_route_after_plan(_state_with_action(ReActActionType.ASK_CLARIFICATION)) == "clarify"


def test_loop_route_after_retrieval_returns_to_plan() -> None:
    """RED (slice 4): retrieval success returns to plan (loop back-edge)."""

    assert loop_route_after_retrieval({}) == "plan"
    assert loop_route_after_retrieval({"governance_refusal": "REFUSED_NO_EVIDENCE"}) == "end"


def test_loop_route_after_tool_returns_to_plan() -> None:
    """RED (slice 4): tool success returns to plan (loop back-edge)."""

    assert loop_route_after_tool({}) == "plan"
    assert loop_route_after_tool({"governance_refusal": "REFUSED_NO_EVIDENCE"}) == "end"
