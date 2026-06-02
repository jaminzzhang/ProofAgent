"""Tests for file-backed Local Index quarantine staging."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Barrier

import pytest
from filelock import FileLock

import proof_agent.configuration.local_store as local_store_module
from proof_agent.configuration.file_locking import (
    artifact_lock_path,
    locked,
    store_lock_path,
    try_locked,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.errors import ProofAgentError


def _create_local_index_source(
    store: LocalAgentConfigurationStore,
    *,
    source_id: str = "ks_local_index",
    params: dict[str, object] | None = None,
) -> None:
    store.create_knowledge_source(
        source_id=source_id,
        name=source_id,
        provider="local_index",
        params=params or {},
        actor="local-user",
    )


def test_file_lock_paths_are_store_scoped_and_artifact_key_hashed(tmp_path: Path) -> None:
    artifact_key = "content-sha256/config-sha256"

    assert store_lock_path(tmp_path) == tmp_path / ".locks" / "store.lock"
    assert artifact_lock_path(tmp_path, artifact_key) == (
        tmp_path / ".locks" / "artifacts" / f"{sha256(artifact_key.encode()).hexdigest()}.lock"
    )


def test_locked_normalizes_timeout_and_try_locked_is_non_blocking(tmp_path: Path) -> None:
    path = store_lock_path(tmp_path)
    path.parent.mkdir(parents=True)

    with FileLock(path).acquire(timeout=0):
        with try_locked(path) as acquired:
            assert acquired is False

        with pytest.raises(ProofAgentError) as exc:
            with locked(path, timeout_seconds=0):
                raise AssertionError("unreachable")

    assert exc.value.code == "PA_INGESTION_004"


def test_create_source_validates_worker_concurrency_before_persistence(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)
    _create_local_index_source(
        store,
        source_id="ks_bounded",
        params={"worker_concurrency": 8},
    )

    assert store.get_knowledge_source_worker_concurrency("ks_local_index") == 2
    assert store.get_knowledge_source_worker_concurrency("ks_bounded") == 8

    for index, value in enumerate((0, 9, True, 1.5, "2")):
        source_id = f"ks_invalid_{index}"
        with pytest.raises(ProofAgentError) as exc:
            _create_local_index_source(
                store,
                source_id=source_id,
                params={"worker_concurrency": value},
            )

        assert exc.value.code == "PA_INGESTION_001"
        assert store.get_knowledge_source(source_id) is None


def test_create_source_rejects_nested_raw_secret_before_persistence(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    with pytest.raises(ProofAgentError) as exc:
        _create_local_index_source(
            store,
            params={
                "ingestion_model": {
                    "provider": "openai",
                    "name": "gpt-4.1-mini",
                    "params": {"api_key": "sk-do-not-store"},
                }
            },
        )

    assert exc.value.code == "PA_SECRET_001"
    assert "sk-do-not-store" not in str(exc.value)
    assert store.get_knowledge_source("ks_local_index") is None


def test_stage_quarantined_upload_atomically_persists_bytes_and_record(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)

    first = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="../../Travel Policy.md",
        content_type="text/markdown",
        content=b"# Travel policy\n",
        actor="local-user",
    )
    second = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="expense-policy.md",
        content_type="text/markdown",
        content=b"# Expense policy\n",
        actor="local-user",
    )

    assert first.filename == "Travel_Policy.md"
    assert first.state == "queued"
    assert first.size_bytes == len(b"# Travel policy\n")
    assert first.storage_path.endswith(f"/{first.upload_id}/original-upload.bin")
    assert store.quarantined_knowledge_upload_bytes_path(first).read_bytes() == b"# Travel policy\n"
    assert (
        store.get_quarantined_knowledge_upload(
            source_id="ks_local_index",
            upload_id=first.upload_id,
        )
        == first
    )
    assert store.list_quarantined_knowledge_uploads("ks_local_index") == [first, second]
    assert store.list_knowledge_documents("ks_local_index") == []
    assert store.count_reserved_knowledge_document_slots("ks_local_index") == 2

    uploads_root = tmp_path / "knowledge_sources" / "ks_local_index" / "quarantined_uploads"
    assert sorted(path.name for path in uploads_root.iterdir()) == sorted(
        [first.upload_id, second.upload_id]
    )
    assert (uploads_root / first.upload_id / "upload.json").exists()


def test_staging_counts_managed_documents_against_source_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_store_module, "KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY", 1)
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)
    store.add_knowledge_document(
        source_id="ks_local_index",
        filename="existing.md",
        content_type="text/markdown",
        content=b"# Existing\n",
        state="ready",
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as exc:
        store.stage_quarantined_knowledge_upload(
            source_id="ks_local_index",
            filename="new.md",
            content_type="text/markdown",
            content=b"# New\n",
            actor="local-user",
        )

    assert exc.value.code == "PA_INGESTION_004"
    assert store.count_reserved_knowledge_document_slots("ks_local_index") == 1


def test_concurrent_staging_cannot_exceed_source_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_store_module, "KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY", 1)
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)
    barrier = Barrier(2)

    def stage(filename: str) -> str:
        barrier.wait()
        try:
            store.stage_quarantined_knowledge_upload(
                source_id="ks_local_index",
                filename=filename,
                content_type="text/markdown",
                content=b"# Policy\n",
                actor="local-user",
            )
        except ProofAgentError as exc:
            return exc.code
        return "staged"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(stage, ("first.md", "second.md")))

    assert sorted(results) == ["PA_INGESTION_004", "staged"]
    assert store.count_reserved_knowledge_document_slots("ks_local_index") == 1
    assert len(store.list_quarantined_knowledge_uploads("ks_local_index")) == 1


def test_store_lock_timeout_leaves_no_half_staged_upload(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)
    path = store_lock_path(tmp_path)

    with FileLock(path).acquire(timeout=0):
        with pytest.raises(ProofAgentError) as exc:
            store.stage_quarantined_knowledge_upload(
                source_id="ks_local_index",
                filename="blocked.md",
                content_type="text/markdown",
                content=b"# Blocked\n",
                actor="local-user",
                lock_timeout_seconds=0,
            )

    assert exc.value.code == "PA_INGESTION_004"
    assert store.list_quarantined_knowledge_uploads("ks_local_index") == []
