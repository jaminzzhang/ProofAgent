from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.receipt import ReceiptOutcome


class ContextAdmission(FrozenModel):
    """Trace-safe result of admitting prior chat turns into a new run."""

    admitted: bool
    turn_count: int = 0
    included_turn_ids: tuple[str, ...] = Field(default_factory=tuple)
    summary: str = ""
    char_count: int = 0
    max_turns: int = 3


class ConversationTurn(FrozenModel):
    """One operator chat turn linked to a governed Harness run."""

    turn_id: str
    run_id: str
    agent_id: str
    question: str
    final_output: str
    outcome: ReceiptOutcome
    created_at: str
    context_admission: ContextAdmission
    evidence: tuple[Mapping[str, Any], ...] = Field(default_factory=tuple)
    approval_state: Mapping[str, Any] | None = None

    @field_validator("evidence", mode="after")
    @classmethod
    def freeze_evidence(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_validator("approval_state", mode="after")
    @classmethod
    def freeze_approval_state(cls, value: Any) -> Any:
        if value is None:
            return None
        return freeze_value(value)


class ConversationRecord(FrozenModel):
    """A staff-facing chat timeline composed of governed run turns."""

    conversation_id: str
    agent_id: str
    created_at: str
    updated_at: str
    turns: tuple[ConversationTurn, ...] = Field(default_factory=tuple)


def context_admission_payload(admission: ContextAdmission) -> dict[str, Any]:
    """Return a plain JSON-ready context admission payload."""

    return {
        "admitted": admission.admitted,
        "turn_count": admission.turn_count,
        "included_turn_ids": list(admission.included_turn_ids),
        "summary": admission.summary,
        "char_count": admission.char_count,
        "max_turns": admission.max_turns,
    }


def conversation_record_payload(record: ConversationRecord) -> dict[str, Any]:
    """Return a plain JSON-ready conversation response payload."""

    return {
        "conversation_id": record.conversation_id,
        "agent_id": record.agent_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "turns": [_turn_payload(turn) for turn in record.turns],
    }


def _turn_payload(turn: ConversationTurn) -> dict[str, Any]:
    return {
        "turn_id": turn.turn_id,
        "run_id": turn.run_id,
        "agent_id": turn.agent_id,
        "question": turn.question,
        "final_output": turn.final_output,
        "outcome": turn.outcome.value,
        "created_at": turn.created_at,
        "context_admission": context_admission_payload(turn.context_admission),
        "evidence": [dict(chunk) if isinstance(chunk, FrozenDict) else dict(chunk) for chunk in turn.evidence],
        "approval_state": dict(turn.approval_state) if turn.approval_state is not None else None,
        "links": {
            "run_detail": f"/api/runs/{turn.run_id}",
            "trace": f"/api/runs/{turn.run_id}/trace",
            "receipt": f"/api/runs/{turn.run_id}/receipt",
        },
    }
