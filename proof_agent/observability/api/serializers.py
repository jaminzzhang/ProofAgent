"""Contract-to-response serialization for the dashboard API.

Converts frozen Pydantic contract models into JSON-friendly dicts
suitable for FastAPI response models.  Keeps API response shapes
decoupled from internal contract evolution.
"""

from __future__ import annotations

from typing import Any

from proof_agent.contracts.dashboard import DashboardEvidenceChunk, RunDetail, RunSummary


def serialize_dashboard_evidence_chunk(
    chunk: DashboardEvidenceChunk,
) -> dict[str, Any]:
    """Convert a typed, content-free evidence projection to plain JSON data."""

    return chunk.model_dump(mode="json")


def serialize_run_summary(summary: RunSummary) -> dict[str, Any]:
    """Convert a RunSummary contract into an API response dict."""
    return {
        "run_id": summary.run_id,
        "question": summary.question,
        "outcome": summary.outcome.value,
        "run_purpose": summary.run_purpose.value,
        "agent_id": summary.agent_id,
        "agent_version_id": summary.agent_version_id,
        "draft_id": summary.draft_id,
        "validation_capture_id": summary.validation_capture_id,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "approval_status": summary.approval_status.value if summary.approval_status else None,
        "error_code": summary.error_code,
    }


def serialize_run_detail(detail: RunDetail) -> dict[str, Any]:
    """Convert a RunDetail contract into an API response dict."""
    return {
        "run_id": detail.run_id,
        "question": detail.question,
        "outcome": detail.outcome.value,
        "run_purpose": detail.run_purpose.value,
        "agent_id": detail.agent_id,
        "agent_version_id": detail.agent_version_id,
        "draft_id": detail.draft_id,
        "validation_capture_id": detail.validation_capture_id,
        "created_at": detail.created_at,
        "updated_at": detail.updated_at,
        "approval_status": detail.approval_status.value if detail.approval_status else None,
        "error_code": detail.error_code,
        "trace_events": list(detail.trace_events),
        "receipt_markdown": detail.receipt_markdown,
        "evidence_chunks": [
            serialize_dashboard_evidence_chunk(chunk) for chunk in detail.evidence_chunks
        ],
        "citation_refs": list(detail.citation_refs),
        "policy_decisions": list(detail.policy_decisions),
        "model_usage": detail.model_usage,
        "approval_state": detail.approval_state,
        "pending_approvals": list(detail.pending_approvals),
        "governance_details": detail.governance_details,
        "workflow_projection": detail.workflow_projection.model_dump(mode="json"),
    }
