from __future__ import annotations

from datetime import datetime
from typing import Protocol

from proof_agent.contracts.artifacts import ArtifactObjectVersion
from proof_agent.contracts.release_registry import (
    ReleaseFinalization,
    ReleaseRegistryRecord,
)


class ReleaseRegistryConflictError(RuntimeError):
    """A release already exists or no longer satisfies a conditional transition."""


class ReleaseRegistryNotFoundError(LookupError):
    """The requested release does not exist."""


class ReleaseRegistryRepository(Protocol):
    def create_preparing(self, record: ReleaseRegistryRecord) -> ReleaseRegistryRecord: ...

    def finalize(
        self,
        release_id: str,
        finalization: ReleaseFinalization,
    ) -> ReleaseRegistryRecord: ...

    def get(self, release_id: str) -> ReleaseRegistryRecord | None: ...

    def list(self) -> tuple[ReleaseRegistryRecord, ...]: ...

    def resolve_exact_visible(
        self,
        ref: ArtifactObjectVersion,
        *,
        now: datetime,
    ) -> ArtifactObjectVersion | None: ...


__all__ = [
    "ReleaseRegistryConflictError",
    "ReleaseRegistryNotFoundError",
    "ReleaseRegistryRepository",
]
