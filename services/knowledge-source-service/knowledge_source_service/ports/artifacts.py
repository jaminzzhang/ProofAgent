"""Immutable artifact authority boundary."""

from __future__ import annotations

from typing import Protocol

from knowledge_source_service.domain.artifacts import ExactArtifactReference


class ImmutableArtifactStore(Protocol):
    """Write and retrieve exact versioned bytes without mutable-key semantics."""

    def put_immutable(
        self,
        *,
        object_key: str,
        content: bytes,
        media_type: str,
    ) -> ExactArtifactReference: ...

    def get_exact(self, reference: ExactArtifactReference) -> bytes: ...
