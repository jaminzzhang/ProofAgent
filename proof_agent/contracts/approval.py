from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.policy import PolicyDecisionType


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


class PendingApproval(FrozenModel):
    """Durable governance snapshot for an approval-waiting workflow continuation."""

    run_id: str
    thread_id: str
    approval_id: str
    action_id: str
    tool_name: str
    parameters: Mapping[str, Any] = Field(default_factory=FrozenDict)
    policy_decision: PolicyDecisionType
    checkpoint_id: str
    status: ApprovalStatus
    created_at: str
    expires_at: str

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(cls, value: Any) -> Any:
        return freeze_value(value)
