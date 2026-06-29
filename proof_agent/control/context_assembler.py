from __future__ import annotations

from proof_agent.contracts import (
    ContextAssemblyBudget,
    ConversationCompactionSummary,
    ContextSourceRef,
    ContextSourceType,
    ControlledRunContext,
    ConversationRecord,
    ReceiptOutcome,
    WorkingContextSection,
)
from proof_agent.control.conversation import admit_conversation_context


def assemble_controlled_run_context(
    *,
    run_id: str,
    conversation: ConversationRecord,
    max_recent_turns: int = 3,
    compact_older_turns: bool = False,
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
    all_source_refs = (*source_refs, *clarification_source_refs, *compaction_source_refs)
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
    return ControlledRunContext(
        run_id=run_id,
        sources=all_source_refs,
        working_sections=working_sections,
        budget=ContextAssemblyBudget(
            max_tokens=0,
            estimated_tokens=admission.char_count,
            dropped_source_refs=admission.dropped_turn_ids,
            fallback_reasons=admission.fallback_reasons,
        ),
        compaction_summaries=compaction_summaries,
    )


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
