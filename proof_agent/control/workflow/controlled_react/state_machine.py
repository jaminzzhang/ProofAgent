from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from proof_agent.contracts import (
    ControlledReActRunPhase,
    ControlledReActRunState,
    ObservationRecord,
    ReActActionProposal,
)


class TransitionCommandType(str, Enum):
    RECORD_OBSERVATION = "record_observation"


@dataclass(frozen=True)
class TransitionCommand:
    command_id: str
    command_type: TransitionCommandType
    action: ReActActionProposal


@dataclass(frozen=True)
class EffectResult:
    command_id: str
    observation_record: ObservationRecord | None = None


@dataclass(frozen=True)
class TransitionResult:
    state: ControlledReActRunState
    outcome: object | None = None


class ControlledReActStateMachine:
    """Pure transition kernel for Controlled ReAct orchestration."""

    def advance(
        self,
        state: ControlledReActRunState,
        command: TransitionCommand,
        effect: EffectResult,
    ) -> TransitionResult:
        if command.command_type is TransitionCommandType.RECORD_OBSERVATION:
            return self._record_observation(state, command, effect)
        raise ValueError(f"unsupported transition command: {command.command_type}")

    def _record_observation(
        self,
        state: ControlledReActRunState,
        command: TransitionCommand,
        effect: EffectResult,
    ) -> TransitionResult:
        if effect.command_id != command.command_id:
            raise ValueError("effect result does not match transition command")
        observation = effect.observation_record
        if observation is None:
            raise ValueError("record_observation requires an ObservationRecord")
        if observation.action_id != command.action.action_id:
            raise ValueError("observation action_id does not match command action")
        if _has_observation(state, observation):
            return TransitionResult(state=state)
        if state.phase is not ControlledReActRunPhase.OBSERVING:
            raise ValueError("observation records can only be committed while observing")
        next_state = state.model_copy(
            update={
                "phase": ControlledReActRunPhase.PLANNING,
                "observation_records": state.observation_records + (observation,),
            }
        )
        return TransitionResult(state=next_state)


def _has_observation(
    state: ControlledReActRunState,
    observation: ObservationRecord,
) -> bool:
    return any(
        existing.observation_id == observation.observation_id
        and existing.action_id == observation.action_id
        for existing in state.observation_records
    )
