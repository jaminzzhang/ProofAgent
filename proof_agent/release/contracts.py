from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, Self, TypeAlias, cast

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from proof_agent.contracts._base import FrozenModel, freeze_value


Sha256: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
GateStatus: TypeAlias = Literal["passed", "failed", "skipped", "error", "not_run"]

_SourceCommit: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{40}$"),
]
_OciDigest: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]
_NonEmptyString: TypeAlias = Annotated[str, StringConstraints(min_length=1)]
_NonNegativeInt: TypeAlias = Annotated[int, Field(ge=0)]
_MetricValue: TypeAlias = float | int | str | bool


INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS: tuple[str, ...] = (
    "backend_frontend_quality",
    "distribution_image",
    "supply_chain_runtime_security",
    "identity_authorization",
    "secrets_egress",
    "deterministic_evaluation",
    "real_llm_evaluation",
    "dependency_compatibility",
    "capacity_responsiveness",
    "queue_progress",
    "resilience_recovery",
    "deployment",
    "browser_operations",
)


class StrictFrozenModel(FrozenModel):
    """Strict, closed, immutable base for release-boundary contracts."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
    )


class DigestRef(StrictFrozenModel):
    sha256: Sha256
    length: _NonNegativeInt


class ProductionCandidateBinding(StrictFrozenModel):
    schema_version: Literal["proofagent.candidate-binding.v1"]
    source_commit: _SourceCommit
    clean_tree: Literal[True]
    product_version: _NonEmptyString
    oci_digest: _OciDigest
    python_distribution: DigestRef
    dashboard_assets: DigestRef
    operator_chat_assets: DigestRef
    migration_set: DigestRef
    agent_id: Literal["agent_management_insurance_specialist"]
    agent_version: _NonEmptyString
    agent_bundle: DigestRef
    evaluation_contract: DigestRef
    configuration_snapshot: DigestRef
    gate_profile: DigestRef
    deployment_compatibility_manifest: DigestRef


class EvidenceRef(StrictFrozenModel):
    evidence_id: _NonEmptyString
    kind: _NonEmptyString
    uri: _NonEmptyString
    digest: DigestRef
    candidate_binding_sha256: Sha256
    produced_at: AwareDatetime
    expires_at: AwareDatetime | None = None


class GateResult(StrictFrozenModel):
    gate_id: _NonEmptyString
    status: GateStatus
    candidate_binding_sha256: Sha256
    evidence: tuple[EvidenceRef, ...]
    metrics: Mapping[str, _MetricValue]
    blocker_codes: tuple[str, ...] = ()

    @field_validator("metrics", mode="after")
    @classmethod
    def freeze_metrics(
        cls,
        value: Mapping[str, _MetricValue],
    ) -> Mapping[str, _MetricValue]:
        return cast("Mapping[str, _MetricValue]", freeze_value(value))

    @field_serializer("metrics")
    def serialize_metrics(self, value: Mapping[str, _MetricValue]) -> dict[str, _MetricValue]:
        return dict(value)


class ReleaseGateManifest(StrictFrozenModel):
    schema_version: Literal["proofagent.release-gate-manifest.v1"]
    profile_id: Literal["initial-private-pilot-v1"]
    candidate: ProductionCandidateBinding
    results: tuple[GateResult, ...]
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def reject_duplicate_gate_ids(self) -> Self:
        gate_ids = tuple(result.gate_id for result in self.results)
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError("ReleaseGateManifest gate ids must be unique")
        return self


class GateProfile(StrictFrozenModel):
    schema_version: Literal["proofagent.gate-profile.v1"]
    profile_id: Literal["initial-private-pilot-v1"]
    required_gate_ids: tuple[str, ...]

    @model_validator(mode="after")
    def require_initial_private_pilot_gates(self) -> Self:
        if self.required_gate_ids != INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS:
            raise ValueError(
                "initial-private-pilot-v1 required_gate_ids must match the package-owned profile"
            )
        return self
