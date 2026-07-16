from __future__ import annotations

from proof_agent.capabilities.persistence.postgres._common import ConnectionSource
from proof_agent.capabilities.persistence.postgres._versioned_assets import (
    PostgresVersionedAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import tool_source_versions, tool_sources
from proof_agent.contracts.agent_configuration import ToolSource
from proof_agent.contracts.shared_assets import SharedAssetKind, SharedAssetVersionRef


class PostgresToolAssetRepository:
    def __init__(self, connection_source: ConnectionSource) -> None:
        self._assets = PostgresVersionedAssetRepository(
            connection_source,
            kind=SharedAssetKind.TOOL_SOURCE,
            base_table=tool_sources,
            version_table=tool_source_versions,
            id_column_name="source_id",
        )

    def save_source(
        self,
        source: ToolSource,
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

    def get_tool_source(self, source_id: str) -> ToolSource | None:
        payload = self._assets.get_payload(source_id)
        return None if payload is None else ToolSource.model_validate(payload)

    def list_tool_sources(self) -> tuple[ToolSource, ...]:
        return tuple(ToolSource.model_validate(payload) for payload in self._assets.list_payloads())

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None:
        return self._assets.resolve_version(asset_id, version_id=version_id)
