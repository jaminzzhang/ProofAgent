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
