from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import EvaluationSubjectManifest
from proof_agent.evaluation.errors import EvaluationInputError


def load_evaluation_subject_manifest(path: Path | str) -> EvaluationSubjectManifest:
    """Load an Evaluation Subject Manifest from YAML."""

    manifest_path = Path(path)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise EvaluationInputError("Evaluation subject manifest YAML must be a mapping.")
    normalized = _normalize_manifest(raw, base_dir=manifest_path.parent)
    manifest = EvaluationSubjectManifest.model_validate(normalized)
    _validate_local_artifact_refs_exist(manifest)
    return manifest


def _normalize_manifest(raw: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    normalized = {str(key): value for key, value in raw.items()}
    subjects = normalized.get("subjects", ())
    if not isinstance(subjects, list | tuple):
        raise EvaluationInputError("Evaluation subject manifest subjects must be a list.")
    normalized["subjects"] = [
        _normalize_subject(subject, base_dir=base_dir) for subject in subjects
    ]
    return normalized


def _normalize_subject(raw: Any, *, base_dir: Path) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise EvaluationInputError("Evaluation subject entries must be mappings.")
    subject = {str(key): value for key, value in raw.items()}

    artifacts = subject.pop("artifacts", None)
    if artifacts is not None:
        if not isinstance(artifacts, Mapping):
            raise EvaluationInputError("Evaluation subject artifacts must be a mapping.")
        subject["trace"] = _artifact_ref(
            artifacts,
            ref_key="trace_ref",
            hash_key="trace_sha256",
            base_dir=base_dir,
        )
        subject["receipt"] = _artifact_ref(
            artifacts,
            ref_key="receipt_ref",
            hash_key="receipt_sha256",
            base_dir=base_dir,
        )
        run_meta_ref = artifacts.get("run_meta_ref")
        if run_meta_ref is not None:
            subject["run_meta"] = {
                "ref": _resolve_local_path(run_meta_ref, base_dir=base_dir),
                "sha256": artifacts.get("run_meta_sha256"),
            }

    projections = subject.pop("projections", None)
    if projections is not None:
        if not isinstance(projections, Mapping):
            raise EvaluationInputError("Evaluation subject projections must be a mapping.")
        evaluated_response = projections.get("evaluated_response")
        if not isinstance(evaluated_response, Mapping):
            raise EvaluationInputError(
                "Evaluation subject projections.evaluated_response must be a mapping."
            )
        subject["response_projection"] = _normalize_projection(
            evaluated_response,
            base_dir=base_dir,
        )

    if isinstance(subject.get("trace"), Mapping):
        subject["trace"] = _normalize_direct_artifact_ref(subject["trace"], base_dir=base_dir)
    if isinstance(subject.get("receipt"), Mapping):
        subject["receipt"] = _normalize_direct_artifact_ref(subject["receipt"], base_dir=base_dir)
    if isinstance(subject.get("run_meta"), Mapping):
        subject["run_meta"] = _normalize_direct_artifact_ref(subject["run_meta"], base_dir=base_dir)
    if isinstance(subject.get("response_projection"), Mapping):
        subject["response_projection"] = _normalize_projection(
            subject["response_projection"],
            base_dir=base_dir,
        )
    return subject


def _artifact_ref(
    artifacts: Mapping[str, Any],
    *,
    ref_key: str,
    hash_key: str,
    base_dir: Path,
) -> dict[str, Any]:
    ref = artifacts.get(ref_key)
    if ref is None:
        raise EvaluationInputError(f"Evaluation subject missing artifact ref: {ref_key}")
    return {
        "ref": _resolve_local_path(ref, base_dir=base_dir),
        "sha256": artifacts.get(hash_key),
    }


def _normalize_direct_artifact_ref(value: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    normalized = {str(key): item for key, item in value.items()}
    ref = normalized.get("ref")
    if ref is not None:
        normalized["ref"] = _resolve_local_path(ref, base_dir=base_dir)
    return normalized


def _normalize_projection(value: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    normalized = {str(key): item for key, item in value.items()}
    if normalized.get("text") is not None and normalized.get("sensitivity") != "local_only":
        raise EvaluationInputError("inline response text is allowed only with sensitivity: local_only")
    ref = normalized.get("ref")
    if ref is not None:
        normalized["ref"] = _resolve_local_path(ref, base_dir=base_dir)
    return normalized


def _resolve_local_path(value: Any, *, base_dir: Path) -> Path:
    raw_value = str(value)
    if raw_value.startswith(("http://", "https://")):
        raise EvaluationInputError("Evaluation subject refs must not use mutable endpoint URLs.")
    path = Path(raw_value)
    _reject_mutable_ref(path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve(strict=False)


def _reject_mutable_ref(path: Path) -> None:
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part == "runs" and parts[index + 1] == "latest":
            raise EvaluationInputError("Evaluation subject refs must not point at runs/latest.")


def _validate_local_artifact_refs_exist(manifest: EvaluationSubjectManifest) -> None:
    for subject in manifest.subjects:
        refs = [subject.trace.ref, subject.receipt.ref]
        if subject.run_meta is not None:
            refs.append(subject.run_meta.ref)
        if subject.response_projection.ref is not None:
            refs.append(subject.response_projection.ref)
        missing = [str(ref) for ref in refs if not ref.exists()]
        if missing:
            raise EvaluationInputError("missing local artifact ref: " + ", ".join(missing))
