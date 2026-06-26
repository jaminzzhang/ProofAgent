from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.evidence import EvidenceChunk
from proof_agent.contracts.react_workflow import ReActActionProposal, ReActActionType


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
    phase: ControlledReActRunPhase = ControlledReActRunPhase.PLANNING
    plan_round: int = 0
    action_history: tuple[ReActActionProposal, ...] = Field(default_factory=tuple)
    observation_records: tuple[ObservationRecord, ...] = Field(default_factory=tuple)
    intent_resolution: Mapping[str, Any] | None = None
    memory_context: Mapping[str, Any] = Field(default_factory=FrozenDict)
    memory_read_performed: bool = False
    observation_trace_projections: tuple[Mapping[str, Any], ...] = Field(
        default_factory=tuple
    )

    @field_validator(
        "intent_resolution",
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
