"""Evaluation export endpoints for the dashboard."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from proof_agent.contracts import (
    EvaluationCaseRef,
    EvaluationResponseProjectionAudience,
    EvaluationSubjectExportSelection,
)
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.subject_exports import (
    export_evaluation_subject_manifest_from_run_store,
)
from proof_agent.evaluation.store import EvaluationStore
from proof_agent.observability.api.dependencies import get_evaluation_store, get_store
from proof_agent.observability.storage.run_store import RunStore

router = APIRouter(tags=["evaluation"])

_SAFE_MANIFEST_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


@router.get("/evaluation/analyses")
def list_evaluation_analyses(
    store: EvaluationStore = Depends(get_evaluation_store),
) -> dict[str, Any]:
    """List Evaluation Analyzer artifact summaries."""

    analyses = store.list_analyses()
    return {
        "data": [_jsonable(analysis.model_dump(mode="python", warnings=False)) for analysis in analyses],
        "meta": {"total": len(analyses)},
    }


@router.get("/evaluation/analyses/{analysis_id}/cases")
def list_evaluation_case_results(
    analysis_id: str,
    store: EvaluationStore = Depends(get_evaluation_store),
) -> dict[str, Any]:
    """List case-level Evaluation Analyzer results for one analysis."""

    try:
        case_results = store.get_case_results(analysis_id)
    except EvaluationInputError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "analysis_id": analysis_id,
        "data": [
            _jsonable(case_result.model_dump(mode="python", warnings=False))
            for case_result in case_results
        ],
        "meta": {"total": len(case_results)},
    }


class EvaluationSubjectExportSelectionRequest(BaseModel):
    case_ref: EvaluationCaseRef
    run_id: str
    response_projection_ref: Path
    response_projection_audience: EvaluationResponseProjectionAudience
    response_projection_sensitivity: Literal["local_only", "release_safe"] = "release_safe"


class EvaluationSubjectExportRequest(BaseModel):
    suite_id: str
    manifest_id: str
    version: str
    selections: tuple[EvaluationSubjectExportSelectionRequest, ...] = Field(
        min_length=1,
    )


@router.post("/evaluation/subject-manifests/export")
def export_evaluation_subject_manifest(
    request: EvaluationSubjectExportRequest,
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """Export selected completed runs as an Evaluation Subject Manifest."""

    if not _SAFE_MANIFEST_ID.match(request.manifest_id):
        raise HTTPException(
            status_code=400,
            detail="manifest_id may contain only letters, numbers, dots, underscores, and hyphens.",
        )
    output_path = (
        store.history_dir.parent / "evaluation_subject_exports" / f"{request.manifest_id}.yaml"
    )
    try:
        manifest = export_evaluation_subject_manifest_from_run_store(
            store=store,
            suite_id=request.suite_id,
            manifest_id=request.manifest_id,
            version=request.version,
            selections=tuple(
                EvaluationSubjectExportSelection(
                    case_ref=selection.case_ref,
                    run_id=selection.run_id,
                    response_projection_ref=selection.response_projection_ref,
                    response_projection_audience=selection.response_projection_audience,
                    response_projection_sensitivity=selection.response_projection_sensitivity,
                )
                for selection in request.selections
            ),
            output_path=output_path,
        )
    except EvaluationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "manifest_id": manifest.manifest_id,
        "suite_id": manifest.suite_id,
        "version": manifest.version,
        "subject_count": len(manifest.subjects),
        "manifest_path": str(output_path),
    }


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
