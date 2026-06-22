from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import (
    EvaluationExecutionSurface,
    EvaluationResponseProjectionAudience,
    ReceiptOutcome,
    RunPurpose,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.observability.storage.run_store import RunStore


class ProductionSampleImportSelection(FrozenModel):
    sample_id: str
    run_id: str
    response_projection_ref: Path
    response_projection_audience: EvaluationResponseProjectionAudience
    redaction_reviewer: str = Field(min_length=1)
    redaction_confirmed: bool
    execution_surface: EvaluationExecutionSurface = EvaluationExecutionSurface.RUN_EXECUTION_API


class ProductionSampleImportBatch(FrozenModel):
    batch_id: str
    version: str
    batch_dir: Path
    candidates_path: Path
    candidate_count: int


class ProductionSamplePromotionCase(FrozenModel):
    case_id: str
    question: str
    intent_type: str
    expected_resolution: str
    risk_class: str
    capability_path: str
    expected_outcome: ReceiptOutcome
    required_citation_refs: tuple[str, ...] = Field(default_factory=tuple)


class ProductionSampleReviewerConfirmation(FrozenModel):
    reviewer: str = Field(min_length=1)
    confirmed: bool
    notes: str | None = None


class ProductionSamplePromotion(FrozenModel):
    sample_id: str
    status: Literal["promoted"]
    output_dir: Path
    suite_path: Path
    subject_manifest_path: Path
    promotion_record_path: Path


def import_curated_production_samples(
    *,
    store: RunStore,
    output_dir: Path | str,
    batch_id: str,
    version: str,
    selections: Iterable[ProductionSampleImportSelection],
) -> ProductionSampleImportBatch:
    """Import reviewed production runs as diagnostic-only curation candidates."""

    selected = tuple(selections)
    if not selected:
        raise EvaluationInputError("Production sample import requires at least one selection.")

    batch_dir = Path(output_dir) / batch_id
    candidates_path = batch_dir / "production_sample_candidates.jsonl"

    rows = [
        _candidate_row(
            store=store,
            selection=selection,
            batch_dir=batch_dir,
        )
        for selection in selected
    ]
    batch_dir.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    (batch_dir / "production_sample_import.json").write_text(
        json.dumps(
            {
                "batch_id": batch_id,
                "version": version,
                "candidate_count": len(rows),
                "candidates_path": "production_sample_candidates.jsonl",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return ProductionSampleImportBatch(
        batch_id=batch_id,
        version=version,
        batch_dir=batch_dir,
        candidates_path=candidates_path,
        candidate_count=len(rows),
    )


def _candidate_row(
    *,
    store: RunStore,
    selection: ProductionSampleImportSelection,
    batch_dir: Path,
) -> dict[str, object]:
    if not selection.redaction_confirmed:
        raise EvaluationInputError(
            "Redaction reviewer confirmation is required for production sample import."
        )

    detail = store.get_run_detail(selection.run_id)
    if detail is None:
        raise EvaluationInputError(f"Production sample run not found: {selection.run_id}")
    if detail.run_purpose != RunPurpose.PRODUCTION:
        raise EvaluationInputError(
            f"Production sample import requires run_purpose production: {selection.run_id}"
        )

    run_dir = store.history_dir / selection.run_id
    trace_path = run_dir / "trace.jsonl"
    receipt_path = run_dir / "governance_receipt.md"
    run_meta_path = run_dir / "run_meta.json"
    response_path = _resolve_response_projection_ref(
        selection.response_projection_ref,
        run_dir=run_dir,
    )
    _require_files(trace_path, receipt_path, run_meta_path, response_path)
    response_text = response_path.read_text(encoding="utf-8")
    return {
        "sample_id": selection.sample_id,
        "source_run_id": selection.run_id,
        "curation_status": "diagnostic_only",
        "formal_scoring_allowed": False,
        "run_purpose": detail.run_purpose.value,
        "redaction_review": {
            "reviewer": selection.redaction_reviewer,
            "confirmed": selection.redaction_confirmed,
        },
        "artifacts": {
            "trace_ref": _relative_ref(trace_path, batch_dir),
            "trace_sha256": _sha256(trace_path),
            "receipt_ref": _relative_ref(receipt_path, batch_dir),
            "receipt_sha256": _sha256(receipt_path),
            "run_meta_ref": _relative_ref(run_meta_path, batch_dir),
            "run_meta_sha256": _sha256(run_meta_path),
            "response_projection_ref": _relative_ref(response_path, batch_dir),
            "response_projection_audience": selection.response_projection_audience.value,
            "response_projection_sha256": _sha256(response_path),
        },
        "execution_surface": selection.execution_surface.value,
        "safe_summary": {
            "question_sha256": _text_sha256(detail.question),
            "question_text_length": len(detail.question),
            "response_text_sha256": _text_sha256(response_text),
            "response_text_length": len(response_text),
        },
    }


def promote_curated_production_sample(
    *,
    batch_dir: Path | str,
    sample_id: str,
    output_dir: Path | str,
    suite_id: str,
    suite_version: str,
    manifest_id: str,
    case: ProductionSamplePromotionCase,
    domain_review: ProductionSampleReviewerConfirmation,
    harness_review: ProductionSampleReviewerConfirmation,
) -> ProductionSamplePromotion:
    """Promote one diagnostic production candidate into formal evaluation artifacts."""

    _require_confirmation("Domain Evaluation Reviewer", domain_review)
    _require_confirmation("Harness Evaluation Reviewer", harness_review)
    source_batch_dir = Path(batch_dir)
    candidate = _load_candidate(source_batch_dir, sample_id)
    destination = Path(output_dir) / sample_id
    destination.mkdir(parents=True, exist_ok=True)
    suite_path = destination / "evaluation_suite.yaml"
    subject_manifest_path = destination / "evaluation_subjects.yaml"
    promotion_record_path = destination / "production_sample_promotion.json"

    suite_payload = _suite_payload(
        suite_id=suite_id,
        suite_version=suite_version,
        case=case,
        source_sample_id=sample_id,
    )
    subject_payload = _subject_manifest_payload(
        manifest_id=manifest_id,
        version=suite_version,
        suite_id=suite_id,
        case_id=case.case_id,
        candidate=candidate,
        source_batch_dir=source_batch_dir,
        subject_manifest_path=subject_manifest_path,
    )
    promotion_record = {
        "sample_id": sample_id,
        "status": "promoted",
        "source_run_id": candidate["source_run_id"],
        "suite_path": "evaluation_suite.yaml",
        "subject_manifest_path": "evaluation_subjects.yaml",
        "domain_review": _review_json(domain_review),
        "harness_review": _review_json(harness_review),
    }

    suite_path.write_text(yaml.safe_dump(suite_payload, sort_keys=False), encoding="utf-8")
    subject_manifest_path.write_text(
        yaml.safe_dump(subject_payload, sort_keys=False),
        encoding="utf-8",
    )
    promotion_record_path.write_text(
        json.dumps(promotion_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ProductionSamplePromotion(
        sample_id=sample_id,
        status="promoted",
        output_dir=destination,
        suite_path=suite_path,
        subject_manifest_path=subject_manifest_path,
        promotion_record_path=promotion_record_path,
    )


def _require_confirmation(
    role: str,
    review: ProductionSampleReviewerConfirmation,
) -> None:
    if not review.confirmed:
        raise EvaluationInputError(f"{role} confirmation is required for promotion.")


def _load_candidate(batch_dir: Path, sample_id: str) -> dict[str, Any]:
    candidates_path = batch_dir / "production_sample_candidates.jsonl"
    if not candidates_path.is_file():
        raise EvaluationInputError(f"Production sample candidates not found: {batch_dir}")
    for line in candidates_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if isinstance(raw, dict) and raw.get("sample_id") == sample_id:
            return raw
    raise EvaluationInputError(f"Production sample candidate not found: {sample_id}")


def _suite_payload(
    *,
    suite_id: str,
    suite_version: str,
    case: ProductionSamplePromotionCase,
    source_sample_id: str,
) -> dict[str, Any]:
    return {
        "suite_id": suite_id,
        "version": suite_version,
        "name": "Curated Production Evaluation Samples",
        "purpose": "production_curation",
        "cases": [
            {
                "case_id": case.case_id,
                "question": case.question,
                "intent_type": case.intent_type,
                "expected_resolution": case.expected_resolution,
                "risk_class": case.risk_class,
                "capability_path": case.capability_path,
                "expected": {
                    "outcome": case.expected_outcome.value,
                    "required_citation_refs": list(case.required_citation_refs),
                },
                "metadata": {
                    "curation_status": "promoted",
                    "source_sample_id": source_sample_id,
                    "source": "curated_production_sample",
                },
            }
        ],
    }


def _subject_manifest_payload(
    *,
    manifest_id: str,
    version: str,
    suite_id: str,
    case_id: str,
    candidate: dict[str, Any],
    source_batch_dir: Path,
    subject_manifest_path: Path,
) -> dict[str, Any]:
    artifacts = _mapping(candidate.get("artifacts"))
    return {
        "manifest_id": manifest_id,
        "version": version,
        "suite_id": suite_id,
        "subjects": [
            {
                "case_ref": {"case_id": case_id},
                "artifacts": {
                    "trace_ref": _promotion_ref(
                        artifacts["trace_ref"],
                        source_batch_dir=source_batch_dir,
                        destination=subject_manifest_path,
                    ),
                    "trace_sha256": artifacts["trace_sha256"],
                    "receipt_ref": _promotion_ref(
                        artifacts["receipt_ref"],
                        source_batch_dir=source_batch_dir,
                        destination=subject_manifest_path,
                    ),
                    "receipt_sha256": artifacts["receipt_sha256"],
                    "run_meta_ref": _promotion_ref(
                        artifacts["run_meta_ref"],
                        source_batch_dir=source_batch_dir,
                        destination=subject_manifest_path,
                    ),
                    "run_meta_sha256": artifacts["run_meta_sha256"],
                },
                "projections": {
                    "evaluated_response": {
                        "audience": artifacts["response_projection_audience"],
                        "ref": _promotion_ref(
                            artifacts["response_projection_ref"],
                            source_batch_dir=source_batch_dir,
                            destination=subject_manifest_path,
                        ),
                        "sha256": artifacts["response_projection_sha256"],
                        "sensitivity": "release_safe",
                    }
                },
                "execution_surface": str(candidate.get("execution_surface") or "run_execution_api"),
                "run_ref": {
                    "run_id": candidate["source_run_id"],
                    "source": "run_store",
                },
                "metadata": {
                    "curation_status": "promoted",
                    "source_sample_id": candidate["sample_id"],
                    "source": "curated_production_sample",
                },
            }
        ],
    }


def _promotion_ref(value: Any, *, source_batch_dir: Path, destination: Path) -> str:
    source_path = source_batch_dir / str(value)
    return os.path.relpath(source_path.resolve(strict=False), start=destination.parent)


def _review_json(review: ProductionSampleReviewerConfirmation) -> dict[str, object]:
    payload: dict[str, object] = {
        "reviewer": review.reviewer,
        "confirmed": review.confirmed,
    }
    if review.notes is not None:
        payload["notes"] = review.notes
    return payload


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise EvaluationInputError("Production sample candidate artifacts must be a mapping.")


def _resolve_response_projection_ref(path: Path, *, run_dir: Path) -> Path:
    if path.is_absolute():
        return path
    return run_dir / path


def _require_files(*paths: Path) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise EvaluationInputError(
            "cannot import missing production sample artifact refs: " + ", ".join(missing)
        )


def _relative_ref(path: Path, base_dir: Path) -> str:
    return os.path.relpath(path, start=base_dir)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
