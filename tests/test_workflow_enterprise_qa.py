from pathlib import Path
import json

from proof_agent.runtime.langgraph_runner import run_with_langgraph


def test_supported_question_answers_with_citations(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )
    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert "Travel meals are reimbursed" in result.final_output
    assert result.trace_path.exists()
    assert result.receipt_path.exists()

    events = [
        json.loads(line)
        for line in result.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]
    assert "model_request" in event_types
    assert "model_response" in event_types


def test_unsupported_question_refuses_without_evidence(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path,
    )
    assert result.outcome == "REFUSED_NO_EVIDENCE"


def test_tool_question_waits_for_approval(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("examples/enterprise_qa/agent.yaml"),
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )
    assert result.outcome == "WAITING_FOR_APPROVAL"


def test_tool_question_handles_denied_approval(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("examples/enterprise_qa/agent.yaml"),
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
        approved=False,
    )
    assert result.outcome == "TOOL_APPROVAL_DENIED"
