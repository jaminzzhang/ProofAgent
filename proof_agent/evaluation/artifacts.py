from __future__ import annotations

import json
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from proof_agent.contracts import EvaluationAnalysisSummary, EvaluationGateStatus


def write_evaluation_analysis_artifacts(summary: EvaluationAnalysisSummary) -> None:
    """Write Analyzer-owned report, JSONL results, and analysis receipt artifacts."""

    if summary.artifact_dir is None:
        return
    artifact_dir = Path(summary.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "evaluation_report.md").write_text(_report_markdown(summary), encoding="utf-8")
    (artifact_dir / "evaluation_results.jsonl").write_text(_results_jsonl(summary), encoding="utf-8")
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
        "## Case Results",
        "",
    ]
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
    return "\n".join(lines) + "\n"


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
