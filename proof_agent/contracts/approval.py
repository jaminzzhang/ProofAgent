from __future__ import annotations

from enum import Enum

from proof_agent.contracts._base import FrozenModel


class ApprovalStatus(str, Enum):
    REQUESTED = "requested"
    GRANTED = "granted"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class ApprovalState(FrozenModel):
    run_id: str
    approval_id: str
    state: ApprovalStatus
    tool_name: str
    requested_at: str
    expires_at: str
    reason: str
    trace_event_id: str
    terminal_trace_event_id: str | None = None
