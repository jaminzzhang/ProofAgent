"""S3-first creation of exact immutable Knowledge Base Releases."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from knowledge_source_service.application.projection_encoding import ProjectionTextEncoder
from knowledge_source_service.domain.identities import content_identifier, sha256_json
from knowledge_source_service.domain.knowledge_catalog import (
    DocumentSourceVersion,
    KnowledgeBaseReleaseSnapshot,
    KnowledgeSourceVersion,
    RetrievalProjectionBinding,
)
from knowledge_source_service.domain.publications import PublishedKnowledgeBaseRelease
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalog
from knowledge_source_service.ports.search_projection import (
    HybridSearchProjection,
    ProjectionEvidenceUnit,
)


@dataclass(frozen=True)
class PublishKnowledgeReleaseCommand:
    knowledge_space_id: str
    knowledge_base_id: str
    knowledge_source_version_ids: tuple[str, ...]


class KnowledgeReleaseApplication:
    """Finalize a manifest before making an exact Release queryable."""

    def __init__(
        self,
        *,
        artifacts: ImmutableArtifactStore,
        catalog: KnowledgeCatalog,
        projection: HybridSearchProjection | None = None,
        encoder: ProjectionTextEncoder | None = None,
    ) -> None:
        if (projection is None) != (encoder is None):
            raise ValueError("projection and encoder must be configured together")
        self._artifacts = artifacts
        self._catalog = catalog
        self._projection = projection
        self._encoder = encoder

    def publish(
        self,
        command: PublishKnowledgeReleaseCommand,
    ) -> PublishedKnowledgeBaseRelease:
        if not command.knowledge_source_version_ids:
            raise ValueError("a Knowledge Base Release requires at least one Source Version")
        if len(set(command.knowledge_source_version_ids)) != len(
            command.knowledge_source_version_ids
        ):
            raise ValueError("a Knowledge Base Release cannot repeat a Source Version")
        resolved_versions: list[KnowledgeSourceVersion] = []
        for source_version_id in command.knowledge_source_version_ids:
            version = self._catalog.get_source_version(source_version_id)
            if version is None:
                raise ValueError(
                    "a Knowledge Base Release references an unknown Source Version"
                )
            if version.knowledge_space_id != command.knowledge_space_id:
                raise ValueError(
                    "a Knowledge Base Release cannot contain cross-Space Source Versions"
                )
            resolved_versions.append(version)

        base_version_digest = sha256_json(
            {
                "space": command.knowledge_space_id,
                "base": command.knowledge_base_id,
                "source_versions": command.knowledge_source_version_ids,
            }
        )
        base_version_id = content_identifier("base-version", base_version_digest)
        projection_binding = self._build_projection(
            base_version_id=base_version_id,
            versions=tuple(resolved_versions),
        )
        manifest_payload: dict[str, object] = {
            "schema": "knowledge-release-manifest.v1",
            "base_version": base_version_id,
            "source_versions": command.knowledge_source_version_ids,
        }
        if projection_binding is not None:
            manifest_payload["retrieval_projection"] = {
                "index_identity": projection_binding.index_identity,
                "mapping_digest": projection_binding.mapping_digest,
                "corpus_digest": projection_binding.corpus_digest,
                "document_count": projection_binding.document_count,
                "dense_revision": projection_binding.dense_revision,
                "sparse_revision": projection_binding.sparse_revision,
                "dense_dimension": projection_binding.dense_dimension,
            }
        manifest_content = json.dumps(
            manifest_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        release_manifest_digest = f"sha256:{sha256(manifest_content).hexdigest()}"
        release_id = content_identifier("release", release_manifest_digest)
        release = KnowledgeBaseReleaseSnapshot(
            knowledge_space_id=command.knowledge_space_id,
            knowledge_base_id=command.knowledge_base_id,
            knowledge_base_version_id=base_version_id,
            knowledge_base_release_id=release_id,
            knowledge_source_version_ids=command.knowledge_source_version_ids,
            release_manifest_digest=release_manifest_digest,
            retrieval_projection=projection_binding,
        )
        object_key = (
            f"spaces/{command.knowledge_space_id}/bases/{command.knowledge_base_id}/"
            f"releases/{release_id}/release-manifest.json"
        )
        manifest_reference = self._artifacts.put_immutable(
            object_key=object_key,
            content=manifest_content,
            media_type="application/vnd.knowledge.release-manifest+json",
        )
        if (
            manifest_reference.sha256 != release_manifest_digest
            or self._artifacts.get_exact(manifest_reference) != manifest_content
        ):
            raise ValueError("Knowledge Base Release manifest failed exact verification")
        publication = PublishedKnowledgeBaseRelease(
            release=release,
            release_manifest_artifact=manifest_reference,
        )
        self._catalog.put_release(publication)
        return publication

    def _build_projection(
        self,
        *,
        base_version_id: str,
        versions: tuple[KnowledgeSourceVersion, ...],
    ) -> RetrievalProjectionBinding | None:
        documents = tuple(
            version for version in versions if isinstance(version, DocumentSourceVersion)
        )
        if not documents or self._projection is None or self._encoder is None:
            return None
        projection_digest = sha256_json(
            {
                "base_version_id": base_version_id,
                "dense_revision": self._encoder.dense_revision,
                "sparse_revision": self._encoder.sparse_revision,
                "dense_dimension": self._encoder.dense_dimension,
                "evidence_units": [
                    {
                        "knowledge_source_version_id": document.knowledge_source_version_id,
                        "evidence_unit_id": unit.evidence_unit_id,
                        "content_hash": unit.content_hash,
                    }
                    for document in documents
                    for unit in document.evidence_units
                ],
            }
        )
        index_identity = (
            f"kss-index-{projection_digest.removeprefix('sha256:')[:32]}"
        )
        projection_documents: list[ProjectionEvidenceUnit] = []
        for document in documents:
            for unit in document.evidence_units:
                encoded = self._encoder.encode(unit.text)
                projection_documents.append(
                    ProjectionEvidenceUnit(
                        evidence_unit_id=unit.evidence_unit_id,
                        knowledge_source_id=document.knowledge_source_id,
                        knowledge_source_version_id=(
                            document.knowledge_source_version_id
                        ),
                        text=unit.text,
                        content_hash=unit.content_hash,
                        dense_vector=encoded.dense_vector,
                        sparse_vector=encoded.sparse_vector,
                    )
                )
        attestation = self._projection.rebuild(
            index_identity=index_identity,
            dense_dimension=self._encoder.dense_dimension,
            documents=tuple(projection_documents),
        )
        return RetrievalProjectionBinding(
            index_identity=attestation.index_identity,
            mapping_digest=attestation.mapping_digest,
            corpus_digest=attestation.corpus_digest,
            document_count=attestation.document_count,
            dense_revision=self._encoder.dense_revision,
            sparse_revision=self._encoder.sparse_revision,
            dense_dimension=self._encoder.dense_dimension,
        )
