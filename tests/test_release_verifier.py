from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from proof_agent.delivery import cli as cli_module
from proof_agent.release.contracts import (
    DigestRef,
    EvidenceRef,
    GateResult,
    ProductionCandidateBinding,
    ReleaseGateManifest,
)
from proof_agent.release.digests import (
    build_content_addressed_uri,
    candidate_binding_sha256,
    canonical_json_bytes,
    digest_ref,
    parse_content_addressed_uri,
)
from proof_agent.release.profile import (
    INITIAL_PRIVATE_PILOT_PROFILE,
    initial_private_pilot_profile_bytes,
)
from proof_agent.release.verifier import (
    EvidenceRootArtifactReader,
    ReleaseDecision,
    verify_release_manifest,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SOURCE_COMMIT = "c" * 40
GENERATED_AT = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)
CHECKED_AT = GENERATED_AT + timedelta(hours=1)


class MappingArtifactReader:
    def __init__(self, artifacts: dict[str, bytes], error_ids: set[str] | None = None) -> None:
        self.artifacts = artifacts
        self.error_ids = error_ids or set()

    def read(self, evidence: EvidenceRef) -> bytes:
        if evidence.evidence_id in self.error_ids:
            raise OSError("artifact unavailable")
        return self.artifacts[evidence.evidence_id]


class AttestationStub:
    def __init__(self, *, accepted: bool = True, raises: bool = False) -> None:
        self.accepted = accepted
        self.raises = raises
        self.calls = 0

    def verify(
        self,
        *,
        evidence: EvidenceRef,
        artifact: bytes,
        candidate_binding_sha256: str,
    ) -> bool:
        del evidence, artifact, candidate_binding_sha256
        self.calls += 1
        if self.raises:
            raise RuntimeError("attestation backend unavailable")
        return self.accepted


VALID_METRICS: dict[str, dict[str, bool | int | float | str]] = {
    "backend_frontend_quality": {
        "line_coverage_percent": 90,
        "required_command_failures": 0,
        "required_integration_skips": 0,
    },
    "distribution_image": {
        "clean_install_passed": True,
        "image_readiness_passed": True,
    },
    "supply_chain_runtime_security": {
        "unresolved_critical_findings": 0,
        "unresolved_high_findings": 0,
        "runtime_hardening_passed": True,
    },
    "identity_authorization": {"required_checks_passed": True},
    "secrets_egress": {"required_checks_passed": True},
    "deterministic_evaluation": {
        "required_case_failures": 0,
        "required_case_skips": 0,
    },
    "real_llm_evaluation": {
        "required_case_failures": 0,
        "required_case_skips": 0,
        "sample_count": 1,
    },
    "dependency_compatibility": {
        "postgresql_bound": True,
        "s3_bound": True,
        "oidc_bound": True,
        "secret_provider_bound": True,
        "gateway_bound": True,
        "model_bound": True,
        "tool_mode_bound": True,
        "deployment_compatibility_manifest_sha256": "d" * 64,
    },
    "capacity_responsiveness": {
        "online_sessions": 20,
        "active_attempts": 5,
        "queued_runs": 50,
        "overload_request_51_passed": True,
        "load_duration_seconds": 1800,
        "admission_sample_count": 200,
        "first_progress_sample_count": 200,
        "terminal_sample_count": 100,
        "admission_p95_ms": 500,
        "first_progress_p95_ms": 1000,
        "free_slot_start_p95_ms": 1000,
        "standard_terminal_p95_ms": 60000,
        "max_attempt_terminal_ms": 120000,
    },
    "queue_progress": {
        "required_checks_passed": True,
        "soak_duration_seconds": 14400,
    },
    "resilience_recovery": {
        "fault_matrix_passed": True,
        "reference_digest_verification_percent": 100,
        "rpo_minutes": 15,
        "rto_minutes": 240,
        "topology_sha256": "f" * 64,
        "backup_policy_sha256": "1" * 64,
        "migration_set_sha256": "e" * 64,
    },
    "deployment": {
        "required_checks_passed": True,
        "drain_seconds": 150,
        "soak_seconds": 1800,
        "topology_sha256": "f" * 64,
        "backup_policy_sha256": "1" * 64,
        "migration_set_sha256": "e" * 64,
        "deployment_compatibility_manifest_sha256": "d" * 64,
    },
    "browser_operations": {
        "required_checks_passed": True,
        "pilot_operator_count": 3,
        "support_window_seconds": 32400,
        "required_scenario_coverage_percent": 100,
    },
}


