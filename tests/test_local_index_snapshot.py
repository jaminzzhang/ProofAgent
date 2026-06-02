"""Tests for optional-dependency-safe Local Index runtime snapshot loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_agent.capabilities.knowledge.local_index_snapshot import (
    load_ready_snapshot_manifest,
)
from proof_agent.contracts import (
    KnowledgeSourceSnapshotDocument,
    KnowledgeSourceSnapshotManifest,
)
from proof_agent.errors import ProofAgentError


def _document(
    *,
    document_id: str = "doc_policy",
    revision_id: str = "rev_policy",
    filename: str = "policy.md",
    artifact_path: str = "artifacts/doc_policy/rev_policy",
) -> KnowledgeSourceSnapshotDocument:
    return KnowledgeSourceSnapshotDocument(
        document_id=document_id,
        revision_id=revision_id,
        filename=filename,
        content_type="text/markdown",
        content_hash="a" * 64,
        artifact_path=artifact_path,
        routing_metadata={"department": "claims"},
    )


def _manifest(
    *,
    documents: tuple[KnowledgeSourceSnapshotDocument, ...] | None = None,
) -> KnowledgeSourceSnapshotManifest:
    return KnowledgeSourceSnapshotManifest(
        schema_version="local_index.snapshot.v2",
        snapshot_id="kssnapshot_policy_001",
        source_id="ks_policy",
        state="READY",
        validation_level="foundation",
        source_draft_version_id="ksdraft_policy_001",
        candidate_digest="b" * 64,
        foundation_validation_id="ksvalidation_policy_001",
        documents=documents if documents is not None else (_document(),),
        created_at="2026-06-02T00:00:00Z",
        created_by="operator",
    )


def _write_manifest(
    snapshot_path: Path,
    *,
    manifest: KnowledgeSourceSnapshotManifest | None = None,
    payload: object | None = None,
) -> None:
    snapshot_path.mkdir(parents=True)
    serialized = (
        payload
        if payload is not None
        else (manifest if manifest is not None else _manifest()).model_dump(mode="json")
    )
    (snapshot_path / "snapshot.json").write_text(json.dumps(serialized), encoding="utf-8")


def _assert_invalid_snapshot(
    snapshot_path: Path,
    artifact_root: Path,
    *,
    expected_message: str,
) -> None:
    with pytest.raises(ProofAgentError) as exc:
        load_ready_snapshot_manifest(snapshot_path, artifact_root=artifact_root)

    assert exc.value.code == "PA_KNOWLEDGE_001"
    assert expected_message in str(exc.value)


def test_load_ready_snapshot_manifest_returns_sorted_runtime_descriptors(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshots" / "snapshot"
    artifact_root = tmp_path / "store"
    artifact_root.mkdir()
    beta = _document(
        document_id="doc_beta",
        revision_id="rev_beta",
        filename="beta.md",
        artifact_path="artifacts/doc_beta/rev_beta",
    )
    alpha = _document(
        document_id="doc_alpha",
        revision_id="rev_alpha",
        filename="alpha.md",
        artifact_path="artifacts/doc_alpha/rev_alpha",
    )
    _write_manifest(snapshot_path, manifest=_manifest(documents=(beta, alpha)))

    runtime = load_ready_snapshot_manifest(snapshot_path, artifact_root=artifact_root)

    assert runtime.snapshot_id == "kssnapshot_policy_001"
    assert runtime.source_id == "ks_policy"
    assert runtime.state == "READY"
    assert runtime.validation_level == "foundation"
    assert [document.document_id for document in runtime.documents] == [
        "doc_alpha",
        "doc_beta",
    ]
    assert runtime.documents[0].artifact_path == (
        artifact_root / "artifacts/doc_alpha/rev_alpha"
    ).resolve()
    assert runtime.documents[0].artifact_root == artifact_root.resolve()
    assert runtime.documents[0].revision_id == "rev_alpha"
    assert runtime.documents[0].filename == "alpha.md"
    assert runtime.documents[0].content_type == "text/markdown"
    assert runtime.documents[0].content_hash == "a" * 64
    assert runtime.documents[0].routing_metadata == {"department": "claims"}


def test_load_ready_snapshot_manifest_rejects_missing_snapshot_json(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot"
    snapshot_path.mkdir()

    _assert_invalid_snapshot(snapshot_path, tmp_path, expected_message="snapshot.json")


def test_load_ready_snapshot_manifest_rejects_malformed_json(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot"
    snapshot_path.mkdir()
    (snapshot_path / "snapshot.json").write_text("{", encoding="utf-8")

    _assert_invalid_snapshot(snapshot_path, tmp_path, expected_message="snapshot.json")


def test_load_ready_snapshot_manifest_rejects_historical_v1_directory(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot"
    snapshot_path.mkdir()
    (snapshot_path / "artifact_meta.json").write_text("{}", encoding="utf-8")

    _assert_invalid_snapshot(snapshot_path, tmp_path, expected_message="snapshot.v2")


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"state": "BUILDING"}, "snapshot.json"),
        ({"schema_version": "local_index.snapshot.v1"}, "snapshot.json"),
        ({"documents": []}, "at least one document"),
    ],
)
def test_load_ready_snapshot_manifest_rejects_invalid_manifest(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    snapshot_path = tmp_path / "snapshot"
    payload = _manifest().model_dump(mode="json")
    payload.update(overrides)
    _write_manifest(snapshot_path, payload=payload)

    _assert_invalid_snapshot(snapshot_path, tmp_path, expected_message=expected_message)


def test_load_ready_snapshot_manifest_rejects_duplicate_document_id(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot"
    duplicate = _document(artifact_path="artifacts/doc_policy/another_revision")
    _write_manifest(snapshot_path, manifest=_manifest(documents=(_document(), duplicate)))

    _assert_invalid_snapshot(snapshot_path, tmp_path, expected_message="document_id")


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_id": ""},
        {"revision_id": ""},
        {"filename": ""},
        {"artifact_path": ""},
    ],
)
def test_load_ready_snapshot_manifest_rejects_empty_document_identity(
    tmp_path: Path,
    overrides: dict[str, str],
) -> None:
    snapshot_path = tmp_path / "snapshot"
    payload = _manifest().model_dump(mode="json")
    payload["documents"][0].update(overrides)
    _write_manifest(snapshot_path, payload=payload)

    _assert_invalid_snapshot(snapshot_path, tmp_path, expected_message=next(iter(overrides)))


def test_load_ready_snapshot_manifest_rejects_absolute_artifact_path(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot"
    _write_manifest(
        snapshot_path,
        manifest=_manifest(documents=(_document(artifact_path="/absolute/artifact"),)),
    )

    _assert_invalid_snapshot(snapshot_path, tmp_path, expected_message="relative")


@pytest.mark.parametrize(
    "artifact_path",
    [
        "C:/escape",
        r"..\escape",
        r"artifacts\doc_policy\rev_policy",
    ],
)
def test_load_ready_snapshot_manifest_rejects_non_posix_artifact_path(
    tmp_path: Path,
    artifact_path: str,
) -> None:
    snapshot_path = tmp_path / "snapshot"
    _write_manifest(
        snapshot_path,
        manifest=_manifest(documents=(_document(artifact_path=artifact_path),)),
    )

    _assert_invalid_snapshot(snapshot_path, tmp_path, expected_message="relative")


def test_load_ready_snapshot_manifest_rejects_parent_artifact_path_escape(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot"
    artifact_root = tmp_path / "store"
    _write_manifest(
        snapshot_path,
        manifest=_manifest(documents=(_document(artifact_path="../escape"),)),
    )

    _assert_invalid_snapshot(snapshot_path, artifact_root, expected_message="escapes")


def test_load_ready_snapshot_manifest_rejects_symlink_artifact_path_escape(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot"
    artifact_root = tmp_path / "store"
    artifact_root.mkdir()
    escape_link = artifact_root / "escape"
    try:
        escape_link.symlink_to(tmp_path / "outside", target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not supported by this platform.")
    _write_manifest(
        snapshot_path,
        manifest=_manifest(documents=(_document(artifact_path="escape/revision"),)),
    )

    _assert_invalid_snapshot(snapshot_path, artifact_root, expected_message="escapes")
