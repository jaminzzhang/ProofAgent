from pathlib import Path

from proof_agent.audit.receipt import generate_receipt


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
