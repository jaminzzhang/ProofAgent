from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from proof_agent.contracts import (
    ControlledReActRunState,
    ObservationRecord,
    ObservationTruthArtifact,
    ObservationTruthKind,
    ReActActionProposal,
    RetrievalObservationTruth,
    ToolObservationTruth,
)
from proof_agent.control.workflow.controlled_react.state_machine import (
    ControlledReActStateMachine,
    EffectResult,
    TransitionCommand,
    TransitionCommandType,
    TransitionResult,
)
from proof_agent.control.workflow.controlled_react.artifact_binding import (
    bind_observation_truth,
    require_bound_observation_truth,
)


class _ObservationTruthStore(Protocol):
    def save(self, truth: ObservationTruthArtifact) -> str: ...

    def load(self, truth_ref: str) -> ObservationTruthArtifact: ...


@dataclass(frozen=True)
class ObservationIdentity:
    observation_id: str
    truth_ref: str
    commit_key: tuple[str, str, str, str]

    @classmethod
    def allocate(
        cls,
        *,
        run_id: str,
        plan_round: int,
        action_id: str,
    ) -> ObservationIdentity:
        observation_id = f"obs_{plan_round}_{action_id}"
        truth_ref = f"observation://{run_id}/{observation_id}/truth"
        return cls(
            observation_id=observation_id,
            truth_ref=truth_ref,
            commit_key=(run_id, action_id, observation_id, truth_ref),
        )


@dataclass(frozen=True)
class ObservationEffect:
    observation_record: ObservationRecord
    truth_artifact: ObservationTruthArtifact
    trace_projection: Mapping[str, Any] = field(default_factory=dict)
    tool_summary_fields: tuple[str, ...] = field(default_factory=tuple)
    tool_summary_projection: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ObservationCommitResult:
    state: ControlledReActRunState
    trace_projection: Mapping[str, Any]


class InMemoryObservationTruthStore:
    def __init__(self) -> None:
        self._truth: dict[str, ObservationTruthArtifact] = {}
        self._ref_by_base: dict[str, str] = {}

    def save(self, truth: ObservationTruthArtifact) -> str:
        binding = require_bound_observation_truth(truth)
        existing_ref = self._ref_by_base.get(binding.base_reference)
        if existing_ref is not None and existing_ref != binding.reference:
            raise ValueError("conflicting observation truth already exists")
        self._truth[binding.reference] = binding.truth
        self._ref_by_base[binding.base_reference] = binding.reference
        return binding.reference

    def load(self, truth_ref: str) -> ObservationTruthArtifact:
        return self._truth[truth_ref]


