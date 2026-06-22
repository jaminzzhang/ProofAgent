from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from proof_agent.contracts._base import FrozenModel


class ExploratoryProbeRunRequest(FrozenModel):
    probe_run_version: str = "exploratory-probes.v1"
    campaign_id: str
    version: str
    target_agent_id: str
    target_agent_version_id: str | None = None
    max_cases: int
    surfaces: tuple[dict[str, Any], ...] = Field(default_factory=tuple)


class ExploratoryProbeResult(FrozenModel):
    probe_id: str
    status: Literal["passed_with_diagnostics", "needs_review"]
    source: Literal["exploratory"] = "exploratory"
    surface_ref: str | None = None
    intent_boundary: str | None = None
    finding_summary: str
    diagnostic_blocker_candidate: bool = False


ExploratoryProbeRunner = Callable[
    [ExploratoryProbeRunRequest],
    Iterable[ExploratoryProbeResult],
]


def run_exploratory_probes(
    *,
    runner: ExploratoryProbeRunner,
    request: ExploratoryProbeRunRequest,
) -> tuple[ExploratoryProbeResult, ...]:
    """Run injected diagnostic probes without affecting formal campaign scoring."""

    return tuple(runner(request))


def write_exploratory_probe_artifacts(
    *,
    artifact_dir: Path,
    results: Iterable[ExploratoryProbeResult],
) -> None:
    diagnostics_dir = artifact_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    (diagnostics_dir / "exploratory_probe_results.jsonl").write_text(
        "".join(
            json.dumps(result.model_dump(mode="json"), sort_keys=True) + "\n" for result in results
        ),
        encoding="utf-8",
    )
