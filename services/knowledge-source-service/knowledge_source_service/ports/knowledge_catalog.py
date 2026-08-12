"""Read boundary for exact immutable Knowledge Base Releases."""

from __future__ import annotations

from typing import Protocol

from knowledge_source_service.domain.knowledge_catalog import (
    KnowledgeBaseReleaseSnapshot,
    KnowledgeSourceVersion,
)
from knowledge_source_service.domain.publications import (
    PublishedDatasetSourceVersion,
    PublishedDocumentSourceVersion,
    PublishedKnowledgeBaseRelease,
)


class KnowledgeCatalogReader(Protocol):
    """Resolve only exact release and source-version identities."""

    def get_release(self, knowledge_base_release_id: str) -> KnowledgeBaseReleaseSnapshot | None: ...

    def get_source_version(
        self, knowledge_source_version_id: str
    ) -> KnowledgeSourceVersion | None: ...


class KnowledgeCatalogWriter(Protocol):
    """Make already-finalized immutable snapshots visible."""

    def put_document_source_version(
        self,
        publication: PublishedDocumentSourceVersion,
    ) -> None: ...

    def put_dataset_source_version(
        self,
        publication: PublishedDatasetSourceVersion,
    ) -> None: ...

    def put_release(self, publication: PublishedKnowledgeBaseRelease) -> None: ...


class KnowledgeCatalog(KnowledgeCatalogReader, KnowledgeCatalogWriter, Protocol):
    """Exact read/write catalog used by intake and Release application services."""