class ObservationSummaryBuilder:
    def build(
        self,
        truth: ObservationTruthArtifact,
        *,
        tool_summary_fields: tuple[str, ...] = (),
        tool_summary_projection: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if isinstance(truth, RetrievalObservationTruth):
            return self._build_retrieval_summary(truth)
        if isinstance(truth, ToolObservationTruth):
            return self._build_tool_summary(
                truth,
                tool_summary_fields=tool_summary_fields,
                tool_summary_projection=tool_summary_projection,
            )
        raise ValueError(f"unsupported observation truth kind: {truth.kind}")

    @staticmethod
    def _build_retrieval_summary(
        truth: RetrievalObservationTruth,
    ) -> Mapping[str, Any]:
        rejected_count = int(truth.rejected_evidence_summary.get("count", 0) or 0)
        summary: dict[str, Any] = {
            "truth_kind": ObservationTruthKind.RETRIEVAL.value,
            "accepted_evidence_count": len(truth.accepted_evidence),
            "rejected_evidence_count": rejected_count,
            "citation_count": len(truth.citation_refs),
        }
        for key in ("min_score", "evidence_validation"):
            if key in truth.admission_metadata:
                summary[key] = truth.admission_metadata[key]
        return summary

    @staticmethod
    def _build_tool_summary(
        truth: ToolObservationTruth,
        *,
        tool_summary_fields: tuple[str, ...],
        tool_summary_projection: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        fields = (
            dict(tool_summary_projection)
            if tool_summary_projection is not None
            else {
                field: truth.authorized_result[field]
                for field in tool_summary_fields
                if field in truth.authorized_result
            }
        )
        redacted_count = int(truth.redaction_metadata.get("redacted_field_count", 0) or 0)
        return {
            "truth_kind": ObservationTruthKind.TOOL.value,
            "tool_name": truth.tool_name,
            "result_schema_id": truth.result_schema_id,
            "fields": fields,
            "result": fields,
            "redacted_field_count": redacted_count,
        }


class ObservationCommitter:
    def __init__(self, *, truth_store: _ObservationTruthStore) -> None:
        self._truth_store = truth_store
        self._state_machine = ControlledReActStateMachine()
        self._summary_builder = ObservationSummaryBuilder()

    def commit(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        effect: ObservationEffect,
        *,
        expected_identity: ObservationIdentity | None = None,
    ) -> ObservationCommitResult:
        self._validate_effect(state, action, effect, expected_identity=expected_identity)
        record = self._record_with_authoritative_summary(effect)
        truth_binding = bind_observation_truth(effect.truth_artifact)
        bound_record = record.model_copy(update={"truth_ref": truth_binding.reference})
        existing_record = _matching_observation(state, bound_record)
        if existing_record is not None:
            if existing_record.truth_ref != truth_binding.reference:
                raise ValueError(
                    "conflicting observation payload for committed observation identity"
                )
            return ObservationCommitResult(
                state=state,
                trace_projection=_trace_projection(existing_record, effect),
            )
        result = self._commit_record(state, action, bound_record)
        trace_projection = _trace_projection(bound_record, effect)
        saved_truth_ref = self._truth_store.save(truth_binding.truth)
        if saved_truth_ref != truth_binding.reference:
            raise ValueError("truth store returned a mismatched truth_ref")
        return ObservationCommitResult(
            state=result.state,
            trace_projection=trace_projection,
        )

    def _record_with_authoritative_summary(
        self,
        effect: ObservationEffect,
    ) -> ObservationRecord:
        summary = self._summary_builder.build(
            effect.truth_artifact,
            tool_summary_fields=effect.tool_summary_fields,
            tool_summary_projection=effect.tool_summary_projection,
        )
        return effect.observation_record.model_copy(update={"summary": summary})

    def _commit_record(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        record: ObservationRecord,
    ) -> TransitionResult:
        command_id = f"commit_{record.observation_id}"
        return self._state_machine.advance(
            state,
            TransitionCommand(
                command_id=command_id,
                command_type=TransitionCommandType.RECORD_OBSERVATION,
                action=action,
            ),
            EffectResult(
                command_id=command_id,
                observation_record=record,
            ),
        )

    @staticmethod
    def _validate_effect(
        state: ControlledReActRunState,
        action: ReActActionProposal,
        effect: ObservationEffect,
        *,
        expected_identity: ObservationIdentity | None,
    ) -> None:
        record = effect.observation_record
        truth = effect.truth_artifact
        if record.round != state.plan_round:
            raise ValueError("observation round does not match current plan round")
        if record.action_id != action.action_id:
            raise ValueError("observation action_id does not match action")
        if record.action_type != action.action_type:
            raise ValueError("observation action_type does not match action")
        if truth.action_id != action.action_id:
            raise ValueError("truth action_id does not match action")
        if record.observation_id != truth.observation_id:
            raise ValueError("observation_id does not match truth artifact")
        if record.truth_ref != truth.truth_ref:
            raise ValueError("observation truth_ref does not match truth artifact")
        if expected_identity is None:
            return
        if record.observation_id != expected_identity.observation_id:
            raise ValueError("observation_id does not match allocated observation identity")
        if record.truth_ref != expected_identity.truth_ref:
            raise ValueError("truth_ref does not match allocated observation identity")


def _matching_observation(
    state: ControlledReActRunState,
    record: ObservationRecord,
) -> ObservationRecord | None:
    return next(
        (
            existing
            for existing in state.observation_records
            if existing.observation_id == record.observation_id
            and existing.action_id == record.action_id
        ),
        None,
    )


def _trace_projection(
    record: ObservationRecord,
    effect: ObservationEffect,
) -> Mapping[str, Any]:
    projection: dict[str, Any] = {
        "observation_id": record.observation_id,
        "action_id": record.action_id,
        "action_type": record.action_type.value,
        "round": record.round,
        "truth_ref": record.truth_ref,
        "accepted_evidence_count": record.accepted_evidence_count,
        "new_evidence_count": record.new_evidence_count,
        "source_refs": list(record.source_refs),
        "citation_refs": list(record.citation_refs),
        **dict(record.summary),
    }
    for key, value in effect.trace_projection.items():
        if key not in projection:
            projection[str(key)] = value
    return projection
