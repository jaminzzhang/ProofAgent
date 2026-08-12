"""Bounded offline verification of exact Release authority and projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogReader
from knowledge_source_service.ports.search_projection import (
    HybridSearchProjection,
    ProjectionAttestation,
)


class ReleaseIntegrityCatalog(KnowledgeCatalogReader, Protocol):
    def list_queryable_release_ids(
        self,
        *,
        after_release_id: str | None,
        limit: int,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class ReleaseIntegrityBatch:
    verified_releases: int
    next_release_id: str | None


class KnowledgeReleaseIntegrityWorker:
    """Replay PostgreSQL/S3 authority and verify any pinned search generation."""

    def __init__(
        self,
        *,
        catalog: ReleaseIntegrityCatalog,
        projection: HybridSearchProjection,
    ) -> None:
        self._catalog = catalog
        self._projection = projection

    def run_batch(
        self,
        *,
        after_release_id: str | None,
        limit: int,
    ) -> ReleaseIntegrityBatch:
        if not 1 <= limit <= 1000:
            raise ValueError("Release integrity batch limit is invalid")
        release_ids = self._catalog.list_queryable_release_ids(
            after_release_id=after_release_id,
            limit=limit,
        )
        if (
            len(release_ids) > limit
            or tuple(sorted(release_ids)) != release_ids
            or len(set(release_ids)) != len(release_ids)
            or (
                after_release_id is not None
                and any(release_id <= after_release_id for release_id in release_ids)
            )
        ):
            raise ValueError("Release integrity catalog returned an invalid page")
        for release_id in release_ids:
            release = self._catalog.get_release(release_id)
            if release is None or release.knowledge_base_release_id != release_id:
                raise ValueError("queryable Release could not be replayed exactly")
            for source_version_id in release.knowledge_source_version_ids:
                source = self._catalog.get_source_version(source_version_id)
                if (
                    source is None
                    or source.knowledge_source_version_id != source_version_id
                    or source.knowledge_space_id != release.knowledge_space_id
                ):
                    raise ValueError(
                        "Release member Source Version could not be replayed exactly"
                    )
            binding = release.retrieval_projection
            if binding is not None:
                self._projection.verify_generation(
                    ProjectionAttestation(
                        index_identity=binding.index_identity,
                        mapping_digest=binding.mapping_digest,
                        corpus_digest=binding.corpus_digest,
                        document_count=binding.document_count,
                    )
                )
        return ReleaseIntegrityBatch(
            verified_releases=len(release_ids),
            next_release_id=release_ids[-1] if release_ids else None,
        )
