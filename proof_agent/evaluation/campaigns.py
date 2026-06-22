from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import (
    EvaluationAnalysisSummary,
    EvaluationCampaignCapabilityCoverage,
    EvaluationCampaignCapabilityStatus,
    EvaluationCampaignReadinessStatus,
    EvaluationCampaignSuiteRun,
    EvaluationCampaignSummary,
    EvaluationGateStatus,
    EvaluationReleaseDecisionStatus,
    EvaluationSuite,
)
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.sample_production import (
    EvaluationSampleRunner,
    produce_evaluation_subject_manifest_from_samples,
)
from proof_agent.evaluation.suites import load_evaluation_suite
from proof_agent.observability.storage.run_store import RunStore


def run_evaluation_campaign(
    *,
    campaign_path: Path | str,
    output_dir: Path | str | None = None,
    run_store: RunStore | None = None,
    sample_runner: EvaluationSampleRunner | None = None,
) -> EvaluationCampaignSummary:
    """Run a manifest-driven Evaluation Campaign over existing formal subjects."""

    manifest_path = Path(campaign_path)
    raw = _load_campaign_yaml(manifest_path)
    campaign_id = _required_string(raw, "campaign_id")
    version = _required_string(raw, "version")
    target = _required_mapping(raw, "target")
    target_agent_id = _required_string(target, "agent_id")
    target_agent_version_id = _optional_string(target, "agent_version_id")
    suite_specs = _formal_suite_specs(raw)
    campaign_dir = (Path(output_dir) if output_dir is not None else Path("runs/evaluation_campaigns"))
    artifact_dir = campaign_dir / campaign_id
    analyzer_output_dir = artifact_dir / "analyzer"

    analyses: list[tuple[str, EvaluationSuite, EvaluationAnalysisSummary]] = []
    for spec in suite_specs:
        suite_path = _resolve_path(spec["suite_ref"], base_dir=manifest_path.parent)
        source = str(spec.get("source", "formal"))
        suite = load_evaluation_suite(suite_path)
        if spec.get("produce_samples") is True:
            if run_store is None or sample_runner is None:
                raise EvaluationInputError(
                    "Evaluation Campaign sample production requires run_store and sample_runner."
                )
            subjects_path = artifact_dir / str(
                spec.get("subjects_output_ref") or "subject_manifest.yaml"
            )
            produce_evaluation_subject_manifest_from_samples(
                store=run_store,
                suite=suite,
                sample_runner=sample_runner,
                output_path=subjects_path,
                manifest_id=str(
                    spec.get("subject_manifest_id")
                    or f"{campaign_id}_{suite.suite_id}_subjects"
                ),
                version=version,
                target_agent_id=target_agent_id,
                target_agent_version_id=target_agent_version_id,
            )
        else:
            subjects_path = _resolve_path(spec["subjects_ref"], base_dir=manifest_path.parent)
        analysis = analyze_evaluation(
            suite_path=suite_path,
            subjects_path=subjects_path,
            output_dir=analyzer_output_dir,
        )
        analyses.append((source, suite, analysis))

    capability_coverage = _capability_coverage(analyses)
    governed_resolution_rate = _aggregate_required_case_rate(analyses)
    artifact_sufficiency_rate = min(
        (analysis.artifact_sufficiency_rate for _, _, analysis in analyses),
        default=1.0,
    )
    deterministic_gate_pass_rate = min(
        (analysis.deterministic_gate_pass_rate for _, _, analysis in analyses),
        default=1.0,
    )
    blocking_reasons = _blocking_reasons(analyses)
    summary = EvaluationCampaignSummary(
        campaign_id=campaign_id,
        version=version,
        target_agent_id=target_agent_id,
        target_agent_version_id=target_agent_version_id,
        readiness_status=(
            EvaluationCampaignReadinessStatus.BLOCKED
            if blocking_reasons
            else EvaluationCampaignReadinessStatus.READY
        ),
        blocking_reasons=blocking_reasons,
        governed_resolution_rate=governed_resolution_rate,
        artifact_sufficiency_rate=artifact_sufficiency_rate,
        deterministic_gate_pass_rate=deterministic_gate_pass_rate,
        suite_runs=tuple(
            EvaluationCampaignSuiteRun(
                source=source,
                suite_id=analysis.suite_id,
                suite_version=analysis.suite_version,
                analysis_id=analysis.analysis_id,
                release_decision_status=analysis.release_decision.status,
                total_required_cases=analysis.total_required_cases,
                passed_required_cases=analysis.passed_required_cases,
                governed_resolution_rate=analysis.governed_resolution_rate,
                artifact_dir=analysis.artifact_dir,
            )
            for source, _, analysis in analyses
        ),
        capability_coverage=capability_coverage,
        artifact_dir=artifact_dir,
    )
    _write_campaign_artifacts(summary)
    return summary


