from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from proof_agent.contracts import ReActActionProposal, ReActActionType, ReasoningSummary
from proof_agent.runtime.langgraph_runner import run_with_langgraph


REACT_AGENT = Path("examples/react_enterprise_qa/agent.yaml")


def _trace_events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _event_types(events: list[dict[str, Any]]) -> list[str]:
    return [event["event_type"] for event in events]


def test_supported_travel_meal_question_answers_with_react_review_trace(
    tmp_path: Path,
) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert "Travel meals are reimbursed" in result.final_output

    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    for event_type in (
        "reasoning_summary",
        "action_proposal",
        "review_requested",
        "review_decision",
        "policy_decision",
    ):
        assert event_type in event_types
    assert event_types.index("review_decision") < event_types.index("policy_decision")
    review_points = {
        event["payload"]["enforcement_point"]
        for event in events
        if event["event_type"] == "review_requested"
    }
    assert "before_retrieval_step" in review_points
    assert event_types.count("policy_decision") == 4
    assert "model_request" in event_types
    assert "model_response" in event_types


def test_unsupported_discount_question_refuses_without_evidence(tmp_path: Path) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"


def test_underspecified_customer_claim_question_requests_clarification(
    tmp_path: Path,
) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="Can this customer claim it?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "WAITING_FOR_USER_CLARIFICATION"
    assert "provide" in result.final_output.lower()
    assert "clarification_requested" in _event_types(_trace_events(result.trace_path))


def test_tool_question_waits_for_approval(tmp_path: Path) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )

    assert result.outcome == "WAITING_FOR_APPROVAL"
    assert "approval_requested" in _event_types(_trace_events(result.trace_path))


def test_unknown_tool_proposal_fails_closed_without_raising(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def propose_unknown_tool(self: object, **kwargs: object) -> ReActActionProposal:
        return ReActActionProposal(
            action_id="act_tool_unknown",
            action_type=ReActActionType.PROPOSE_TOOL_CALL,
            reasoning_summary=ReasoningSummary(
                goal="Attempt an unsafe tool proposal.",
                observations=("The planner proposed a tool outside the manifest allowlist.",),
                candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL,),
                selected_action=ReActActionType.PROPOSE_TOOL_CALL,
                rationale_summary="The runtime must validate and fail closed before tool execution.",
                risk_flags=("tool_allowlist_violation",),
                required_evidence=(),
            ),
            parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
            target_tool_name="missing_tool",
            risk_level="medium",
        )

    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.DeterministicReActPlanner.plan",
        propose_unknown_tool,
    )

    result = run_with_langgraph(
        REACT_AGENT,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "tool request was rejected" in result.final_output
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    assert "tool_request" in event_types
    assert "approval_requested" not in event_types
    assert "tool_result" not in event_types


def test_llm_planner_invalid_output_fails_closed_with_trace(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def invalid_plan(self: object, **kwargs: object) -> ReActActionProposal:
        from proof_agent.capabilities.models.normalization import (
            ModelOutputNormalizationError,
        )

        raise ModelOutputNormalizationError(
            role="react_planner",
            error_code="model_output_json_parse_failed",
            message="Model output did not contain a valid JSON object.",
            raw_content_length=31,
        )

    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.DeterministicReActPlanner.plan",
        invalid_plan,
    )

    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "planner output failed validation" in result.final_output.lower()

    events = _trace_events(result.trace_path)
    failure = next(
        event
        for event in events
        if event["event_type"] == "model_output_normalization_failed"
    )
    assert failure["payload"]["role"] == "react_planner"
    assert failure["payload"]["error_code"] == "model_output_json_parse_failed"
