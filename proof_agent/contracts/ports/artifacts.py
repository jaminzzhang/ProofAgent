from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import BinaryIO, Protocol

from proof_agent.contracts.artifacts import ArtifactObjectVersion, ArtifactPutRequest


class ArtifactStore(Protocol):
    def put_immutable(
        self,
        request: ArtifactPutRequest,
        body: BinaryIO,
    ) -> ArtifactObjectVersion: ...

    def head_exact(self, ref: ArtifactObjectVersion) -> ArtifactObjectVersion: ...

    def open_exact(self, ref: ArtifactObjectVersion) -> BinaryIO: ...

    def delete_exact(self, ref: ArtifactObjectVersion) -> None: ...

    def iter_versions_before(
        self,
        *,
        prefix: str,
        before: datetime,
    ) -> Iterator[ArtifactObjectVersion]: ...


__all__ = ["ArtifactStore"]
