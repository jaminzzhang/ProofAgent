from __future__ import annotations

from dataclasses import dataclass

from proof_agent.capabilities.persistence.postgres.model_repository import (
    PostgresModelAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.tool_repository import (
    PostgresToolAssetRepository,
)
from proof_agent.contracts.agent_configuration import SharedModelConnection, ToolSource


@dataclass(frozen=True)
class PostgresRuntimeSharedAssetReader:
    """Read-only Published Run facade over exact production asset repositories."""

    models: PostgresModelAssetRepository
    tools: PostgresToolAssetRepository

    def get_model_connection(self, connection_id: str) -> SharedModelConnection | None:
        return self.models.get_model_connection(connection_id)

    def get_tool_source(self, source_id: str) -> ToolSource | None:
        return self.tools.get_tool_source(source_id)


__all__ = ["PostgresRuntimeSharedAssetReader"]
