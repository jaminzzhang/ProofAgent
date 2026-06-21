from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_receipt(trace_path: Path, receipt_path: Path) -> None:
    """Render the human-readable Governance Receipt from the machine trace."""

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
    """Group raw trace events into the sections expected by the receipt template."""

    first = events[0] if events else {}
    final = next((event for event in reversed(events) if event["event_type"] == "final_output"), {})
    final_payload = final.get("payload", {})
    policy_events = [event for event in events if event["event_type"] == "policy_decision"]
    evidence_events = [event for event in events if event["event_type"] == "evidence_evaluation"]
    retrieval_events = [
        event
        for event in events
        if event["event_type"] in {"retrieval_plan", "retrieval_step", "retrieval_result"}
    ]
    tool_events = [
        event
        for event in events
        if event["event_type"] in {"tool_request", "tool_result", "approval_requested"}
    ]
    memory_events = [event for event in events if event["event_type"].startswith("memory_")]
    intent_resolution_events = _events_by_type(events, {"intent_resolution"})
    reasoning_summary_events = _events_by_type(events, {"reasoning_summary"})
    action_proposal_events = _events_by_type(events, {"action_proposal"})
    review_events = _events_by_type(
        events,
        {"review_requested", "review_decision", "review_error", "review_overridden"},
    )
    clarification_events = _events_by_type(events, {"clarification_requested"})
    business_flow_skill_pack_admission = _extract_business_flow_skill_pack_admission(
        events
    )
    business_flow_stage_context_applications = (
        _extract_business_flow_stage_context_applications(events)
    )
    model_usage = _extract_model_usage(events)
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
        "evidence_summaries": _extract_evidence_summaries(evidence_events),
        "retrieval_events": retrieval_events,
        "tool_events": tool_events,
        "tool_result_summaries": _extract_tool_result_summaries(tool_events),
        "memory_events": memory_events,
        "intent_resolution_events": intent_resolution_events,
        "reasoning_summary_events": reasoning_summary_events,
        "action_proposal_events": action_proposal_events,
        "review_events": review_events,
        "clarification_events": clarification_events,
        "business_flow_skill_pack_admission": business_flow_skill_pack_admission,
        "business_flow_stage_context_applications": (
            business_flow_stage_context_applications
        ),
        "model_usage": model_usage,
        "trace_path": trace_path,
        "receipt_path": receipt_path,
        "redacted_fields": redacted_fields,
    }


