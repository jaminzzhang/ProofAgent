from __future__ import annotations

from datetime import datetime
from collections.abc import Callable
from typing import Protocol

from proof_agent.contracts.artifacts import (
    ArtifactManifest,
    ArtifactObjectVersion,
    ArtifactOwner,
    ArtifactOwnerBinding,
    BoundArtifactManifest,
)


class ArtifactReferenceRepository(Protocol):
    def commit_visible_manifest(
        self,
        manifest: ArtifactManifest,
        *,
        manifest_ref: ArtifactObjectVersion,
    ) -> ArtifactOwnerBinding: ...

    def get_visible_binding(
        self,
        owner: ArtifactOwner,
        *,
        now: datetime,
    ) -> ArtifactOwnerBinding | None: ...

    def get_manifest(self, manifest_id: str) -> ArtifactManifest | None: ...

    def get_bound_manifest(
        self,
        manifest_id: str,
        *,
        now: datetime,
    ) -> BoundArtifactManifest | None: ...

    def mark_corrupt(self, ref: ArtifactObjectVersion, *, now: datetime | None = None) -> int: ...

    def expire_due(self, *, now: datetime) -> int: ...

    def contains_exact(self, ref: ArtifactObjectVersion) -> bool: ...

    def delete_if_unreferenced(
        self,
        ref: ArtifactObjectVersion,
        *,
        deleter: Callable[[], None],
    ) -> bool: ...

    def list_bound_manifests(self) -> tuple[BoundArtifactManifest, ...]: ...


__all__ = ["ArtifactReferenceRepository"]
