from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources
from typing import Any

import pytest
from pydantic import ValidationError

import proof_agent.release as release
from proof_agent.release import (
    DigestRef,
    EvidenceRef,
    GateProfile,
    GateResult,
    INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS,
    ProductionCandidateBinding,
    ReleaseGateManifest,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SOURCE_COMMIT = "c" * 40
NOW = datetime(2026, 7, 12, 8, 30, tzinfo=timezone.utc)


def _digest(*, sha256: str = SHA_A, length: int = 1) -> DigestRef:
    return DigestRef(sha256=sha256, length=length)


def _candidate(**overrides: Any) -> ProductionCandidateBinding:
    values: dict[str, Any] = {
        "schema_version": "proofagent.candidate-binding.v1",
        "source_commit": SOURCE_COMMIT,
        "clean_tree": True,
        "product_version": "0.1.0",
        "oci_digest": f"sha256:{SHA_A}",
        "python_distribution": _digest(),
        "dashboard_assets": _digest(),
        "operator_chat_assets": _digest(),
        "migration_set": _digest(),
        "agent_id": "agent_management_insurance_specialist",
        "agent_version": "2026.07.12",
        "agent_bundle": _digest(),
        "evaluation_contract": _digest(),
        "configuration_snapshot": _digest(),
        "gate_profile": _digest(),
        "deployment_compatibility_manifest": _digest(),
    }
    values.update(overrides)
    return ProductionCandidateBinding(**values)


def _evidence(**overrides: Any) -> EvidenceRef:
    values: dict[str, Any] = {
        "evidence_id": "evidence-backend-frontend-quality",
        "kind": "test-report",
        "uri": "artifact://release/evidence/test-report.json",
        "digest": _digest(sha256=SHA_B, length=2048),
        "candidate_binding_sha256": SHA_A,
        "produced_at": NOW,
        "expires_at": None,
    }
    values.update(overrides)
    return EvidenceRef(**values)


def _gate_result(**overrides: Any) -> GateResult:
    values: dict[str, Any] = {
        "gate_id": "backend_frontend_quality",
        "status": "passed",
        "candidate_binding_sha256": SHA_A,
        "evidence": (_evidence(),),
        "metrics": {
            "coverage": 0.95,
            "test_count": 128,
            "suite": "release",
            "blocking": False,
        },
        "blocker_codes": (),
    }
    values.update(overrides)
    return GateResult(**values)


def _manifest(**overrides: Any) -> ReleaseGateManifest:
    values: dict[str, Any] = {
        "schema_version": "proofagent.release-gate-manifest.v1",
        "profile_id": "initial-private-pilot-v1",
        "candidate": _candidate(),
        "results": (_gate_result(),),
        "generated_at": NOW,
    }
    values.update(overrides)
    return ReleaseGateManifest(**values)


def test_release_manifest_round_trips_json_and_is_deeply_frozen() -> None:
    source_metrics: dict[str, float | int | str | bool] = {
        "coverage": 0.95,
        "test_count": 128,
        "suite": "release",
        "blocking": False,
    }
    manifest = _manifest(results=(_gate_result(metrics=source_metrics),))

    round_tripped = ReleaseGateManifest.model_validate_json(manifest.model_dump_json())

    assert round_tripped == manifest
    assert round_tripped.model_dump(mode="json")["results"][0]["metrics"] == source_metrics
    source_metrics["coverage"] = 0.1
    assert manifest.results[0].metrics["coverage"] == 0.95
    with pytest.raises(ValidationError):
        manifest.profile_id = "another-profile"  # type: ignore[misc]
    with pytest.raises(TypeError):
        manifest.results[0].metrics["coverage"] = 0.1  # type: ignore[index]


def test_release_contracts_reject_unknown_fields_at_top_and_nested_levels() -> None:
    manifest_payload = _manifest().model_dump()
    manifest_payload["provider"] = "vendor-specific"
    with pytest.raises(ValidationError):
        ReleaseGateManifest.model_validate(manifest_payload)

    candidate_payload = _candidate().model_dump()
    candidate_payload["python_distribution"]["algorithm"] = "sha256"
    with pytest.raises(ValidationError):
        ProductionCandidateBinding.model_validate(candidate_payload)


def test_release_contracts_use_strict_python_input_types() -> None:
    with pytest.raises(ValidationError):
        DigestRef(sha256=SHA_A, length="1")  # type: ignore[arg-type]


def test_gate_result_metrics_are_required() -> None:
    payload = _gate_result().model_dump()
    del payload["metrics"]

    with pytest.raises(ValidationError):
        GateResult.model_validate(payload)


@pytest.mark.parametrize(
    "non_finite",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
    ],
)
def test_gate_result_rejects_non_finite_metric_python_input(non_finite: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        _gate_result(metrics={"score": non_finite})


@pytest.mark.parametrize(
    ("non_finite", "json_token"),
    [
        pytest.param(float("nan"), "NaN", id="nan"),
        pytest.param(float("inf"), "Infinity", id="positive-infinity"),
        pytest.param(float("-inf"), "-Infinity", id="negative-infinity"),
    ],
)
def test_gate_result_rejects_non_finite_metric_json_tokens(
    non_finite: float,
    json_token: str,
) -> None:
    payload = _gate_result().model_dump(mode="json")
    payload["metrics"] = {"score": non_finite}
    raw_json = json.dumps(payload, allow_nan=True)
    assert f'"score": {json_token}' in raw_json

    with pytest.raises(ValidationError, match="finite"):
        GateResult.model_validate_json(raw_json)


def test_gate_result_finite_float_metric_round_trips_as_float() -> None:
    result = _gate_result(metrics={"score": 0.125})

    round_tripped = GateResult.model_validate_json(result.model_dump_json())

    assert type(round_tripped.metrics["score"]) is float
    assert round_tripped.metrics["score"] == 0.125


def test_release_manifest_rejects_duplicate_gate_ids() -> None:
    duplicate = _gate_result()

    with pytest.raises(ValidationError, match="unique"):
        _manifest(results=(duplicate, duplicate))


@pytest.mark.parametrize(
    "oci_digest",
    [
        "repo:latest",
        SHA_A,
        f"sha256:{'A' * 64}",
        f"sha256:{'a' * 63}",
        f"sha512:{SHA_A}",
    ],
)
def test_candidate_binding_rejects_nonimmutable_or_malformed_oci_digest(
    oci_digest: str,
) -> None:
    with pytest.raises(ValidationError):
        _candidate(oci_digest=oci_digest)


def test_candidate_binding_requires_the_single_release_agent() -> None:
    missing_agent = _candidate().model_dump()
    del missing_agent["agent_id"]
    with pytest.raises(ValidationError):
        ProductionCandidateBinding.model_validate(missing_agent)

    with pytest.raises(ValidationError):
        _candidate(agent_id="another_agent")


@pytest.mark.parametrize("sha256", ["A" * 64, "a" * 63, f"sha256:{SHA_A}"])
def test_digest_ref_rejects_noncanonical_sha256(sha256: str) -> None:
    with pytest.raises(ValidationError):
        _digest(sha256=sha256)


@pytest.mark.parametrize("field", ["candidate_binding_sha256"])
def test_evidence_ref_rejects_noncanonical_sha256(field: str) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{field: "A" * 64})


