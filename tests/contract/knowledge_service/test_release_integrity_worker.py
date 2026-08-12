from __future__ import annotations

from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.integrity_worker import (
    KnowledgeReleaseIntegrityWorker,
)
from knowledge_source_service.domain.knowledge_catalog import (
    KnowledgeBaseReleaseSnapshot,
    RetrievalProjectionBinding,
)
from knowledge_source_service.ports.search_projection import ProjectionAttestation


class _InspectableCatalog(InMemoryKnowledgeCatalog):
    def __init__(self) -> None:
        super().__init__()
        self.release: KnowledgeBaseReleaseSnapshot | None = None

    def list_queryable_release_ids(
        self,
        *,
        after_release_id: str | None,
        limit: int,
    ) -> tuple[str, ...]:
        assert after_release_id is None
        assert limit == 25
        return ("release-integrity-1",)

    def get_release(
        self,
        knowledge_base_release_id: str,
    ) -> KnowledgeBaseReleaseSnapshot | None:
        assert knowledge_base_release_id == "release-integrity-1"
        return self.release


class _VerifyingProjection:
    def __init__(self) -> None:
        self.attestations: list[ProjectionAttestation] = []

    def verify_generation(self, attestation: ProjectionAttestation) -> None:
        self.attestations.append(attestation)


def test_integrity_worker_replays_exact_sources_and_projection_attestation() -> None:
    catalog = _InspectableCatalog()
    document = catalog.add_document(
        knowledge_space_id="space-integrity",
        knowledge_source_id="source-integrity",
        media_type="text/plain",
        content="Exact immutable policy.",
    )
    binding = RetrievalProjectionBinding(
        index_identity="index-integrity-1",
        mapping_digest=f"sha256:{'1' * 64}",
        corpus_digest=f"sha256:{'2' * 64}",
        document_count=1,
        dense_revision="dense-v1",
        sparse_revision="sparse-v1",
        dense_dimension=32,
    )
    catalog.release = KnowledgeBaseReleaseSnapshot(
        knowledge_space_id="space-integrity",
        knowledge_base_id="base-integrity",
        knowledge_base_version_id="base-version-integrity",
        knowledge_base_release_id="release-integrity-1",
        knowledge_source_version_ids=(document.knowledge_source_version_id,),
        release_manifest_digest=f"sha256:{'3' * 64}",
        retrieval_projection=binding,
    )
    projection = _VerifyingProjection()

    batch = KnowledgeReleaseIntegrityWorker(
        catalog=catalog,
        projection=projection,
    ).run_batch(after_release_id=None, limit=25)

    assert batch.verified_releases == 1
    assert batch.next_release_id == "release-integrity-1"
    assert projection.attestations == [
        ProjectionAttestation(
            index_identity=binding.index_identity,
            mapping_digest=binding.mapping_digest,
            corpus_digest=binding.corpus_digest,
            document_count=binding.document_count,
        )
    ]