def _extract_business_flow_skill_pack_admission(
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    event = _last_event(events, "business_flow_skill_pack_admission")
    if event is None:
        return None
    payload = event.get("payload", {})
    candidate_packs: list[dict[str, str]] = []
    raw_candidate_packs = payload.get("candidate_packs")
    if isinstance(raw_candidate_packs, list | tuple):
        for item in raw_candidate_packs:
            if not isinstance(item, dict):
                continue
            candidate_packs.append(
                {
                    "pack_id": _audit_value(item.get("pack_id")),
                    "confidence": _audit_value(item.get("confidence")),
                    "reason": _audit_value(item.get("reason")),
                }
            )
    return {
        "decision": _audit_value(payload.get("decision")),
        "selected_pack_id": _audit_value(payload.get("selected_pack_id")),
        "recommendation_type": _audit_value(payload.get("recommendation_type")),
        "route_confidence": _audit_value(payload.get("route_confidence")),
        "candidate_count": _audit_value(payload.get("candidate_count")),
        "candidate_packs": candidate_packs,
        "failure_reason": _audit_value(payload.get("failure_reason")),
        "recommendation_id": _audit_value(payload.get("recommendation_id")),
        "intent_resolution_id": _audit_value(payload.get("intent_resolution_id")),
    }


def _extract_business_flow_stage_context_applications(
    events: list[dict[str, Any]],
) -> list[dict[str, str]]:
    applications: list[dict[str, str]] = []
    for event in events:
        if event.get("event_type") != "workflow_stage_context_applied":
            continue
        payload = event.get("payload", {})
        if payload.get("context_source") != "business_flow_skill_pack":
            continue
        applications.append(
            {
                "stage_id": _audit_value(payload.get("stage_id")),
                "business_flow_skill_pack_id": _audit_value(
                    payload.get("business_flow_skill_pack_id")
                ),
                "prompt_fields": _join_audit_values(payload.get("prompt_fields")),
                "context_options": _join_audit_values(payload.get("context_options")),
                "business_context_length": _audit_value(
                    payload.get("business_context_length")
                ),
                "task_instruction_count": _audit_value(
                    payload.get("task_instruction_count")
                ),
                "redaction_applied": _audit_value(payload.get("redaction_applied")),
            }
        )
    return applications


def _extract_model_usage(events: list[dict[str, Any]]) -> dict[str, str] | None:
    """Normalize model trace events into one receipt-friendly audit section."""

    request = _last_event(events, "model_request")
    response = _last_event(events, "model_response")
    error = _last_event(events, "model_error")
    if request is None and response is None and error is None:
        return None

    request_payload = request.get("payload", {}) if request else {}
    response_payload = response.get("payload", {}) if response else {}
    error_payload = error.get("payload", {}) if error else {}
    token_usage = response_payload.get("token_usage") or {}
    source_payload = error_payload or response_payload or request_payload
    status = "error" if error else (response or request or {}).get("status", "unknown")

    return {
        "provider": _audit_value(source_payload.get("provider")),
        "model": _audit_value(source_payload.get("model")),
        "status": _audit_value(status),
        "message_count": _audit_value(request_payload.get("message_count")),
        "estimated_tokens": _audit_value(request_payload.get("estimated_tokens")),
        "stream": _audit_value(request_payload.get("stream")),
        "cost_class": _audit_value(request_payload.get("cost_class")),
        "finish_reason": _audit_value(response_payload.get("finish_reason")),
        "content_length": _audit_value(response_payload.get("content_length")),
        "input_tokens": _audit_value(token_usage.get("input_tokens")),
        "output_tokens": _audit_value(token_usage.get("output_tokens")),
        "total_tokens": _audit_value(token_usage.get("total_tokens")),
        "error_code": _audit_value(error_payload.get("error_code")),
        "error_class": _audit_value(error_payload.get("error_class")),
        "retryable": _audit_value(error_payload.get("retryable")),
    }


def _extract_tool_result_summaries(
    events: list[dict[str, Any]],
) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for event in events:
        if event.get("event_type") != "tool_result":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, Mapping):
            continue
        summaries.append(
            {
                "tool_contract_id": _audit_value(
                    payload.get("tool_contract_id") or payload.get("tool_name")
                ),
                "provider": _audit_value(payload.get("provider")),
                "tool_source_id": _audit_value(payload.get("tool_source_id")),
                "mcp_tool_name": _audit_value(payload.get("mcp_tool_name")),
                "classification": _audit_value(payload.get("result_classification")),
                "schema_validation": _audit_value(
                    payload.get("result_schema_validation")
                ),
                "contract_snapshot_digest": _audit_value(
                    payload.get("contract_snapshot_digest")
                ),
                "side_effect_class": _audit_value(payload.get("side_effect_class")),
                "idempotency_key_digest": _audit_value(
                    payload.get("idempotency_key_digest")
                ),
                "summary": _format_tool_result_summary(
                    payload.get("summary"),
                    payload.get("summary_fields"),
                ),
            }
        )
    return summaries


def _format_tool_result_summary(summary: Any, summary_fields: Any) -> str:
    if not isinstance(summary, Mapping):
        return "n/a"
    fields = summary_fields if isinstance(summary_fields, list | tuple) else summary.keys()
    items = [
        f"{field}={_audit_value(summary.get(field))}"
        for field in fields
        if field in summary
    ]
    return "; ".join(items) or "n/a"


def _extract_evidence_summaries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in reversed(events):
        evidence = event.get("payload", {}).get("metadata", {}).get("evidence")
        if isinstance(evidence, list | tuple):
            return [dict(item) for item in evidence if isinstance(item, dict)]
    return []


def _last_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    return next(
        (event for event in reversed(events) if event.get("event_type") == event_type),
        None,
    )


def _events_by_type(
    events: list[dict[str, Any]],
    event_types: set[str],
) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event_type") in event_types]


def _audit_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _join_audit_values(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value) or "n/a"
    return _audit_value(value)
