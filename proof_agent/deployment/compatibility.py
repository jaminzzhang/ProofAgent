"""Load, validate and canonically hash a Deployment Compatibility Manifest."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

from pydantic import TypeAdapter

from proof_agent.contracts.deployment import DeploymentCompatibilityManifest
from proof_agent.release.digests import (
    canonical_json_bytes,
    reject_duplicate_json_keys,
    sha256_hex,
)


MAX_COMPATIBILITY_EVIDENCE_AGE = timedelta(hours=72)
MAX_FUTURE_CLOCK_SKEW = timedelta(minutes=5)


def load_deployment_compatibility_manifest(
    path: Path,
    *,
    checked_at: datetime,
) -> DeploymentCompatibilityManifest:
    """Load one strict manifest and reject stale or future-dated compatibility proof."""

    raw = path.read_text(encoding="utf-8")
    reject_duplicate_json_keys(raw)
    payload = json.loads(raw)
    manifest = TypeAdapter(DeploymentCompatibilityManifest).validate_python(payload)
    validate_deployment_compatibility_freshness(manifest, checked_at=checked_at)
    return manifest


def validate_deployment_compatibility_freshness(
    manifest: DeploymentCompatibilityManifest,
    *,
    checked_at: datetime,
) -> None:
    if checked_at.utcoffset() is None:
        raise ValueError("compatibility checked_at must be timezone-aware")
    for component in manifest.components:
        verified_at = component.evidence.verified_at
        if verified_at > checked_at + MAX_FUTURE_CLOCK_SKEW:
            raise ValueError(
                f"{component.component_id} compatibility evidence is future-dated"
            )
        if checked_at - verified_at > MAX_COMPATIBILITY_EVIDENCE_AGE:
            raise ValueError(
                f"{component.component_id} compatibility evidence is older than 72 hours"
            )


def deployment_compatibility_sha256(
    manifest: DeploymentCompatibilityManifest,
) -> str:
    """Return the exact candidate-binding digest for the canonical manifest."""

    return sha256_hex(canonical_json_bytes(manifest))


__all__ = [
    "MAX_COMPATIBILITY_EVIDENCE_AGE",
    "deployment_compatibility_sha256",
    "load_deployment_compatibility_manifest",
    "validate_deployment_compatibility_freshness",
]
