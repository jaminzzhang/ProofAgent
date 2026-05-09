from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_receipt(trace_path: Path, receipt_path: Path) -> None:
    events = _read_trace_events(trace_path)
    context = _build_context(events, trace_path=trace_path, receipt_path=receipt_path)
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("governance_receipt.md.j2")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(template.render(context), encoding="utf-8")


def _read_trace_events(trace_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _build_context(
    events: list[dict[str, Any]], *, trace_path: Path, receipt_path: Path
) -> dict[str, Any]:
    first = events[0] if events else {}
    final = next((event for event in reversed(events) if event["event_type"] == "final_output"), {})
    final_payload = final.get("payload", {})
    policy_events = [event for event in events if event["event_type"] == "policy_decision"]
    evidence_events = [event for event in events if event["event_type"] == "evidence_evaluation"]
    tool_events = [
        event
        for event in events
        if event["event_type"] in {"tool_request", "tool_result", "approval_requested"}
    ]
    memory_events = [event for event in events if event["event_type"].startswith("memory_")]
    redacted_fields = [
        field
        for event in events
        for field in event.get("redaction", {}).get("fields", [])
    ]

    return {
        "run_id": final.get("run_id") or first.get("run_id", "unknown"),
        "timestamp": final.get("timestamp") or first.get("timestamp", "unknown"),
        "agent_name": final_payload.get("agent_name", "unknown"),
        "question": final_payload.get("question", "unknown"),
        "final_outcome": final_payload.get("outcome", "unknown"),
        "policy_events": policy_events,
        "evidence_events": evidence_events,
        "tool_events": tool_events,
        "memory_events": memory_events,
        "trace_path": trace_path,
        "receipt_path": receipt_path,
        "redacted_fields": redacted_fields,
    }
