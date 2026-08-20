"""Deployment-owned registry of external snapshot connections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from knowledge_source_service.ports.snapshots import JsonSnapshotReader


@dataclass(frozen=True)
class JsonSnapshotConnection:
    """One admitted connection without exposing its endpoint or credential."""

    connection_id: str
    connection_kind: Literal["http_json", "postgresql"]
    reader: JsonSnapshotReader

    def __post_init__(self) -> None:
        if not self.connection_id.strip():
            raise ValueError("snapshot connection identity must not be blank")


class KnowledgeSnapshotConnectionRegistry(Protocol):
    def contains(self, connection_id: str) -> bool: ...

    def resolve(self, connection_id: str) -> JsonSnapshotConnection: ...
