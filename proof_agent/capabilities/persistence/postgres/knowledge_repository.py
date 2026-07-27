from __future__ import annotations

from proof_agent.capabilities.persistence.postgres._common import ConnectionSource
from proof_agent.capabilities.persistence.postgres._versioned_assets import (
    PostgresVersionedAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    knowledge_source_versions,
    knowledge_sources,
)
from proof_agent.contracts.agent_configuration import KnowledgeSource
from proof_agent.contracts.persistence import KnowledgeSourceRecord
from proof_agent.contracts.shared_assets import SharedAssetKind, SharedAssetVersionRef


class PostgresKnowledgeAssetRepository:
    def __init__(self, connection_source: ConnectionSource) -> None:
        self._assets = PostgresVersionedAssetRepository(
            connection_source,
            kind=SharedAssetKind.KNOWLEDGE_SOURCE,
            base_table=knowledge_sources,
            version_table=knowledge_source_versions,
            id_column_name="source_id",
        )

    def save_source(
        self,
        source: KnowledgeSource,
        *,
        expected_revision: int,
    ) -> SharedAssetVersionRef:
        return self._assets.save(
            source,
            asset_id=source.source_id,
            lifecycle_state=source.lifecycle_state.value,
            created_at=source.created_at,
            updated_at=source.updated_at,
            expected_revision=expected_revision,
        )

    def get_knowledge_source(self, source_id: str) -> KnowledgeSource | None:
        payload = self._assets.get_payload(source_id)
        return None if payload is None else KnowledgeSource.model_validate(payload)

    def get_source_record(self, source_id: str) -> KnowledgeSourceRecord | None:
        record = self._assets.get_payload_record(source_id)
        if record is None:
            return None
        payload, revision = record
        return KnowledgeSourceRecord(
            source=KnowledgeSource.model_validate(payload),
            revision=revision,
        )

    def list_knowledge_sources(self) -> tuple[KnowledgeSource, ...]:
        return tuple(
            KnowledgeSource.model_validate(payload) for payload in self._assets.list_payloads()
        )

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None:
        return self._assets.resolve_version(asset_id, version_id=version_id)