EVIDENCE_KINDS: dict[str, tuple[str, ...]] = {
    "backend_frontend_quality": ("candidate_static",),
    "distribution_image": ("candidate_static",),
    "supply_chain_runtime_security": ("vulnerability_scan",),
    "identity_authorization": ("production_dependency",),
    "secrets_egress": ("production_dependency",),
    "deterministic_evaluation": ("candidate_static",),
    "real_llm_evaluation": ("real_llm",),
    "dependency_compatibility": ("production_dependency",),
    "capacity_responsiveness": ("load",),
    "queue_progress": ("load",),
    "resilience_recovery": ("fault", "combined_restore"),
    "deployment": ("blue_green",),
    "browser_operations": ("browser",),
}


MAX_AGES: dict[str, timedelta | None] = {
    "candidate_static": None,
    "vulnerability_scan": timedelta(hours=24),
    "production_dependency": timedelta(hours=72),
    "real_llm": timedelta(hours=72),
    "load": timedelta(hours=72),
    "fault": timedelta(hours=72),
    "combined_restore": timedelta(days=30),
    "blue_green": timedelta(hours=72),
    "browser": timedelta(hours=72),
}


def _candidate(**overrides: Any) -> ProductionCandidateBinding:
    profile_bytes = initial_private_pilot_profile_bytes()
    values: dict[str, Any] = {
        "schema_version": "proofagent.candidate-binding.v1",
        "source_commit": SOURCE_COMMIT,
        "clean_tree": True,
        "product_version": "0.1.0",
        "oci_digest": f"sha256:{SHA_A}",
        "python_distribution": DigestRef(sha256=SHA_A, length=1),
        "dashboard_assets": DigestRef(sha256=SHA_A, length=1),
        "operator_chat_assets": DigestRef(sha256=SHA_A, length=1),
        "migration_set": DigestRef(sha256="e" * 64, length=1),
        "agent_id": "agent_management_insurance_specialist",
        "agent_version": "2026.07.12",
        "agent_bundle": DigestRef(sha256=SHA_A, length=1),
        "evaluation_contract": DigestRef(sha256=SHA_A, length=1),
        "configuration_snapshot": DigestRef(sha256=SHA_A, length=1),
        "gate_profile": digest_ref(profile_bytes),
        "deployment_compatibility_manifest": DigestRef(sha256="d" * 64, length=12),
    }
    values.update(overrides)
    return ProductionCandidateBinding(**values)


def _valid_manifest() -> tuple[ReleaseGateManifest, dict[str, bytes]]:
    candidate = _candidate()
    binding = candidate_binding_sha256(candidate)
    artifacts: dict[str, bytes] = {}
    results: list[GateResult] = []
    for gate_id in INITIAL_PRIVATE_PILOT_PROFILE.gate_ids:
        evidence_items: list[EvidenceRef] = []
        for kind in EVIDENCE_KINDS[gate_id]:
            evidence_id = f"{gate_id}-{kind}"
            artifact = canonical_json_bytes({"evidence_id": evidence_id})
            artifacts[evidence_id] = artifact
            max_age = MAX_AGES[kind]
            produced_at = GENERATED_AT - timedelta(hours=1)
            expires_at = None if max_age is None else produced_at + max_age
            artifact_digest = digest_ref(artifact)
            evidence_items.append(
                EvidenceRef(
                    evidence_id=evidence_id,
                    kind=kind,
                    uri=build_content_addressed_uri(artifact_digest.sha256),
                    digest=artifact_digest,
                    candidate_binding_sha256=binding,
                    produced_at=produced_at,
                    expires_at=expires_at,
                )
            )
        results.append(
            GateResult(
                gate_id=gate_id,
                status="passed",
                candidate_binding_sha256=binding,
                evidence=tuple(evidence_items),
                metrics=VALID_METRICS[gate_id],
            )
        )
    return (
        ReleaseGateManifest(
            schema_version="proofagent.release-gate-manifest.v1",
            profile_id="initial-private-pilot-v1",
            candidate=candidate,
            results=tuple(results),
            generated_at=GENERATED_AT,
        ),
        artifacts,
    )


