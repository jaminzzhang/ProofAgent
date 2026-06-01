"""READY snapshot metadata contract for Local Index runtime loading."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proof_agent.errors import ProofAgentError

SNAPSHOT_SCHEMA_VERSION = "local_index.snapshot.v1"
SNAPSHOT_PROVIDER = "local_index"
SNAPSHOT_ENGINE_NAME = "llama-index-tree"


@dataclass(frozen=True)
class LocalIndexSnapshotMetadata:
    """Trace-safe identity for one immutable published Local Index snapshot."""

    snapshot_id: str
    state: str
    provider: str
    engine_name: str
    engine_version: str


def load_ready_snapshot_metadata(index_path: Path) -> LocalIndexSnapshotMetadata:
    """Load and validate the publication sidecar for a READY Local Index snapshot."""
    sidecar_path = index_path / "artifact_meta.json"
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise _invalid_snapshot(
            f"Local Index snapshot is missing {sidecar_path.name}.",
            "Publish a READY local_index snapshot with an artifact_meta.json sidecar.",
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise _invalid_snapshot(
            f"Local Index snapshot has an unreadable or malformed {sidecar_path.name}.",
            "Publish the snapshot again with a valid artifact_meta.json sidecar.",
        ) from exc

    if not isinstance(payload, dict):
        raise _invalid_snapshot(
            "Local Index artifact_meta.json must contain a JSON object.",
            "Publish the snapshot again with a valid artifact_meta.json object.",
        )

    schema_version = _required_string(payload, "schema_version")
    snapshot_id = _required_string(payload, "snapshot_id")
    state = _required_string(payload, "state")
    provider = _required_string(payload, "provider")
    engine_name = _required_string(payload, "engine_name")
    engine_version = _required_string(payload, "engine_version")

    if schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise _invalid_snapshot(
            f"Local Index snapshot schema_version must be {SNAPSHOT_SCHEMA_VERSION}.",
            "Publish the snapshot again using the supported local_index snapshot schema.",
        )
    if state != "READY":
        raise _invalid_snapshot(
            "Local Index runtime load requires a READY snapshot.",
            "Wait for snapshot publication to reach READY before activating this source.",
        )
    if provider != SNAPSHOT_PROVIDER:
        raise _invalid_snapshot(
            f"Local Index snapshot provider must be {SNAPSHOT_PROVIDER}.",
            "Use a snapshot published by the local_index provider.",
        )
    if engine_name != SNAPSHOT_ENGINE_NAME:
        raise _invalid_snapshot(
            f"Local Index snapshot engine_name must be {SNAPSHOT_ENGINE_NAME}.",
            "Publish the snapshot again using the supported Local Index engine.",
        )

    return LocalIndexSnapshotMetadata(
        snapshot_id=snapshot_id,
        state=state,
        provider=provider,
        engine_name=engine_name,
        engine_version=engine_version,
    )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid_snapshot(
            f"Local Index artifact_meta.json requires a non-empty {key}.",
            f"Publish the snapshot again with a non-empty {key}.",
        )
    return value


def _invalid_snapshot(message: str, fix: str) -> ProofAgentError:
    return ProofAgentError("PA_KNOWLEDGE_001", message, fix)