def _load_campaign_yaml(path: Path) -> Mapping[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise EvaluationInputError("Evaluation Campaign YAML must be a mapping.")
    return raw


def _formal_suite_specs(raw: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    suites = _required_mapping(raw, "suites")
    formal = suites.get("formal")
    if not isinstance(formal, list | tuple) or not formal:
        raise EvaluationInputError("Evaluation Campaign suites.formal must be a non-empty list.")
    specs: list[Mapping[str, Any]] = []
    for spec in formal:
        if not isinstance(spec, Mapping):
            raise EvaluationInputError("Evaluation Campaign formal suite entries must be mappings.")
        if spec.get("suite_ref") is None:
            raise EvaluationInputError(
                "Evaluation Campaign formal suite entries require suite_ref."
            )
        if spec.get("produce_samples") is not True and spec.get("subjects_ref") is None:
            raise EvaluationInputError(
                "Evaluation Campaign formal suite entries require subjects_ref unless "
                "produce_samples is true."
            )
        specs.append(spec)
    return tuple(specs)


def _capability_coverage(
    analyses: list[tuple[str, EvaluationSuite, EvaluationAnalysisSummary]],
) -> tuple[EvaluationCampaignCapabilityCoverage, ...]:
    totals: dict[str, int] = defaultdict(int)
    passes: dict[str, int] = defaultdict(int)
    for _, suite, analysis in analyses:
        result_by_case_id = {result.case_id: result for result in analysis.case_results}
        for case in suite.cases:
            if not case.required_for_release:
                continue
            totals[case.capability_path] += 1
            result = result_by_case_id.get(case.case_id)
            if result is not None and result.status == EvaluationGateStatus.PASSED:
                passes[case.capability_path] += 1
    coverage: list[EvaluationCampaignCapabilityCoverage] = []
    for capability_path in sorted(totals):
        required_cases = totals[capability_path]
        passed_required_cases = passes[capability_path]
        failed_required_cases = required_cases - passed_required_cases
        coverage.append(
            EvaluationCampaignCapabilityCoverage(
                capability_path=capability_path,
                status=(
                    EvaluationCampaignCapabilityStatus.PASSED
                    if failed_required_cases == 0
                    else EvaluationCampaignCapabilityStatus.FAILED
                ),
                required_cases=required_cases,
                passed_required_cases=passed_required_cases,
                failed_required_cases=failed_required_cases,
            )
        )
    return tuple(coverage)


def _aggregate_required_case_rate(
    analyses: list[tuple[str, EvaluationSuite, EvaluationAnalysisSummary]],
) -> float:
    required = sum(analysis.total_required_cases for _, _, analysis in analyses)
    if required == 0:
        return 1.0
    passed = sum(analysis.passed_required_cases for _, _, analysis in analyses)
    return passed / required


def _blocking_reasons(
    analyses: list[tuple[str, EvaluationSuite, EvaluationAnalysisSummary]],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if any(
        analysis.release_decision.status == EvaluationReleaseDecisionStatus.BLOCKED
        for _, _, analysis in analyses
    ):
        reasons.append("analyzer release decision blocked")
    for _, _, analysis in analyses:
        for reason in analysis.release_decision.blocking_reasons:
            if reason not in reasons:
                reasons.append(reason)
    return tuple(reasons)


def _write_campaign_artifacts(summary: EvaluationCampaignSummary) -> None:
    artifact_dir = Path(summary.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    page_data_dir = artifact_dir / "page_data"
    page_data_dir.mkdir(parents=True, exist_ok=True)
    summary_data = _summary_json(summary)
    (artifact_dir / "campaign_summary.json").write_text(
        json.dumps(summary_data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (page_data_dir / "evaluation_lab_summary.json").write_text(
        json.dumps(summary_data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "campaign_report.md").write_text(
        _campaign_report(summary),
        encoding="utf-8",
    )


def _summary_json(summary: EvaluationCampaignSummary) -> dict[str, Any]:
    data = _jsonable(summary.model_dump(mode="python", warnings=False))
    if not isinstance(data, dict):
        raise TypeError("Evaluation Campaign summary must serialize to a mapping.")
    return data


def _campaign_report(summary: EvaluationCampaignSummary) -> str:
    lines = [
        "# Evaluation Campaign Report",
        "",
        f"- campaign_id: {summary.campaign_id}",
        f"- version: {summary.version}",
        f"- target_agent_id: {summary.target_agent_id}",
        f"- target_agent_version_id: {summary.target_agent_version_id or 'none'}",
        f"- readiness_status: {summary.readiness_status.value}",
        f"- governed_resolution_rate: {summary.governed_resolution_rate:.3f}",
        f"- artifact_sufficiency_rate: {summary.artifact_sufficiency_rate:.3f}",
        f"- deterministic_gate_pass_rate: {summary.deterministic_gate_pass_rate:.3f}",
        "blocking_reasons: "
        + (", ".join(summary.blocking_reasons) if summary.blocking_reasons else "none"),
        "",
        "## Capability Coverage",
        "",
    ]
    for capability in summary.capability_coverage:
        lines.append(
            "- "
            f"{capability.capability_path}: {capability.status.value} "
            f"({capability.passed_required_cases}/{capability.required_cases})"
        )
    return "\n".join(lines) + "\n"


def _required_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise EvaluationInputError(f"Evaluation Campaign {key} must be a mapping.")
    return value


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError(f"Evaluation Campaign {key} must be a non-empty string.")
    return value


def _optional_string(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise EvaluationInputError(f"Evaluation Campaign {key} must be a string.")
    return value


def _resolve_path(value: Any, *, base_dir: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (base_dir / path).resolve(strict=False)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
