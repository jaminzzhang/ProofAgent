import json
from pathlib import Path

from proof_agent.audit.receipt import generate_receipt


def test_receipt_renders_successful_model_usage(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    _write_trace(
        trace_path,
        [
            {
                "run_id": "run_model_success",
                "timestamp": "2026-05-10T00:00:00Z",
                "event_type": "run_started",
                "status": "ok",
                "payload": {},
                "redaction": {"fields": []},
            },
            {
                "run_id": "run_model_success",
                "timestamp": "2026-05-10T00:00:01Z",
                "event_type": "model_request",
                "status": "ok",
                "payload": {
                    "provider": "openai_compatible",
                    "model": "gpt-test",
                    "message_count": 2,
                    "estimated_tokens": 128,
                    "stream": False,
                    "cost_class": "remote",
                },
                "redaction": {"fields": []},
            },
            {
                "run_id": "run_model_success",
                "timestamp": "2026-05-10T00:00:02Z",
                "event_type": "model_response",
                "status": "ok",
                "payload": {
                    "provider": "openai_compatible",
                    "model": "gpt-test",
                    "finish_reason": "stop",
                    "content_length": 42,
                    "token_usage": {
                        "input_tokens": 111,
                        "output_tokens": 22,
                        "total_tokens": 133,
                    },
                },
                "redaction": {"fields": []},
            },
            {
                "run_id": "run_model_success",
                "timestamp": "2026-05-10T00:00:03Z",
                "event_type": "final_output",
                "status": "ok",
                "payload": {
                    "agent_name": "enterprise_qa",
                    "question": "Question?",
                    "outcome": "ANSWERED_WITH_CITATIONS",
                },
                "redaction": {"fields": []},
            },
        ],
    )

    generate_receipt(trace_path, receipt_path)

    receipt = receipt_path.read_text(encoding="utf-8")
    assert "## Model Usage" in receipt
    assert "| Provider | openai_compatible |" in receipt
    assert "| Model | gpt-test |" in receipt
    assert "| Estimated Tokens | 128 |" in receipt
    assert "| Total Tokens | 133 |" in receipt
    assert "| Status | ok |" in receipt


def test_receipt_renders_model_error_for_auditing(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    _write_trace(
        trace_path,
        [
            {
                "run_id": "run_model_error",
                "timestamp": "2026-05-10T00:00:00Z",
                "event_type": "run_started",
                "status": "ok",
                "payload": {},
                "redaction": {"fields": []},
            },
            {
                "run_id": "run_model_error",
                "timestamp": "2026-05-10T00:00:01Z",
                "event_type": "model_error",
                "status": "error",
                "payload": {
                    "provider": "openai_compatible",
                    "model": "gpt-test",
                    "error_code": "PA_MODEL_003",
                    "error_class": "ProofAgentError",
                    "retryable": False,
                    "message": "missing API key environment variable: OPENAI_API_KEY",
                },
                "redaction": {"fields": []},
            },
            {
                "run_id": "run_model_error",
                "timestamp": "2026-05-10T00:00:02Z",
                "event_type": "final_output",
                "status": "blocked",
                "payload": {
                    "agent_name": "enterprise_qa",
                    "question": "Question?",
                    "outcome": "REFUSED_NO_EVIDENCE",
                },
                "redaction": {"fields": []},
            },
        ],
    )

    generate_receipt(trace_path, receipt_path)

    receipt = receipt_path.read_text(encoding="utf-8")
    assert "| Status | error |" in receipt
    assert "| Error Code | PA_MODEL_003 |" in receipt
    assert "| Error Class | ProofAgentError |" in receipt


def _write_trace(trace_path: Path, events: list[dict[str, object]]) -> None:
    trace_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events),
        encoding="utf-8",
    )
