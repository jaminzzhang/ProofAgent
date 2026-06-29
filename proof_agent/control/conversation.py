from __future__ import annotations

import re

from proof_agent.contracts import ContextAdmission, ConversationRecord, ReceiptOutcome


def admit_conversation_context(
    conversation: ConversationRecord,
    *,
    max_turns: int = 3,
    max_chars: int = 1200,
) -> ContextAdmission:
    """Admit a trace-safe summary of recent conversation turns."""

    turns = conversation.turns[-max_turns:] if max_turns > 0 else ()
    dropped_turn_ids = tuple(
        turn.turn_id for turn in conversation.turns[: max(0, len(conversation.turns) - len(turns))]
    )
    clarification_turn_ids = _clarification_turn_ids(conversation)
    if not turns:
        return ContextAdmission(
            admitted=False,
            turn_count=0,
            included_turn_ids=(),
            summary="No prior turns admitted.",
            char_count=0,
            max_turns=max_turns,
            dropped_turn_ids=dropped_turn_ids,
            fallback_reasons=(("older_turns_outside_recent_window",) if dropped_turn_ids else ()),
            clarification_turn_ids=clarification_turn_ids,
        )

    parts = []
    for index, turn in enumerate(turns, start=1):
        question = _truncate(_normalize_space(turn.question), 160)
        answer = _truncate(_normalize_space(turn.final_output), 220)
        parts.append(
            f"prior turn {index}: question={question}; "
            f"outcome={turn.outcome.value}; answer_summary={answer}"
        )
    summary = _truncate(" | ".join(parts), max_chars)
    return ContextAdmission(
        admitted=True,
        turn_count=len(turns),
        included_turn_ids=tuple(turn.turn_id for turn in turns),
        summary=summary,
        char_count=len(summary),
        max_turns=max_turns,
        dropped_turn_ids=dropped_turn_ids,
        fallback_reasons=(("older_turns_outside_recent_window",) if dropped_turn_ids else ()),
        clarification_turn_ids=clarification_turn_ids,
    )


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: max(0, limit - 3)]}..."


def _clarification_turn_ids(conversation: ConversationRecord) -> tuple[str, ...]:
    if not conversation.turns:
        return ()
    latest_turn = conversation.turns[-1]
    if latest_turn.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION:
        return (latest_turn.turn_id,)
    return ()
