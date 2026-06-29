from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.conversation import ContextAdmission
from proof_agent.contracts.evidence import EvidenceChunk
from proof_agent.contracts.react_workflow import ReActActionProposal, ReActActionType
from proof_agent.contracts.workflow_execution import WorkflowStageLlmInteraction


class ControlledReActRunPhase(str, Enum):
    """Internal phase of one Controlled ReAct Orchestrator run."""

    PLANNING = "planning"
    OBSERVING = "observing"
    WAITING = "waiting"
    TERMINAL = "terminal"


class ObservationTruthKind(str, Enum):
    """Typed truth payload variants for Observation Records."""

    RETRIEVAL = "retrieval"
    TOOL = "tool"


class ToolProposalParameterSource(str, Enum):
    """Allowed source classes for planner-visible tool proposal parameters."""

    USER_SUPPLIED = "user_supplied"
    CONTROLLED_CONTEXT = "controlled_context"
    AUTHORIZED_RESOURCE_HANDLE = "authorized_resource_handle"
    SYSTEM_GENERATED = "system_generated"
    PLANNER_LITERAL = "planner_literal"


class ToolProposalParameter(FrozenModel):
    """Planner-visible parameter projection for one tool proposal parameter."""

    name: str
    required: bool = False
    value_type: str = "string"
    value_source: ToolProposalParameterSource = ToolProposalParameterSource.USER_SUPPLIED
    description: str | None = None
    enum_values: tuple[str, ...] = Field(default_factory=tuple)


class ToolProposalInterface(FrozenModel):
    """Planner-visible tool proposal projection, without execution schemas."""

    tool_contract_id: str
    purpose: str
    risk_level: str
    read_only: bool
    requires_approval: bool
    semantic_result_summary: str | None = None
    parameters: tuple[ToolProposalParameter, ...] = Field(default_factory=tuple)
    source: str | None = None
    remaining_call_budget: int | None = None
    mcp_tool_name: str | None = None
    tool_source_id: str | None = None
    input_schema: Mapping[str, Any] = Field(default_factory=FrozenDict)
    result_schema: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("input_schema", "result_schema", mode="after")
    @classmethod
    def freeze_hidden_schema_placeholders(cls, value: Any) -> Any:
        return freeze_value(value)


class EffectiveToolProposalScope(FrozenModel):
    """Round-scoped planner-visible tool proposal scope."""

    run_id: str
    plan_round: int
    tool_interfaces: tuple[ToolProposalInterface, ...] = Field(default_factory=tuple)
    excluded: Mapping[str, Any] = Field(default_factory=FrozenDict)
    schema_digest: str

    @property
    def tool_contract_ids(self) -> tuple[str, ...]:
        return tuple(interface.tool_contract_id for interface in self.tool_interfaces)

    @field_validator("excluded", mode="after")
    @classmethod
    def freeze_excluded(cls, value: Any) -> Any:
        return freeze_value(value)


class BoundToolProposal(FrozenModel):
    """Execution-ready tool proposal after Control Plane parameter binding."""

    action_id: str
    tool_contract_id: str
    parameters: Mapping[str, Any] = Field(default_factory=FrozenDict)
    parameter_sources: Mapping[str, str] = Field(default_factory=FrozenDict)
    parameter_digest: str
    scope_digest: str | None = None

    @field_validator("parameters", "parameter_sources", mode="after")
    @classmethod
    def freeze_bound_mappings(cls, value: Any) -> Any:
        return freeze_value(value)


class ApprovedToolProposalSnapshot(FrozenModel):
    """Frozen approval object for one concrete bound tool proposal."""

    snapshot_id: str
    action_id: str
    tool_contract_id: str
    parameters: Mapping[str, Any] = Field(default_factory=FrozenDict)
    parameter_digest: str
    scope_digest: str | None = None
    policy_decision: str
    risk_level: str
    approval_reason: str

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(cls, value: Any) -> Any:
        return freeze_value(value)