def _verify(
    manifest: ReleaseGateManifest,
    artifacts: dict[str, bytes],
    *,
    checked_at: datetime = CHECKED_AT,
    attestation: AttestationStub | None = None,
    reader: MappingArtifactReader | None = None,
) -> ReleaseDecision:
    return verify_release_manifest(
        manifest,
        checked_at=checked_at,
        artifact_reader=reader or MappingArtifactReader(artifacts),
        attestation_verifier=attestation or AttestationStub(),
    )


def _replace_result(
    manifest: ReleaseGateManifest,
    gate_id: str,
    **changes: Any,
) -> ReleaseGateManifest:
    results = tuple(
        result.model_copy(update=changes) if result.gate_id == gate_id else result
        for result in manifest.results
    )
    return manifest.model_copy(update={"results": results})


def _replace_evidence(
    manifest: ReleaseGateManifest,
    gate_id: str,
    evidence_index: int = 0,
    **changes: Any,
) -> ReleaseGateManifest:
    result = next(result for result in manifest.results if result.gate_id == gate_id)
    evidence = list(result.evidence)
    evidence[evidence_index] = evidence[evidence_index].model_copy(update=changes)
    return _replace_result(manifest, gate_id, evidence=tuple(evidence))


def test_all_exact_thirteen_passing_gates_produce_go() -> None:
    manifest, artifacts = _valid_manifest()

    decision = _verify(manifest, artifacts)

    assert decision.decision == "GO"
    assert decision.candidate_binding_sha256 == candidate_binding_sha256(manifest.candidate)
    assert decision.checked_at == CHECKED_AT
    assert decision.blocker_codes == ()


@pytest.mark.parametrize("status", ["failed", "skipped", "error", "not_run"])
def test_required_nonpassing_status_produces_no_go(status: str) -> None:
    manifest, artifacts = _valid_manifest()
    manifest = _replace_result(manifest, "backend_frontend_quality", status=status)

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert f"gate.status:backend_frontend_quality:{status}" in decision.blocker_codes


def test_missing_and_unknown_gates_produce_no_go() -> None:
    manifest, artifacts = _valid_manifest()
    missing_results = manifest.results[1:]
    unknown = manifest.results[0].model_copy(update={"gate_id": "producer_optional_gate"})
    manifest = manifest.model_copy(update={"results": (*missing_results, unknown)})

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert "gate.missing:backend_frontend_quality" in decision.blocker_codes
    assert "gate.unknown:producer_optional_gate" in decision.blocker_codes


def test_candidate_mutation_invalidates_old_result_and_evidence_bindings() -> None:
    manifest, artifacts = _valid_manifest()
    changed_candidate = manifest.candidate.model_copy(update={"product_version": "0.1.1"})
    manifest = manifest.model_copy(update={"candidate": changed_candidate})

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert any(code.startswith("gate.binding_mismatch:") for code in decision.blocker_codes)
    assert any(code.startswith("evidence.binding_mismatch:") for code in decision.blocker_codes)


def test_artifact_length_and_digest_mismatch_are_blockers() -> None:
    manifest, artifacts = _valid_manifest()
    target = manifest.results[0].evidence[0]
    artifacts[target.evidence_id] = b"different"

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert f"evidence.length_mismatch:{target.evidence_id}" in decision.blocker_codes
    assert f"evidence.digest_mismatch:{target.evidence_id}" in decision.blocker_codes


