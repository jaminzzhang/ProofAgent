from __future__ import annotations

import json
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from proof_agent.contracts import (
    EvaluationAnalysisSummary,
    EvaluationCampaignDiagnostics,
    EvaluationCampaignSummary,
    EvaluationDiagnosticInputBundle,
    EvaluationDiagnosticInputCase,
)


CodingAgentDiagnosticReviewer = Callable[
    [EvaluationDiagnosticInputBundle],
    EvaluationCampaignDiagnostics,
]


def run_coding_agent_diagnostics(
    *,
    campaign: EvaluationCampaignSummary,
    analyses: Iterable[EvaluationAnalysisSummary],
    reviewer: CodingAgentDiagnosticReviewer,
) -> tuple[EvaluationDiagnosticInputBundle, EvaluationCampaignDiagnostics]:
    """Run an injected coding-agent reviewer over safe Evaluation Campaign facts."""

    input_bundle = build_coding_agent_diagnostic_input(campaign=campaign, analyses=analyses)
    diagnostics = reviewer(input_bundle)
    return input_bundle, _normalized_diagnostics(diagnostics)


def build_coding_agent_diagnostic_input(
    *,
    campaign: EvaluationCampaignSummary,
    analyses: Iterable[EvaluationAnalysisSummary],
) -> EvaluationDiagnosticInputBundle:
    cases: list[EvaluationDiagnosticInputCase] = []
    for analysis in analyses:
        for case in analysis.case_results:
            cases.append(
                EvaluationDiagnosticInputCase(
                    case_id=case.case_id,
                    expected_outcome=case.expected_outcome.value,
                    actual_outcome=case.actual_outcome.value if case.actual_outcome else None,
                    status=case.status.value,
                    primary_failure_owner=(
                        case.primary_failure_owner.value
                        if case.primary_failure_owner is not None
                        else None
                    ),
                    response_projection=case.response_projection,
                    gate_results=tuple(
                        {
                            "gate": gate.gate.value,
                            "status": gate.status.value,
                            "reason": gate.reason,
                            "failure_owner": (
                                gate.failure_owner.value if gate.failure_owner is not None else None
                            ),
                        }
                        for gate in case.gates
                    ),
                    warnings=case.warnings,
                )
            )
    return EvaluationDiagnosticInputBundle(
        campaign_id=campaign.campaign_id,
        version=campaign.version,
        target_agent_id=campaign.target_agent_id,
        target_agent_version_id=campaign.target_agent_version_id,
        readiness_status=campaign.readiness_status.value,
        governed_resolution_rate=campaign.governed_resolution_rate,
        artifact_sufficiency_rate=campaign.artifact_sufficiency_rate,
        deterministic_gate_pass_rate=campaign.deterministic_gate_pass_rate,
        cases=tuple(cases),
    )


def write_coding_agent_diagnostic_artifacts(
    *,
    artifact_dir: Path,
    input_bundle: EvaluationDiagnosticInputBundle,
    diagnostics: EvaluationCampaignDiagnostics,
) -> None:
    diagnostics_dir = artifact_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    (diagnostics_dir / "coding_agent_input_bundle.json").write_text(
        json.dumps(_jsonable(input_bundle.model_dump(mode="python")), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (diagnostics_dir / "coding_agent_diagnostics.json").write_text(
        json.dumps(_jsonable(diagnostics.model_dump(mode="python")), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _normalized_diagnostics(
    diagnostics: EvaluationCampaignDiagnostics,
) -> EvaluationCampaignDiagnostics:
    case_diagnostics = diagnostics.case_diagnostics
    scores = tuple(case.quality_score for case in case_diagnostics)
    blocker_count = sum(1 for case in case_diagnostics if case.diagnostic_blocker_candidate)
    mean_score = round(sum(scores) / len(scores), 4) if scores else None
    return diagnostics.model_copy(
        update={
            "evaluated_case_count": len(case_diagnostics),
            "mean_quality_score": mean_score,
            "diagnostic_blocker_candidate_count": blocker_count,
        }
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
