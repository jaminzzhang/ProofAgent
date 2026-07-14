"""Load and validate publication-bound insurance Knowledge gold suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError
import yaml  # type: ignore[import-untyped]

from proof_agent.contracts.evaluation import InsuranceKnowledgeGoldSuite
from proof_agent.evaluation.errors import EvaluationInputError


def load_insurance_knowledge_suite(path: Path | str) -> InsuranceKnowledgeGoldSuite:
    """Load one reviewable gold suite through the strict evaluation contract."""

    suite_path = Path(path)
    try:
        raw = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationInputError(
            f"Unable to read insurance Knowledge suite: {suite_path}"
        ) from exc
    if not isinstance(raw, dict):
        raise EvaluationInputError("Insurance Knowledge suite YAML must be a mapping.")
    try:
        return InsuranceKnowledgeGoldSuite.model_validate(_plain_mapping(raw))
    except ValidationError as exc:
        raise EvaluationInputError(f"Invalid insurance Knowledge suite: {exc}") from exc


def _plain_mapping(value: dict[Any, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


__all__ = ["load_insurance_knowledge_suite"]
