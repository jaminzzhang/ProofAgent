from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.react_workflow import ReActActionProposal, ReActActionType


class ControlledReActRunPhase(str, Enum):
    """Internal phase of one Controlled ReAct Orchestrator run."""

    PLANNING = "planning"
    OBSERVING = "observing"
    WAITING = "waiting"
    TERMINAL = "terminal"


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

    @field_validator("intent_resolution", "memory_context", mode="after")
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
