from __future__ import annotations

from enum import Enum

from pydantic import ConfigDict, Field, field_validator

from proof_agent.contracts._base import FrozenModel

CONTEXT_SUMMARY_FORBIDDEN_NAMES = frozenset(
    {
        "raw_prompt",
        "raw_context",
        "raw_transcript",
        "raw_memory",
        "provider_response",
        "chain_of_thought",
        "raw_chain_of_thought",
        "secret",
        "password",
        "api_key",
        "access_token",
        "bearer",
        "authorization",
    }
)


class ContextModel(FrozenModel):
    """Base for run context contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ContextSourceType(str, Enum):
    """Trace-safe source categories admitted into Controlled Run Context."""

    CONVERSATION_TURN = "conversation_turn"
    CONVERSATION_COMPACTION_SUMMARY = "conversation_compaction_summary"
    CLARIFICATION_STATE = "clarification_state"
    MEMORY_RECALL = "memory_recall"


class ContextSourceRef(ContextModel):
    """Trace-safe reference to one admitted context source."""

    source_type: ContextSourceType
    source_id: str


class WorkingContextSection(ContextModel):
    """Trace-safe summary of one Working Context section."""

    section_id: str
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    priority: int
    stable_prefix: bool = False
    estimated_tokens: int = 0

    @field_validator("section_id")
    @classmethod
    def reject_raw_section_id(cls, value: str) -> str:
        if value.strip().lower() in CONTEXT_SUMMARY_FORBIDDEN_NAMES:
            raise ValueError("Working Context section id is not trace-safe.")
        return value


class ContextAssemblyBudget(ContextModel):
    """Trace-safe budget facts from Context Assembler."""

    max_tokens: int
    estimated_tokens: int
    dropped_source_refs: tuple[str, ...] = Field(default_factory=tuple)
    fallback_reasons: tuple[str, ...] = Field(default_factory=tuple)


class ConversationCompactionSummary(ContextModel):
    """Provenance-bearing summary for older conversation turns."""

    summary_id: str
    covered_turn_ids: tuple[str, ...] = Field(default_factory=tuple)
    strategy: str
    summary: str = ""
    omission_risks: tuple[str, ...] = Field(default_factory=tuple)


class TraceSafeContextAssemblySummary(ContextModel):
    """Ordinary trace-safe projection of run-start context assembly."""

    run_id: str
    source_refs: tuple[ContextSourceRef, ...] = Field(default_factory=tuple)
    working_sections: tuple[WorkingContextSection, ...] = Field(default_factory=tuple)
    budget: ContextAssemblyBudget


class ControlledRunContext(ContextModel):
    """Controlled Run Context assembled for one governed run."""

    run_id: str
    sources: tuple[ContextSourceRef, ...] = Field(default_factory=tuple)
    working_sections: tuple[WorkingContextSection, ...] = Field(default_factory=tuple)
    budget: ContextAssemblyBudget
    compaction_summaries: tuple[ConversationCompactionSummary, ...] = Field(default_factory=tuple)

    def cache_stable_working_sections(self) -> tuple[WorkingContextSection, ...]:
        return tuple(
            sorted(
                self.working_sections,
                key=lambda section: (
                    not section.stable_prefix,
                    section.priority,
                    section.section_id,
                ),
            )
        )

    def trace_safe_summary(self) -> TraceSafeContextAssemblySummary:
        return TraceSafeContextAssemblySummary(
            run_id=self.run_id,
            source_refs=self.sources,
            working_sections=self.cache_stable_working_sections(),
            budget=self.budget,
        )
