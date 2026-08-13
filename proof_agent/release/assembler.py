from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from proof_agent.release.contracts import (
    GateResult,
    ProductionCandidateBinding,
    ReleaseGateManifest,
)
from proof_agent.release.digests import candidate_binding_sha256, digest_ref
from proof_agent.release.profile import INITIAL_PRIVATE_PILOT_PROFILE


def assemble_release_manifest(
    *,
    candidate: ProductionCandidateBinding,
    results: Sequence[GateResult],
    generated_at: datetime,
) -> ReleaseGateManifest:
    """Close a partial gate set into a complete, fail-closed release manifest."""

    profile = INITIAL_PRIVATE_PILOT_PROFILE
    packaged_profile_digest = digest_ref(profile.binding_bytes)
    if candidate.gate_profile != packaged_profile_digest:
        raise ValueError("candidate is not bound to the packaged Gate Profile")

    counts = Counter(result.gate_id for result in results)
    duplicates = tuple(gate_id for gate_id, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate gate results: {', '.join(sorted(duplicates))}")
    unknown = tuple(gate_id for gate_id in counts if gate_id not in profile.gate_ids)
    if unknown:
        raise ValueError(f"unknown gate results: {', '.join(sorted(unknown))}")

    binding = candidate_binding_sha256(candidate)
    supplied = {result.gate_id: result for result in results}
    for result in supplied.values():
        if result.candidate_binding_sha256 != binding:
            raise ValueError(f"gate result binding mismatch: {result.gate_id}")

    complete_results = tuple(
        supplied.get(gate_id)
        or GateResult(
            gate_id=gate_id,
            status="not_run",
            candidate_binding_sha256=binding,
            evidence=(),
            metrics={},
            blocker_codes=(f"gate.not_run:{gate_id}",),
        )
        for gate_id in profile.gate_ids
    )
    return ReleaseGateManifest(
        schema_version="proofagent.release-gate-manifest.v2",
        profile_id=profile.gate_profile.profile_id,
        candidate=candidate,
        results=complete_results,
        generated_at=generated_at,
    )


__all__ = ["assemble_release_manifest"]
