from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from proof_agent.contracts._base import FrozenModel


class SharedAssetKind(str, Enum):
    """Versioned shared-configuration families referenced by Agent publication."""

    KNOWLEDGE_SOURCE = "knowledge_source"
    MODEL_CONNECTION = "model_connection"
    TOOL_SOURCE = "tool_source"


class SharedAssetVersionRequest(FrozenModel):
    """Request to resolve one shared asset to an immutable version."""

    kind: SharedAssetKind
    asset_id: str
    version_id: str | None = None


class SharedAssetVersionRef(FrozenModel):
    """Adapter-neutral immutable reference frozen into a published Agent version."""

    kind: SharedAssetKind
    asset_id: str
    version_id: str
    revision: int = Field(ge=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResolvedSharedAssetVersions(FrozenModel):
    """Exact, de-duplicated shared-asset versions resolved for publication."""

    versions: tuple[SharedAssetVersionRef, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def require_unique_assets(self) -> "ResolvedSharedAssetVersions":
        identities = [(item.kind, item.asset_id) for item in self.versions]
        if len(identities) != len(set(identities)):
            raise ValueError("shared asset resolution contains duplicate asset identities")
        return self
