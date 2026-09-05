from __future__ import annotations

import json
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from proof_agent.contracts import (
    EvaluationAnalysisSummary,
    EvaluationCaseResult,
    EvaluationGateStatus,
)


def write_evaluation_analysis_artifacts(summary: EvaluationAnalysisSummary) -> None:
    """Write Analyzer-owned report, JSONL results, and analysis receipt artifacts."""

    if summary.artifact_dir is None:
        return
    artifact_dir = Path(summary.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "evaluation_report.md").write_text(_report_markdown(summary), encoding="utf-8")
    (artifact_dir / "evaluation_results.jsonl").write_text(
        _results_jsonl(summary), encoding="utf-8"
    )
    (artifact_dir / "evaluation_quality.json").write_text(
        json.dumps(
            {
                "schema_version": "evaluation-quality-report.v1",
                "analysis_id": summary.analysis_id,
                "analyzer_version": summary.analyzer_version,
                "suite_id": summary.suite_id,
                "suite_version": summary.suite_version,
                "subject_manifest_id": summary.subject_manifest_id,
                "subject_manifest_version": summary.subject_manifest_version,
                "gate_profile_id": summary.gate_profile_id,
                "judge_mode": summary.judge_mode,
                "metrics": summary.quality_metrics.model_dump(mode="json")
                if summary.quality_metrics
                else None,
                "cases": [_case_quality_json(result) for result in summary.case_results],
                "scenario_steps": [
                    _case_quality_json(step)
                    for scenario in summary.scenario_results
                    for step in scenario.step_results
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "evaluation_analysis_receipt.md").write_text(
        _analysis_receipt_markdown(summary),
        encoding="utf-8",
    )


def _report_markdown(summary: EvaluationAnalysisSummary) -> str:
    lines = [
        "# Evaluation Report",
        "",
        f"- analysis_id: {summary.analysis_id}",
        f"- suite_id: {summary.suite_id}",
        f"- subject_manifest_id: {summary.subject_manifest_id}",
        f"- governed_resolution_rate: {summary.governed_resolution_rate:.3f}",
        f"- scenario_governed_resolution_rate: {summary.scenario_governed_resolution_rate:.3f}",
        f"- subject_coverage_rate: {summary.subject_coverage_rate:.3f}",
        f"- artifact_sufficiency_rate: {summary.artifact_sufficiency_rate:.3f}",
        f"- release_decision: {summary.release_decision.status.value}",
        "",
    ]
    lines.extend(_quality_markdown(summary))
    if summary.behavior_metrics:
        lines.extend(["## Behavior Metrics", ""])
        for metric, value in sorted(summary.behavior_metrics.items()):
            lines.append(f"- {metric}: {value:.3f}")
        lines.append("")
    lines.extend(["## Case Results", ""])
    for result in summary.case_results:
        lines.append(f"- {result.case_id}: {result.status.value}")
    if summary.scenario_results:
        lines.extend(["", "## Scenario Results", ""])
        for scenario_result in summary.scenario_results:
            outcomes = ", ".join(scenario_result.actual_ordered_outcomes) or "none"
            lines.append(
                f"- {scenario_result.scenario_id}: {scenario_result.status.value} ({outcomes})"
            )
    return "\n".join(lines) + "\n"


def _results_jsonl(summary: EvaluationAnalysisSummary) -> str:
    lines = [
        json.dumps(_jsonable(result.model_dump(mode="python", warnings=False)), sort_keys=True)
        for result in summary.case_results
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def _analysis_receipt_markdown(summary: EvaluationAnalysisSummary) -> str:
    failed_cases = [
        result.case_id
        for result in summary.case_results
        if result.status == EvaluationGateStatus.FAILED
    ]
    lines = [
        "# Evaluation Analysis Receipt",
        "",
        f"analyzer_version: {summary.analyzer_version}",
        f"analysis_id: {summary.analysis_id}",
        f"suite_id: {summary.suite_id}",
        f"suite_version: {summary.suite_version}",
        f"subject_manifest_id: {summary.subject_manifest_id}",
        f"subject_manifest_version: {summary.subject_manifest_version}",
        f"gate_profile_id: {summary.gate_profile_id}",
        f"judge_mode: {summary.judge_mode}",
        f"release_decision: {summary.release_decision.status.value}",
        "release_blocking_reasons: "
        + (
            ", ".join(summary.release_decision.blocking_reasons)
            if summary.release_decision.blocking_reasons
            else "none"
        ),
        f"governed_resolution_rate: {summary.governed_resolution_rate:.3f}",
        f"scenario_governed_resolution_rate: {summary.scenario_governed_resolution_rate:.3f}",
        f"subject_coverage_rate: {summary.subject_coverage_rate:.3f}",
        f"artifact_sufficiency_rate: {summary.artifact_sufficiency_rate:.3f}",
        f"failed_cases: {', '.join(failed_cases) if failed_cases else 'none'}",
    ]
    if summary.agent:
        lines.extend(["", "## Agent Provenance", ""])
        for key, value in sorted(summary.agent.items()):
            lines.append(f"{key}: {value}")
    lines.extend(["", *_quality_markdown(summary)])
    return "\n".join(lines).rstrip() + "\n"


def _case_quality_json(result: EvaluationCaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "scenario_id": result.scenario_id,
        "scenario_step_id": result.scenario_step_id,
        "included_in_cohort": result.quality_cohort_included,
        "quality": result.quality.model_dump(mode="json") if result.quality else None,
    }


def _quality_markdown(summary: EvaluationAnalysisSummary) -> list[str]:
    metrics = summary.quality_metrics
    if metrics is None:
        return ["## Verified Quality", "", "Quality was not evaluated by this analysis.", ""]
    lines = [
        "## Verified Quality",
        "",
        f"- schema_version: {metrics.schema_version}",
        f"- cohort_scope: {metrics.cohort_scope}",
        f"- total_required_cases: {metrics.total_required_cases}",
        f"- unclassified_required_count: {metrics.unclassified_required_count}",
        "",
        "GRR measures governed resolution. Quality uses separate targets and verifiers.",
        "Verified success = passed / total; coverage = (passed + failed) / total.",
        "Unevaluated cases remain in total. With unmeasured cases this is not an accuracy estimate.",
        "An empty cohort is n/a. Refusal success only matches the curated refusal decision;",
        "it does not verify wording or prove that no answer exists. Answer semantics and task",
        "completion have no positive verifier in this version. Quality is not a release gate.",
        "",
        "| target | total | passed | failed | not_evaluated | verified_success_rate | assessment_coverage_rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for cohort in metrics.cohorts:
        success = (
            f"{cohort.verified_success_rate:.3f}"
            if cohort.verified_success_rate is not None
            else "n/a"
        )
        coverage = (
            f"{cohort.assessment_coverage_rate:.3f}"
            if cohort.assessment_coverage_rate is not None
            else "n/a"
        )
        lines.append(
            f"| {cohort.target.value} | {cohort.total} | {cohort.passed} | {cohort.failed} | "
            f"{cohort.not_evaluated} | {success} | {coverage} |"
        )
    lines.extend(["", "### Case Quality", ""])
    results = (
        *summary.case_results,
        *(step for scenario in summary.scenario_results for step in scenario.step_results),
    )
    for result in results:
        label = result.case_id
        if result.scenario_id is not None:
            label += f" ({result.scenario_id}/{result.scenario_step_id}; outside cohort)"
        elif result.quality_cohort_included is False:
            label += " (outside cohort)"
        quality = result.quality
        if quality is None:
            lines.append(f"- {label}: quality not recorded")
        else:
            target = quality.target.value if quality.target else "unclassified"
            lines.append(f"- {label}: {target}; {quality.status.value}; {quality.reason.value}")
    return [*lines, ""]


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
