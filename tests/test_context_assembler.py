from __future__ import annotations

from proof_agent.contracts import (
    ContextAdmission,
    MemoryRecallAdmission,
    MemoryRecallWorkingPayload,
    MemoryScope,
    ContextSourceType,
    ConversationRecord,
    ConversationTurn,
    ReceiptOutcome,
)
from proof_agent.control.context_assembler import assemble_controlled_run_context
from proof_agent.control.context_assembler import assemble_run_start_context_from_admission


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


def test_context_assembler_builds_run_start_context_from_compatibility_admission() -> None:
    admission = ContextAdmission(
        admitted=True,
        turn_count=1,
        included_turn_ids=("turn_001",),
        summary="1 prior turn admitted.",
        char_count=180,
        max_turns=3,
    )

    assembly = assemble_run_start_context_from_admission(
        run_id="run_next",
        conversation_context=admission,
    )

    assert assembly.conversation_context == admission
    assert assembly.controlled_run_context.run_id == "run_next"
    assert assembly.trace_safe_summary.source_refs[0].source_type is (
        ContextSourceType.CONVERSATION_TURN
    )
    assert assembly.trace_safe_summary.source_refs[0].source_id == "turn_001"
    assert assembly.trace_safe_summary.working_sections[0].section_id == "recent_turns"
    assert assembly.trace_safe_summary.budget.estimated_tokens == 180


def test_context_assembler_adds_memory_recall_source_refs_and_section() -> None:
    admission = MemoryRecallAdmission(
        admitted=True,
        scope=MemoryScope.CASE,
        case_id="cust_conv_001",
        agent_id="insurance_customer_service",
        included_memory_ids=("mem_case_001",),
        summary="Case focus: inpatient reimbursement.",
        fact_keys=("case_focus",),
        fact_count=1,
        working_payload=MemoryRecallWorkingPayload(
            scope=MemoryScope.CASE,
            source_refs=("mem_case_001",),
            summary="Case focus: inpatient reimbursement.",
            facts={"case_focus": "inpatient reimbursement"},
        ),
    )

    assembly = assemble_run_start_context_from_admission(
        run_id="run_next",
        conversation_context=ContextAdmission(admitted=False),
        memory_recall_admissions=(admission,),
    )

    assert (
        ContextSourceType.MEMORY_RECALL,
        "mem_case_001",
    ) in {
        (source.source_type, source.source_id)
        for source in assembly.trace_safe_summary.source_refs
    }
    assert [
        section.section_id for section in assembly.trace_safe_summary.working_sections
    ] == ["memory_recall"]
