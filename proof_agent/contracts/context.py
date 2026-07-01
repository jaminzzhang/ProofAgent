from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import ConfigDict, Field, field_serializer, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.conversation import ContextAdmission
from proof_agent.contracts.memory import MemoryScope

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


class MemoryRecallTraceSummary(ContextModel):
    """Ordinary trace-safe summary of admitted memory recall."""

    admitted: bool = True
    scope: MemoryScope
    case_id: str = ""
    subject_ref: str = ""
    agent_id: str = ""
    included_memory_ids: tuple[str, ...] = Field(default_factory=tuple)
    rejected_memory_ids: tuple[str, ...] = Field(default_factory=tuple)
    summary: str = ""
    fact_keys: tuple[str, ...] = Field(default_factory=tuple)
    fact_count: int = 0
    lifecycle_refs: tuple[str, ...] = Field(default_factory=tuple)
    rejection_reasons: Mapping[str, str] = Field(default_factory=FrozenDict)

    @field_validator("fact_keys", "lifecycle_refs", mode="after")
    @classmethod
    def reject_secret_like_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _reject_forbidden_names(value)
        return value

    @field_validator("rejection_reasons", mode="after")
    @classmethod
    def freeze_rejection_reasons(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("rejection_reasons")
    def serialize_rejection_reasons(self, value: Mapping[str, str]) -> dict[str, Any]:
        return _jsonable_mapping(value)


class MemoryRecallWorkingPayload(ContextModel):
    """Model-facing memory recall payload admitted into Working Context."""

    scope: MemoryScope
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    summary: str = ""
    facts: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("facts", mode="after")
    @classmethod
    def freeze_facts(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            _reject_forbidden_names(tuple(str(key) for key in value))
        return freeze_value(value)

    @field_serializer("facts")
    def serialize_facts(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _jsonable_mapping(value)


class MemoryRecallAdmission(ContextModel):
    """Control Plane admission of recalled memory into run context."""

    admitted: bool
    scope: MemoryScope
    case_id: str = ""
    subject_ref: str = ""
    agent_id: str = ""
    included_memory_ids: tuple[str, ...] = Field(default_factory=tuple)
    rejected_memory_ids: tuple[str, ...] = Field(default_factory=tuple)
    summary: str = ""
    fact_keys: tuple[str, ...] = Field(default_factory=tuple)
    fact_count: int = 0
    lifecycle_refs: tuple[str, ...] = Field(default_factory=tuple)
    rejection_reasons: Mapping[str, str] = Field(default_factory=FrozenDict)
    working_payload: MemoryRecallWorkingPayload | None = None

    @field_validator("fact_keys", "lifecycle_refs", mode="after")
    @classmethod
    def reject_secret_like_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _reject_forbidden_names(value)
        return value

    @field_validator("rejection_reasons", mode="after")
    @classmethod
    def freeze_rejection_reasons(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("rejection_reasons")
    def serialize_rejection_reasons(self, value: Mapping[str, str]) -> dict[str, Any]:
        return _jsonable_mapping(value)

    def trace_summary(self) -> MemoryRecallTraceSummary:
        return MemoryRecallTraceSummary(
            admitted=self.admitted,
            scope=self.scope,
            case_id=self.case_id,
            subject_ref=self.subject_ref,
            agent_id=self.agent_id,
            included_memory_ids=self.included_memory_ids,
            rejected_memory_ids=self.rejected_memory_ids,
            summary=self.summary,
            fact_keys=self.fact_keys,
            fact_count=self.fact_count,
            lifecycle_refs=self.lifecycle_refs,
            rejection_reasons=self.rejection_reasons,
        )


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


class RunStartContextAssembly(ContextModel):
    """Run-start context package shared by runtime families."""

    controlled_run_context: ControlledRunContext
    trace_safe_summary: TraceSafeContextAssemblySummary
    conversation_context: ContextAdmission | None = None
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = Field(default_factory=tuple)
    context_summary_ref: str | None = None

    @classmethod
    def from_controlled_run_context(
        cls,
        controlled_run_context: ControlledRunContext,
        *,
        conversation_context: ContextAdmission | None = None,
        memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = (),
        context_summary_ref: str | None = None,
    ) -> "RunStartContextAssembly":
        return cls(
            controlled_run_context=controlled_run_context,
            trace_safe_summary=controlled_run_context.trace_safe_summary(),
            conversation_context=conversation_context,
            memory_recall_admissions=memory_recall_admissions,
            context_summary_ref=context_summary_ref,
        )


def _reject_forbidden_names(names: tuple[str, ...]) -> None:
    for name in names:
        if name.strip().lower() in CONTEXT_SUMMARY_FORBIDDEN_NAMES:
            raise ValueError("Memory recall summary contains a non-trace-safe key.")


def _jsonable_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _jsonable(item) for key, item in value.items()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _jsonable_mapping(value)
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
