from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from proof_agent.evaluation.errors import EvaluationInputError


class EvaluationCampaignStore:
    """Read-only index over Evaluation Campaign page-data artifacts."""

    def __init__(self, root_dir: Path | str) -> None:
        self._root_dir = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def list_campaigns(self) -> tuple[dict[str, Any], ...]:
        if not self._root_dir.exists():
            return ()
        campaigns = [
            campaign
            for path in sorted(self._root_dir.iterdir())
            if path.is_dir()
            for campaign in [self._load_campaign(path)]
            if campaign is not None
        ]
        return tuple(campaigns)

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        page_data_path = self._page_data_path(campaign_id)
        if not page_data_path.is_file():
            raise EvaluationInputError(
                f"Evaluation Campaign artifacts not found: {campaign_id}"
            )
        return _read_json_mapping(page_data_path)

    def _load_campaign(self, campaign_dir: Path) -> dict[str, Any] | None:
        page_data_path = campaign_dir / "page_data" / "evaluation_lab_summary.json"
        if not page_data_path.is_file():
            return None
        return _read_json_mapping(page_data_path)

    def _page_data_path(self, campaign_id: str) -> Path:
        if (
            not campaign_id
            or campaign_id in {".", ".."}
            or Path(campaign_id).name != campaign_id
        ):
            raise EvaluationInputError(
                f"Evaluation Campaign artifacts not found: {campaign_id}"
            )
        return self._root_dir / campaign_id / "page_data" / "evaluation_lab_summary.json"


def _read_json_mapping(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvaluationInputError(f"Evaluation Campaign page data must be a mapping: {path}")
    return raw
