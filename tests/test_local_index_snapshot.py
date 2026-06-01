"""Tests for immutable Local Index snapshot metadata loading."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_agent.capabilities.knowledge.local_index_snapshot import (
    load_ready_snapshot_metadata,
)
from proof_agent.errors import ProofAgentError


def _write_artifact_meta(index_path: Path, **overrides: object) -> None:
    payload = {
        "schema_version": "local_index.snapshot.v1",
        "snapshot_id": "snapshot_enterprise_policy_001",
        "state": "READY",
        "provider": "local_index",
        "engine_name": "llama-index-tree",
        "engine_version": "0.12",
    }
    payload.update(overrides)
    index_path.mkdir()
    (index_path / "artifact_meta.json").write_text(json.dumps(payload), encoding="utf-8")


def test_load_ready_snapshot_metadata_returns_trace_safe_identity(tmp_path: Path) -> None:
    index_path = tmp_path / "snapshot"
    _write_artifact_meta(index_path)

    metadata = load_ready_snapshot_metadata(index_path)

    assert metadata.snapshot_id == "snapshot_enterprise_policy_001"
    assert metadata.state == "READY"
    assert metadata.provider == "local_index"
    assert metadata.engine_name == "llama-index-tree"
    assert metadata.engine_version == "0.12"
    assert not hasattr(metadata, "index_path")


def test_load_ready_snapshot_metadata_rejects_missing_sidecar(tmp_path: Path) -> None:
    index_path = tmp_path / "snapshot"
    index_path.mkdir()

    with pytest.raises(ProofAgentError) as exc:
        load_ready_snapshot_metadata(index_path)

    assert exc.value.code == "PA_KNOWLEDGE_001"
    assert "artifact_meta.json" in str(exc.value)


def test_load_ready_snapshot_metadata_rejects_malformed_sidecar(tmp_path: Path) -> None:
    index_path = tmp_path / "snapshot"
    index_path.mkdir()
    (index_path / "artifact_meta.json").write_text("{", encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        load_ready_snapshot_metadata(index_path)

    assert exc.value.code == "PA_KNOWLEDGE_001"
    assert "artifact_meta.json" in str(exc.value)


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"state": "BUILDING"}, "READY"),
        ({"provider": "http_json"}, "local_index"),
        ({"engine_name": "pageindex"}, "llama-index-tree"),
        ({"snapshot_id": ""}, "snapshot_id"),
    ],
)
def test_load_ready_snapshot_metadata_rejects_invalid_identity(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    index_path = tmp_path / "snapshot"
    _write_artifact_meta(index_path, **overrides)

    with pytest.raises(ProofAgentError) as exc:
        load_ready_snapshot_metadata(index_path)

    assert exc.value.code == "PA_KNOWLEDGE_001"
    assert expected_message in str(exc.value)