class RetrievalObservationTruth(FrozenModel):
    """Full governed retrieval payload referenced by an Observation Record."""

    truth_ref: str
    observation_id: str
    action_id: str
    kind: Literal[ObservationTruthKind.RETRIEVAL] = ObservationTruthKind.RETRIEVAL
    accepted_evidence: tuple[EvidenceChunk, ...] = Field(default_factory=tuple)
    rejected_evidence_summary: Mapping[str, Any] = Field(default_factory=FrozenDict)
    admission_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    citation_refs: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("rejected_evidence_summary", "admission_metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class ToolObservationTruth(FrozenModel):
    """Full governed tool payload referenced by an Observation Record."""

    truth_ref: str
    observation_id: str
    action_id: str
    kind: Literal[ObservationTruthKind.TOOL] = ObservationTruthKind.TOOL
    tool_name: str
    authorized_result: Mapping[str, Any] = Field(default_factory=FrozenDict)
    result_schema_id: str | None = None
    approval_ref: str | None = None
    redaction_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("authorized_result", "redaction_metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


ObservationTruthArtifact = RetrievalObservationTruth | ToolObservationTruth


class AnswerEvidenceContext(FrozenModel):
    """Resolved final-answer truth context prepared by the Orchestrator."""

    run_id: str
    observation_truth: tuple[ObservationTruthArtifact, ...] = Field(default_factory=tuple)
    citation_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    validation_precheck: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("validation_precheck", mode="after")
    @classmethod
    def freeze_validation_precheck(cls, value: Any) -> Any:
        return freeze_value(value)


class ObservationRecord(FrozenModel):
    """Control-state result of one observation action."""

    observation_id: str
    action_id: str
    action_type: ReActActionType
    round: int
    truth_ref: str
    summary: Mapping[str, Any] = Field(default_factory=FrozenDict)
    accepted_evidence_count: int = 0
    new_evidence_count: int = 0
    unresolved_subgoals: tuple[str, ...] = Field(default_factory=tuple)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    citation_refs: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("summary", mode="after")
    @classmethod
    def freeze_summary(cls, value: Any) -> Any:
        return freeze_value(value)


class ControlledReActRunState(FrozenModel):
    """Typed state advanced by the Controlled ReAct Orchestrator."""

    run_id: str
    template_name: str
    template_descriptor_version: str
    question: str
    conversation_context: ContextAdmission | None = None
    phase: ControlledReActRunPhase = ControlledReActRunPhase.PLANNING
    plan_round: int = 0
    action_history: tuple[ReActActionProposal, ...] = Field(default_factory=tuple)
    observation_records: tuple[ObservationRecord, ...] = Field(default_factory=tuple)
    intent_resolution: Mapping[str, Any] | None = None
    effective_tool_proposal_scope: EffectiveToolProposalScope | None = None
    effective_react_action_set: tuple[ReActActionType, ...] = Field(default_factory=tuple)
    bound_tool_proposal: BoundToolProposal | None = None
    approved_tool_proposal_snapshot: ApprovedToolProposalSnapshot | None = None
    tool_proposal_scope_trace_projections: tuple[Mapping[str, Any], ...] = Field(
        default_factory=tuple
    )
    memory_context: Mapping[str, Any] = Field(default_factory=FrozenDict)
    memory_read_performed: bool = False
    observation_trace_projections: tuple[Mapping[str, Any], ...] = Field(default_factory=tuple)
    stage_llm_interactions: tuple[WorkflowStageLlmInteraction, ...] = Field(
        default_factory=tuple
    )

    @field_validator(
        "intent_resolution",
        "tool_proposal_scope_trace_projections",
        "memory_context",
        "observation_trace_projections",
        mode="after",
    )
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        if value is None:
            return None
        return freeze_value(value)


class ControlledReActRunStateSnapshot(FrozenModel):
    """Protected resumable capture of one Controlled ReAct run state."""

    snapshot_id: str
    run_id: str
    state: ControlledReActRunState
