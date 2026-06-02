"""Tests for optional-dependency-safe Local Index artifact compatibility checks."""

from __future__ import annotations

import json
from pathlib import Path

from proof_agent.capabilities.knowledge.ingestion.artifacts import (
    ARTIFACT_META_FILENAME,
    REQUIRED_LLAMA_INDEX_FILES,
    is_compatible_local_index_artifact,
    is_runtime_compatible_local_index_artifact,
    local_index_artifact_metadata,
)
from proof_agent.contracts import KnowledgeArtifactBuildSpec


def _build_spec() -> KnowledgeArtifactBuildSpec:
    return KnowledgeArtifactBuildSpec(
        provider="local_index",
        engine_name="llama-index-tree",
        engine_version="llama-index-tree@0.14.22",
        parser_fingerprint_identity="markdown:utf-8:v1",
        content_hash="a" * 64,
        parsed_text_sha256="b" * 64,
    )


def _write_artifact(
    path: Path,
    *,
    build_spec: KnowledgeArtifactBuildSpec,
    fingerprint: str,
) -> None:
    path.mkdir(parents=True)
    for filename in REQUIRED_LLAMA_INDEX_FILES:
        (path / filename).write_text("{}", encoding="utf-8")
    (path / ARTIFACT_META_FILENAME).write_text(
        json.dumps(
            local_index_artifact_metadata(
                build_spec=build_spec,
                ingestion_config_fingerprint=fingerprint,
            )
        ),
        encoding="utf-8",
    )


def test_compatible_local_index_artifact_requires_matching_files_and_sidecar(
    tmp_path: Path,
) -> None:
    spec = _build_spec()
    fingerprint = "fingerprint"
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint=fingerprint)

    assert is_compatible_local_index_artifact(
        artifact_path,
        build_spec=spec,
        ingestion_config_fingerprint=fingerprint,
    )


def test_local_index_artifact_compatibility_rejects_missing_directory(tmp_path: Path) -> None:
    assert not is_compatible_local_index_artifact(
        tmp_path / "missing",
        build_spec=_build_spec(),
        ingestion_config_fingerprint="fingerprint",
    )


def test_local_index_artifact_compatibility_rejects_missing_required_file(tmp_path: Path) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")
    (artifact_path / REQUIRED_LLAMA_INDEX_FILES[0]).unlink()

    assert not is_compatible_local_index_artifact(
        artifact_path,
        build_spec=spec,
        ingestion_config_fingerprint="fingerprint",
    )


def test_local_index_artifact_compatibility_rejects_malformed_sidecar(tmp_path: Path) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")
    (artifact_path / ARTIFACT_META_FILENAME).write_text("{", encoding="utf-8")

    assert not is_compatible_local_index_artifact(
        artifact_path,
        build_spec=spec,
        ingestion_config_fingerprint="fingerprint",
    )


def test_local_index_artifact_compatibility_rejects_changed_metadata(tmp_path: Path) -> None:
    spec = _build_spec()
    fingerprint = "fingerprint"
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint=fingerprint)

    assert not is_compatible_local_index_artifact(
        artifact_path,
        build_spec=spec.model_copy(update={"content_hash": "c" * 64}),
        ingestion_config_fingerprint=fingerprint,
    )
    assert not is_compatible_local_index_artifact(
        artifact_path,
        build_spec=spec,
        ingestion_config_fingerprint="changed-fingerprint",
    )

    metadata_path = artifact_path / ARTIFACT_META_FILENAME
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema_version"] = "local_index.artifact.changed"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert not is_compatible_local_index_artifact(
        artifact_path,
        build_spec=spec,
        ingestion_config_fingerprint=fingerprint,
    )


def test_runtime_compatible_local_index_artifact_accepts_self_described_revision(
    tmp_path: Path,
) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")

    assert is_runtime_compatible_local_index_artifact(
        artifact_path,
        content_hash=spec.content_hash,
    )


def test_runtime_local_index_artifact_rejects_missing_directory(tmp_path: Path) -> None:
    assert not is_runtime_compatible_local_index_artifact(
        tmp_path / "missing",
        content_hash=_build_spec().content_hash,
    )


def test_runtime_local_index_artifact_rejects_missing_sidecar(tmp_path: Path) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")
    (artifact_path / ARTIFACT_META_FILENAME).unlink()

    assert not is_runtime_compatible_local_index_artifact(
        artifact_path,
        content_hash=spec.content_hash,
    )


def test_runtime_local_index_artifact_rejects_non_object_sidecar(tmp_path: Path) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")
    (artifact_path / ARTIFACT_META_FILENAME).write_text("[]", encoding="utf-8")

    assert not is_runtime_compatible_local_index_artifact(
        artifact_path,
        content_hash=spec.content_hash,
    )


def test_runtime_local_index_artifact_rejects_manifest_content_hash_mismatch(
    tmp_path: Path,
) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")

    assert not is_runtime_compatible_local_index_artifact(
        artifact_path,
        content_hash="c" * 64,
    )


def test_runtime_local_index_artifact_rejects_missing_required_file(tmp_path: Path) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")
    (artifact_path / REQUIRED_LLAMA_INDEX_FILES[0]).unlink()

    assert not is_runtime_compatible_local_index_artifact(
        artifact_path,
        content_hash=spec.content_hash,
    )


def test_runtime_local_index_artifact_rejects_malformed_sidecar(tmp_path: Path) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")
    (artifact_path / ARTIFACT_META_FILENAME).write_text("{", encoding="utf-8")

    assert not is_runtime_compatible_local_index_artifact(
        artifact_path,
        content_hash=spec.content_hash,
    )


def test_runtime_local_index_artifact_rejects_wrong_fixed_metadata(tmp_path: Path) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")
    metadata_path = artifact_path / ARTIFACT_META_FILENAME

    for key, invalid_value in (
        ("schema_version", "local_index.artifact.changed"),
        ("provider", "http_json"),
        ("engine_name", "pageindex"),
    ):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        original_value = metadata[key]
        metadata[key] = invalid_value
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        assert not is_runtime_compatible_local_index_artifact(
            artifact_path,
            content_hash=spec.content_hash,
        )

        metadata[key] = original_value
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")


def test_runtime_local_index_artifact_rejects_empty_required_identity(
    tmp_path: Path,
) -> None:
    spec = _build_spec()
    artifact_path = tmp_path / "artifact"
    _write_artifact(artifact_path, build_spec=spec, fingerprint="fingerprint")
    metadata_path = artifact_path / ARTIFACT_META_FILENAME

    for key in (
        "engine_version",
        "parser_identity",
        "ingestion_config_fingerprint",
    ):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        original_value = metadata[key]
        metadata[key] = ""
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        assert not is_runtime_compatible_local_index_artifact(
            artifact_path,
            content_hash=spec.content_hash,
        )

        metadata[key] = original_value
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
