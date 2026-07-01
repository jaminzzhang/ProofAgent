from __future__ import annotations

from proof_agent.contracts import (
    ContextAssemblyBudget,
    ConversationCompactionSummary,
    ContextSourceRef,
    ContextSourceType,
    ControlledRunContext,
    ConversationRecord,
    MemoryRecallAdmission,
    ReceiptOutcome,
    RunStartContextAssembly,
    WorkingContextSection,
)
from proof_agent.contracts import ContextAdmission
from proof_agent.control.conversation import admit_conversation_context


def assemble_controlled_run_context(
    *,
    run_id: str,
    conversation: ConversationRecord,
    max_recent_turns: int = 3,
    compact_older_turns: bool = False,
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = (),
) -> ControlledRunContext:
    """Assemble the first Controlled Run Context slice from a conversation timeline."""

    admission = admit_conversation_context(conversation, max_turns=max_recent_turns)
    source_refs = tuple(
        ContextSourceRef(
            source_type=ContextSourceType.CONVERSATION_TURN,
            source_id=turn_id,
        )
        for turn_id in admission.included_turn_ids
    )
    clarification_source_refs = _clarification_source_refs(conversation)
    compaction_summaries = _compaction_summaries(
        conversation,
        max_recent_turns=max_recent_turns,
        enabled=compact_older_turns,
    )
    compaction_source_refs = tuple(
        ContextSourceRef(
            source_type=ContextSourceType.CONVERSATION_COMPACTION_SUMMARY,
            source_id=summary.summary_id,
        )
        for summary in compaction_summaries
    )
    memory_source_refs = _memory_recall_source_refs(memory_recall_admissions)
    all_source_refs = (
        *source_refs,
        *clarification_source_refs,
        *compaction_source_refs,
        *memory_source_refs,
    )
    working_sections = (
        (
            WorkingContextSection(
                section_id="recent_turns",
                source_refs=admission.included_turn_ids,
                priority=60,
                stable_prefix=False,
                estimated_tokens=admission.char_count,
            ),
        )
        if source_refs
        else ()
    )
    if clarification_source_refs:
        working_sections = (
            WorkingContextSection(
                section_id="clarification_continuation",
                source_refs=tuple(source.source_id for source in clarification_source_refs),
                priority=30,
                stable_prefix=False,
                estimated_tokens=0,
            ),
            *working_sections,
        )
    if compaction_source_refs:
        working_sections = (
            WorkingContextSection(
                section_id="conversation_compaction_summary",
                source_refs=tuple(source.source_id for source in compaction_source_refs),
                priority=50,
                stable_prefix=False,
                estimated_tokens=sum(len(summary.summary) for summary in compaction_summaries),
            ),
            *working_sections,
        )
    if memory_source_refs:
        working_sections = (
            *working_sections,
            WorkingContextSection(
                section_id="memory_recall",
                source_refs=tuple(source.source_id for source in memory_source_refs),
                priority=70,
                stable_prefix=False,
                estimated_tokens=sum(
                    len(memory.summary)
                    for memory in memory_recall_admissions
                    if memory.admitted
                ),
            ),
        )
    return ControlledRunContext(
        run_id=run_id,
        sources=all_source_refs,
        working_sections=working_sections,
        budget=ContextAssemblyBudget(
            max_tokens=0,
            estimated_tokens=admission.char_count
            + sum(
                len(memory.summary)
                for memory in memory_recall_admissions
                if memory.admitted
            ),
            dropped_source_refs=admission.dropped_turn_ids,
            fallback_reasons=admission.fallback_reasons,
        ),
        compaction_summaries=compaction_summaries,
    )


def assemble_run_start_context_from_admission(
    *,
    run_id: str,
    conversation_context: ContextAdmission,
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = (),
) -> RunStartContextAssembly:
    """Build a run-start context package from the compatibility admission result."""

    controlled_run_context = _controlled_run_context_from_admission(
        run_id=run_id,
        conversation_context=conversation_context,
        memory_recall_admissions=memory_recall_admissions,
    )
    return RunStartContextAssembly.from_controlled_run_context(
        controlled_run_context,
        conversation_context=conversation_context,
        memory_recall_admissions=memory_recall_admissions,
    )


def assemble_run_start_context(
    *,
    run_id: str,
    conversation: ConversationRecord,
    max_recent_turns: int = 3,
    compact_older_turns: bool = False,
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = (),
) -> RunStartContextAssembly:
    """Assemble the run-start context package from a conversation timeline."""

    conversation_context = admit_conversation_context(
        conversation,
        max_turns=max_recent_turns,
    )
    controlled_run_context = assemble_controlled_run_context(
        run_id=run_id,
        conversation=conversation,
        max_recent_turns=max_recent_turns,
        compact_older_turns=compact_older_turns,
        memory_recall_admissions=memory_recall_admissions,
    )
    return RunStartContextAssembly.from_controlled_run_context(
        controlled_run_context,
        conversation_context=conversation_context,
        memory_recall_admissions=memory_recall_admissions,
    )


