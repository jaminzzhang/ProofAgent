from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class EvidenceStatus(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EvidenceChunk(FrozenModel):
    source: str
    content: str
    score: float
    status: EvidenceStatus
    citation: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)
