from __future__ import annotations

from proof_agent.capabilities.persistence.postgres._common import ConnectionSource
from proof_agent.capabilities.persistence.postgres._versioned_assets import (
    PostgresVersionedAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    model_connection_versions,
    model_connections,
)
from proof_agent.contracts.agent_configuration import SharedModelConnection
from proof_agent.contracts.shared_assets import SharedAssetKind, SharedAssetVersionRef


class PostgresModelAssetRepository:
    def __init__(self, connection_source: ConnectionSource) -> None:
        self._assets = PostgresVersionedAssetRepository(
            connection_source,
            kind=SharedAssetKind.MODEL_CONNECTION,
            base_table=model_connections,
            version_table=model_connection_versions,
            id_column_name="connection_id",
        )

    def save_connection(
        self,
        connection: SharedModelConnection,
        *,
        expected_revision: int,
    ) -> SharedAssetVersionRef:
        return self._assets.save(
            connection,
            asset_id=connection.connection_id,
            lifecycle_state=connection.lifecycle_state.value,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
            expected_revision=expected_revision,
        )

    def get_model_connection(self, connection_id: str) -> SharedModelConnection | None:
        payload = self._assets.get_payload(connection_id)
        return None if payload is None else SharedModelConnection.model_validate(payload)

    def list_model_connections(self) -> tuple[SharedModelConnection, ...]:
        return tuple(
            SharedModelConnection.model_validate(payload)
            for payload in self._assets.list_payloads()
        )

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None:
        return self._assets.resolve_version(asset_id, version_id=version_id)
