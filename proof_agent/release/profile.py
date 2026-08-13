from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from proof_agent.release.contracts import (
    EvidenceRule,
    GateProfile,
    GateRule,
    MetricRule,
)
from proof_agent.release.digests import canonical_json_bytes, reject_duplicate_json_keys


@dataclass(frozen=True, slots=True)
class ReleaseProfile:
    """One immutable, complete policy used by producers and the verifier."""

    gate_profile: GateProfile
    source_bytes: bytes
    binding_bytes: bytes

    @property
    def gate_ids(self) -> tuple[str, ...]:
        return self.gate_profile.required_gate_ids

    @property
    def gates(self) -> tuple[GateRule, ...]:
        return self.gate_profile.gates


def initial_private_pilot_profile_source_bytes() -> bytes:
    return (
        resources.files("proof_agent.release")
        .joinpath("profiles")
        .joinpath("initial-private-pilot-v2.json")
        .read_bytes()
    )


def release_profile_binding_bytes(profile: ReleaseProfile) -> bytes:
    """Return the canonical bytes covered by Production Candidate Binding."""

    return canonical_json_bytes(profile.gate_profile)


def _load_initial_private_pilot_profile() -> ReleaseProfile:
    source_bytes = initial_private_pilot_profile_source_bytes()
    reject_duplicate_json_keys(source_bytes)
    gate_profile = GateProfile.model_validate_json(source_bytes)
    profile = ReleaseProfile(
        gate_profile=gate_profile,
        source_bytes=source_bytes,
        binding_bytes=b"",
    )
    return ReleaseProfile(
        gate_profile=gate_profile,
        source_bytes=source_bytes,
        binding_bytes=release_profile_binding_bytes(profile),
    )


INITIAL_PRIVATE_PILOT_PROFILE = _load_initial_private_pilot_profile()


def initial_private_pilot_profile_bytes() -> bytes:
    return INITIAL_PRIVATE_PILOT_PROFILE.binding_bytes


def initial_private_pilot_profile() -> ReleaseProfile:
    return INITIAL_PRIVATE_PILOT_PROFILE


__all__ = [
    "EvidenceRule",
    "GateRule",
    "INITIAL_PRIVATE_PILOT_PROFILE",
    "MetricRule",
    "ReleaseProfile",
    "initial_private_pilot_profile",
    "initial_private_pilot_profile_bytes",
    "initial_private_pilot_profile_source_bytes",
    "release_profile_binding_bytes",
]
