from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import cast

from proof_agent.release.contracts import (
    EvidenceRef,
    GateResult,
    GateRule,
    MetricRule,
    ProductionCandidateBinding,
)
from proof_agent.release.digests import candidate_binding_sha256, digest_ref
from proof_agent.release.profile import INITIAL_PRIVATE_PILOT_PROFILE


_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def evaluate_gate(
    *,
    candidate: ProductionCandidateBinding,
    gate_id: str,
    evidence: Sequence[EvidenceRef],
    metrics: Mapping[str, float | int | str | bool],
    evaluated_at: datetime,
) -> GateResult:
    """Evaluate raw pipeline facts against the candidate-bound Gate Profile."""

    binding = candidate_binding_sha256(candidate)
    blockers = gate_policy_blockers(
        candidate=candidate,
        gate_id=gate_id,
        evidence=evidence,
        metrics=metrics,
        evaluated_at=evaluated_at,
    )
    return GateResult(
        gate_id=gate_id,
        status="passed" if not blockers else "failed",
        candidate_binding_sha256=binding,
        evidence=tuple(evidence),
        metrics=metrics,
        blocker_codes=tuple(sorted(set(blockers))),
    )


def gate_policy_blockers(
    *,
    candidate: ProductionCandidateBinding,
    gate_id: str,
    evidence: Sequence[EvidenceRef],
    metrics: Mapping[str, object],
    evaluated_at: datetime,
) -> tuple[str, ...]:
    """Interpret the active profile for producers and the independent verifier."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    blockers = _collect_policy_blockers(
        candidate=candidate,
        rule=_required_gate_rule(gate_id),
        evidence=evidence,
        metrics=metrics,
        evaluated_at=evaluated_at,
        expected_binding=candidate_binding_sha256(candidate),
    )
    return tuple(sorted(set(blockers)))


def _required_gate_rule(gate_id: str) -> GateRule:
    for rule in INITIAL_PRIVATE_PILOT_PROFILE.gates:
        if rule.gate_id == gate_id:
            return rule
    raise ValueError(f"unknown gate id: {gate_id}")


def _collect_policy_blockers(
    *,
    candidate: ProductionCandidateBinding,
    rule: GateRule,
    evidence: Sequence[EvidenceRef],
    metrics: Mapping[str, object],
    evaluated_at: datetime,
    expected_binding: str,
) -> list[str]:
    blockers: list[str] = []
    packaged_profile = digest_ref(INITIAL_PRIVATE_PILOT_PROFILE.binding_bytes)
    if candidate.gate_profile.sha256 != packaged_profile.sha256:
        blockers.append("profile.sha256_mismatch")
    if candidate.gate_profile.length != packaged_profile.length:
        blockers.append("profile.length_mismatch")

    actual_kinds = tuple(item.kind for item in evidence)
    allowed_kinds = tuple(item.kind for item in rule.evidence)
    for kind in allowed_kinds:
        count = actual_kinds.count(kind)
        if count == 0:
            blockers.append(f"evidence.missing:{rule.gate_id}:{kind}")
        elif count != 1:
            blockers.append(f"evidence.cardinality:{rule.gate_id}:{kind}")
    for kind in actual_kinds:
        if kind not in allowed_kinds:
            blockers.append(f"evidence.kind_unknown:{rule.gate_id}:{kind}")
    for evidence_id, count in Counter(item.evidence_id for item in evidence).items():
        if count > 1:
            blockers.append(f"evidence.duplicate_id:{evidence_id}")

    evidence_rules = {item.kind: item for item in rule.evidence}
    for item in evidence:
        if item.candidate_binding_sha256 != expected_binding:
            blockers.append(f"evidence.binding_mismatch:{item.evidence_id}")
        if item.produced_at > evaluated_at:
            blockers.append(f"evidence.produced_in_future:{item.evidence_id}")
        expires_at = item.expires_at
        if expires_at is not None:
            if expires_at <= item.produced_at:
                blockers.append(f"evidence.expiry_not_after_production:{item.evidence_id}")
            if evaluated_at >= expires_at:
                blockers.append(f"evidence.expired:{item.evidence_id}")
        evidence_rule = evidence_rules.get(item.kind)
        if evidence_rule is None:
            continue
        if evidence_rule.expiry_required and expires_at is None:
            blockers.append(f"evidence.expiry_missing:{item.evidence_id}")
        if evidence_rule.max_age_seconds is None:
            continue
        max_age = timedelta(seconds=evidence_rule.max_age_seconds)
        if (
            expires_at is not None
            and expires_at > item.produced_at
            and expires_at - item.produced_at > max_age
        ):
            blockers.append(f"evidence.expiry_exceeds_policy:{item.evidence_id}")
        if evaluated_at >= item.produced_at and evaluated_at - item.produced_at >= max_age:
            blockers.append(f"evidence.policy_stale:{item.evidence_id}")

    allowed_metric_keys = {item.key for item in rule.metrics}
    for key in metrics:
        if key not in allowed_metric_keys:
            blockers.append(f"metric.unknown:{rule.gate_id}:{key}")
    for metric_rule in rule.metrics:
        if metric_rule.key not in metrics:
            blockers.append(f"metric.missing:{rule.gate_id}:{metric_rule.key}")
            continue
        value = metrics[metric_rule.key]
        if not _metric_type_matches(value, metric_rule):
            blockers.append(f"metric.type_mismatch:{rule.gate_id}:{metric_rule.key}")
            continue
        if not _metric_satisfies(value, metric_rule, candidate):
            blockers.append(f"metric.{metric_rule.failure}:{rule.gate_id}:{metric_rule.key}")
    return blockers


def _metric_type_matches(value: object, rule: MetricRule) -> bool:
    if rule.kind == "bool":
        return type(value) is bool
    if rule.kind == "int":
        return type(value) is int
    if rule.kind == "number":
        return type(value) is int or (type(value) is float and math.isfinite(value))
    return type(value) is str and _LOWER_SHA256.fullmatch(value) is not None


def _metric_satisfies(
    value: object,
    rule: MetricRule,
    candidate: ProductionCandidateBinding,
) -> bool:
    if rule.comparison == "format":
        return True
    if rule.comparison == "binding":
        expected_by_target = {
            "migration_set": candidate.migration_set.sha256,
            "knowledge_service_migration_set": (
                candidate.knowledge_source_service.migration_set.sha256
            ),
            "knowledge_service_openapi_contract": (
                candidate.knowledge_source_service.openapi_contract.sha256
            ),
            "deployment_compatibility_manifest": (
                candidate.deployment_compatibility_manifest.sha256
            ),
        }
        binding_target = rule.binding_target
        if binding_target is None:
            return False
        expected = expected_by_target[binding_target]
        return value == expected
    if rule.comparison == "equal":
        return value == rule.expected
    numeric_value = cast("int | float", value)
    if rule.minimum_allowed is not None and numeric_value < rule.minimum_allowed:
        return False
    if rule.maximum_allowed is not None and numeric_value > rule.maximum_allowed:
        return False
    numeric_expected = cast("int | float", rule.expected)
    if rule.comparison == "minimum":
        return numeric_value >= numeric_expected
    return numeric_value <= numeric_expected


__all__ = ["evaluate_gate", "gate_policy_blockers"]
