"""Optional-dependency-safe Local Index revision-artifact compatibility checks."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, cast

from proof_agent.contracts import KnowledgeArtifactBuildSpec

ARTIFACT_SCHEMA_VERSION = "local_index.artifact.v1"
ARTIFACT_META_FILENAME = "artifact_meta.json"
REQUIRED_LLAMA_INDEX_FILES = (
    "docstore.json",
    "index_store.json",
    "graph_store.json",
    "default__vector_store.json",
    "image__vector_store.json",
)


def local_index_artifact_metadata(
    *,
    build_spec: KnowledgeArtifactBuildSpec,
    ingestion_config_fingerprint: str,
) -> dict[str, str]:
    """Return the persisted sidecar fields that define compatible artifact reuse."""

    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "provider": build_spec.provider,
        "engine_name": build_spec.engine_name,
        "engine_version": build_spec.engine_version,
        "parser_identity": build_spec.parser_fingerprint_identity,
        "content_hash": build_spec.content_hash,
        "ingestion_config_fingerprint": ingestion_config_fingerprint,
    }


def is_compatible_local_index_artifact(
    artifact_path: Path,
    *,
    build_spec: KnowledgeArtifactBuildSpec,
    ingestion_config_fingerprint: str,
) -> bool:
    """Return whether one published revision artifact is complete and compatible."""

    if not artifact_path.is_dir():
        return False
    if any(not (artifact_path / filename).is_file() for filename in REQUIRED_LLAMA_INDEX_FILES):
        return False
    metadata = _read_json_object(artifact_path / ARTIFACT_META_FILENAME)
    return metadata is not None and all(
        metadata.get(key) == value
        for key, value in local_index_artifact_metadata(
            build_spec=build_spec,
            ingestion_config_fingerprint=ingestion_config_fingerprint,
        ).items()
    )


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return cast(dict[str, Any], payload)
