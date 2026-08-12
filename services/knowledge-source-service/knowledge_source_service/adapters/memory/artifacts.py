"""Deterministic immutable artifact adapter for tests only."""

from __future__ import annotations

from hashlib import sha256

from knowledge_source_service.domain.artifacts import ExactArtifactReference


class InMemoryImmutableArtifactStore:
    """Exercise exact-object semantics without becoming a production fallback."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[ExactArtifactReference, bytes]] = {}

    def put_immutable(
        self,
        *,
        object_key: str,
        content: bytes,
        media_type: str,
    ) -> ExactArtifactReference:
        if type(content) is not bytes or not content:
            raise ValueError("immutable artifact content must be nonempty exact bytes")
        digest_hex = sha256(content).hexdigest()
        reference = ExactArtifactReference(
            object_key=object_key,
            version_id=f"memory-version-{digest_hex}",
            sha256=f"sha256:{digest_hex}",
            size_bytes=len(content),
            media_type=media_type,
        )
        existing = self._objects.get(object_key)
        if existing is not None:
            if existing != (reference, content):
                raise ValueError("immutable artifact key already contains different bytes")
            return existing[0]
        self._objects[object_key] = (reference, content)
        return reference

    def get_exact(self, reference: ExactArtifactReference) -> bytes:
        stored = self._objects.get(reference.object_key)
        if stored is None or stored[0] != reference:
            raise ValueError("exact immutable artifact is unavailable")
        digest_hex = sha256(stored[1]).hexdigest()
        if f"sha256:{digest_hex}" != reference.sha256:
            raise ValueError("immutable artifact integrity check failed")
        return stored[1]

    def keys(self) -> tuple[str, ...]:
        """Expose deterministic test inspection without a production listing contract."""

        return tuple(sorted(self._objects))
