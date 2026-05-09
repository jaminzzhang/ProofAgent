from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    condition: dict[str, Any]
    decision: dict[str, Any]
    reason_template: str


class PolicyDecision(FrozenModel):
    decision: PolicyDecisionType
    enforcement_point: EnforcementPoint
    reason: str
    policy_rule_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    trace_event_id: str


class EvidenceChunk(FrozenModel):
    source: str
    content: str
    score: float
    status: EvidenceStatus


class ApprovalState(FrozenModel):
    state: ApprovalStatus
    tool_name: str
    reason: str
    trace_event_id: str


class TraceEvent(FrozenModel):
    schema_version: str = "trace.v1"
    run_id: str
    event_id: str
    sequence: int
    timestamp: str
    event_type: str
    span_id: str
    parent_span_id: str | None = None
    status: Literal["ok", "blocked", "waiting", "error"]
    payload: dict[str, Any]
    redaction: dict[str, Any]


class ToolRequest(FrozenModel):
    tool_name: str
    action: str
    parameters: dict[str, Any]
    risk_level: str
    requested_by_node: str
    requires_approval: bool


class ValidationResult(FrozenModel):
    validator_name: str
    status: ValidationStatus
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowState(FrozenModel):
    run_id: str
    workflow_name: str
    current_node: str
    question: str
    evidence: list[EvidenceChunk] = Field(default_factory=list)
    policy_decisions: list[PolicyDecision] = Field(default_factory=list)
    tool_requests: list[ToolRequest] = Field(default_factory=list)
    approval_state: ApprovalState | None = None
    memory_writes: list[dict[str, Any]] = Field(default_factory=list)
    final_output: str | None = None


class RunResult(FrozenModel):
    final_output: str
    outcome: ReceiptOutcome
    trace_path: Path
    receipt_path: Path

