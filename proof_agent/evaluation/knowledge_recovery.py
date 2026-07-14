"""Fail-closed evidence contract for disposable Hybrid recovery drills."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import ConfigDict, Field

from proof_agent.contracts._base import FrozenModel
from proof_agent.evaluation.errors import EvaluationInputError


RecoveryFault = Literal[
    "fail_after_opensearch_refresh",
    "drop_generation_index",
    "corrupt_test_prefix_artifact",
    "cutover_then_rollback_agent_version",
]


class KnowledgeRecoveryResult(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fault: RecoveryFault
    passed: bool
    failed_gate: str | None
    prior_publication_visible: bool
    manifest_root_reproduced: bool
    attestation_reproduced: bool
    cleanup_idempotent: bool
    production_pointers_unchanged_before_cutover: bool
    rollback_pointer_restored: bool
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def run_recovery_drill(
    *,
    fault: RecoveryFault,
    disposable_test_marker: bool,
    expected_manifest_root: str,
    rebuilt_manifest_root: str,
    prior_publication_visible: bool = True,
    attestation_reproduced: bool = True,
    cleanup_idempotent: bool = True,
    production_pointers_unchanged_before_cutover: bool = True,
    rollback_pointer_restored: bool = True,
) -> KnowledgeRecoveryResult:
    """Evaluate evidence from a guarded fault run without hiding the first failed gate."""

    if not disposable_test_marker:
        raise EvaluationInputError("recovery fault injection requires a disposable-test marker")
    gates = (
        ("prior_publication_visibility", prior_publication_visible),
        ("manifest_root_reproduction", rebuilt_manifest_root == expected_manifest_root),
        ("attestation_reproduction", attestation_reproduced),
        ("cleanup_idempotence", cleanup_idempotent),
        ("pre_cutover_pointer_stability", production_pointers_unchanged_before_cutover),
        ("rollback_pointer_restoration", rollback_pointer_restored),
    )
    failed_gate = next((name for name, passed in gates if not passed), None)
    payload = {
        "fault": fault,
        "passed": failed_gate is None,
        "failed_gate": failed_gate,
        "prior_publication_visible": prior_publication_visible,
        "manifest_root_reproduced": rebuilt_manifest_root == expected_manifest_root,
        "attestation_reproduced": attestation_reproduced,
        "cleanup_idempotent": cleanup_idempotent,
        "production_pointers_unchanged_before_cutover": production_pointers_unchanged_before_cutover,
        "rollback_pointer_restored": rollback_pointer_restored,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return KnowledgeRecoveryResult(
        fault=fault,
        passed=failed_gate is None,
        failed_gate=failed_gate,
        prior_publication_visible=prior_publication_visible,
        manifest_root_reproduced=rebuilt_manifest_root == expected_manifest_root,
        attestation_reproduced=attestation_reproduced,
        cleanup_idempotent=cleanup_idempotent,
        production_pointers_unchanged_before_cutover=(
            production_pointers_unchanged_before_cutover
        ),
        rollback_pointer_restored=rollback_pointer_restored,
        artifact_sha256=digest,
    )


__all__ = ["KnowledgeRecoveryResult", "RecoveryFault", "run_recovery_drill"]
