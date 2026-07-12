from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from proof_agent.contracts import (
    ControlledReActRunStateSnapshot,
    ObservationTruthArtifact,
)
from proof_agent.errors import ProofAgentError


SNAPSHOT_BINDING_SCHEMA_VERSION = "proofagent.controlled-react.snapshot-binding.v1"
OBSERVATION_TRUTH_BINDING_SCHEMA_VERSION = (
    "proofagent.controlled-react.observation-truth-binding.v1"
)
CONTROLLED_REACT_SNAPSHOT_REF_PREFIX = "controlled-react://"
OBSERVATION_TRUTH_REF_PREFIX = "observation://"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class SnapshotArtifactBinding:
    reference: str
    digest: str
    run_id: str
    snapshot_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ObservationTruthArtifactBinding:
    base_reference: str
    reference: str
    digest: str
    run_id: str
    observation_id: str
    truth: ObservationTruthArtifact
    normalized_payload: dict[str, Any]


def bind_controlled_react_snapshot(
    snapshot: ControlledReActRunStateSnapshot,
) -> SnapshotArtifactBinding:
    """Bind the complete snapshot payload to one versioned content digest."""

    run_id = require_safe_identifier(snapshot.run_id, label="run id")
    snapshot_id = require_safe_identifier(snapshot.snapshot_id, label="snapshot id")
    if snapshot.state.run_id != run_id:
        raise _identity_error("controlled ReAct snapshot", snapshot.run_id)
    payload = model_payload(snapshot)
    digest = _binding_digest(
        {
            "schema_version": SNAPSHOT_BINDING_SCHEMA_VERSION,
            "payload": payload,
        }
    )
    reference = f"{CONTROLLED_REACT_SNAPSHOT_REF_PREFIX}{run_id}/{snapshot_id}/sha256/{digest}"
    return SnapshotArtifactBinding(
        reference=reference,
        digest=digest,
        run_id=run_id,
        snapshot_id=snapshot_id,
        payload=payload,
    )


def verify_controlled_react_snapshot_binding(
    snapshot: ControlledReActRunStateSnapshot,
    reference: str,
) -> SnapshotArtifactBinding:
    run_id, snapshot_id, digest = parse_snapshot_reference(reference)
    binding = bind_controlled_react_snapshot(snapshot)
    if (
        binding.run_id != run_id
        or binding.snapshot_id != snapshot_id
        or not hmac.compare_digest(binding.digest, digest)
        or binding.reference != reference
    ):
        raise _identity_error("controlled ReAct snapshot", reference)
    return binding


def bind_observation_truth(
    truth: ObservationTruthArtifact,
) -> ObservationTruthArtifactBinding:
    """Bind complete Observation Truth semantics while breaking the ref cycle."""

    run_id, observation_id, supplied_digest = _parse_observation_reference(
        truth.truth_ref,
        digest_required=False,
    )
    if truth.observation_id != observation_id:
        raise _identity_error("controlled ReAct observation truth", truth.truth_ref)
    base_reference = _observation_base_reference(run_id, observation_id)
    normalized_truth = truth.model_copy(update={"truth_ref": base_reference})
    normalized_payload = model_payload(normalized_truth)
    digest = _binding_digest(
        {
            "schema_version": OBSERVATION_TRUTH_BINDING_SCHEMA_VERSION,
            "run_id": run_id,
            "payload": normalized_payload,
        }
    )
    reference = f"{base_reference}/sha256/{digest}"
    if supplied_digest is not None and (
        not hmac.compare_digest(supplied_digest, digest) or truth.truth_ref != reference
    ):
        raise _identity_error("controlled ReAct observation truth", truth.truth_ref)
    bound_truth = normalized_truth.model_copy(update={"truth_ref": reference})
    return ObservationTruthArtifactBinding(
        base_reference=base_reference,
        reference=reference,
        digest=digest,
        run_id=run_id,
        observation_id=observation_id,
        truth=bound_truth,
        normalized_payload=normalized_payload,
    )