def test_gate_result_rejects_noncanonical_candidate_binding_sha256() -> None:
    with pytest.raises(ValidationError):
        _gate_result(candidate_binding_sha256="A" * 64)


@pytest.mark.parametrize("source_commit", ["C" * 40, "c" * 39, "c" * 41])
def test_candidate_binding_rejects_noncanonical_source_commit(source_commit: str) -> None:
    with pytest.raises(ValidationError):
        _candidate(source_commit=source_commit)


def test_digest_ref_rejects_negative_length() -> None:
    with pytest.raises(ValidationError):
        _digest(length=-1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("produced_at", datetime(2026, 7, 12, 8, 30)),
        ("expires_at", datetime(2026, 7, 13, 8, 30)),
    ],
)
def test_evidence_ref_requires_timezone_aware_datetimes(field: str, value: datetime) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{field: value})


def test_release_manifest_requires_timezone_aware_generated_at() -> None:
    with pytest.raises(ValidationError):
        _manifest(generated_at=datetime(2026, 7, 12, 8, 30))


def test_evidence_ref_defaults_expiration_to_none() -> None:
    payload = _evidence().model_dump()
    del payload["expires_at"]

    evidence = EvidenceRef.model_validate(payload)

    assert evidence.expires_at is None


def test_packaged_initial_private_pilot_profile_is_exact_and_frozen() -> None:
    profile_resource = (
        resources.files("proof_agent.release")
        .joinpath("profiles")
        .joinpath("initial-private-pilot-v1.json")
    )

    profile = GateProfile.model_validate_json(profile_resource.read_text(encoding="utf-8"))

    assert profile.required_gate_ids == INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS
    assert profile.required_gate_ids == (
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
    with pytest.raises(ValidationError):
        profile.profile_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        profile.required_gate_ids[0] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    "required_gate_ids",
    [
        INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS[:-1],
        (
            INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS[1],
            INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS[0],
            *INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS[2:],
        ),
        (*INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS[:-1], "backend_frontend_quality"),
    ],
)
def test_initial_private_pilot_profile_rejects_missing_reordered_or_duplicate_gates(
    required_gate_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        GateProfile(
            schema_version="proofagent.gate-profile.v1",
            profile_id="initial-private-pilot-v1",
            required_gate_ids=required_gate_ids,
        )


def test_initial_private_pilot_profile_cannot_move_required_gate_to_optional() -> None:
    payload = {
        "schema_version": "proofagent.gate-profile.v1",
        "profile_id": "initial-private-pilot-v1",
        "required_gate_ids": list(INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS[:-1]),
        "optional_gate_ids": [INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS[-1]],
    }

    with pytest.raises(ValidationError):
        GateProfile.model_validate_json(json.dumps(payload))


def test_release_contract_json_schemas_are_closed_at_every_object_layer() -> None:
    manifest_schema = ReleaseGateManifest.model_json_schema()

    assert manifest_schema["additionalProperties"] is False
    for definition in (
        "DigestRef",
        "EvidenceRef",
        "GateResult",
        "ProductionCandidateBinding",
    ):
        assert manifest_schema["$defs"][definition]["additionalProperties"] is False

    assert GateProfile.model_json_schema()["additionalProperties"] is False


def test_release_package_exports_only_provider_neutral_contracts() -> None:
    expected_exports = {
        "DigestRef",
        "EvidenceRef",
        "GateProfile",
        "GateResult",
        "GateStatus",
        "INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS",
        "ProductionCandidateBinding",
        "ReleaseGateManifest",
        "Sha256",
        "StrictFrozenModel",
    }

    assert set(release.__all__) == expected_exports
    assert not any("provider" in exported.lower() for exported in release.__all__)
