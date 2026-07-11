from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from importlib import resources
from typing import Literal

from proof_agent.release.contracts import (
    INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS,
    GateProfile,
)


MetricKind = Literal["bool", "int", "number", "sha256"]
MetricComparison = Literal["equal", "minimum", "maximum", "binding", "format"]
MetricFailure = Literal["threshold_missed", "insufficient_sample", "binding_mismatch"]
BindingTarget = Literal["migration_set", "deployment_compatibility_manifest"]


@dataclass(frozen=True, slots=True)
class EvidenceRule:
    kind: str
    max_age: timedelta | None
    expiry_required: bool


@dataclass(frozen=True, slots=True)
class MetricRule:
    key: str
    kind: MetricKind
    comparison: MetricComparison
    expected: bool | int | float | None = None
    failure: MetricFailure = "threshold_missed"
    binding_target: BindingTarget | None = None
    minimum_allowed: int | float | None = None
    maximum_allowed: int | float | None = None


@dataclass(frozen=True, slots=True)
class GateRule:
    gate_id: str
    evidence: tuple[EvidenceRule, ...]
    metrics: tuple[MetricRule, ...]


@dataclass(frozen=True, slots=True)
class ReleaseProfile:
    gate_profile: GateProfile
    exact_bytes: bytes
    gates: tuple[GateRule, ...]

    @property
    def gate_ids(self) -> tuple[str, ...]:
        return tuple(rule.gate_id for rule in self.gates)


def _evidence(
    kind: str,
    max_age: timedelta | None = None,
    *,
    expiry_required: bool = False,
) -> EvidenceRule:
    return EvidenceRule(kind=kind, max_age=max_age, expiry_required=expiry_required)


def _bool(key: str) -> MetricRule:
    return MetricRule(key=key, kind="bool", comparison="equal", expected=True)


def _minimum(
    key: str,
    expected: int,
    *,
    failure: MetricFailure = "threshold_missed",
) -> MetricRule:
    return MetricRule(
        key=key,
        kind="int",
        comparison="minimum",
        expected=expected,
        failure=failure,
    )


def _maximum(key: str, expected: int) -> MetricRule:
    return MetricRule(key=key, kind="int", comparison="maximum", expected=expected)


def _equal(key: str, expected: int) -> MetricRule:
    return MetricRule(key=key, kind="int", comparison="equal", expected=expected)


def _minimum_number(
    key: str,
    expected: int | float,
    *,
    maximum_allowed: int | float | None = None,
) -> MetricRule:
    return MetricRule(
        key=key,
        kind="number",
        comparison="minimum",
        expected=expected,
        maximum_allowed=maximum_allowed,
    )


def _maximum_number(key: str, expected: int | float) -> MetricRule:
    return MetricRule(
        key=key,
        kind="number",
        comparison="maximum",
        expected=expected,
        minimum_allowed=0,
    )


def _equal_number(key: str, expected: int | float) -> MetricRule:
    return MetricRule(key=key, kind="number", comparison="equal", expected=expected)


def _sha256(key: str) -> MetricRule:
    return MetricRule(key=key, kind="sha256", comparison="format")


def _binding(key: str, target: BindingTarget) -> MetricRule:
    return MetricRule(
        key=key,
        kind="sha256",
        comparison="binding",
        failure="binding_mismatch",
        binding_target=target,
    )


_HOURS_24 = timedelta(hours=24)
_HOURS_72 = timedelta(hours=72)
_DAYS_30 = timedelta(days=30)

