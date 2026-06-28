from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from proof_agent.contracts import (
    AnswerEvidenceContext,
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EffectiveToolProposalScope,
    EvidenceChunk,
    IntentResolutionResult,
    ObservationTruthArtifact,
    PolicyDecision,
    ReActActionProposal,
    ReceiptOutcome,
    ReviewDecision,
    ValidationResult,
    WorkflowStageLlmInteraction,
)
from proof_agent.control.workflow.controlled_react.observation_commit import (
    ObservationEffect,
    ObservationIdentity,
)
from proof_agent.observability.audit.trace import TraceEmitter


class PlannerPort(Protocol):
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal: ...


class ToolProposalScopePort(Protocol):
    def resolve(self, state: ControlledReActRunState) -> EffectiveToolProposalScope: ...


class IntentResolutionPort(Protocol):
    def resolve(self, state: ControlledReActRunState) -> IntentResolutionResult: ...


class MemoryPort(Protocol):
    def read(self, state: ControlledReActRunState) -> Mapping[str, Any]: ...

    def prepare_write(
        self,
        state: ControlledReActRunState,
        answer: AnswerSynthesisResult,
    ) -> MemoryWriteCandidate | None: ...

    def commit_write(self, candidate: MemoryWriteCandidate) -> ValidationResult: ...


@dataclass(frozen=True)
class AnswerSynthesisResult:
    outcome: ReceiptOutcome
    final_output: str
    message: str
    reasoning_summary: Mapping[str, Any] | None = None
    model_usage_summary: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceChunk, ...] = field(default_factory=tuple)
    stage_llm_interactions: tuple[WorkflowStageLlmInteraction, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MemoryWriteCandidate:
    values: Mapping[str, Any]
    write_source: str = "controlled_react_v3"

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(sorted(str(field_name) for field_name in self.values))

    @property
    def field_count(self) -> int:
        return len(self.field_names)


class AnswerSynthesisPort(Protocol):
    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
    ) -> AnswerSynthesisResult: ...


class KnowledgeObservationPort(Protocol):
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect: ...


class ToolObservationPort(Protocol):
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect: ...


class ObservationTruthStorePort(Protocol):
    def save(self, truth: ObservationTruthArtifact) -> str: ...

    def load(self, truth_ref: str) -> ObservationTruthArtifact: ...


class PolicyPort(Protocol):
    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision: ...

    def evaluate_memory_write(
        self,
        state: ControlledReActRunState,
        candidate: MemoryWriteCandidate,
    ) -> PolicyDecision: ...


class ReviewPort(Protocol):
    def review(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ReviewDecision: ...


class TracePort(TraceEmitter, Protocol):
    pass


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
    trace: TracePort | None = None
    tool_proposal_scope: ToolProposalScopePort | None = None
    snapshot_store: SnapshotStorePort | None = None
    observation_truth_store: ObservationTruthStorePort | None = None
