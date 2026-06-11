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

    def fake_run_with_langgraph(agent_yaml, *, question, runs_dir):
        calls.append((agent_yaml, question, runs_dir))
        return RunResult(
            final_output="Governed answer",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            trace_path=tmp_path / "trace.jsonl",
            receipt_path=tmp_path / "governance_receipt.md",
        )

    monkeypatch.setattr(
        "proof_agent.evaluation.compare.harness_rag.run_with_langgraph",
        fake_run_with_langgraph,
    )

    result = run_harness_rag("What is the reimbursement rule for travel meals?")

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert result.message == "Governed answer"
    assert calls