def require_bound_observation_truth(
    truth: ObservationTruthArtifact,
) -> ObservationTruthArtifactBinding:
    _, _, supplied_digest = _parse_observation_reference(
        truth.truth_ref,
        digest_required=True,
    )
    binding = bind_observation_truth(truth)
    if supplied_digest is None or not hmac.compare_digest(
        supplied_digest,
        binding.digest,
    ):
        raise _identity_error("controlled ReAct observation truth", truth.truth_ref)
    return binding


def parse_snapshot_reference(reference: str) -> tuple[str, str, str]:
    if not reference.startswith(CONTROLLED_REACT_SNAPSHOT_REF_PREFIX):
        raise _invalid_reference_error("controlled ReAct snapshot", reference)
    parts = reference.removeprefix(CONTROLLED_REACT_SNAPSHOT_REF_PREFIX).split("/")
    if len(parts) != 4 or parts[2] != "sha256":
        raise _invalid_reference_error("controlled ReAct snapshot", reference)
    run_id = require_safe_identifier(parts[0], label="run id")
    snapshot_id = require_safe_identifier(parts[1], label="snapshot id")
    digest = require_sha256_digest(parts[3])
    return run_id, snapshot_id, digest


def parse_bound_observation_reference(reference: str) -> tuple[str, str, str]:
    run_id, observation_id, digest = _parse_observation_reference(
        reference,
        digest_required=True,
    )
    if digest is None:
        raise _invalid_reference_error("observation truth", reference)
    return run_id, observation_id, digest


def observation_base_reference(reference: str) -> str:
    run_id, observation_id, _ = _parse_observation_reference(
        reference,
        digest_required=False,
    )
    return _observation_base_reference(run_id, observation_id)


def canonical_json_bytes(value: Any) -> bytes:
    """Encode canonical UTF-8 JSON and reject non-finite numeric values."""

    try:
        return json.dumps(
            jsonable(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "controlled ReAct artifact is not canonical JSON",
            "Use finite JSON-compatible values in controlled run artifacts.",
        ) from exc


def model_payload(value: Any) -> dict[str, Any]:
    model_dump = getattr(value, "model_dump", None)
    if not callable(model_dump):
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "controlled ReAct artifact payload is not a contract model",
            "Use a typed Controlled ReAct artifact.",
        )
    payload = jsonable(model_dump(warnings=False))
    if not isinstance(payload, dict):
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "controlled ReAct artifact payload must be a JSON object",
            "Use a typed Controlled ReAct artifact.",
        )
    return payload


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    value_attr = getattr(value, "value", None)
    if isinstance(value_attr, str):
        return value_attr
    return value


def require_safe_identifier(value: str, *, label: str) -> str:
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
            f"invalid controlled ReAct artifact {label}",
            "Use a non-empty single-segment identifier without path separators.",
        )
    return value


def require_sha256_digest(value: str) -> str:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise _invalid_reference_error("SHA-256 artifact", value)
    return value


def _binding_digest(envelope: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def _parse_observation_reference(
    reference: str,
    *,
    digest_required: bool,
) -> tuple[str, str, str | None]:
    if not reference.startswith(OBSERVATION_TRUTH_REF_PREFIX):
        raise _invalid_reference_error("observation truth", reference)
    parts = reference.removeprefix(OBSERVATION_TRUTH_REF_PREFIX).split("/")
    is_base = len(parts) == 3 and parts[2] == "truth"
    is_bound = len(parts) == 5 and parts[2] == "truth" and parts[3] == "sha256"
    if (digest_required and not is_bound) or (not is_base and not is_bound):
        raise _invalid_reference_error("observation truth", reference)
    run_id = require_safe_identifier(parts[0], label="run id")
    observation_id = require_safe_identifier(parts[1], label="observation id")
    digest = require_sha256_digest(parts[4]) if is_bound else None
    return run_id, observation_id, digest


def _observation_base_reference(run_id: str, observation_id: str) -> str:
    return f"{OBSERVATION_TRUTH_REF_PREFIX}{run_id}/{observation_id}/truth"


def _invalid_reference_error(artifact_name: str, reference: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        f"invalid {artifact_name} reference: {reference}",
        "Use the immutable digest-bearing reference emitted at commit time.",
    )


def _identity_error(artifact_name: str, reference: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        f"{artifact_name} identity or digest does not match: {reference}",
        "Discard the stale artifact and restart the run.",
    )
