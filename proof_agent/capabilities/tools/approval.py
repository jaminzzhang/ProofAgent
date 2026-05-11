from __future__ import annotations

from datetime import UTC, datetime, timedelta

from proof_agent.contracts import ApprovalState, ApprovalStatus


def create_approval_state(
    *,
    run_id: str,
    approval_id: str,
    state: ApprovalStatus,
    tool_name: str,
    reason: str,
    trace_event_id: str = "",
    timeout_seconds: int = 60,
) -> ApprovalState:
    """Create a timestamped approval contract with a deterministic timeout window."""

    requested_at = datetime.now(UTC)
    expires_at = requested_at + timedelta(seconds=timeout_seconds)
    return ApprovalState(
        run_id=run_id,
        approval_id=approval_id,
        state=state,
        tool_name=tool_name,
        requested_at=requested_at.isoformat().replace("+00:00", "Z"),
        expires_at=expires_at.isoformat().replace("+00:00", "Z"),
        reason=reason,
        trace_event_id=trace_event_id,
        terminal_trace_event_id=trace_event_id if state != ApprovalStatus.REQUESTED else None,
    )
