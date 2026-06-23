"""Evaluation export endpoints for the dashboard."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.contracts import (
    EvaluationCaseRef,
    EvaluationResponseProjectionAudience,
    EvaluationSubjectExportSelection,
    ReceiptOutcome,
)
from proof_agent.evaluation.campaign_store import EvaluationCampaignStore
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.production_samples import (
    ProductionSamplePromotionCase,
    ProductionSampleReviewerConfirmation,
    promote_curated_production_sample,
)
from proof_agent.evaluation.production_sample_store import ProductionSampleCurationStore
from proof_agent.evaluation.subject_exports import (
    export_evaluation_subject_manifest_from_run_store,
)
from proof_agent.evaluation.store import EvaluationStore
from proof_agent.observability.api.dependencies import (
    get_evaluation_campaign_store,
    get_evaluation_store,
    get_operator_identity,
    get_production_sample_curation_store,
    get_store,
)
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
    require_operator_permission,
)
from proof_agent.observability.storage.run_store import RunStore

router = APIRouter(tags=["evaluation"])

_SAFE_MANIFEST_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_CURATED_SAMPLE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


@router.get("/evaluation/analyses")
def list_evaluation_analyses(
    store: EvaluationStore = Depends(get_evaluation_store),
) -> dict[str, Any]:
    """List Evaluation Analyzer artifact summaries."""

    analyses = store.list_analyses()
    return {
        "data": [
            _jsonable(analysis.model_dump(mode="python", warnings=False)) for analysis in analyses
        ],
        "meta": {"total": len(analyses)},
    }


@router.get("/evaluation/campaigns")
def list_evaluation_campaigns(
    store: EvaluationCampaignStore = Depends(get_evaluation_campaign_store),
) -> dict[str, Any]:
    """List Evaluation Campaign page-data summaries."""

    campaigns = store.list_campaigns()
    return {
        "data": [_jsonable(campaign) for campaign in campaigns],
        "meta": {"total": len(campaigns)},
    }


@router.get("/evaluation/campaigns/{campaign_id}")
def get_evaluation_campaign(
    campaign_id: str,
    store: EvaluationCampaignStore = Depends(get_evaluation_campaign_store),
) -> dict[str, Any]:
    """Read one Evaluation Campaign page-data summary."""

    try:
        campaign = store.get_campaign(campaign_id)
    except EvaluationInputError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return cast(dict[str, Any], _jsonable(campaign))


@router.get("/evaluation/campaigns/{campaign_id}/cases")
def list_evaluation_campaign_cases(
    campaign_id: str,
    store: EvaluationCampaignStore = Depends(get_evaluation_campaign_store),
) -> dict[str, Any]:
    """List case-level Evaluation Campaign page-data rows."""

    try:
        case_rows = store.get_campaign_cases(campaign_id)
    except EvaluationInputError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "campaign_id": campaign_id,
        "data": [_jsonable(row) for row in case_rows],
        "meta": {"total": len(case_rows)},
    }


@router.get("/evaluation/campaigns/{campaign_id}/trends")
def get_evaluation_campaign_trends(
    campaign_id: str,
    store: EvaluationCampaignStore = Depends(get_evaluation_campaign_store),
) -> dict[str, Any]:
    """Read one Evaluation Campaign version-aware trend projection."""

    try:
        trends = store.get_campaign_trends(campaign_id)
    except EvaluationInputError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return cast(dict[str, Any], _jsonable(trends))


@router.get("/evaluation/production-samples/candidates")
def list_evaluation_production_sample_candidates(
    store: ProductionSampleCurationStore = Depends(get_production_sample_curation_store),
) -> dict[str, Any]:
    """List diagnostic curated production sample candidates."""

    try:
        candidates = store.list_candidates()
    except EvaluationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "data": [_jsonable(candidate) for candidate in candidates],
        "meta": {"total": len(candidates)},
    }


@router.get("/evaluation/production-samples/promotions")
def list_evaluation_production_sample_promotions(
    store: ProductionSampleCurationStore = Depends(get_production_sample_curation_store),
) -> dict[str, Any]:
    """List promoted curated production sample records."""

    try:
        promotions = store.list_promotions()
    except EvaluationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "data": [_jsonable(promotion) for promotion in promotions],
        "meta": {"total": len(promotions)},
    }


class ProductionSamplePromotionCaseRequest(BaseModel):
    """Case metadata required to promote a curated production sample."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    intent_type: str = Field(min_length=1)
    expected_resolution: str = Field(min_length=1)
    risk_class: str = Field(min_length=1)
    capability_path: str = Field(min_length=1)
    expected_outcome: ReceiptOutcome
    required_citation_refs: tuple[str, ...] = Field(default_factory=tuple)


