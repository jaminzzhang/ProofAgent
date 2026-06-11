from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, cast

from proof_agent.contracts import ApprovalState, ApprovalStatus, PendingApproval, PolicyDecisionType


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


def create_pending_approval(
    *,
    approval_state: ApprovalState,
    thread_id: str,
    action_id: str,
    parameters: Mapping[str, Any],
    policy_decision: PolicyDecisionType,
    checkpoint_id: str,
) -> PendingApproval:
    """Create the durable approval-waiting continuation snapshot."""

    return PendingApproval(
        run_id=approval_state.run_id,
        thread_id=thread_id,
        approval_id=approval_state.approval_id,
        action_id=action_id,
        tool_name=approval_state.tool_name,
        parameters=parameters,
        policy_decision=policy_decision,
        checkpoint_id=checkpoint_id,
        status=approval_state.state,
        created_at=approval_state.requested_at,
        expires_at=approval_state.expires_at,
    )


def pending_approval_payload(pending: PendingApproval) -> dict[str, Any]:
    """Return a plain JSON-compatible PendingApproval payload."""

    return cast(dict[str, Any], _jsonable(pending.model_dump(warnings=False)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
