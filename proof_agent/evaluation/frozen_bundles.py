from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import (
    EvaluationArtifactRef,
    EvaluationFrozenBundleVerification,
    EvaluationFrozenSubjectBundle,
    EvaluationSubject,
)
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.subjects import load_evaluation_subject_manifest
from proof_agent.evaluation.suites import load_evaluation_suite


def freeze_evaluation_subject_bundle(
    *,
    suite_path: Path | str,
    subjects_path: Path | str,
    output_dir: Path | str,
    bundle_id: str,
    version: str,
) -> EvaluationFrozenSubjectBundle:
    """Copy a suite, subject manifest, and linked artifacts into a portable bundle."""

    suite = load_evaluation_suite(suite_path)
    manifest = load_evaluation_subject_manifest(subjects_path)
    if suite.suite_id != manifest.suite_id:
        raise EvaluationInputError(
            f"subject manifest suite_id {manifest.suite_id} does not match suite {suite.suite_id}"
        )

    bundle_dir = Path(output_dir) / bundle_id
    if bundle_dir.exists() and any(bundle_dir.iterdir()):
        raise EvaluationInputError(f"frozen subject bundle already exists: {bundle_dir}")
    bundle_dir.mkdir(parents=True, exist_ok=True)

    bundled_suite_path = bundle_dir / "evaluation_suite.yaml"
    bundled_subjects_path = bundle_dir / "evaluation_subjects.yaml"
    bundle_manifest_path = bundle_dir / "bundle_manifest.yaml"
    _write_bundled_suite(suite_path, bundled_suite_path, suite.model_dump(mode="python"))

    artifact_count = 0
    bundled_subjects: list[dict[str, Any]] = []
    for subject in manifest.subjects:
        subject_dir = bundle_dir / "artifacts" / _subject_label(subject)
        subject_dir.mkdir(parents=True, exist_ok=True)
        bundled_subject, copied_count = _freeze_subject(subject, subject_dir, bundled_subjects_path)
        artifact_count += copied_count
        bundled_subjects.append(bundled_subject)

    subjects_payload = {
        "manifest_id": manifest.manifest_id,
        "version": manifest.version,
        "suite_id": manifest.suite_id,
        "agent": dict(manifest.agent),
        "subjects": bundled_subjects,
    }
    bundled_subjects_path.write_text(
        yaml.safe_dump(subjects_payload, sort_keys=False),
        encoding="utf-8",
    )
    bundle_manifest_path.write_text(
        yaml.safe_dump(
            {
                "bundle_id": bundle_id,
                "version": version,
                "suite_id": suite.suite_id,
                "suite_version": suite.version,
                "subject_manifest_id": manifest.manifest_id,
                "subject_manifest_version": manifest.version,
                "artifact_count": artifact_count,
                "agent": dict(manifest.agent),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    return EvaluationFrozenSubjectBundle(
        bundle_id=bundle_id,
        version=version,
        suite_id=suite.suite_id,
        suite_version=suite.version,
        subject_manifest_id=manifest.manifest_id,
        subject_manifest_version=manifest.version,
        bundle_dir=bundle_dir,
        suite_path=bundled_suite_path,
        subject_manifest_path=bundled_subjects_path,
        bundle_manifest_path=bundle_manifest_path,
        artifact_count=artifact_count,
    )


def verify_evaluation_subject_bundle(bundle_dir: Path | str) -> EvaluationFrozenBundleVerification:
    """Verify that a frozen bundle's declared artifact hashes still match."""

    root = Path(bundle_dir)
    bundle_manifest = _read_yaml(root / "bundle_manifest.yaml")
    subjects_path = root / "evaluation_subjects.yaml"
    manifest = load_evaluation_subject_manifest(subjects_path)

    missing: list[str] = []
    mismatched: list[str] = []
    checked = 0
    for subject in manifest.subjects:
        refs = [
            subject.trace,
            subject.receipt,
            *( [subject.run_meta] if subject.run_meta is not None else [] ),
        ]
        if subject.response_projection.ref is not None:
            refs.append(
                EvaluationArtifactRef(
                    ref=subject.response_projection.ref,
                    sha256=subject.response_projection.sha256,
                )
            )
        for ref in refs:
            if ref is None:
                continue
            checked += 1
            relative = _relative_ref(ref.ref, root / "bundle_manifest.yaml")
            if not ref.ref.is_file():
                missing.append(relative)
                continue
            if ref.sha256 is not None and _sha256(ref.ref) != ref.sha256:
                mismatched.append(relative)

    status: Literal["passed", "failed"] = "failed" if missing or mismatched else "passed"
    return EvaluationFrozenBundleVerification(
        bundle_id=str(bundle_manifest.get("bundle_id") or root.name),
        status=status,
        checked_artifact_count=checked,
        missing_artifacts=tuple(missing),
        mismatched_artifacts=tuple(mismatched),
        suite_id=str(bundle_manifest.get("suite_id")) if bundle_manifest.get("suite_id") else None,
        subject_manifest_id=(
            str(bundle_manifest.get("subject_manifest_id"))
            if bundle_manifest.get("subject_manifest_id")
            else None
        ),
    )


def _freeze_subject(
    subject: EvaluationSubject,
    subject_dir: Path,
    bundled_subjects_path: Path,
) -> tuple[dict[str, Any], int]:
    if subject.response_projection.ref is None:
        raise EvaluationInputError(
            "frozen release bundles require file-backed response projections."
        )

    trace = _copy_artifact(subject.trace, subject_dir / "trace.jsonl")
    receipt = _copy_artifact(subject.receipt, subject_dir / "governance_receipt.md")
    artifacts: dict[str, str] = {
        "trace_ref": _relative_ref(trace, bundled_subjects_path),
        "trace_sha256": _sha256(trace),
        "receipt_ref": _relative_ref(receipt, bundled_subjects_path),
        "receipt_sha256": _sha256(receipt),
    }
    count = 2
    if subject.run_meta is not None:
        run_meta = _copy_artifact(subject.run_meta, subject_dir / "run_meta.json")
        artifacts["run_meta_ref"] = _relative_ref(run_meta, bundled_subjects_path)
        artifacts["run_meta_sha256"] = _sha256(run_meta)
        count += 1

    response_dest = subject_dir / _response_projection_filename(subject.response_projection.ref)
    response_ref = _copy_path(subject.response_projection.ref, response_dest)
    evaluated_response = {
        "audience": subject.response_projection.audience.value,
        "ref": _relative_ref(response_ref, bundled_subjects_path),
        "sha256": _sha256(response_ref),
        "sensitivity": subject.response_projection.sensitivity or "release_safe",
    }
    count += 1

    payload: dict[str, Any] = {
        "case_ref": subject.case_ref.model_dump(exclude_none=True),
        "artifacts": artifacts,
        "projections": {"evaluated_response": evaluated_response},
        "execution_surface": subject.execution_surface.value,
    }
    if subject.run_ref is not None:
        payload["run_ref"] = subject.run_ref.model_dump(exclude_none=True)
    if subject.metadata:
        payload["metadata"] = dict(subject.metadata)
    return payload, count


def _copy_artifact(ref: EvaluationArtifactRef, destination: Path) -> Path:
    return _copy_path(ref.ref, destination)


def _write_bundled_suite(
    source_suite_path: Path | str,
    bundled_suite_path: Path,
    suite_payload: dict[str, Any],
) -> None:
    source_path = Path(source_suite_path)
    if source_path.is_file():
        shutil.copy2(source_path, bundled_suite_path)
        return
    bundled_suite_path.write_text(
        yaml.safe_dump(_jsonable(suite_payload), sort_keys=False),
        encoding="utf-8",
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EvaluationInputError(f"frozen bundle manifest not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise EvaluationInputError(f"frozen bundle manifest must be a mapping: {path}")
    return {str(key): value for key, value in raw.items()}


def _copy_path(source: Path, destination: Path) -> Path:
    if not source.is_file():
        raise EvaluationInputError(f"cannot freeze missing artifact ref: {source}")
    shutil.copy2(source, destination)
    return destination


def _relative_ref(path: Path, manifest_path: Path) -> str:
    return os.path.relpath(path, start=manifest_path.parent)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subject_label(subject: EvaluationSubject) -> str:
    parts = [subject.case_ref.case_id]
    if subject.case_ref.scenario_id is not None:
        parts.insert(0, subject.case_ref.scenario_id)
    if subject.case_ref.scenario_step_id is not None:
        parts.append(subject.case_ref.scenario_step_id)
    return "_".join(_safe_path_part(part) for part in parts)


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _response_projection_filename(path: Path) -> str:
    suffix = path.suffix or ".txt"
    return f"evaluated_response{suffix}"


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
