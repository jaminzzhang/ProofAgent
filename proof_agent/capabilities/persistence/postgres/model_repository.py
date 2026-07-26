from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
import yaml  # type: ignore[import-untyped]

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
)
from proof_agent.capabilities.persistence.postgres._versioned_assets import (
    PostgresVersionedAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    agent_drafts,
    agent_version_shared_asset_refs,
    knowledge_sources,
    model_connection_versions,
    model_connections,
)
from proof_agent.contracts.agent_configuration import (
    SharedModelConnection,
    SharedModelConnectionReferenceSummary,
)
from proof_agent.contracts.shared_assets import SharedAssetKind, SharedAssetVersionRef


class PostgresModelAssetRepository:
    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source
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

    def get_model_connection_reference_summary(
        self,
        connection_id: str,
    ) -> SharedModelConnectionReferenceSummary:
        """Count exact configuration references without loading secret material."""

        with read_connection(self._connection_source) as connection:
            draft_payloads = connection.execute(
                sa.select(agent_drafts.c.draft_json)
            ).scalars()
            draft_count = sum(
                _count_shared_model_connection_refs(payload, connection_id=connection_id)
                for payload in draft_payloads
            )
            published_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(agent_version_shared_asset_refs)
                .where(
                    agent_version_shared_asset_refs.c.asset_kind
                    == SharedAssetKind.MODEL_CONNECTION.value,
                    agent_version_shared_asset_refs.c.asset_id == connection_id,
                )
            ).scalar_one()
            knowledge_payloads = connection.execute(
                sa.select(knowledge_sources.c.configuration_json)
            ).scalars()
            knowledge_count = sum(
                _count_shared_model_connection_refs(payload, connection_id=connection_id)
                for payload in knowledge_payloads
            )
        return SharedModelConnectionReferenceSummary(
            connection_id=connection_id,
            draft_agent_reference_count=draft_count,
            published_agent_version_reference_count=published_count,
            knowledge_source_reference_count=knowledge_count,
            in_flight_operation_count=0,
            audit_retention_blocked=True,
        )

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None:
        return self._assets.resolve_version(asset_id, version_id=version_id)


def _count_shared_model_connection_refs(value: Any, *, connection_id: str) -> int:
    return sum(1 for item in _shared_model_connection_ids(value) if item == connection_id)


def _shared_model_connection_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            parsed = yaml.safe_load(value) or {}
        except yaml.YAMLError:
            return ()
        if parsed == value:
            return ()
        return _shared_model_connection_ids(parsed)
    if isinstance(value, Mapping):
        connection_ids: list[str] = []
        if value.get("model_source") == "shared" and isinstance(
            value.get("connection_id"), str
        ):
            connection_ids.append(value["connection_id"])
        for item in value.values():
            connection_ids.extend(_shared_model_connection_ids(item))
        return tuple(connection_ids)
    if isinstance(value, list | tuple):
        nested_connection_ids: list[str] = []
        for item in value:
            nested_connection_ids.extend(_shared_model_connection_ids(item))
        return tuple(nested_connection_ids)
    return ()
