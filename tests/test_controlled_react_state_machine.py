from __future__ import annotations

from proof_agent.contracts import (
    ControlledReActRunPhase,
    ControlledReActRunState,
    ObservationRecord,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
)
from proof_agent.control.workflow.controlled_react import (
    ControlledReActStateMachine,
    EffectResult,
    TransitionCommand,
    TransitionCommandType,
)


def test_observation_action_returns_to_planning_after_recording_observation() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    observation = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=ReActActionType.PLAN_RETRIEVAL,
        round=1,
        truth_ref="evidence",
        summary={
            "accepted_evidence_count": 2,
            "new_evidence_count": 2,
            "citation_count": 2,
        },
        accepted_evidence_count=2,
        new_evidence_count=2,
        unresolved_subgoals=(),
        source_refs=("claims-guide.md",),
        citation_refs=("claims-guide.md#documents",),
    )

    result = ControlledReActStateMachine().advance(
        state,
        TransitionCommand(
            command_id="cmd_observe",
            command_type=TransitionCommandType.RECORD_OBSERVATION,
            action=action,
        ),
        EffectResult(
            command_id="cmd_observe",
            observation_record=observation,
        ),
    )

    assert result.state.phase is ControlledReActRunPhase.PLANNING
    assert result.state.observation_records == (observation,)
    assert result.outcome is None


def test_replayed_observation_commit_is_idempotent() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    observation = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=ReActActionType.PLAN_RETRIEVAL,
        round=1,
        truth_ref="evidence",
        summary={"accepted_evidence_count": 1},
        accepted_evidence_count=1,
        new_evidence_count=1,
        unresolved_subgoals=(),
        source_refs=("claims-guide.md",),
        citation_refs=("claims-guide.md#documents",),
    )
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.PLANNING,
        plan_round=1,
        action_history=(action,),
        observation_records=(observation,),
    )

    result = ControlledReActStateMachine().advance(
        state,
        TransitionCommand(
            command_id="cmd_observe",
            command_type=TransitionCommandType.RECORD_OBSERVATION,
            action=action,
        ),
        EffectResult(
            command_id="cmd_observe",
            observation_record=observation,
        ),
    )

    assert result.state.phase is ControlledReActRunPhase.PLANNING
    assert result.state.observation_records == (observation,)
    assert result.outcome is None


def _proposal(action_id: str, action_type: ReActActionType) -> ReActActionProposal:
    return ReActActionProposal(
        action_id=action_id,
        action_type=action_type,
        reasoning_summary=ReasoningSummary(
            goal="answer the user with governed evidence",
            observations=(),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="Need one governed observation before answering.",
            risk_flags=(),
            required_evidence=("policy document",),
        ),
        parameters={"query": "required claim documents"},
        risk_level="low",
    )
