from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.approval import ApprovalState
from proof_agent.contracts.evidence import EvidenceChunk
from proof_agent.contracts.policy import PolicyDecision
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.tool import ToolRequest
from proof_agent.contracts.workflow_execution import (
    WorkflowTemplateExecutionInput,
    WorkflowTemplateExecutionResult,
)


class ValidationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class ValidationResult(FrozenModel):
    """Normalized validator output recorded in traces and policy metadata."""

    validator_name: str
    status: ValidationStatus
    reason: str
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class WorkflowState(FrozenModel):
    """Serializable workflow snapshot shared between orchestration nodes.

    This intentionally stores contract objects instead of framework-native state
    so that LangGraph, plain Python, or future runtimes can use the same schema.
    """

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
    """Minimal result returned to CLI commands after audit artifacts are written."""

    final_output: str
    outcome: ReceiptOutcome
    trace_path: Path
    receipt_path: Path
    workflow_template_execution_input: WorkflowTemplateExecutionInput | None = None
    workflow_template_execution_result: WorkflowTemplateExecutionResult | None = None
