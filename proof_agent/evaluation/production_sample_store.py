from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from proof_agent.evaluation.errors import EvaluationInputError


class ProductionSampleCurationStore:
    """Read-only index over curated production sample artifacts."""

    def __init__(self, root_dir: Path | str) -> None:
        self._root_dir = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def list_candidates(self) -> tuple[dict[str, Any], ...]:
        if not self._root_dir.exists():
            return ()
        rows: list[dict[str, Any]] = []
        for candidates_path in sorted(
            self._root_dir.rglob("production_sample_candidates.jsonl")
        ):
            batch_id = candidates_path.parent.name
            for row in _read_jsonl_mappings(candidates_path):
                rows.append(
                    {
                        "batch_id": batch_id,
                        "batch_dir": str(candidates_path.parent),
                        **row,
                    }
                )
        return tuple(rows)

    def list_promotions(self) -> tuple[dict[str, Any], ...]:
        if not self._root_dir.exists():
            return ()
        promotions: list[dict[str, Any]] = []
        for promotion_path in sorted(
            self._root_dir.rglob("production_sample_promotion.json")
        ):
            promotion = _read_json_mapping(promotion_path)
            promotions.append(
                {
                    "promotion_dir": str(promotion_path.parent),
                    "promotion_record_path": str(promotion_path),
                    **promotion,
                }
            )
        return tuple(promotions)


def _read_jsonl_mappings(path: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise EvaluationInputError(
                f"Production sample curation row must be a mapping: {path}"
            )
        rows.append(raw)
    return tuple(rows)


def _read_json_mapping(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvaluationInputError(
            f"Production sample promotion record must be a mapping: {path}"
        )
    return raw
