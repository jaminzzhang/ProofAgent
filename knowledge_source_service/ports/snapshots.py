"""Provider-neutral immutable snapshot boundaries for external data."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from knowledge_source_service.domain.identities import is_sha256_digest


class JsonSnapshot:
    """One bounded JSON observation captured before any Knowledge Query."""

    def __init__(
        self,
        *,
        content: bytes,
        source_identity_digest: str,
        observed_at: datetime,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        if type(content) is not bytes or not content:
            raise ValueError("JSON snapshot content must be nonempty exact bytes")
        if not is_sha256_digest(source_identity_digest):
            raise ValueError("snapshot source identity digest is invalid")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("snapshot observation time must be timezone-aware")
        if any(
            value is not None and (not value.strip() or len(value) > 512)
            for value in (etag, last_modified)
        ):
            raise ValueError("snapshot revision metadata is invalid")
        self.content = content
        self.source_identity_digest = source_identity_digest
        self.observed_at = observed_at
        self.etag = etag
        self.last_modified = last_modified


class JsonSnapshotReader(Protocol):
    """Capture one external JSON revision without exposing query-time access."""

    def read(self) -> JsonSnapshot: ...
