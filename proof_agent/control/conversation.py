from __future__ import annotations

import re

from proof_agent.contracts import ContextAdmission, ConversationRecord, ReceiptOutcome
from proof_agent.errors import ProofAgentError
from proof_agent.control.conversation_task_state import (
    conversation_task_history, has_task_statement, reduce_task_state, render_task_state,
)


def admit_conversation_context(
    conversation: ConversationRecord,
    *,
    max_turns: int = 3,
    max_chars: int = 1200,
    current_question: str | None = None,
    current_turn_id: str = "current-request",
) -> ContextAdmission:
    """Admit a trace-safe summary of recent conversation turns."""

    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    history = conversation_task_history(conversation)
    task_state = history.state
    if current_question is not None:
        task_state = reduce_task_state(task_state, current_question, current_turn_id)
    superseded = history.observed_values - {item.value for item in task_state.items}
    task_summary = render_task_state(task_state)
    if len(task_summary) > max_chars:
        raise ProofAgentError("PA_REACT_001", "Active task constraints exceed the conversation context budget.", "Shorten active constraints or start a separate conversation.")
    turns = conversation.turns[-max_turns:] if max_turns > 0 else ()
    dropped_turn_ids = tuple(
        turn.turn_id for turn in conversation.turns[: max(0, len(conversation.turns) - len(turns))]
    )
    clarification_turn_ids = _clarification_turn_ids(conversation)
    if not turns:
        return ContextAdmission(
            task_state=task_state,
            admitted=bool(task_summary),
            turn_count=0,
            included_turn_ids=(),
            summary=task_summary or "No prior turns admitted.",
            recent_summary="No prior turns admitted.",
            char_count=len(task_summary),
            max_turns=max_turns,
            dropped_turn_ids=dropped_turn_ids,
            fallback_reasons=(("older_turns_outside_recent_window",) if dropped_turn_ids else ()),
            clarification_turn_ids=clarification_turn_ids,
        )

    parts = []
    for index, turn in enumerate(turns, start=1):
        if has_task_statement(turn.question):
            parts.append(f"prior turn {index}: task state represented by the current snapshot; outcome={turn.outcome.value}")
            continue
        question = _truncate(_normalize_space(turn.question), 160)
        answer = _truncate(_normalize_space(turn.final_output), 220)
        if any(value in turn.final_output for value in superseded):
            answer = "Superseded task-state detail omitted."
        parts.append(
            f"prior turn {index}: question={question}; "
            f"outcome={turn.outcome.value}; answer_summary={answer}"
        )
    remaining = max(0, max_chars - len(task_summary) - (1 if task_summary else 0))
    recent = _truncate(" | ".join(parts), remaining) if remaining else ""
    summary = "\n".join(part for part in (task_summary, recent) if part)
    return ContextAdmission(
        task_state=task_state,
        admitted=True,
        turn_count=len(turns),
        included_turn_ids=tuple(turn.turn_id for turn in turns),
        summary=summary,
        recent_summary=recent,
        char_count=len(summary),
        max_turns=max_turns,
        dropped_turn_ids=dropped_turn_ids,
        fallback_reasons=(("older_turns_outside_recent_window",) if dropped_turn_ids else ()),
        clarification_turn_ids=clarification_turn_ids,
    )


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if limit < 3:
        return value[:limit]
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


def bound_task_context(admission: ContextAdmission, max_bytes: int) -> ContextAdmission:
    """Conservatively budget UTF-8 bytes and retain every active state item."""
    if admission.task_state is None or not (admission.task_state.items or admission.task_state.unresolved):
        return admission
    required = render_task_state(admission.task_state)
    if len(required.encode("utf-8")) > max_bytes:
        raise ProofAgentError("PA_REACT_001", "Active task constraints exceed the conversation context budget.", "Shorten active constraints or start a separate conversation.")
    if len(admission.summary.encode("utf-8")) <= max_bytes:
        return admission
    return admission.model_copy(update={
        "summary": required, "recent_summary": "", "char_count": len(required),
        "included_turn_ids": (), "turn_count": 0,
        "dropped_turn_ids": tuple(dict.fromkeys((*admission.dropped_turn_ids, *admission.included_turn_ids))),
        "fallback_reasons": (*admission.fallback_reasons, "task_context_recent_detail_trimmed"),
    })
