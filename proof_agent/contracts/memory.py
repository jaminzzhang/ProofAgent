from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenModel, freeze_value


class MemoryScope(str, Enum):
    """Proof Agent memory scope."""

    CASE = "case"
    USER = "user"
    SHARED = "shared"


class MemorySensitivity(str, Enum):
    """Memory sensitivity level used by admission policy."""

    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class MemoryStatus(str, Enum):
    """Lifecycle status for stored memory."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MemoryCandidate(FrozenModel):
    """Trace-safe memory proposed from governed run facts."""

    scope: MemoryScope
    case_id: str = ""
    subject_ref: str = ""
    agent_id: str
    summary: str
    facts: Mapping[str, Any] = Field(default_factory=dict)
    source_run_id: str
    source_turn_id: str
    expires_at: str
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL

    @field_validator("facts", mode="after")
    @classmethod
    def freeze_facts(cls, value: Any) -> Any:
        return freeze_value(value)


class MemoryRecord(FrozenModel):
    """Stored memory record returned by a Memory Provider Adapter."""

    memory_id: str
    scope: MemoryScope
    case_id: str = ""
    subject_ref: str = ""
    agent_id: str
    summary: str
    facts: Mapping[str, Any] = Field(default_factory=dict)
    source_run_id: str
    source_turn_id: str
    created_at: str
    expires_at: str
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL
    status: MemoryStatus = MemoryStatus.ACTIVE

    @field_validator("facts", mode="after")
    @classmethod
    def freeze_facts(cls, value: Any) -> Any:
        return freeze_value(value)


class MemoryQuery(FrozenModel):
    """Bounded memory lookup request."""

    scope: MemoryScope
    case_id: str = ""
    subject_ref: str = ""
    agent_id: str
    max_records: int = 5
    allow_restricted: bool = False
    consent_granted: bool = False
    query_text: str = ""


class MemoryAdmission(FrozenModel):
    """Control Plane decision for admitting memory into context."""

    admitted: bool
    included_memory_ids: tuple[str, ...] = Field(default_factory=tuple)
    summary: str = ""
    facts: Mapping[str, Any] = Field(default_factory=dict)
    rejected_memory_ids: tuple[str, ...] = Field(default_factory=tuple)
    rejection_reasons: Mapping[str, str] = Field(default_factory=dict)

    @field_validator("facts", "rejection_reasons", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        return freeze_value(value)
