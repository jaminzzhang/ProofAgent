from __future__ import annotations

from enum import Enum
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FrozenDict(Mapping[str, Any]):
    def __init__(self, items: Mapping[str, Any] | None = None) -> None:
        self._data = dict(items or {})

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return repr(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return False


def freeze_value(value: Any) -> Any:
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict({str(key): freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze_value(item) for item in value)
    return value


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class PolicyDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    ESCALATE = "escalate"


class EnforcementPoint(str, Enum):
    BEFORE_RETRIEVAL = "before_retrieval"
    BEFORE_ANSWER = "before_answer"
    BEFORE_TOOL_CALL = "before_tool_call"
    BEFORE_MEMORY_WRITE = "before_memory_write"


class ReceiptOutcome(str, Enum):
    ANSWERED_WITH_CITATIONS = "ANSWERED_WITH_CITATIONS"
    REFUSED_NO_EVIDENCE = "REFUSED_NO_EVIDENCE"
    ESCALATED_WEAK_EVIDENCE = "ESCALATED_WEAK_EVIDENCE"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    TOOL_APPROVAL_DENIED = "TOOL_APPROVAL_DENIED"
    FAILED_WITH_TRACE = "FAILED_WITH_TRACE"
    FAILED_RECEIPT_UNAVAILABLE = "FAILED_RECEIPT_UNAVAILABLE"


class EvidenceStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ApprovalStatus(str, Enum):
    REQUESTED = "requested"
    GRANTED = "granted"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class ValidationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class TraceEventType(str, Enum):
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
    FINAL_OUTPUT = "final_output"
    REDACTION_APPLIED = "redaction_applied"
    ARTIFACT_WRITTEN = "artifact_written"
    RUN_FAILED = "run_failed"


class WorkflowConfig(FrozenModel):
    runtime: str
    template: str


class KnowledgeConfig(FrozenModel):
    provider: str
    path: Path


class ModelConfig(FrozenModel):
    provider: str
    name: str


class PolicyConfig(FrozenModel):
    file: Path


class ToolsConfig(FrozenModel):
    file: Path


class MemoryConfig(FrozenModel):
    provider: str


class AuditConfig(FrozenModel):
    trace: Path
    receipt: Path


class AgentManifest(FrozenModel):
    name: str
    purpose: str
    workflow: WorkflowConfig
    knowledge: KnowledgeConfig
    model: ModelConfig
    policy: PolicyConfig
    tools: ToolsConfig
    memory: MemoryConfig
    audit: AuditConfig


class PolicyRule(FrozenModel):
    rule_id: str
    enforcement_point: EnforcementPoint
    condition: Mapping[str, Any]
    decision: Mapping[str, Any]
    reason_template: str

    @field_validator("condition", "decision", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        return freeze_value(value)


class PolicyDecision(FrozenModel):
    decision: PolicyDecisionType
    enforcement_point: EnforcementPoint
    reason: str
    policy_rule_id: str
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    trace_event_id: str

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class EvidenceChunk(FrozenModel):
    source: str
    content: str
    score: float
    status: EvidenceStatus


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


class TraceEvent(FrozenModel):
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


class ToolRequest(FrozenModel):
    tool_name: str
    action: str
    parameters: Mapping[str, Any]
    risk_level: str
    requested_by_node: str
    requires_approval: bool

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(cls, value: Any) -> Any:
        return freeze_value(value)


class ValidationResult(FrozenModel):
    validator_name: str
    status: ValidationStatus
    reason: str
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class WorkflowState(FrozenModel):
    run_id: str
    workflow_name: str
    current_node: str
    question: str
    evidence: tuple[EvidenceChunk, ...] = Field(default_factory=tuple)
    policy_decisions: tuple[PolicyDecision, ...] = Field(default_factory=tuple)
    tool_requests: tuple[ToolRequest, ...] = Field(default_factory=tuple)
    approval_state: ApprovalState | None = None
    memory_writes: tuple[Mapping[str, Any], ...] = Field(default_factory=tuple)
    final_output: str | None = None

    @field_validator("memory_writes", mode="after")
    @classmethod
    def freeze_memory_writes(cls, value: Any) -> Any:
        return freeze_value(value)


class RunResult(FrozenModel):
    final_output: str
    outcome: ReceiptOutcome
    trace_path: Path
    receipt_path: Path
