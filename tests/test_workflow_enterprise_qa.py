from pathlib import Path

from proof_agent.workflow.orchestrator import run_enterprise_qa


def test_supported_question_answers_with_citations(tmp_path: Path) -> None:
    result = run_enterprise_qa(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )
    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert result.trace_path.exists()
    assert result.receipt_path.exists()


def test_unsupported_question_refuses_without_evidence(tmp_path: Path) -> None:
    result = run_enterprise_qa(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path,
    )
    assert result.outcome == "REFUSED_NO_EVIDENCE"


def test_tool_question_waits_for_approval(tmp_path: Path) -> None:
    result = run_enterprise_qa(
        Path("examples/enterprise_qa/agent.yaml"),
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )
    assert result.outcome == "WAITING_FOR_APPROVAL"


def test_tool_question_handles_denied_approval(tmp_path: Path) -> None:
    result = run_enterprise_qa(
        Path("examples/enterprise_qa/agent.yaml"),
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
        approved=False,
    )
    assert result.outcome == "TOOL_APPROVAL_DENIED"
