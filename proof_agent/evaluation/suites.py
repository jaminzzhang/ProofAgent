from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import EvaluationSuite
from proof_agent.evaluation.errors import EvaluationInputError

BUILTIN_SUITES = {
    "smoke": "insurance_qa_smoke.yaml",
    "insurance_qa_smoke": "insurance_qa_smoke.yaml",
    "v3_intent_execution": "v3_intent_execution.yaml",
}


def load_evaluation_suite(path: Path | str) -> EvaluationSuite:
    """Load an Evaluation Suite from a YAML file."""

    suite_path = _suite_path(path)
    raw = yaml.safe_load(suite_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise EvaluationInputError("Evaluation suite YAML must be a mapping.")
    suite = EvaluationSuite.model_validate(_plain_mapping(raw))
    _reject_duplicate_case_ids(suite)
    _reject_duplicate_scenario_ids(suite)
    _reject_duplicate_scenario_step_ids(suite)
    return suite


def _plain_mapping(value: dict[Any, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


def _suite_path(path: Path | str) -> Path:
    key = str(path)
    if key in BUILTIN_SUITES:
        return Path(__file__).parent / "suites" / BUILTIN_SUITES[key]
    return Path(path)


def _reject_duplicate_case_ids(suite: EvaluationSuite) -> None:
    seen: set[str] = set()
    for case in suite.cases:
        if case.case_id in seen:
            raise EvaluationInputError(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)


def _reject_duplicate_scenario_ids(suite: EvaluationSuite) -> None:
    seen: set[str] = set()
    for scenario in suite.scenarios:
        if scenario.scenario_id in seen:
            raise EvaluationInputError(f"duplicate scenario_id: {scenario.scenario_id}")
        seen.add(scenario.scenario_id)


def _reject_duplicate_scenario_step_ids(suite: EvaluationSuite) -> None:
    for scenario in suite.scenarios:
        seen: set[str] = set()
        for step in scenario.steps:
            if step.step_id in seen:
                raise EvaluationInputError(
                    f"duplicate scenario step_id in {scenario.scenario_id}: {step.step_id}"
                )
            seen.add(step.step_id)
