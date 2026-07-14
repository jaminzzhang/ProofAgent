import json
from pathlib import Path

from proof_agent.observability.audit.trace import TraceWriter


def test_trace_writer_emits_ordered_jsonl(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    writer = TraceWriter(trace_path, run_id="run_test")
    writer.emit("run_started", status="ok", payload={"manifest_path": "agent.yaml"})
    writer.emit("final_output", status="ok", payload={"outcome": "ANSWERED_WITH_CITATIONS"})
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2]


def test_trace_writer_redacts_secret_payload(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    writer = TraceWriter(trace_path, run_id="run_test")
    writer.emit("tool_request", status="ok", payload={"access_token": "secret-token"})
    event = json.loads(trace_path.read_text(encoding="utf-8"))
    assert "secret-token" not in event["payload"].values()
    assert event["redaction"]["applied"] is True


def test_hybrid_trace_projects_counts_without_excluded_identity_or_content(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    writer = TraceWriter(trace_path, run_id="run_test")

    writer.emit(
        "hybrid_retrieval_summary",
        status="ok",
        payload={
            "binding_id": "kb_hybrid",
            "generation_id": "generation_007",
            "excluded_count": 1,
            "authority_passed_count": 2,
            "excluded_rule_unit_ids": ["rule_restricted"],
            "excluded_content": "restricted underwriting rule",
            "acl_claims": {"institution_id": "secret-institution"},
            "vendor_payload": {"hits": ["raw"]},
        },
    )

    event = json.loads(trace_path.read_text(encoding="utf-8"))
    assert event["payload"]["excluded_count"] == 1
    assert event["payload"]["authority_passed_count"] == 2
    assert "excluded_rule_unit_ids" not in event["payload"]
    assert "excluded_content" not in event["payload"]
    assert "acl_claims" not in event["payload"]
    assert "vendor_payload" not in event["payload"]
    assert set(event["redaction"]["fields"]) >= {
        "excluded_rule_unit_ids",
        "excluded_content",
        "acl_claims",
        "vendor_payload",
    }
