from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import field_validator

from proof_agent.contracts._base import FrozenModel, freeze_value


class TraceEventType(str, Enum):
    """Closed set of audit event names for trace.v1."""

    RUN_STARTED = "run_started"
    MANIFEST_LOADED = "manifest_loaded"
    POLICY_DECISION = "policy_decision"
    RETRIEVAL_STARTED = "retrieval_started"
    RETRIEVAL_RESULT = "retrieval_result"
    EVIDENCE_EVALUATION = "evidence_evaluation"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    TOOL_REQUEST = "tool_request"
    TOOL_RESULT = "tool_result"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE_REQUESTED = "memory_write_requested"
    MEMORY_WRITE_DECISION = "memory_write_decision"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    MODEL_ERROR = "model_error"
    FINAL_OUTPUT = "final_output"
    REDACTION_APPLIED = "redaction_applied"
    ARTIFACT_WRITTEN = "artifact_written"
    RUN_FAILED = "run_failed"


class TraceEvent(FrozenModel):
    """Append-only audit event persisted as one JSON object per trace line."""

    schema_version: Literal["trace.v1"] = "trace.v1"
    run_id: str
    event_id: str
    sequence: int
    timestamp: str
    event_type: TraceEventType
    span_id: str
    parent_span_id: str | None = None
    status: Literal["ok", "blocked", "waiting", "error"]
    payload: Mapping[str, Any]
    redaction: Mapping[str, Any]

    @field_validator("payload", "redaction", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        return freeze_value(value)
