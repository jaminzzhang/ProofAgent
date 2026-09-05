"""Offline diagnostic baseline; never a production readiness authority."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType

from proof_agent.evaluation.exploratory_probes import (
    ExploratoryProbeResult,
    write_exploratory_probe_artifacts,
)


BASELINE_VERSION = "agent-kernel-baseline.v1"
PROBE_REQUIREMENTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "numeric_answer_validation": ("correct_answer_accepted", "wrong_amount_rejected"),
        "compound_retrieval_completion": ("both_sources_queried", "both_facts_reach_answer"),
        "intent_rewrite_reaches_kss": ("required_rewrite_reaches_kss",),
        "structured_fact_reaches_answer": ("structured_amount_reaches_answer",),
        "long_conversation_constraints": ("budget_retained", "submission_prohibition_retained"),
    }
)
Probe = Callable[[], Mapping[str, bool]]


def evaluate_observation(probe_id: str, facts: Mapping[str, object]) -> ExploratoryProbeResult:
    """Only complete, strictly boolean observations satisfy a probe's contract."""
    requirements = PROBE_REQUIREMENTS[probe_id]
    valid = set(facts) == set(requirements) and all(type(value) is bool for value in facts.values())
    passed = valid and all(facts[name] is True for name in requirements)
    # Never serialize unexpected keys or values from a measurement adapter.
    observation = (
        ", ".join(f"{name}={str(facts[name]).lower()}" for name in requirements)
        if valid
        else "invalid_or_missing_observation"
    )
    return _result(
        probe_id,
        passed=passed,
        summary=f"expected: {', '.join(requirements)}=true; observed: {observation}",
    )


def run_kernel_baseline(
    *, probes: Mapping[str, Probe] | None = None
) -> tuple[ExploratoryProbeResult, ...]:
    if probes is None:
        from proof_agent.evaluation.demo.kernel_probes import build_kernel_probes

        probes = build_kernel_probes()
    results: list[ExploratoryProbeResult] = []
    for probe_id in PROBE_REQUIREMENTS:
        probe = probes.get(probe_id)
        if probe is None:
            results.append(_result(probe_id, passed=False, summary="probe_not_run"))
            continue
        try:
            results.append(evaluate_observation(probe_id, probe()))
        except Exception:
            # Fixed diagnostics only: adapter exceptions can contain prompts or secrets.
            results.append(_result(probe_id, passed=False, summary="probe_execution_error"))
    if set(probes) - set(PROBE_REQUIREMENTS):
        results.append(_result("baseline_registry", passed=False, summary="unexpected_probe"))
    return tuple(results)


def baseline_passed(results: Iterable[ExploratoryProbeResult]) -> bool:
    results = tuple(results)
    return (
        len(results) == len(PROBE_REQUIREMENTS)
        and {result.probe_id for result in results} == set(PROBE_REQUIREMENTS)
        and all(
            result.status == "passed_with_diagnostics" and not result.diagnostic_blocker_candidate
            for result in results
        )
    )


def write_kernel_baseline_artifacts(
    *, artifact_dir: Path, results: tuple[ExploratoryProbeResult, ...], source_fingerprint: str
) -> None:
    write_exploratory_probe_artifacts(artifact_dir=artifact_dir, results=results)
    status = "passed_with_diagnostics" if baseline_passed(results) else "needs_review"
    metadata = {
        "baseline_version": BASELINE_VERSION,
        "source_fingerprint": source_fingerprint,
        "execution_scope": "synthetic_local",
        "production_readiness": "not_evaluated",
        "status": status,
        "required_probe_ids": list(PROBE_REQUIREMENTS),
        "results": [result.model_dump(mode="json") for result in results],
    }
    (artifact_dir / "kernel_baseline.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# Agent kernel diagnostic baseline", ""]
    lines.extend(
        f"- {key}: {metadata[key]}"
        for key in (
            "baseline_version",
            "source_fingerprint",
            "execution_scope",
            "production_readiness",
            "status",
        )
    )
    lines.extend(
        ["", "These fixed synthetic probes do not measure population answer accuracy.", ""]
    )
    for result in results:
        lines.extend([f"- {result.probe_id}: {result.status}", f"  {result.finding_summary}"])
    (artifact_dir / "kernel_baseline.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def baseline_source_fingerprint(root: Path) -> str:
    """Hash code and fixed inputs without reading environment files or runtime data."""
    paths = sorted(
        {
            *root.joinpath("proof_agent").rglob("*.py"),
            *root.joinpath("proof_agent/evaluation/demo/fixtures").rglob("*.yaml"),
            *root.joinpath("proof_agent/evaluation/demo/fixtures").rglob("*.json"),
            root / "scripts/check-agent-kernel-baseline.py",
            root / "uv.lock",
        }
    )
    digest = sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(sha256(path.read_bytes()).digest())
    return f"sha256:{digest.hexdigest()}"


def run_baseline_check(
    *, artifact_dir: Path, root: Path, probes: Mapping[str, Probe] | None = None
) -> int:
    before = baseline_source_fingerprint(root)
    results = run_kernel_baseline(probes=probes)
    if baseline_source_fingerprint(root) != before:
        results += (_result("baseline_source", passed=False, summary="source_changed_during_run"),)
    write_kernel_baseline_artifacts(
        artifact_dir=artifact_dir, results=results, source_fingerprint=before
    )
    return 0 if baseline_passed(results) else 1


def _result(probe_id: str, *, passed: bool, summary: str) -> ExploratoryProbeResult:
    return ExploratoryProbeResult(
        probe_id=probe_id,
        status="passed_with_diagnostics" if passed else "needs_review",
        finding_summary=summary,
        diagnostic_blocker_candidate=not passed,
    )
