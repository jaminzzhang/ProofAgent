from pathlib import Path

from proof_agent.evaluation.compare.harness_rag import run_harness_rag
from proof_agent.evaluation.compare.plain_rag import run_plain_rag
from proof_agent.contracts import ReceiptOutcome, RunResult


def test_plain_and_harness_diverge_on_unsupported_question() -> None:
    question = "What discount should we give this customer next year?"
    plain = run_plain_rag(question)
    harness = run_harness_rag(question)
    assert plain.outcome == "ANSWERED_LOOSELY"
    assert harness.outcome == "REFUSED_NO_EVIDENCE"


def test_harness_compare_reuses_enterprise_workflow(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_execute_agent_package_run(request):
        calls.append((request.agent_yaml, request.question, request.runs_dir))
        return RunResult(
            final_output="Governed answer",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            trace_path=tmp_path / "trace.jsonl",
            receipt_path=tmp_path / "governance_receipt.md",
        )

    monkeypatch.setattr(
        "proof_agent.evaluation.compare.harness_rag.execute_agent_package_run",
        fake_execute_agent_package_run,
    )

    result = run_harness_rag("What is the reimbursement rule for travel meals?")

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert result.message == "Governed answer"
    assert calls


def test_harness_compare_executes_v3_agent_package() -> None:
    result = run_harness_rag(
        "What is the reimbursement rule for travel meals?",
        agent_yaml=(
            Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
        ),
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert "Travel meals" in result.message
