from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any

from pydantic import ValidationError

from proof_agent.contracts import (
    ControlledReActRunStateSnapshot,
    ObservationTruthArtifact,
    ObservationTruthKind,
    RetrievalObservationTruth,
    ToolObservationTruth,
)
from proof_agent.errors import ProofAgentError


CONTROLLED_REACT_SNAPSHOT_REF_PREFIX = "controlled-react://"
_OBSERVATION_TRUTH_REF_PREFIX = "observation://"


class FileControlledReActSnapshotStore:
    """Immutable local snapshot store for Controlled ReAct approval resume."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir

    def save(self, snapshot: ControlledReActRunStateSnapshot) -> str:
        run_id = _safe_path_segment(snapshot.run_id, label="run id")
        snapshot_id = _safe_path_segment(snapshot.snapshot_id, label="snapshot id")
        snapshot_ref = f"{CONTROLLED_REACT_SNAPSHOT_REF_PREFIX}{run_id}/{snapshot_id}"
        if snapshot.state.run_id != run_id:
            raise _identity_error(
                artifact_name="controlled ReAct snapshot",
                reference=snapshot_ref,
            )
        _publish_immutable_json(
            self._snapshot_path(run_id, snapshot_id),
            _model_payload(snapshot),
            artifact_name="controlled ReAct snapshot",
            reference=snapshot_ref,
        )
        return snapshot_ref

    def load(self, snapshot_ref: str) -> ControlledReActRunStateSnapshot:
        run_id, snapshot_id = _parse_controlled_react_snapshot_ref(snapshot_ref)
        path = self._snapshot_path(run_id, snapshot_id)
        payload = _read_json_object(
            path,
            artifact_name="controlled ReAct snapshot",
            reference=snapshot_ref,
            missing_fix=(
                "Restart the run so approval resume can persist a fresh snapshot."
            ),
        )
        try:
            snapshot = ControlledReActRunStateSnapshot.model_validate(payload)
        except ValidationError as exc:
            raise _corrupt_artifact_error(
                artifact_name="controlled ReAct snapshot",
                reference=snapshot_ref,
                path=path,
            ) from exc
        if (
            snapshot.run_id != run_id
            or snapshot.snapshot_id != snapshot_id
            or snapshot.state.run_id != run_id
        ):
            raise _identity_error(
                artifact_name="controlled ReAct snapshot",
                reference=snapshot_ref,
                path=path,
            )
        return snapshot

    def _snapshot_path(self, run_id: str, snapshot_id: str) -> Path:
        return self._root_dir / run_id / "controlled_react" / f"{snapshot_id}.json"


class FileObservationTruthStore:
    """Immutable local Observation Truth Store for Controlled ReAct resume."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir

    def save(self, truth: ObservationTruthArtifact) -> str:
        run_id, observation_id = _parse_observation_truth_ref(truth.truth_ref)
        if truth.observation_id != observation_id:
            raise _identity_error(
                artifact_name="controlled ReAct observation truth",
                reference=truth.truth_ref,
            )
        _publish_immutable_json(
            self._truth_path(run_id, observation_id),
            _model_payload(truth),
            artifact_name="controlled ReAct observation truth",
            reference=truth.truth_ref,
        )
        return truth.truth_ref

    def load(self, truth_ref: str) -> ObservationTruthArtifact:
        run_id, observation_id = _parse_observation_truth_ref(truth_ref)
        path = self._truth_path(run_id, observation_id)
        payload = _read_json_object(
            path,
            artifact_name="controlled ReAct observation truth",
            reference=truth_ref,
            missing_fix=(
                "Restart the run so approval resume can persist observation truth."
            ),
        )
        try:
            truth = _observation_truth_from_payload(payload)
        except ValidationError as exc:
            raise _corrupt_artifact_error(
                artifact_name="controlled ReAct observation truth",
                reference=truth_ref,
                path=path,
            ) from exc
        if truth.truth_ref != truth_ref or truth.observation_id != observation_id:
            raise _identity_error(
                artifact_name="controlled ReAct observation truth",
                reference=truth_ref,
                path=path,
            )
        return truth

    def _truth_path(self, run_id: str, observation_id: str) -> Path:
        return (
            self._root_dir
            / run_id
            / "controlled_react"
            / "observation_truth"
            / f"{observation_id}.json"
        )


def _parse_controlled_react_snapshot_ref(snapshot_ref: str) -> tuple[str, str]:
    if not snapshot_ref.startswith(CONTROLLED_REACT_SNAPSHOT_REF_PREFIX):
        raise _invalid_reference_error(
            artifact_name="controlled ReAct snapshot",
            reference=snapshot_ref,
            fix="Use the checkpoint_ref emitted by the pending approval event.",
        )
    payload = snapshot_ref.removeprefix(CONTROLLED_REACT_SNAPSHOT_REF_PREFIX)
    parts = payload.split("/")
    if len(parts) != 2:
        raise _invalid_reference_error(
            artifact_name="controlled ReAct snapshot",
            reference=snapshot_ref,
            fix="Use the checkpoint_ref emitted by the pending approval event.",
        )
    return (
        _safe_path_segment(parts[0], label="run id"),
        _safe_path_segment(parts[1], label="snapshot id"),
    )