def test_gate_and_evidence_binding_mismatches_are_both_blockers() -> None:
    manifest, artifacts = _valid_manifest()
    result = manifest.results[0]
    evidence = result.evidence[0].model_copy(update={"candidate_binding_sha256": SHA_B})
    manifest = _replace_result(
        manifest,
        result.gate_id,
        candidate_binding_sha256=SHA_B,
        evidence=(evidence,),
    )

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert f"gate.binding_mismatch:{result.gate_id}" in decision.blocker_codes
    assert f"evidence.binding_mismatch:{evidence.evidence_id}" in decision.blocker_codes


@pytest.mark.parametrize(
    "uri",
    [
        "runs/latest/evidence.json",
        "/tmp/evidence.json",
        "file:///tmp/evidence.json",
        "../evidence.json",
        f"artifact://sha256/{'A' * 64}",
        f"artifact://sha256/{SHA_A}/suffix",
        f"artifact://sha256/{SHA_A}?download=1",
        f"artifact://sha256/{SHA_A}#fragment",
    ],
)
def test_mutable_local_or_noncanonical_evidence_uri_is_a_blocker(uri: str) -> None:
    manifest, artifacts = _valid_manifest()
    target = manifest.results[0].evidence[0]
    manifest = _replace_evidence(manifest, manifest.results[0].gate_id, uri=uri)

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert f"evidence.uri_invalid:{target.evidence_id}" in decision.blocker_codes


def test_uri_digest_must_equal_evidence_digest() -> None:
    manifest, artifacts = _valid_manifest()
    target = manifest.results[0].evidence[0]
    manifest = _replace_evidence(
        manifest,
        manifest.results[0].gate_id,
        uri=build_content_addressed_uri(SHA_A),
    )

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert f"evidence.uri_digest_mismatch:{target.evidence_id}" in decision.blocker_codes


def test_missing_or_unreadable_artifact_is_a_no_go_without_exception() -> None:
    manifest, artifacts = _valid_manifest()
    first, second = manifest.results[0].evidence[0], manifest.results[1].evidence[0]
    del artifacts[first.evidence_id]
    reader = MappingArtifactReader(artifacts, error_ids={second.evidence_id})

    decision = _verify(manifest, artifacts, reader=reader)

    assert decision.decision == "NO-GO"
    assert f"evidence.unavailable:{first.evidence_id}" in decision.blocker_codes
    assert f"evidence.unavailable:{second.evidence_id}" in decision.blocker_codes


@pytest.mark.parametrize("accepted,raises", [(False, False), (True, True)])
def test_attestation_rejection_or_exception_is_a_no_go(accepted: bool, raises: bool) -> None:
    manifest, artifacts = _valid_manifest()
    verifier = AttestationStub(accepted=accepted, raises=raises)

    decision = _verify(manifest, artifacts, attestation=verifier)

    assert decision.decision == "NO-GO"
    assert any(code.startswith("evidence.attestation_failed:") for code in decision.blocker_codes)
    assert verifier.calls == sum(len(result.evidence) for result in manifest.results)


def test_verifier_has_no_network_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, artifacts = _valid_manifest()

    def fail_network(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "socket", fail_network)

    assert _verify(manifest, artifacts).decision == "GO"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("produced_at", GENERATED_AT + timedelta(seconds=1), "evidence.produced_in_future"),
        (
            "expires_at",
            GENERATED_AT - timedelta(hours=1),
            "evidence.expiry_not_after_production",
        ),
        (
            "expires_at",
            GENERATED_AT + timedelta(hours=25),
            "evidence.expiry_exceeds_policy",
        ),
    ],
)
def test_invalid_evidence_time_relationships_are_blockers(
    field: str,
    value: datetime,
    expected_code: str,
) -> None:
    manifest, artifacts = _valid_manifest()
    gate_id = "supply_chain_runtime_security"
    target = next(result for result in manifest.results if result.gate_id == gate_id).evidence[0]
    manifest = _replace_evidence(manifest, gate_id, **{field: value})

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert f"{expected_code}:{target.evidence_id}" in decision.blocker_codes


