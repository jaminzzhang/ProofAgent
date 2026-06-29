from __future__ import annotations

from proof_agent.contracts import (
    ContextAdmission,
    ContextSourceType,
    ConversationRecord,
    ConversationTurn,
    ReceiptOutcome,
)
from proof_agent.control.context_assembler import assemble_controlled_run_context


def _turn(
    turn_id: str,
    *,
    outcome: ReceiptOutcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS,
) -> ConversationTurn:
    return ConversationTurn(
        turn_id=turn_id,
        run_id=f"run_{turn_id}",
        agent_id="enterprise_qa",
        question=f"Question {turn_id}?",
        final_output=f"Answer {turn_id}.",
        outcome=outcome,
        created_at="2026-06-29T00:00:00Z",
        context_admission=ContextAdmission(admitted=False),
    )


def test_context_assembler_keeps_recent_turns_and_records_dropped_turn_refs() -> None:
    conversation = ConversationRecord(
        conversation_id="conv_123",
        agent_id="enterprise_qa",
        created_at="2026-06-29T00:00:00Z",
        updated_at="2026-06-29T00:00:00Z",
        turns=(
            _turn("turn_001"),
            _turn("turn_002"),
            _turn("turn_003"),
            _turn("turn_004"),
        ),
    )

    context = assemble_controlled_run_context(
        run_id="run_next",
        conversation=conversation,
        max_recent_turns=3,
    )

    assert [source.source_id for source in context.sources] == [
        "turn_002",
        "turn_003",
        "turn_004",
    ]
    assert context.working_sections[0].section_id == "recent_turns"
    assert context.working_sections[0].source_refs == (
        "turn_002",
        "turn_003",
        "turn_004",
    )
    assert context.budget.dropped_source_refs == ("turn_001",)
    assert context.budget.fallback_reasons == ("older_turns_outside_recent_window",)


def test_context_assembler_marks_clarification_continuation_state() -> None:
    conversation = ConversationRecord(
        conversation_id="conv_123",
        agent_id="enterprise_qa",
        created_at="2026-06-29T00:00:00Z",
        updated_at="2026-06-29T00:00:00Z",
        turns=(
            _turn(
                "turn_waiting",
                outcome=ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION,
            ),
        ),
    )

    context = assemble_controlled_run_context(
        run_id="run_next",
        conversation=conversation,
    )

    assert (
        ContextSourceType.CLARIFICATION_STATE,
        "turn_waiting",
    ) in {(source.source_type, source.source_id) for source in context.sources}
    assert [section.section_id for section in context.cache_stable_working_sections()] == [
        "clarification_continuation",
        "recent_turns",
    ]


def test_context_assembler_creates_compaction_summary_for_older_turns() -> None:
    conversation = ConversationRecord(
        conversation_id="conv_123",
        agent_id="enterprise_qa",
        created_at="2026-06-29T00:00:00Z",
        updated_at="2026-06-29T00:00:00Z",
        turns=(
            _turn("turn_001"),
            _turn("turn_002"),
            _turn("turn_003"),
            _turn("turn_004"),
        ),
    )

    context = assemble_controlled_run_context(
        run_id="run_next",
        conversation=conversation,
        max_recent_turns=2,
        compact_older_turns=True,
    )

    assert len(context.compaction_summaries) == 1
    summary = context.compaction_summaries[0]
    assert summary.covered_turn_ids == ("turn_001", "turn_002")
    assert summary.strategy == "deterministic_recent_window_overflow"
    assert (
        ContextSourceType.CONVERSATION_COMPACTION_SUMMARY,
        summary.summary_id,
    ) in {(source.source_type, source.source_id) for source in context.sources}
    assert "conversation_compaction_summary" in [
        section.section_id for section in context.cache_stable_working_sections()
    ]
