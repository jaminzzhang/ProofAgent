from pathlib import Path

from proof_agent.observability.audit.receipt import generate_receipt
from proof_agent.runtime.langgraph_runner import run_with_langgraph


def test_receipt_contains_required_sections(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    trace_path.write_text(
        '{"schema_version":"trace.v1","run_id":"run_test","event_id":"evt_0001","sequence":1,"timestamp":"2026-05-09T00:00:00Z","event_type":"final_output","span_id":"span_final","parent_span_id":null,"status":"ok","payload":{"agent_name":"enterprise_qa","question":"What is the travel meal rule?","outcome":"ANSWERED_WITH_CITATIONS"},"redaction":{"applied":false,"fields":[]}}\n',
        encoding="utf-8",
    )
    generate_receipt(trace_path, receipt_path)
    text = receipt_path.read_text(encoding="utf-8")
    assert "# Governance Receipt" in text
    assert "Final Outcome" in text


def test_receipt_renders_evidence_summary_without_raw_content(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    trace_path.write_text(
        "\n".join(
            [
                '{"schema_version":"trace.v1","run_id":"run_test","event_id":"evt_0001","sequence":1,"timestamp":"2026-05-09T00:00:00Z","event_type":"evidence_evaluation","span_id":"span_evidence","parent_span_id":null,"status":"ok","payload":{"validator_name":"evidence","status":"passed","metadata":{"evidence":[{"source":"policy://travel#meals","citation":"travel-policy.md#meals:L10-L18","score":0.84,"status":"accepted"}]}},"redaction":{"applied":false,"fields":[]}}',
                '{"schema_version":"trace.v1","run_id":"run_test","event_id":"evt_0002","sequence":2,"timestamp":"2026-05-09T00:00:01Z","event_type":"final_output","span_id":"span_final","parent_span_id":null,"status":"ok","payload":{"agent_name":"enterprise_qa","question":"What is the travel meal rule?","outcome":"ANSWERED_WITH_CITATIONS","message":"Travel meals require receipts."},"redaction":{"applied":false,"fields":[]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    generate_receipt(trace_path, receipt_path)
    text = receipt_path.read_text(encoding="utf-8")

    assert "policy://travel#meals" in text
    assert "travel-policy.md#meals:L10-L18" in text
    assert "Travel meals require receipts." not in text


def test_receipt_renders_react_review_sections(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")

    assert "## ReAct Reasoning Summary" in receipt
    assert "## Auto Review" in receipt
    assert "raw chain-of-thought" not in receipt.lower()


def test_receipt_renders_actionable_react_clarification(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"),
        question="Can this customer claim it?",
        runs_dir=tmp_path,
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")
    clarification_section = receipt.split("## Clarification", maxsplit=1)[1].split(
        "\n## ",
        maxsplit=1,
    )[0].strip()

    assert "## Clarification" in receipt
    assert any(
        detail in receipt
        for detail in ("customer_id", "policy_id", "claim_type", "Please provide")
    )
    assert clarification_section != "- waiting"
