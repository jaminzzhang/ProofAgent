from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from proof_agent.contracts import (
    ModelConfig,
    ModelRequest,
    ModelResponse,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
)
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


def test_llm_planner_and_reviewer_calls_emit_safe_model_events(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["react"]["planner"]["provider"] = "openai_compatible"
    manifest["react"]["planner"]["name"] = "planner-test"
    manifest["review"]["subagent"]["provider"] = "openai_compatible"
    manifest["review"]["subagent"]["name"] = "reviewer-test"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    provider = FakeControlPlaneProvider(sentinel)

    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.resolve_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        "proof_agent.capabilities.review.subagent.resolve_provider",
        lambda config: provider,
    )

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    payloads = [event["payload"] for event in events]
    assert sentinel not in json.dumps(payloads, sort_keys=True)

    request_roles = [
        event["payload"]["role"]
        for event in events
        if event["event_type"] == "model_request"
    ]
    response_roles = [
        event["payload"].get("role")
        for event in events
        if event["event_type"] == "model_response"
    ]
    assert "react_planner" in request_roles
    assert "harness_review" in request_roles
    assert "react_planner" in response_roles
    assert "harness_review" in response_roles
    for event in events:
        if (
            event["event_type"] == "model_request"
            and event["payload"]["role"] in {"react_planner", "harness_review"}
        ):
            assert "messages" not in event["payload"]
            assert "content" not in event["payload"]
        if (
            event["event_type"] == "model_response"
            and event["payload"].get("role") in {"react_planner", "harness_review"}
        ):
            assert "messages" not in event["payload"]
            assert "content" not in event["payload"]


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
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"

    def invalid_plan(self: object, **kwargs: object) -> ReActActionProposal:
        from proof_agent.capabilities.models.normalization import (
            ModelOutputNormalizationError,
        )

        raise ModelOutputNormalizationError(
            role="react_planner",
            error_code="model_output_json_parse_failed",
            message=f"Model output did not contain a valid JSON object: {sentinel}",
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
    assert sentinel not in json.dumps(
        [event["payload"] for event in events],
        sort_keys=True,
    )
    failure = next(
        event
        for event in events
        if event["event_type"] == "model_output_normalization_failed"
    )
    assert failure["payload"]["role"] == "react_planner"
    assert failure["payload"]["error_code"] == "model_output_json_parse_failed"


def test_review_normalization_failure_fails_closed_with_trace(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"

    def invalid_review(self: object, **kwargs: object) -> None:
        from proof_agent.capabilities.models.normalization import (
            ModelOutputNormalizationError,
        )

        raise ModelOutputNormalizationError(
            role="harness_review",
            error_code="model_output_json_parse_failed",
            message=f"Model output did not contain a valid JSON object: {sentinel}",
            raw_content_length=29,
        )

    monkeypatch.setattr(
        "proof_agent.capabilities.review.subagent.DeterministicHarnessReviewSubagent.review",
        invalid_review,
    )

    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"

    events = _trace_events(result.trace_path)
    assert sentinel not in json.dumps(
        [event["payload"] for event in events],
        sort_keys=True,
    )
    failure = next(
        event
        for event in events
        if event["event_type"] == "model_output_normalization_failed"
    )
    assert failure["payload"]["role"] == "harness_review"
    assert failure["payload"]["error_code"] == "model_output_json_parse_failed"
    assert failure["payload"]["enforcement_point"] == "before_retrieval_plan"
    review_error = next(event for event in events if event["event_type"] == "review_error")
    assert review_error["payload"]["error_code"] == "model_output_json_parse_failed"
    policy = next(
        event
        for event in events
        if event["event_type"] == "policy_decision"
        and event["payload"]["policy_rule_id"].endswith(".fail_closed")
    )
    assert policy["payload"]["decision"] == "deny"


class FakeControlPlaneProvider:
    provider_name = "openai_compatible"
    model_name = "control-plane-test"

    def __init__(self, sentinel: str) -> None:
        self.sentinel = sentinel
        self.requests: list[ModelRequest] = []

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> "FakeControlPlaneProvider":
        _ = model_config
        return cls("RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE")

    def estimate_tokens(self, request: ModelRequest) -> int:
        return max(1, sum(len(message.content) for message in request.messages) // 4)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        role = request.metadata["role"]
        if role == "react_planner":
            content = json.dumps(
                {
                    "action_id": "act_llm_1",
                    "action_type": "plan_retrieval",
                    "reasoning_summary": {
                        "goal": self.sentinel,
                        "observations": [self.sentinel],
                        "candidate_actions": ["plan_retrieval"],
                        "selected_action": "plan_retrieval",
                        "rationale_summary": self.sentinel,
                        "risk_flags": [self.sentinel],
                        "required_evidence": [self.sentinel],
                    },
                    "parameters": {
                        "query": " travel meal reimbursement rule ",
                        "raw_output": self.sentinel,
                    },
                    "target_tool_name": None,
                    "risk_level": "low",
                }
            )
        elif role == "harness_review":
            point = str(request.metadata["enforcement_point"])
            action_id = str(request.metadata["subject_action_id"])
            content = json.dumps(
                {
                    "review_id": self.sentinel,
                    "enforcement_point": point,
                    "suggested_decision": "allow",
                    "reason": self.sentinel,
                    "confidence": 0.8,
                    "risk_flags": [self.sentinel],
                    "subject_action_id": action_id,
                    "metadata": {"raw_output": self.sentinel},
                }
            )
        else:
            raise AssertionError(f"unexpected role: {role}")
        return ModelResponse(
            content=content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )
