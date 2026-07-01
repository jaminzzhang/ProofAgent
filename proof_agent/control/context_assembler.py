from __future__ import annotations

from proof_agent.contracts import (
    AgentContextConfiguration,
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
from proof_agent.control.context_budget import (
    ContextBudgetKey,
    ContextConvergenceLevel,
    InMemoryContextBudgetCalibrationStore,
    ResolvedContextBudget,
    context_convergence_level,
    resolve_context_budget,
)


_DEFAULT_CONTEXT_BUDGET_KEY = ContextBudgetKey(
    provider="unknown",
    model="unknown",
    role="run_start_context",
)


def assemble_controlled_run_context(
    *,
    run_id: str,
    conversation: ConversationRecord,
    max_recent_turns: int = 3,
    compact_older_turns: bool = False,
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = (),
    context_config: AgentContextConfiguration | None = None,
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore | None = None,
    context_budget_key: ContextBudgetKey | None = None,
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
    working_sections: tuple[WorkingContextSection, ...] = (
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
                    len(memory.summary) for memory in memory_recall_admissions if memory.admitted
                ),
            ),
        )
    estimated_tokens = admission.char_count + sum(
        len(memory.summary) for memory in memory_recall_admissions if memory.admitted
    )
    budget = _resolve_assembly_budget(
        context_config=context_config,
        calibration_store=context_budget_calibration_store,
        key=context_budget_key,
    )
    convergence_level = context_convergence_level(
        estimated_tokens=estimated_tokens,
        budget=budget,
    )
    (
        working_sections,
        convergence_dropped_refs,
        convergence_fallback_reasons,
    ) = _apply_context_convergence(
        working_sections,
        convergence_level=convergence_level,
    )
    return ControlledRunContext(
        run_id=run_id,
        sources=all_source_refs,
        working_sections=working_sections,
        budget=ContextAssemblyBudget(
            max_tokens=budget.max_tokens,
            estimated_tokens=estimated_tokens,
            convergence_level=convergence_level,
            budget_source=budget.budget_source,
            dropped_source_refs=(
                *admission.dropped_turn_ids,
                *convergence_dropped_refs,
            ),
            fallback_reasons=(
                *admission.fallback_reasons,
                *convergence_fallback_reasons,
            ),
            calibration_update_refs=(
                (budget.calibration_update_ref,)
                if budget.calibration_update_ref is not None
                else ()
            ),
        ),
        compaction_summaries=compaction_summaries,
    )


def assemble_run_start_context_from_admission(
    *,
    run_id: str,
    conversation_context: ContextAdmission,
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = (),
    context_config: AgentContextConfiguration | None = None,
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore | None = None,
    context_budget_key: ContextBudgetKey | None = None,
) -> RunStartContextAssembly:
    """Build a run-start context package from the compatibility admission result."""

    controlled_run_context = _controlled_run_context_from_admission(
        run_id=run_id,
        conversation_context=conversation_context,
        memory_recall_admissions=memory_recall_admissions,
        context_config=context_config,
        context_budget_calibration_store=context_budget_calibration_store,
        context_budget_key=context_budget_key,
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
    context_config: AgentContextConfiguration | None = None,
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore | None = None,
    context_budget_key: ContextBudgetKey | None = None,
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
        context_config=context_config,
        context_budget_calibration_store=context_budget_calibration_store,
        context_budget_key=context_budget_key,
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
    context_config: AgentContextConfiguration | None = None,
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore | None = None,
    context_budget_key: ContextBudgetKey | None = None,
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
    working_sections: tuple[WorkingContextSection, ...] = (
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
    estimated_tokens = conversation_context.char_count + sum(
        len(admission.summary) for admission in memory_recall_admissions if admission.admitted
    )
    budget = _resolve_assembly_budget(
        context_config=context_config,
        calibration_store=context_budget_calibration_store,
        key=context_budget_key,
    )
    convergence_level = context_convergence_level(
        estimated_tokens=estimated_tokens,
        budget=budget,
    )
    (
        working_sections,
        convergence_dropped_refs,
        convergence_fallback_reasons,
    ) = _apply_context_convergence(
        working_sections,
        convergence_level=convergence_level,
    )
    return ControlledRunContext(
        run_id=run_id,
        sources=source_refs,
        working_sections=working_sections,
        budget=ContextAssemblyBudget(
            max_tokens=budget.max_tokens,
            estimated_tokens=estimated_tokens,
            convergence_level=convergence_level,
            budget_source=budget.budget_source,
            dropped_source_refs=(
                *conversation_context.dropped_turn_ids,
                *convergence_dropped_refs,
            ),
            fallback_reasons=(
                *conversation_context.fallback_reasons,
                *convergence_fallback_reasons,
            ),
            calibration_update_refs=(
                (budget.calibration_update_ref,)
                if budget.calibration_update_ref is not None
                else ()
            ),
        ),
    )


def _resolve_assembly_budget(
    *,
    context_config: AgentContextConfiguration | None,
    calibration_store: InMemoryContextBudgetCalibrationStore | None,
    key: ContextBudgetKey | None,
) -> ResolvedContextBudget:
    return resolve_context_budget(
        context_config=context_config,
        calibration_store=calibration_store or InMemoryContextBudgetCalibrationStore(),
        key=key or _DEFAULT_CONTEXT_BUDGET_KEY,
    )


def _apply_context_convergence(
    working_sections: tuple[WorkingContextSection, ...],
    *,
    convergence_level: ContextConvergenceLevel,
) -> tuple[tuple[WorkingContextSection, ...], tuple[str, ...], tuple[str, ...]]:
    if convergence_level == "none":
        return working_sections, (), ()
    if convergence_level == "level1":
        return _dedupe_working_sections(working_sections), (), ("context_convergence_level1",)
    if convergence_level == "level2":
        return _narrow_level2_working_sections(working_sections)
    return _deep_compress_working_sections(working_sections)


def _dedupe_working_sections(
    working_sections: tuple[WorkingContextSection, ...],
) -> tuple[WorkingContextSection, ...]:
    return tuple(
        _section_with_refs(section, _dedupe_refs(section.source_refs))
        for section in working_sections
    )


def _narrow_level2_working_sections(
    working_sections: tuple[WorkingContextSection, ...],
) -> tuple[tuple[WorkingContextSection, ...], tuple[str, ...], tuple[str, ...]]:
    narrowed: list[WorkingContextSection] = []
    dropped_refs: list[str] = []
    reasons: list[str] = ["context_convergence_level2"]
    for section in _dedupe_working_sections(working_sections):
        if section.section_id == "recent_turns" and len(section.source_refs) > 2:
            kept_refs = section.source_refs[-2:]
            dropped_refs.extend(section.source_refs[:-2])
            _append_unique(reasons, "conversation_turns_compacted_for_level2")
            narrowed.append(_section_with_refs(section, kept_refs))
            continue
        if section.section_id == "memory_recall" and len(section.source_refs) > 1:
            kept_refs = section.source_refs[:1]
            dropped_refs.extend(section.source_refs[1:])
            _append_unique(reasons, "memory_recall_narrowed_for_level2")
            narrowed.append(_section_with_refs(section, kept_refs))
            continue
        narrowed.append(section)
    return tuple(narrowed), tuple(dropped_refs), tuple(reasons)


def _deep_compress_working_sections(
    working_sections: tuple[WorkingContextSection, ...],
) -> tuple[tuple[WorkingContextSection, ...], tuple[str, ...], tuple[str, ...]]:
    compressed: list[WorkingContextSection] = []
    dropped_refs: list[str] = []
    for section in _dedupe_working_sections(working_sections):
        if section.section_id == "clarification_continuation":
            compressed.append(section)
            continue
        if section.section_id == "recent_turns" and section.source_refs:
            kept_refs = section.source_refs[-1:]
            dropped_refs.extend(section.source_refs[:-1])
            compressed.append(_section_with_refs(section, kept_refs))
            continue
        if section.section_id == "memory_recall" and section.source_refs:
            kept_refs = section.source_refs[:1]
            dropped_refs.extend(section.source_refs[1:])
            compressed.append(_section_with_refs(section, kept_refs))
            continue
        dropped_refs.extend(section.source_refs)
    return (
        tuple(compressed),
        tuple(dropped_refs),
        (
            "context_convergence_deep_compression",
            "task_continuity_skeleton_deep_compression",
        ),
    )


def _section_with_refs(
    section: WorkingContextSection,
    refs: tuple[str, ...],
) -> WorkingContextSection:
    if refs == section.source_refs:
        return section
    estimated_tokens = _scaled_estimated_tokens(
        section.estimated_tokens,
        old_count=len(section.source_refs),
        new_count=len(refs),
    )
    return section.model_copy(
        update={
            "source_refs": refs,
            "estimated_tokens": estimated_tokens,
        }
    )


def _scaled_estimated_tokens(
    estimated_tokens: int,
    *,
    old_count: int,
    new_count: int,
) -> int:
    if old_count <= 0 or new_count <= 0:
        return 0
    return max(1, int(estimated_tokens * (new_count / old_count)))


def _dedupe_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    deduped: list[str] = []
    for ref in refs:
        if ref not in deduped:
            deduped.append(ref)
    return tuple(deduped)


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


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
