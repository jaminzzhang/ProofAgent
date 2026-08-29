"""Adapt the exact Release builder to the Preparation Worker seam."""

from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.base_preparations import KnowledgeBaseVersion
from knowledge_source_service.domain.publications import PreparedKnowledgeBaseRelease


class KnowledgeReleaseCandidateBuilder:
    def __init__(self, *, releases: KnowledgeReleaseApplication) -> None:
        self._releases = releases

    def build(self, base_version: KnowledgeBaseVersion) -> PreparedKnowledgeBaseRelease:
        return self._releases.prepare(
            PublishKnowledgeReleaseCommand(
                knowledge_space_id=base_version.knowledge_space_id,
                knowledge_base_id=base_version.knowledge_base_id,
                knowledge_source_version_ids=tuple(
                    member.knowledge_source_version_id for member in base_version.members
                ),
            )
        )