_GATE_RULES = (
    GateRule(
        "backend_frontend_quality",
        (_evidence("candidate_static"),),
        (
            _minimum_number("line_coverage_percent", 90, maximum_allowed=100),
            _equal("required_command_failures", 0),
            _equal("required_integration_skips", 0),
        ),
    ),
    GateRule(
        "distribution_image",
        (_evidence("candidate_static"),),
        (_bool("clean_install_passed"), _bool("image_readiness_passed")),
    ),
    GateRule(
        "supply_chain_runtime_security",
        (_evidence("vulnerability_scan", _HOURS_24, expiry_required=True),),
        (
            _equal("unresolved_critical_findings", 0),
            _equal("unresolved_high_findings", 0),
            _bool("runtime_hardening_passed"),
        ),
    ),
    GateRule(
        "identity_authorization",
        (_evidence("production_dependency", _HOURS_72, expiry_required=True),),
        (_bool("required_checks_passed"),),
    ),
    GateRule(
        "secrets_egress",
        (_evidence("production_dependency", _HOURS_72, expiry_required=True),),
        (_bool("required_checks_passed"),),
    ),
    GateRule(
        "deterministic_evaluation",
        (_evidence("candidate_static"),),
        (_equal("required_case_failures", 0), _equal("required_case_skips", 0)),
    ),
    GateRule(
        "real_llm_evaluation",
        (_evidence("real_llm", _HOURS_72, expiry_required=True),),
        (
            _equal("required_case_failures", 0),
            _equal("required_case_skips", 0),
            _minimum("sample_count", 1, failure="insufficient_sample"),
        ),
    ),
    GateRule(
        "dependency_compatibility",
        (_evidence("production_dependency", _HOURS_72, expiry_required=True),),
        (
            _bool("postgresql_bound"),
            _bool("s3_bound"),
            _bool("oidc_bound"),
            _bool("secret_provider_bound"),
            _bool("gateway_bound"),
            _bool("model_bound"),
            _bool("tool_mode_bound"),
            _binding(
                "deployment_compatibility_manifest_sha256",
                "deployment_compatibility_manifest",
            ),
        ),
    ),
    GateRule(
        "capacity_responsiveness",
        (_evidence("load", _HOURS_72, expiry_required=True),),
        (
            _minimum("online_sessions", 20),
            _equal("active_attempts", 5),
            _equal("queued_runs", 50),
            _bool("overload_request_51_passed"),
            _minimum_number("load_duration_seconds", 1800),
            _minimum("admission_sample_count", 200, failure="insufficient_sample"),
            _minimum("first_progress_sample_count", 200, failure="insufficient_sample"),
            _minimum("terminal_sample_count", 100, failure="insufficient_sample"),
            _maximum_number("admission_p95_ms", 500),
            _maximum_number("first_progress_p95_ms", 1000),
            _maximum_number("free_slot_start_p95_ms", 1000),
            _maximum_number("standard_terminal_p95_ms", 60000),
            _maximum_number("max_attempt_terminal_ms", 120000),
        ),
    ),
    GateRule(
        "queue_progress",
        (_evidence("load", _HOURS_72, expiry_required=True),),
        (_bool("required_checks_passed"), _minimum_number("soak_duration_seconds", 14400)),
    ),
    GateRule(
        "resilience_recovery",
        (
            _evidence("fault", _HOURS_72, expiry_required=True),
            _evidence("combined_restore", _DAYS_30, expiry_required=True),
        ),
        (
            _bool("fault_matrix_passed"),
            _equal_number("reference_digest_verification_percent", 100),
            _maximum_number("rpo_minutes", 15),
            _maximum_number("rto_minutes", 240),
            _sha256("topology_sha256"),
            _sha256("backup_policy_sha256"),
            _binding("migration_set_sha256", "migration_set"),
        ),
    ),
    GateRule(
        "deployment",
        (_evidence("blue_green", _HOURS_72, expiry_required=True),),
        (
            _bool("required_checks_passed"),
            _maximum_number("drain_seconds", 150),
            _minimum_number("soak_seconds", 1800),
            _sha256("topology_sha256"),
            _sha256("backup_policy_sha256"),
            _binding("migration_set_sha256", "migration_set"),
            _binding(
                "deployment_compatibility_manifest_sha256",
                "deployment_compatibility_manifest",
            ),
        ),
    ),
    GateRule(
        "browser_operations",
        (_evidence("browser", _HOURS_72, expiry_required=True),),
        (
            _bool("required_checks_passed"),
            _minimum("pilot_operator_count", 3),
            _maximum("pilot_operator_count", 5),
            _minimum_number("support_window_seconds", 32400),
            _equal_number("required_scenario_coverage_percent", 100),
        ),
    ),
)


def initial_private_pilot_profile_bytes() -> bytes:
    return (
        resources.files("proof_agent.release")
        .joinpath("profiles")
        .joinpath("initial-private-pilot-v1.json")
        .read_bytes()
    )


def _load_initial_private_pilot_profile() -> ReleaseProfile:
    exact_bytes = initial_private_pilot_profile_bytes()
    gate_profile = GateProfile.model_validate_json(exact_bytes)
    profile = ReleaseProfile(gate_profile=gate_profile, exact_bytes=exact_bytes, gates=_GATE_RULES)
    if profile.gate_ids != INITIAL_PRIVATE_PILOT_REQUIRED_GATE_IDS:
        raise RuntimeError("release policy gate ids do not match the packaged Gate Profile")
    return profile


INITIAL_PRIVATE_PILOT_PROFILE = _load_initial_private_pilot_profile()


def initial_private_pilot_profile() -> ReleaseProfile:
    return INITIAL_PRIVATE_PILOT_PROFILE