def test_required_expiry_missing_is_a_blocker() -> None:
    manifest, artifacts = _valid_manifest()
    gate_id = "identity_authorization"
    target = next(result for result in manifest.results if result.gate_id == gate_id).evidence[0]
    manifest = _replace_evidence(manifest, gate_id, expires_at=None)

    decision = _verify(manifest, artifacts)

    assert f"evidence.expiry_missing:{target.evidence_id}" in decision.blocker_codes


def test_evidence_older_than_policy_or_expired_is_a_blocker() -> None:
    manifest, artifacts = _valid_manifest()
    gate_id = "real_llm_evaluation"
    target = next(result for result in manifest.results if result.gate_id == gate_id).evidence[0]
    produced_at = CHECKED_AT - timedelta(hours=73)
    manifest = _replace_evidence(
        manifest,
        gate_id,
        produced_at=produced_at,
        expires_at=produced_at + timedelta(hours=72),
    )

    decision = _verify(manifest, artifacts)

    assert f"evidence.policy_stale:{target.evidence_id}" in decision.blocker_codes
    assert f"evidence.expired:{target.evidence_id}" in decision.blocker_codes


def test_static_evidence_optional_expiry_must_still_be_current() -> None:
    manifest, artifacts = _valid_manifest()
    target = manifest.results[0].evidence[0]
    manifest = _replace_evidence(
        manifest,
        manifest.results[0].gate_id,
        expires_at=CHECKED_AT,
    )

    decision = _verify(manifest, artifacts)

    assert f"evidence.expired:{target.evidence_id}" in decision.blocker_codes


@pytest.mark.parametrize("field", ["sha256", "length"])
def test_exact_packaged_gate_profile_bytes_must_match_candidate(field: str) -> None:
    manifest, artifacts = _valid_manifest()
    changes = {field: SHA_A if field == "sha256" else manifest.candidate.gate_profile.length + 1}
    gate_profile = manifest.candidate.gate_profile.model_copy(update=changes)
    manifest = manifest.model_copy(
        update={"candidate": manifest.candidate.model_copy(update={"gate_profile": gate_profile})}
    )

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert f"profile.{field}_mismatch" in decision.blocker_codes


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("postgresql_bound", False),
        ("s3_bound", False),
        ("oidc_bound", False),
        ("secret_provider_bound", False),
        ("gateway_bound", False),
        ("model_bound", False),
        ("tool_mode_bound", False),
        ("deployment_compatibility_manifest_sha256", SHA_A),
    ],
)
def test_incomplete_or_mismatched_dependency_compatibility_is_a_blocker(
    key: str,
    value: bool | str,
) -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["dependency_compatibility"])
    metrics[key] = value
    manifest = _replace_result(manifest, "dependency_compatibility", metrics=metrics)

    decision = _verify(manifest, artifacts)

    category = "threshold_missed" if isinstance(value, bool) else "binding_mismatch"
    assert f"metric.{category}:dependency_compatibility:{key}" in decision.blocker_codes


