from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from proof_agent.contracts.persistence import (
    PersistenceInvariantError,
    PersistenceNotFoundError,
)
from proof_agent.contracts.shared_assets import (
    ResolvedSharedAssetVersions,
    SharedAssetKind,
    SharedAssetVersionRef,
    SharedAssetVersionRequest,
)
from proof_agent.contracts.agent_configuration import SharedModelConnection, ToolSource


class KnowledgeAssetRepository(Protocol):
    """Resolve Knowledge Sources to immutable publication references."""

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None: ...


class ModelConnectionReader(Protocol):
    """Read the live model connection needed by runtime configuration resolution."""

    def get_model_connection(self, connection_id: str) -> SharedModelConnection | None: ...


class ModelAssetRepository(ModelConnectionReader, Protocol):
    """Resolve model connections to immutable publication references."""

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None: ...


class ToolSourceReader(Protocol):
    """Read the live Tool Source needed by runtime gateway construction."""

    def get_tool_source(self, source_id: str) -> ToolSource | None: ...


class ToolAssetRepository(ToolSourceReader, Protocol):
    """Resolve Tool Sources to immutable publication references."""

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None: ...


class RuntimeSharedAssetReader(ModelConnectionReader, ToolSourceReader, Protocol):
    """Narrow read-only asset seam used by one Published Agent execution."""

    pass


def resolve_shared_asset_versions(
    requests: Sequence[SharedAssetVersionRequest],
    *,
    knowledge: KnowledgeAssetRepository,
    models: ModelAssetRepository,
    tools: ToolAssetRepository,
) -> ResolvedSharedAssetVersions:
    """Resolve a publication's heterogeneous asset set exactly and fail closed."""

    repositories = {
        SharedAssetKind.KNOWLEDGE_SOURCE: knowledge,
        SharedAssetKind.MODEL_CONNECTION: models,
        SharedAssetKind.TOOL_SOURCE: tools,
    }
    versions: list[SharedAssetVersionRef] = []
    for request in requests:
        resolved = repositories[request.kind].resolve_version(
            request.asset_id,
            version_id=request.version_id,
        )
        requested_version = request.version_id or "<latest>"
        if resolved is None:
            raise PersistenceNotFoundError(
                resource_type=f"{request.kind.value}_version",
                resource_id=f"{request.asset_id}:{requested_version}",
            )
        if resolved.kind is not request.kind or resolved.asset_id != request.asset_id:
            raise PersistenceInvariantError("shared asset adapter returned a mismatched identity")
        if request.version_id is not None and resolved.version_id != request.version_id:
            raise PersistenceInvariantError("shared asset adapter returned a mismatched version")
        versions.append(resolved)
    return ResolvedSharedAssetVersions(versions=tuple(versions))
