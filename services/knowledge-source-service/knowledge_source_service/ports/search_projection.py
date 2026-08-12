"""Rebuildable hybrid search projection boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ProjectionEvidenceUnit:
    evidence_unit_id: str
    knowledge_source_id: str
    knowledge_source_version_id: str
    text: str
    content_hash: str
    dense_vector: tuple[float, ...]
    sparse_vector: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.evidence_unit_id or not self.text:
            raise ValueError("projection Evidence Unit identity and text are required")
        if not self.dense_vector or not self.sparse_vector:
            raise ValueError("projection dense and sparse vectors are required")


@dataclass(frozen=True)
class ProjectionAttestation:
    index_identity: str
    mapping_digest: str
    corpus_digest: str
    document_count: int


@dataclass(frozen=True)
class ProjectionLaneHit:
    lane: Literal["lexical", "sparse", "dense"]
    evidence_unit_id: str
    native_score: float
    lane_rank: int
    index_identity: str


@dataclass(frozen=True)
class HybridProjectionResult:
    lexical: tuple[ProjectionLaneHit, ...]
    sparse: tuple[ProjectionLaneHit, ...]
    dense: tuple[ProjectionLaneHit, ...]


class HybridSearchProjection(Protocol):
    def rebuild(
        self,
        *,
        index_identity: str,
        dense_dimension: int,
        documents: tuple[ProjectionEvidenceUnit, ...],
    ) -> ProjectionAttestation: ...

    def verify_generation(self, attestation: ProjectionAttestation) -> None: ...

    def query(
        self,
        *,
        index_identity: str,
        lexical_query: str,
        dense_vector: tuple[float, ...],
        sparse_vector: Mapping[str, float],
        top_k: int,
    ) -> HybridProjectionResult: ...
