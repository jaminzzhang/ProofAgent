"""Tests for file-backed Local Index quarantine staging."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from threading import Barrier

import pytest
from filelock import FileLock

import proof_agent.configuration.local_store as local_store_module
from proof_agent.capabilities.knowledge.ingestion import (
    ingestion_config_fingerprint,
    parse_quarantined_upload,
)
from proof_agent.configuration.file_locking import (
    artifact_lock_path,
    locked,
    store_lock_path,
    try_locked,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.errors import ProofAgentError


def _local_index_params() -> dict[str, object]:
    return {
        "ingestion_model": {
            "provider": "openai",
            "name": "gpt-4.1-mini",
            "params": {"api_key_env": "OPENAI_API_KEY"},
        }
    }


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


def test_accept_upload_promotes_original_derivative_document_job_and_marker(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store, params=_local_index_params())
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\r\n",
        actor="local-user",
    )
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )

    document, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
    )

    suffix = upload.upload_id.removeprefix("upload_")
    accepted = store.get_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
    )
    revision_dir = store.knowledge_document_original_path(document).parent
    marker_path = (
        tmp_path
        / "knowledge_sources"
        / upload.source_id
        / "upload_promotions"
        / f"{upload.upload_id}.json"
    )

    assert document.document_id == f"doc_{suffix}"
    assert document.revision_id == f"rev_{suffix}"
    assert document.ingestion_job_id == f"job_{suffix}"
    assert document.state == "queued"
    assert store.knowledge_document_original_path(document).read_bytes() == b"# Policy\r\n"
    assert (revision_dir / "parsed-text.txt").read_text(encoding="utf-8") == "# Policy\n"
    parser_meta = json.loads((revision_dir / "parser-meta.json").read_text(encoding="utf-8"))
    assert parser_meta["fingerprint_identity"] == "markdown:utf-8:v1"
    assert parser_meta["parsed_text_sha256"] == parsed.parser_metadata.parsed_text_sha256
    assert job.job_id == f"job_{suffix}"
    assert job.document_id == document.document_id
    assert job.revision_id == document.revision_id
    assert job.state == "queued"
    assert job.ingestion_config_fingerprint == ingestion_config_fingerprint(job.artifact_build_spec)
    assert job.artifact_build_spec.content_hash == document.content_hash
    assert job.artifact_build_spec.parser_fingerprint_identity == "markdown:utf-8:v1"
    assert accepted is not None
    assert accepted.state == "accepted"
    assert accepted.promoted_document_id == document.document_id
    assert accepted.promoted_revision_id == document.revision_id
    assert accepted.ingestion_job_id == job.job_id
    assert marker_path.exists()
    assert not store.quarantined_knowledge_upload_bytes_path(upload).exists()
    assert store.count_reserved_knowledge_document_slots(upload.source_id) == 1
    assert store.list_knowledge_ingestion_jobs(upload.source_id) == [job]


def test_reject_upload_releases_capacity_and_purge_removes_only_expired_bytes(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="unsupported.exe",
        content_type="application/octet-stream",
        content=b"MZ",
        actor="local-user",
    )

    rejected = store.reject_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        error_code="PA_INGESTION_002",
        error_message="Knowledge upload type is not supported.",
    )

    assert rejected.state == "rejected"
    assert rejected.error_code == "PA_INGESTION_002"
    assert rejected.expires_at is not None
    assert store.count_reserved_knowledge_document_slots(upload.source_id) == 0
    assert store.quarantined_knowledge_upload_bytes_path(rejected).exists()
    assert store.list_knowledge_documents(upload.source_id) == []
    assert store.list_knowledge_ingestion_jobs(upload.source_id) == []

    expires_at = datetime.fromisoformat(rejected.expires_at.replace("Z", "+00:00"))
    assert store.purge_expired_quarantined_upload_bytes(now=expires_at - timedelta(seconds=1)) == []
    assert store.quarantined_knowledge_upload_bytes_path(rejected).exists()

    purged = store.purge_expired_quarantined_upload_bytes(now=expires_at + timedelta(seconds=1))
    refreshed = store.get_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
    )

    assert [item.upload_id for item in purged] == [upload.upload_id]
    assert refreshed is not None
    assert refreshed.purged_at is not None
    assert not store.quarantined_knowledge_upload_bytes_path(refreshed).exists()
    assert (
        tmp_path
        / "knowledge_sources"
        / upload.source_id
        / "quarantined_uploads"
        / upload.upload_id
        / "upload.json"
    ).exists()


def test_accept_upload_replays_deterministically_after_marker_write_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store, params=_local_index_params())
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )

    def interrupt_marker_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated marker interruption")

    monkeypatch.setattr(store, "_write_upload_promotion_marker", interrupt_marker_write)
    with pytest.raises(OSError, match="marker interruption"):
        store.accept_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            parsed_document=parsed,
        )
    monkeypatch.undo()

    document, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
    )

    assert document.document_id == f"doc_{upload.upload_id.removeprefix('upload_')}"
    assert job.job_id == f"job_{upload.upload_id.removeprefix('upload_')}"
    assert len(store.list_knowledge_documents(upload.source_id)) == 1
    assert len(store.list_knowledge_ingestion_jobs(upload.source_id)) == 1


def test_accept_upload_repairs_projection_after_marker_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store, params=_local_index_params())
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )
    original_write = store._write_quarantined_knowledge_upload

    def interrupt_accepted_projection(candidate: object) -> None:
        if getattr(candidate, "state", None) == "accepted":
            raise OSError("simulated accepted projection interruption")
        original_write(candidate)

    monkeypatch.setattr(store, "_write_quarantined_knowledge_upload", interrupt_accepted_projection)
    with pytest.raises(OSError, match="accepted projection interruption"):
        store.accept_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            parsed_document=parsed,
        )
    monkeypatch.undo()

    document, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
    )
    repaired = store.get_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
    )

    assert repaired is not None
    assert repaired.state == "accepted"
    assert repaired.promoted_document_id == document.document_id
    assert repaired.ingestion_job_id == job.job_id
    assert not store.quarantined_knowledge_upload_bytes_path(upload).exists()


def test_accept_upload_rejects_legacy_nested_raw_secret_before_job_persistence(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store, params=_local_index_params())
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    source_path = tmp_path / "knowledge_sources" / upload.source_id / "source.json"
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload["params"]["ingestion_model"]["params"] = {"api_key": "sk-do-not-store"}
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )

    with pytest.raises(ProofAgentError) as exc:
        store.accept_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            parsed_document=parsed,
        )

    assert exc.value.code == "PA_SECRET_001"
    assert "sk-do-not-store" not in str(exc.value)
    assert store.list_knowledge_documents(upload.source_id) == []
    assert store.list_knowledge_ingestion_jobs(upload.source_id) == []


def test_promoted_job_build_spec_remains_frozen_after_source_edit(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store, params=_local_index_params())
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )
    _, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
    )
    source_path = tmp_path / "knowledge_sources" / upload.source_id / "source.json"
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload["params"]["ingestion_model"]["name"] = "gpt-4.1"
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    reloaded = store.get_knowledge_ingestion_job(
        source_id=upload.source_id,
        job_id=job.job_id,
    )

    assert reloaded == job
    assert reloaded is not None
    assert reloaded.artifact_build_spec.declared_ingestion_model is not None
    assert reloaded.artifact_build_spec.declared_ingestion_model["name"] == "gpt-4.1-mini"


def test_promoted_job_freezes_missing_ingestion_model_for_worker_diagnosis(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )

    _, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
    )

    assert job.artifact_build_spec.declared_ingestion_model is None
