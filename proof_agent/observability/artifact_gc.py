from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from proof_agent.contracts.artifacts import ArtifactObjectVersion
from proof_agent.contracts.ports.artifact_references import ArtifactReferenceRepository
from proof_agent.contracts.ports.artifacts import ArtifactStore


ORPHAN_GRACE = timedelta(hours=24)
ORPHAN_HEALTH_LIMIT = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class ArtifactGcReport:
    scanned: int
    referenced: int
    deleted: int
    failed: int
    oldest_orphan_age_seconds: int | None
    release_healthy: bool
    dry_run: bool


class ArtifactGarbageCollector:
    """Reference-safe exact-version orphan collection with a mandatory grace window."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        repository: ArtifactReferenceRepository,
    ) -> None:
        self._store = store
        self._repository = repository

    def collect(self, *, now: datetime, dry_run: bool = True) -> ArtifactGcReport:
        if now.utcoffset() is None:
            raise ValueError("artifact GC timestamp must be timezone-aware")
        scanned = referenced = deleted = failed = 0
        oldest_age: timedelta | None = None
        for ref in self._store.iter_versions_before(
            prefix="objects/",
            before=now - ORPHAN_GRACE,
        ):
            scanned += 1
            if self._repository.contains_exact(ref):
                referenced += 1
                continue
            age = now - ref.created_at
            oldest_age = age if oldest_age is None else max(oldest_age, age)
            if dry_run:
                continue
            try:
                def delete_exact(exact: ArtifactObjectVersion = ref) -> None:
                    self._store.delete_exact(exact)

                removed = self._repository.delete_if_unreferenced(
                    ref,
                    deleter=delete_exact,
                )
            except Exception:
                failed += 1
                continue
            if removed:
                deleted += 1
            else:
                referenced += 1
        return ArtifactGcReport(
            scanned=scanned,
            referenced=referenced,
            deleted=deleted,
            failed=failed,
            oldest_orphan_age_seconds=(
                None if oldest_age is None else max(0, int(oldest_age.total_seconds()))
            ),
            release_healthy=(
                failed == 0 and (oldest_age is None or oldest_age <= ORPHAN_HEALTH_LIMIT)
            ),
            dry_run=dry_run,
        )


__all__ = [
    "ArtifactGarbageCollector",
    "ArtifactGcReport",
    "ORPHAN_GRACE",
    "ORPHAN_HEALTH_LIMIT",
]
