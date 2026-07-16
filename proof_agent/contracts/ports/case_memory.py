from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from proof_agent.contracts.memory import MemoryQuery, MemoryRecord
from proof_agent.contracts.persistence import CaseMemoryAdmission


class CaseMemoryRepository(Protocol):
    """Admit, read, and expire initial-production Case Memory."""

    def admit(self, admission: CaseMemoryAdmission) -> MemoryRecord: ...

    def read(self, query: MemoryQuery, *, as_of: str) -> Sequence[MemoryRecord]: ...

    def expire_due(self, *, as_of: str) -> int: ...
