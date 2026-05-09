from __future__ import annotations

from enum import Enum

from proof_agent.contracts._base import FrozenModel


class EvidenceStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EvidenceChunk(FrozenModel):
    source: str
    content: str
    score: float
    status: EvidenceStatus