def test_missing_dependency_compatibility_component_is_a_blocker() -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["dependency_compatibility"])
    del metrics["gateway_bound"]
    manifest = _replace_result(manifest, "dependency_compatibility", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert "metric.missing:dependency_compatibility:gateway_bound" in decision.blocker_codes


def test_insufficient_capacity_sample_and_threshold_miss_are_distinct() -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["capacity_responsiveness"])
    metrics["admission_sample_count"] = 199
    metrics["online_sessions"] = 19
    manifest = _replace_result(manifest, "capacity_responsiveness", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert (
        "metric.insufficient_sample:capacity_responsiveness:admission_sample_count"
        in decision.blocker_codes
    )
    assert (
        "metric.threshold_missed:capacity_responsiveness:online_sessions" in decision.blocker_codes
    )


def test_coverage_threshold_miss_is_a_blocker() -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["backend_frontend_quality"])
    metrics["line_coverage_percent"] = 89
    manifest = _replace_result(manifest, "backend_frontend_quality", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert (
        "metric.threshold_missed:backend_frontend_quality:line_coverage_percent"
        in decision.blocker_codes
    )


def test_continuous_coverage_and_latency_measurements_accept_finite_floats() -> None:
    manifest, artifacts = _valid_manifest()
    quality_metrics = dict(VALID_METRICS["backend_frontend_quality"])
    quality_metrics["line_coverage_percent"] = 90.5
    capacity_metrics = dict(VALID_METRICS["capacity_responsiveness"])
    capacity_metrics["admission_p95_ms"] = 499.5
    manifest = _replace_result(
        manifest,
        "backend_frontend_quality",
        metrics=quality_metrics,
    )
    manifest = _replace_result(
        manifest,
        "capacity_responsiveness",
        metrics=capacity_metrics,
    )

    assert _verify(manifest, artifacts).decision == "GO"


def test_sample_counts_remain_exact_integers() -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["capacity_responsiveness"])
    metrics["admission_sample_count"] = 200.5
    manifest = _replace_result(manifest, "capacity_responsiveness", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert (
        "metric.type_mismatch:capacity_responsiveness:admission_sample_count"
        in decision.blocker_codes
    )


def test_unbounded_integer_measurement_fails_threshold_without_escaping_verifier() -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["capacity_responsiveness"])
    metrics["admission_p95_ms"] = 10**1000
    manifest = _replace_result(manifest, "capacity_responsiveness", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert decision.decision == "NO-GO"
    assert (
        "metric.threshold_missed:capacity_responsiveness:admission_p95_ms" in decision.blocker_codes
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"unknown_metric": 1}, "metric.unknown:deployment:unknown_metric"),
        ({"required_checks_passed": 1}, "metric.type_mismatch:deployment:required_checks_passed"),
    ],
)
def test_unknown_or_wrongly_typed_metric_is_a_blocker(
    mutation: dict[str, int],
    expected_code: str,
) -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["deployment"])
    metrics.update(mutation)
    manifest = _replace_result(manifest, "deployment", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert expected_code in decision.blocker_codes


def test_missing_metric_is_a_blocker() -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["browser_operations"])
    del metrics["support_window_seconds"]
    manifest = _replace_result(manifest, "browser_operations", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert "metric.missing:browser_operations:support_window_seconds" in decision.blocker_codes


@pytest.mark.parametrize("key", ["topology_sha256", "backup_policy_sha256", "migration_set_sha256"])
def test_recovery_bindings_must_match_current_deployment(key: str) -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["resilience_recovery"])
    metrics[key] = SHA_A
    manifest = _replace_result(manifest, "resilience_recovery", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert f"metric.binding_mismatch:resilience_recovery:{key}" in decision.blocker_codes


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("reference_digest_verification_percent", 99),
        ("rpo_minutes", 16),
        ("rto_minutes", 241),
    ],
)
def test_recovery_thresholds_are_fail_closed(key: str, value: int) -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["resilience_recovery"])
    metrics[key] = value
    manifest = _replace_result(manifest, "resilience_recovery", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert f"metric.threshold_missed:resilience_recovery:{key}" in decision.blocker_codes


def test_deployment_migration_and_dcm_bindings_must_match_candidate() -> None:
    manifest, artifacts = _valid_manifest()
    metrics = dict(VALID_METRICS["deployment"])
    metrics["migration_set_sha256"] = SHA_A
    metrics["deployment_compatibility_manifest_sha256"] = SHA_B
    manifest = _replace_result(manifest, "deployment", metrics=metrics)

    decision = _verify(manifest, artifacts)

    assert "metric.binding_mismatch:deployment:migration_set_sha256" in decision.blocker_codes
    assert (
        "metric.binding_mismatch:deployment:deployment_compatibility_manifest_sha256"
        in decision.blocker_codes
    )


def test_manifest_generated_in_future_is_a_blocker() -> None:
    manifest, artifacts = _valid_manifest()
    manifest = manifest.model_copy(update={"generated_at": CHECKED_AT + timedelta(seconds=1)})

    decision = _verify(manifest, artifacts)

    assert "manifest.generated_in_future" in decision.blocker_codes


def test_deploy_decision_window_expires_after_twenty_four_hours() -> None:
    manifest, artifacts = _valid_manifest()

    decision = _verify(
        manifest, artifacts, checked_at=GENERATED_AT + timedelta(hours=24, seconds=1)
    )

    assert "deployment.window_expired" in decision.blocker_codes


def test_checked_at_must_precede_earliest_required_evidence_expiry() -> None:
    manifest, artifacts = _valid_manifest()
    earliest_expiry = GENERATED_AT + timedelta(hours=2)
    gate_id = "supply_chain_runtime_security"
    manifest = _replace_evidence(manifest, gate_id, expires_at=earliest_expiry)

    decision = _verify(manifest, artifacts, checked_at=earliest_expiry)

    assert "deployment.evidence_window_expired" in decision.blocker_codes


def test_naive_checked_at_is_invalid_api_input() -> None:
    manifest, artifacts = _valid_manifest()

    with pytest.raises(ValueError, match="timezone-aware"):
        _verify(manifest, artifacts, checked_at=datetime(2026, 7, 12, 9, 0))


def test_blocker_codes_are_unique_sorted_and_deterministic() -> None:
    manifest, artifacts = _valid_manifest()
    artifacts[manifest.results[0].evidence[0].evidence_id] = b"bad"

    first = _verify(manifest, artifacts)
    second = _verify(manifest, artifacts)

    assert first.blocker_codes == tuple(sorted(set(first.blocker_codes)))
    assert second == first


def test_canonical_candidate_digest_is_key_order_stable_and_mutation_sensitive() -> None:
    candidate = _candidate()
    forward = candidate.model_dump(mode="json")
    reverse = dict(reversed(tuple(forward.items())))

    assert canonical_json_bytes(forward) == canonical_json_bytes(reverse)
    assert candidate_binding_sha256(candidate) == candidate_binding_sha256(forward)
    assert candidate_binding_sha256(candidate) != candidate_binding_sha256(
        candidate.model_copy(update={"agent_version": "2026.07.13"})
    )


def test_content_addressed_uri_builder_and_parser_are_exact() -> None:
    uri = build_content_addressed_uri(SHA_A)

    assert uri == f"artifact://sha256/{SHA_A}"
    assert parse_content_addressed_uri(uri) == SHA_A


@pytest.mark.parametrize(
    "uri",
    [
        f"http://sha256/{SHA_A}",
        f"artifact://SHA256/{SHA_A}",
        f"artifact://sha256/{'A' * 64}",
        f"artifact://sha256/{SHA_A}/x",
        f"artifact://sha256/{SHA_A}?x=1",
        f"artifact://sha256/{SHA_A}#x",
    ],
)
def test_content_addressed_uri_parser_rejects_every_noncanonical_form(uri: str) -> None:
    with pytest.raises(ValueError):
        parse_content_addressed_uri(uri)


def test_evidence_root_reader_reads_only_normal_content_addressed_file(tmp_path: Path) -> None:
    artifact = b"release evidence"
    artifact_digest = digest_ref(artifact)
    (tmp_path / artifact_digest.sha256).write_bytes(artifact)
    evidence = EvidenceRef(
        evidence_id="normal-file",
        kind="candidate_static",
        uri=build_content_addressed_uri(artifact_digest.sha256),
        digest=artifact_digest,
        candidate_binding_sha256=SHA_A,
        produced_at=GENERATED_AT,
    )

    assert EvidenceRootArtifactReader(tmp_path).read(evidence) == artifact


def test_evidence_root_reader_rejects_symlink_escape(
    tmp_path: Path,
) -> None:
    artifact = b"release evidence"
    artifact_digest = digest_ref(artifact)
    target = tmp_path.parent / f"{tmp_path.name}-outside-evidence"
    target.write_bytes(artifact)
    (tmp_path / artifact_digest.sha256).symlink_to(target)
    evidence = EvidenceRef(
        evidence_id="symlink",
        kind="candidate_static",
        uri=build_content_addressed_uri(artifact_digest.sha256),
        digest=artifact_digest,
        candidate_binding_sha256=SHA_A,
        produced_at=GENERATED_AT,
    )

    with pytest.raises(OSError, match="symlink"):
        EvidenceRootArtifactReader(tmp_path).read(evidence)


def _write_cli_manifest(tmp_path: Path) -> tuple[Path, Path, ReleaseGateManifest]:
    manifest, artifacts = _valid_manifest()
    manifest_path = tmp_path / "release-gate-manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    for result in manifest.results:
        for evidence in result.evidence:
            (evidence_root / evidence.digest.sha256).write_bytes(artifacts[evidence.evidence_id])
    return manifest_path, evidence_root, manifest


def _release_cli_args(
    manifest_path: Path, evidence_root: Path, at: str = "2026-07-12T09:00:00Z"
) -> list[str]:
    return [
        "release",
        "verify",
        "--manifest",
        str(manifest_path),
        "--evidence-root",
        str(evidence_root),
        "--at",
        at,
    ]


def test_release_verify_cli_help() -> None:
    result = CliRunner().invoke(cli_module.app, ["release", "verify", "--help"])

    assert result.exit_code == 0
    assert "--manifest" in result.stdout
    assert "--evidence-root" in result.stdout
    assert "--at" in result.stdout


def test_release_verify_cli_valid_manifest_is_real_no_go_with_unavailable_attestation(
    tmp_path: Path,
) -> None:
    manifest_path, evidence_root, _manifest = _write_cli_manifest(tmp_path)

    result = CliRunner().invoke(cli_module.app, _release_cli_args(manifest_path, evidence_root))

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["decision"] == "NO-GO"
    assert any(code.startswith("evidence.attestation_failed:") for code in payload["blocker_codes"])


def test_release_verify_cli_maps_trusted_go_decision_to_json_and_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, evidence_root, manifest = _write_cli_manifest(tmp_path)
    trusted = ReleaseDecision(
        decision="GO",
        candidate_binding_sha256=candidate_binding_sha256(manifest.candidate),
        checked_at=CHECKED_AT,
        blocker_codes=(),
    )
    monkeypatch.setattr(cli_module, "verify_release_manifest", lambda *args, **kwargs: trusted)

    result = CliRunner().invoke(cli_module.app, _release_cli_args(manifest_path, evidence_root))

    assert result.exit_code == 0
    assert json.loads(result.stdout) == trusted.model_dump(mode="json")


@pytest.mark.parametrize("case", ["malformed", "unknown", "duplicate"])
def test_release_verify_cli_rejects_invalid_manifest_as_input_error(
    tmp_path: Path,
    case: str,
) -> None:
    manifest_path, evidence_root, manifest = _write_cli_manifest(tmp_path)
    if case == "malformed":
        manifest_path.write_text("{", encoding="utf-8")
    else:
        payload = manifest.model_dump(mode="json")
        if case == "unknown":
            payload["producer_override"] = True
        else:
            payload["results"].append(payload["results"][0])
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    result = CliRunner().invoke(cli_module.app, _release_cli_args(manifest_path, evidence_root))

    assert result.exit_code == 2


@pytest.mark.parametrize(
    "at",
    ["2026-07-12T09:00:00", "2026-07-12", "2026-07-12 09:00:00Z", "not-a-time"],
)
def test_release_verify_cli_rejects_naive_or_non_rfc3339_at(tmp_path: Path, at: str) -> None:
    manifest_path, evidence_root, _manifest = _write_cli_manifest(tmp_path)

    result = CliRunner().invoke(
        cli_module.app,
        _release_cli_args(manifest_path, evidence_root, at=at),
    )

    assert result.exit_code == 2


def test_release_verify_cli_rejects_missing_or_nondirectory_evidence_root(tmp_path: Path) -> None:
    manifest_path, _evidence_root, _manifest = _write_cli_manifest(tmp_path)
    missing = tmp_path / "missing"
    regular_file = tmp_path / "regular-file"
    regular_file.write_text("x", encoding="utf-8")

    missing_result = CliRunner().invoke(cli_module.app, _release_cli_args(manifest_path, missing))
    file_result = CliRunner().invoke(cli_module.app, _release_cli_args(manifest_path, regular_file))

    assert missing_result.exit_code == 2
    assert file_result.exit_code == 2
