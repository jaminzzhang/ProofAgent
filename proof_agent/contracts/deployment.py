"""Strict contracts for candidate-bound production dependency compatibility."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import AnyUrl, Field, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel


DeploymentComponentId = Literal[
    "postgresql",
    "s3",
    "oidc",
    "secret_provider",
    "gateway",
    "model_provider",
    "read_only_tool",
]
ToolMode = Literal["disabled", "read_only_https"]

REQUIRED_COMPONENT_IDS = frozenset(
    {"postgresql", "s3", "oidc", "secret_provider", "gateway", "model_provider"}
)
REQUIRED_CAPABILITIES: dict[str, frozenset[str]] = {
    "postgresql": frozenset({"transactions", "advisory_lock", "pitr"}),
    "s3": frozenset(
        {"versioning", "conditional_put", "exact_version_read", "exact_version_delete"}
    ),
    "oidc": frozenset({"discovery", "jwks", "refresh", "revocation", "recovery_group"}),
    "secret_provider": frozenset({"validate", "resolve", "revoke", "rotate"}),
    "gateway": frozenset({"tls", "sse", "atomic_reload"}),
    "model_provider": frozenset(
        {"governed_calls", "timeout", "rate_limit", "provider_errors"}
    ),
    "read_only_tool": frozenset({"read_only", "schema_validation", "authorization"}),
}
_GENERIC_PRODUCT_CLAIMS = frozenset(
    {
        "s3-compatible storage",
        "s3 compatible storage",
        "oidc provider",
        "secret provider",
        "gateway",
        "model provider",
        "compatible service",
    }
)
_UNVERSIONED_MARKERS = frozenset({"latest", "stable", "tbd", "unknown", "unversioned"})


class ImmutableServiceReference(StrictFrozenModel):
    """Digest or provider-owned immutable revision for one exact deployed service."""

    kind: Literal["sha256", "service_revision"]
    value: str = Field(min_length=8, max_length=255)

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        normalized = self.value.strip().lower()
        if self.value.strip() != self.value or normalized in _UNVERSIONED_MARKERS:
            raise ValueError("immutable_reference must name an exact immutable value")
        if self.kind == "sha256" and (
            len(self.value) != 64
            or any(char not in "0123456789abcdef" for char in self.value)
        ):
            raise ValueError("sha256 immutable_reference must be 64 lowercase hex characters")
        if self.kind == "service_revision" and not any(char.isdigit() for char in self.value):
            raise ValueError("service_revision must contain an exact build or revision number")
        return self


class CompatibilityEvidenceRef(StrictFrozenModel):
    """Content-addressed evidence for one exact dependency compatibility exercise."""

    artifact_uri: str = Field(pattern=r"^artifact://sha256/[0-9a-f]{64}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    length: int = Field(gt=0, le=1_073_741_824)
    verified_at: datetime

    @field_validator("verified_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("compatibility evidence timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def bind_uri_to_digest(self) -> Self:
        if self.artifact_uri != f"artifact://sha256/{self.sha256}":
            raise ValueError("compatibility evidence URI and SHA-256 must match")
        return self


class DeploymentCompatibilityComponent(StrictFrozenModel):
    """Concrete version, endpoint and tested capability binding for one dependency."""

    component_id: DeploymentComponentId
    product: str = Field(min_length=1, max_length=128)
    product_version: str = Field(min_length=1, max_length=128)
    immutable_reference: ImmutableServiceReference
    endpoint_origin: AnyUrl
    authentication_method: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    adapter_protocol_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    tested_capabilities: tuple[str, ...] = Field(min_length=1, max_length=32)
    evidence: CompatibilityEvidenceRef

    @field_validator("product", "product_version")
    @classmethod
    def reject_untrimmed_text(cls, value: str) -> str:
        if value.strip() != value or any(ord(char) < 32 for char in value):
            raise ValueError("product identity fields must be trimmed and printable")
        return value

    @field_validator("product")
    @classmethod
    def reject_generic_product_claim(cls, value: str) -> str:
        if value.casefold() in _GENERIC_PRODUCT_CLAIMS:
            raise ValueError("product cannot be a generic compatibility claim")
        return value

    @field_validator("product_version")
    @classmethod
    def require_exact_product_version(cls, value: str) -> str:
        if value.casefold() in _UNVERSIONED_MARKERS or not any(char.isdigit() for char in value):
            raise ValueError("product_version must be an exact version, not a mutable label")
        return value

    @model_validator(mode="after")
    def require_credential_free_exact_endpoint(self) -> Self:
        value = self.endpoint_origin
        if value.username is not None or value.password is not None:
            raise ValueError("dependency endpoint_origin cannot contain credentials")
        if value.query is not None or value.fragment is not None:
            raise ValueError("dependency endpoint_origin cannot contain query or fragment")
        if self.component_id == "postgresql":
            if (
                value.scheme != "postgresql"
                or value.host is None
                or value.port is None
                or value.path is None
                or value.path in {"", "/"}
                or value.path.count("/") != 1
            ):
                raise ValueError(
                    "PostgreSQL endpoint_origin must be "
                    "postgresql://host:port/database without credentials"
                )
        elif value.scheme != "https" or value.path not in (None, "/"):
            raise ValueError(
                "network dependency endpoint_origin must be an exact HTTPS origin"
            )
        return self

    @field_validator("tested_capabilities", mode="before")
    @classmethod
    def canonicalize_capabilities(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        return tuple(sorted(value))

    @model_validator(mode="after")
    def require_component_capabilities(self) -> Self:
        if len(self.tested_capabilities) != len(set(self.tested_capabilities)):
            raise ValueError("tested capabilities must be unique")
        if any(
            not capability
            or len(capability) > 64
            or any(
                not (char.islower() or char.isdigit() or char == "_")
                for char in capability
            )
            for capability in self.tested_capabilities
        ):
            raise ValueError("tested capabilities must use safe lowercase identifiers")
        missing = REQUIRED_CAPABILITIES[self.component_id].difference(
            self.tested_capabilities
        )
        if missing:
            raise ValueError(
                "missing tested capabilities for "
                f"{self.component_id}: {', '.join(sorted(missing))}"
            )
        return self


class DeploymentCompatibilityManifest(StrictFrozenModel):
    """Complete secret-free compatibility binding for one production environment."""

    schema_version: Literal["proofagent.deployment-compatibility.v1"]
    topology: Literal["single_host_blue_green"]
    tls_required: Literal[True]
    tool_mode: ToolMode
    components: tuple[DeploymentCompatibilityComponent, ...] = Field(
        max_length=7,
    )

    @field_validator("components", mode="before")
    @classmethod
    def canonicalize_components(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        return tuple(
            sorted(
                value,
                key=lambda component: (
                    str(component.get("component_id", ""))
                    if isinstance(component, dict)
                    else str(getattr(component, "component_id", ""))
                ),
            )
        )

    @model_validator(mode="after")
    def require_exact_component_set(self) -> Self:
        component_ids = [component.component_id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("deployment component identities must be unique")
        actual = set(component_ids)
        expected = set(REQUIRED_COMPONENT_IDS)
        if self.tool_mode == "read_only_https":
            expected.add("read_only_tool")
        if actual != expected:
            missing = sorted(expected.difference(actual))
            unexpected = sorted(actual.difference(expected))
            details: list[str] = []
            if missing:
                details.append(f"missing={','.join(missing)}")
            if unexpected:
                details.append(f"unexpected={','.join(unexpected)}")
            raise ValueError("deployment manifest required components mismatch: " + "; ".join(details))
        return self


__all__ = [
    "CompatibilityEvidenceRef",
    "DeploymentCompatibilityComponent",
    "DeploymentCompatibilityManifest",
    "DeploymentComponentId",
    "ImmutableServiceReference",
    "REQUIRED_CAPABILITIES",
    "REQUIRED_COMPONENT_IDS",
    "ToolMode",
]
