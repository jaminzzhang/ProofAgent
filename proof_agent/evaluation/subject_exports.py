from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import (
    EvaluationSubjectExportSelection,
    EvaluationSubjectManifest,
)
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.subjects import load_evaluation_subject_manifest
from proof_agent.observability.storage.run_store import RunStore


def export_evaluation_subject_manifest_from_run_store(
    *,
    store: RunStore,
    suite_id: str,
    manifest_id: str,
    version: str,
    selections: Iterable[EvaluationSubjectExportSelection],
    output_path: Path | str,
    agent: Mapping[str, Any] | None = None,
) -> EvaluationSubjectManifest:
    """Export completed RunStore artifacts as an Evaluation Subject Manifest.

    This is a post-run export helper only. It reads existing artifacts from
    RunStore history and does not create Agent runs or evaluate outcomes.
    """

    destination = Path(output_path)
    selected = tuple(selections)
    if not selected:
        raise EvaluationInputError("Evaluation subject export requires at least one selection.")

    subjects: list[dict[str, Any]] = []
    agent_payload = dict(agent) if agent is not None else None
    for selection in selected:
        run_dir = store.history_dir / selection.run_id
        detail = store.get_run_detail(selection.run_id)
        if detail is None:
            raise EvaluationInputError(f"RunStore run is not exportable: {selection.run_id}")
        if agent_payload is None:
            agent_payload = _agent_payload_from_detail(detail)

        trace_path = run_dir / "trace.jsonl"
        receipt_path = run_dir / "governance_receipt.md"
        run_meta_path = run_dir / "run_meta.json"
        response_path = _resolve_response_projection_ref(
            selection.response_projection_ref,
            run_dir=run_dir,
        )
        _require_files(trace_path, receipt_path, run_meta_path, response_path)

        subjects.append(
            {
                "case_ref": selection.case_ref.model_dump(exclude_none=True),
                "artifacts": {
                    "trace_ref": _relative_ref(trace_path, destination),
                    "trace_sha256": _sha256(trace_path),
                    "receipt_ref": _relative_ref(receipt_path, destination),
                    "receipt_sha256": _sha256(receipt_path),
                    "run_meta_ref": _relative_ref(run_meta_path, destination),
                    "run_meta_sha256": _sha256(run_meta_path),
                },
                "projections": {
                    "evaluated_response": {
                        "audience": selection.response_projection_audience.value,
                        "ref": _relative_ref(response_path, destination),
                        "sha256": _sha256(response_path),
                        "sensitivity": selection.response_projection_sensitivity,
                    }
                },
                "execution_surface": selection.execution_surface.value,
                "run_ref": {
                    "run_id": selection.run_id,
                    "source": "run_store",
                },
            }
        )

    payload = {
        "manifest_id": manifest_id,
        "version": version,
        "suite_id": suite_id,
        "agent": agent_payload or {},
        "subjects": subjects,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return load_evaluation_subject_manifest(destination)


def _resolve_response_projection_ref(path: Path, *, run_dir: Path) -> Path:
    if path.is_absolute():
        return path
    return run_dir / path


def _require_files(*paths: Path) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise EvaluationInputError("cannot export missing run artifact refs: " + ", ".join(missing))


def _relative_ref(path: Path, manifest_path: Path) -> str:
    return os.path.relpath(path, start=manifest_path.parent)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _agent_payload_from_detail(detail: Any) -> dict[str, str]:
    payload: dict[str, str] = {}
    for attr in ("agent_id", "agent_version_id", "draft_id"):
        value = getattr(detail, attr, None)
        if value is not None:
            payload[attr] = str(value)
    return payload