def _controlled_run_context_from_admission(
    *,
    run_id: str,
    conversation_context: ContextAdmission,
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = (),
) -> ControlledRunContext:
    source_refs = tuple(
        ContextSourceRef(
            source_type=_context_source_type(source_id),
            source_id=source_id,
        )
        for source_id in conversation_context.included_turn_ids
    )
    clarification_source_refs = tuple(
        ContextSourceRef(
            source_type=ContextSourceType.CLARIFICATION_STATE,
            source_id=source_id,
        )
        for source_id in conversation_context.clarification_turn_ids
    )
    memory_source_refs = _memory_recall_source_refs(memory_recall_admissions)
    source_refs = (*source_refs, *clarification_source_refs, *memory_source_refs)
    section_refs = tuple(conversation_context.included_turn_ids)
    working_sections = (
        (
            WorkingContextSection(
                section_id=_context_section_id(source_refs),
                source_refs=section_refs,
                priority=60,
                stable_prefix=False,
                estimated_tokens=conversation_context.char_count,
            ),
        )
        if conversation_context.admitted and section_refs
        else ()
    )
    if clarification_source_refs:
        working_sections = (
            WorkingContextSection(
                section_id="clarification_continuation",
                source_refs=tuple(source.source_id for source in clarification_source_refs),
                priority=30,
                stable_prefix=False,
                estimated_tokens=0,
            ),
            *working_sections,
        )
    if memory_source_refs:
        working_sections = (
            *working_sections,
            WorkingContextSection(
                section_id="memory_recall",
                source_refs=tuple(source.source_id for source in memory_source_refs),
                priority=70,
                stable_prefix=False,
                estimated_tokens=sum(
                    len(admission.summary)
                    for admission in memory_recall_admissions
                    if admission.admitted
                ),
            ),
        )
    return ControlledRunContext(
        run_id=run_id,
        sources=source_refs,
        working_sections=working_sections,
        budget=ContextAssemblyBudget(
            max_tokens=0,
            estimated_tokens=conversation_context.char_count
            + sum(
                len(admission.summary)
                for admission in memory_recall_admissions
                if admission.admitted
            ),
            dropped_source_refs=conversation_context.dropped_turn_ids,
            fallback_reasons=conversation_context.fallback_reasons,
        ),
    )


def _memory_recall_source_refs(
    admissions: tuple[MemoryRecallAdmission, ...],
) -> tuple[ContextSourceRef, ...]:
    return tuple(
        ContextSourceRef(
            source_type=ContextSourceType.MEMORY_RECALL,
            source_id=memory_id,
        )
        for admission in admissions
        if admission.admitted
        for memory_id in admission.included_memory_ids
    )


def _context_source_type(source_id: str) -> ContextSourceType:
    if source_id.startswith(("turn_", "cust_turn_")):
        return ContextSourceType.CONVERSATION_TURN
    return ContextSourceType.MEMORY_RECALL


def _context_section_id(source_refs: tuple[ContextSourceRef, ...]) -> str:
    if source_refs and all(
        source.source_type is ContextSourceType.MEMORY_RECALL for source in source_refs
    ):
        return "memory_recall"
    return "recent_turns"


def _clarification_source_refs(
    conversation: ConversationRecord,
) -> tuple[ContextSourceRef, ...]:
    if not conversation.turns:
        return ()
    latest_turn = conversation.turns[-1]
    if latest_turn.outcome is not ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION:
        return ()
    return (
        ContextSourceRef(
            source_type=ContextSourceType.CLARIFICATION_STATE,
            source_id=latest_turn.turn_id,
        ),
    )


def _compaction_summaries(
    conversation: ConversationRecord,
    *,
    max_recent_turns: int,
    enabled: bool,
) -> tuple[ConversationCompactionSummary, ...]:
    if not enabled:
        return ()
    older_turns = conversation.turns[: max(0, len(conversation.turns) - max_recent_turns)]
    if not older_turns:
        return ()
    covered_ids = tuple(turn.turn_id for turn in older_turns)
    return (
        ConversationCompactionSummary(
            summary_id=f"compaction:{covered_ids[0]}-{covered_ids[-1]}",
            covered_turn_ids=covered_ids,
            strategy="deterministic_recent_window_overflow",
            summary=(
                f"{len(covered_ids)} older conversation turn(s) were compacted "
                "for Working Context budget."
            ),
            omission_risks=("older_turn_details_not_in_working_context",),
        ),
    )
