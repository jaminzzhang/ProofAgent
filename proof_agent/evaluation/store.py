from __future__ import annotations

import json
from pathlib import Path

from proof_agent.contracts import (
    EvaluationAnalysisRecord,
    EvaluationCaseResult,
    EvaluationReleaseDecisionStatus,
)
from proof_agent.evaluation.errors import EvaluationInputError


class EvaluationStore:
    """Read-only index over Evaluation Analyzer artifact directories."""

    def __init__(self, root_dir: Path | str) -> None:
        self._root_dir = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def list_analyses(self) -> tuple[EvaluationAnalysisRecord, ...]:
        if not self._root_dir.exists():
            return ()
        records = [
            record
            for path in sorted(self._root_dir.iterdir())
            if path.is_dir()
            for record in [self._load_record(path)]
            if record is not None
        ]
        return tuple(records)

    def get_case_results(self, analysis_id: str) -> tuple[EvaluationCaseResult, ...]:
        analysis_dir = self._root_dir / analysis_id
        results_path = analysis_dir / "evaluation_results.jsonl"
        if not results_path.is_file():
            raise EvaluationInputError(f"Evaluation analysis artifacts not found: {analysis_id}")
        results: list[EvaluationCaseResult] = []
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                results.append(EvaluationCaseResult.model_validate(json.loads(line)))
        return tuple(results)

    def _load_record(self, analysis_dir: Path) -> EvaluationAnalysisRecord | None:
        receipt_path = analysis_dir / "evaluation_analysis_receipt.md"
        results_path = analysis_dir / "evaluation_results.jsonl"
        if not receipt_path.is_file() or not results_path.is_file():
            return None
        receipt = _read_receipt_fields(receipt_path)
        case_results = self.get_case_results(analysis_dir.name)
        failed_case_count = sum(1 for result in case_results if result.status.value == "failed")
        return EvaluationAnalysisRecord(
            analysis_id=receipt.get("analysis_id", analysis_dir.name),
            suite_id=receipt.get("suite_id", ""),
            subject_manifest_id=receipt.get("subject_manifest_id", ""),
            release_decision_status=_release_decision_status(receipt.get("release_decision")),
            governed_resolution_rate=_float_field(receipt, "governed_resolution_rate"),
            artifact_sufficiency_rate=_float_field(receipt, "artifact_sufficiency_rate"),
            failed_case_count=failed_case_count,
            total_case_count=len(case_results),
            artifact_dir=analysis_dir,
        )


def _read_receipt_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _release_decision_status(value: str | None) -> EvaluationReleaseDecisionStatus | None:
    if value is None:
        return None
    try:
        return EvaluationReleaseDecisionStatus(value)
    except ValueError:
        return None


def _float_field(fields: dict[str, str], key: str) -> float:
    try:
        return float(fields.get(key, "0"))
    except ValueError:
        return 0.0
