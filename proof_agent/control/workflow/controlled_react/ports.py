from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from proof_agent.contracts import (
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EvidenceChunk,
    IntentResolutionResult,
    ObservationRecord,
    PolicyDecision,
    ReActActionProposal,
    ReceiptOutcome,
    ReviewDecision,
    ValidationResult,
    WorkflowStageLlmInteraction,
)


class PlannerPort(Protocol):
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal: ...


class IntentResolutionPort(Protocol):
    def resolve(self, state: ControlledReActRunState) -> IntentResolutionResult: ...


class MemoryPort(Protocol):
    def read(self, state: ControlledReActRunState) -> Mapping[str, Any]: ...

    def write(
        self,
        state: ControlledReActRunState,
        answer: AnswerSynthesisResult,
    ) -> ValidationResult: ...


@dataclass(frozen=True)
class AnswerSynthesisResult:
    outcome: ReceiptOutcome
    final_output: str
    message: str
    reasoning_summary: Mapping[str, Any] | None = None
    model_usage_summary: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceChunk, ...] = field(default_factory=tuple)
    stage_llm_interactions: tuple[WorkflowStageLlmInteraction, ...] = field(
        default_factory=tuple
    )


class AnswerSynthesisPort(Protocol):
    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> AnswerSynthesisResult: ...


class KnowledgeObservationPort(Protocol):
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord: ...


class ToolObservationPort(Protocol):
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord: ...


class PolicyPort(Protocol):
    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision: ...


class ReviewPort(Protocol):
    def review(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ReviewDecision: ...


class SnapshotStorePort(Protocol):
    def save(self, snapshot: ControlledReActRunStateSnapshot) -> str: ...

    def load(self, snapshot_ref: str) -> ControlledReActRunStateSnapshot: ...


@dataclass(frozen=True)
class ControlledReActPorts:
    planner: PlannerPort
    answer_synthesis: AnswerSynthesisPort
    intent_resolution: IntentResolutionPort | None = None
    memory: MemoryPort | None = None
    knowledge_observation: KnowledgeObservationPort | None = None
    tool_observation: ToolObservationPort | None = None
    policy: PolicyPort | None = None
    review: ReviewPort | None = None
    snapshot_store: SnapshotStorePort | None = None