class ProductionSampleReviewerConfirmationRequest(BaseModel):
    """Reviewer confirmation supplied by an internal evaluation curator."""

    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=1)
    confirmed: bool
    notes: str | None = None


class ProductionSamplePromotionRequest(BaseModel):
    """Request body for reviewer-gated production sample promotion."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    sample_id: str = Field(min_length=1)
    suite_id: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    case: ProductionSamplePromotionCaseRequest
    domain_review: ProductionSampleReviewerConfirmationRequest
    harness_review: ProductionSampleReviewerConfirmationRequest


@router.post("/evaluation/production-samples/promotions")
def promote_evaluation_production_sample(
    request: ProductionSamplePromotionRequest,
    store: ProductionSampleCurationStore = Depends(get_production_sample_curation_store),
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Promote a reviewed curated production sample into formal evaluation artifacts."""

    require_operator_permission(identity, OperatorPermission.EVALUATION_CURATION_REVIEW)
    if not _SAFE_CURATED_SAMPLE_ID.match(request.batch_id):
        raise HTTPException(
            status_code=400,
            detail="batch_id may contain only letters, numbers, dots, underscores, and hyphens.",
        )
    if not _SAFE_CURATED_SAMPLE_ID.match(request.sample_id):
        raise HTTPException(
            status_code=400,
            detail="sample_id may contain only letters, numbers, dots, underscores, and hyphens.",
        )
    try:
        promotion = promote_curated_production_sample(
            batch_dir=store.root_dir / request.batch_id,
            sample_id=request.sample_id,
            output_dir=store.root_dir / "promoted",
            suite_id=request.suite_id,
            suite_version=request.suite_version,
            manifest_id=request.manifest_id,
            case=ProductionSamplePromotionCase(
                case_id=request.case.case_id,
                question=request.case.question,
                intent_type=request.case.intent_type,
                expected_resolution=request.case.expected_resolution,
                risk_class=request.case.risk_class,
                capability_path=request.case.capability_path,
                expected_outcome=request.case.expected_outcome,
                required_citation_refs=request.case.required_citation_refs,
            ),
            domain_review=ProductionSampleReviewerConfirmation(
                reviewer=request.domain_review.reviewer,
                confirmed=request.domain_review.confirmed,
                notes=request.domain_review.notes,
            ),
            harness_review=ProductionSampleReviewerConfirmation(
                reviewer=request.harness_review.reviewer,
                confirmed=request.harness_review.confirmed,
                notes=request.harness_review.notes,
            ),
        )
    except EvaluationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _write_production_sample_promotion_audit(
        promotion_dir=promotion.output_dir,
        actor=identity.operator_id,
        batch_id=request.batch_id,
        sample_id=request.sample_id,
    )
    return cast(
        dict[str, Any],
        _jsonable(
            {
                "sample_id": promotion.sample_id,
                "status": promotion.status,
                "promotion_dir": promotion.output_dir,
                "suite_path": promotion.suite_path,
                "subject_manifest_path": promotion.subject_manifest_path,
                "promotion_record_path": promotion.promotion_record_path,
            }
        ),
    )


def _write_production_sample_promotion_audit(
    *,
    promotion_dir: Path,
    actor: str,
    batch_id: str,
    sample_id: str,
) -> None:
    promotion_dir.joinpath("production_sample_promotion_audit.json").write_text(
        json.dumps(
            {
                "operation": "promoted",
                "actor": actor,
                "permission": OperatorPermission.EVALUATION_CURATION_REVIEW.value,
                "batch_id": batch_id,
                "sample_id": sample_id,
                "created_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


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
