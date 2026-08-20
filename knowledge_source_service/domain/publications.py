"""Immutable artifact bindings made visible by Source and Release publication."""

from __future__ import annotations

from dataclasses import dataclass

from knowledge_source_service.domain.artifacts import ExactArtifactReference
from knowledge_source_service.domain.knowledge_catalog import (
    DatasetSourceVersion,
    DocumentSourceVersion,
    KnowledgeBaseReleaseSnapshot,
)


@dataclass(frozen=True)
class PublishedDocumentSourceVersion:
    version: DocumentSourceVersion
    original_artifact: ExactArtifactReference
    canonical_artifact: ExactArtifactReference
    evidence_manifest_artifact: ExactArtifactReference
    processing_lineage_digest: str


@dataclass(frozen=True)
class PublishedDatasetSourceVersion:
    version: DatasetSourceVersion
    original_artifact: ExactArtifactReference
    canonical_artifact: ExactArtifactReference
    evidence_manifest_artifact: ExactArtifactReference
    processing_lineage_digest: str


@dataclass(frozen=True)
class PublishedKnowledgeBaseRelease:
    release: KnowledgeBaseReleaseSnapshot
    release_manifest_artifact: ExactArtifactReference
