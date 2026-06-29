from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenModel, freeze_value
from proof_agent.contracts.receipt import ReceiptOutcome


class ContextAdmission(FrozenModel):
    """Trace-safe result of admitting prior chat turns into a new run."""

    admitted: bool
    turn_count: int = 0
    included_turn_ids: tuple[str, ...] = Field(default_factory=tuple)
    summary: str = ""
    char_count: int = 0
    max_turns: int = 3
    dropped_turn_ids: tuple[str, ...] = Field(default_factory=tuple)
    fallback_reasons: tuple[str, ...] = Field(default_factory=tuple)
    clarification_turn_ids: tuple[str, ...] = Field(default_factory=tuple)


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
    governance_details: Mapping[str, Any] | None = None

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

    @field_validator("governance_details", mode="after")
    @classmethod
    def freeze_governance_details(cls, value: Any) -> Any:
        if value is None:
            return None
        return freeze_value(value)


class ConversationRecord(FrozenModel):
    """A staff-facing chat timeline composed of governed run turns."""

    conversation_id: str
    agent_id: str
    title: str | None = None
    pinned: bool = False
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
        "dropped_turn_ids": list(admission.dropped_turn_ids),
        "fallback_reasons": list(admission.fallback_reasons),
        "clarification_turn_ids": list(admission.clarification_turn_ids),
    }


def conversation_record_payload(record: ConversationRecord) -> dict[str, Any]:
    """Return a plain JSON-ready conversation response payload."""

    return {
        "conversation_id": record.conversation_id,
        "agent_id": record.agent_id,
        "title": record.title,
        "pinned": record.pinned,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "turns": [_turn_payload(turn) for turn in record.turns],
    }


def _turn_payload(turn: ConversationTurn) -> dict[str, Any]:
    payload = {
        "turn_id": turn.turn_id,
        "run_id": turn.run_id,
        "agent_id": turn.agent_id,
        "question": turn.question,
        "final_output": turn.final_output,
        "outcome": turn.outcome.value,
        "created_at": turn.created_at,
        "context_admission": context_admission_payload(turn.context_admission),
        "evidence": [_plain_payload(chunk) for chunk in turn.evidence],
        "approval_state": _plain_payload(turn.approval_state)
        if turn.approval_state is not None
        else None,
        "links": {
            "run_detail": f"/api/runs/{turn.run_id}",
            "trace": f"/api/runs/{turn.run_id}/trace",
            "receipt": f"/api/runs/{turn.run_id}/receipt",
        },
    }
    if turn.governance_details is not None:
        payload["governance_details"] = _plain_payload(turn.governance_details)
    return payload


def _plain_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_payload(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_payload(item) for item in value]
    return value