def _parse_observation_truth_ref(truth_ref: str) -> tuple[str, str]:
    if not truth_ref.startswith(_OBSERVATION_TRUTH_REF_PREFIX):
        raise _invalid_reference_error(
            artifact_name="observation truth",
            reference=truth_ref,
            fix="Use the truth_ref allocated by the Controlled ReAct Orchestrator.",
        )
    payload = truth_ref.removeprefix(_OBSERVATION_TRUTH_REF_PREFIX)
    parts = payload.split("/")
    if len(parts) != 3 or parts[2] != "truth":
        raise _invalid_reference_error(
            artifact_name="observation truth",
            reference=truth_ref,
            fix="Use the truth_ref allocated by the Controlled ReAct Orchestrator.",
        )
    return (
        _safe_path_segment(parts[0], label="run id"),
        _safe_path_segment(parts[1], label="observation id"),
    )


def _safe_path_segment(value: str, *, label: str) -> str:
    windows_path = PureWindowsPath(value)
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or Path(value).is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
    ):
        raise ProofAgentError(
            "PA_RUNTIME_001",
            f"invalid controlled ReAct local-store {label}",
            "Use a non-empty single-segment identifier without path separators.",
        )
    return value


def _observation_truth_from_payload(
    payload: dict[str, Any],
) -> ObservationTruthArtifact:
    kind = payload.get("kind")
    if kind == ObservationTruthKind.RETRIEVAL.value:
        return RetrievalObservationTruth.model_validate(payload)
    if kind == ObservationTruthKind.TOOL.value:
        return ToolObservationTruth.model_validate(payload)
    raise ProofAgentError(
        "PA_RUNTIME_001",
        f"unsupported controlled ReAct observation truth kind: {kind}",
        "Discard the stale approval checkpoint and restart the run.",
    )


def _model_payload(
    value: ControlledReActRunStateSnapshot | ObservationTruthArtifact,
) -> dict[str, Any]:
    payload = _jsonable(value.model_dump(warnings=False))
    if not isinstance(payload, dict):
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "controlled ReAct local-store payload must be a JSON object",
            "Restart the run with a valid Controlled ReAct artifact.",
        )
    return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    value_attr = getattr(value, "value", None)
    if isinstance(value_attr, str):
        return value_attr
    return value


def _publish_immutable_json(
    path: Path,
    payload: dict[str, Any],
    *,
    artifact_name: str,
    reference: str,
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _storage_write_error(
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        ) from exc

    existing_payload = _read_existing_json_object(
        path,
        artifact_name=artifact_name,
        reference=reference,
    )
    if existing_payload is not None:
        _require_identical_payload(
            existing_payload,
            payload,
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        )
        return

    content = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    temporary_path: Path | None = None
    file_descriptor: int | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            raced_payload = _read_existing_json_object(
                path,
                artifact_name=artifact_name,
                reference=reference,
            )
            if raced_payload is None:
                raise _storage_write_error(
                    artifact_name=artifact_name,
                    reference=reference,
                    path=path,
                )
            _require_identical_payload(
                raced_payload,
                payload,
                artifact_name=artifact_name,
                reference=reference,
                path=path,
            )
    except ProofAgentError:
        raise
    except OSError as exc:
        raise _storage_write_error(
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        ) from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _read_existing_json_object(
    path: Path,
    *,
    artifact_name: str,
    reference: str,
) -> dict[str, Any] | None:
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _corrupt_artifact_error(
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        ) from exc
    return _decode_json_object(
        content,
        artifact_name=artifact_name,
        reference=reference,
        path=path,
    )


def _read_json_object(
    path: Path,
    *,
    artifact_name: str,
    reference: str,
    missing_fix: str,
) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            f"{artifact_name} not found: {reference}",
            missing_fix,
            artifact_path=path,
        ) from exc
    except OSError as exc:
        raise _corrupt_artifact_error(
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        ) from exc
    return _decode_json_object(
        content,
        artifact_name=artifact_name,
        reference=reference,
        path=path,
    )


def _decode_json_object(
    content: bytes,
    *,
    artifact_name: str,
    reference: str,
    path: Path,
) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _corrupt_artifact_error(
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        ) from exc
    if not isinstance(payload, dict):
        raise _corrupt_artifact_error(
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        )
    return payload


def _require_identical_payload(
    existing: dict[str, Any],
    candidate: dict[str, Any],
    *,
    artifact_name: str,
    reference: str,
    path: Path,
) -> None:
    if existing == candidate:
        return
    raise ProofAgentError(
        "PA_RUNTIME_001",
        f"conflicting {artifact_name} already exists: {reference}",
        "Use a new immutable reference instead of replacing persisted run state.",
        artifact_path=path,
    )


def _invalid_reference_error(
    *,
    artifact_name: str,
    reference: str,
    fix: str,
) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        f"invalid {artifact_name} reference: {reference}",
        fix,
    )


def _identity_error(
    *,
    artifact_name: str,
    reference: str,
    path: Path | None = None,
) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        f"{artifact_name} identity does not match its reference: {reference}",
        "Discard the stale artifact and restart the run.",
        artifact_path=path,
    )


def _corrupt_artifact_error(
    *,
    artifact_name: str,
    reference: str,
    path: Path,
) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        f"invalid or corrupt {artifact_name}: {reference}",
        "Discard the stale artifact and restart the run.",
        artifact_path=path,
    )


def _storage_write_error(
    *,
    artifact_name: str,
    reference: str,
    path: Path,
) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        f"failed to persist {artifact_name}: {reference}",
        "Check local storage permissions and retry the run.",
        artifact_path=path,
    )
