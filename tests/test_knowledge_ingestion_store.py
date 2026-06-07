"""Tests for file-backed Local Index quarantine staging."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
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
from proof_agent.configuration.local_store import (
    KnowledgeUploadStagingInput,
    LocalAgentConfigurationStore,
)
from proof_agent.contracts import KnowledgeDocument, KnowledgeIngestionJob
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


def _claim_upload(
    store: LocalAgentConfigurationStore,
    *,
    source_id: str = "ks_local_index",
) -> object:
    claimed = store.claim_next_quarantined_knowledge_upload(source_id=source_id)
    assert claimed is not None
    assert claimed.claim_token is not None
    return claimed


def _promote_markdown_job(
    store: LocalAgentConfigurationStore,
    *,
    source_id: str = "ks_local_index",
) -> tuple[KnowledgeDocument, KnowledgeIngestionJob]:
    _create_local_index_source(store, source_id=source_id, params=_local_index_params())
    upload = store.stage_quarantined_knowledge_upload(
        source_id=source_id,
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    claimed = _claim_upload(store, source_id=source_id)
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )
    return store.accept_quarantined_knowledge_upload(
        source_id=source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed.claim_token,
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


def test_stage_quarantined_upload_preserves_unicode_display_filename(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)

    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="../../理赔 条款.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4\nsample",
        actor="local-user",
    )

    assert upload.filename == "理赔_条款.pdf"
    assert "/" not in upload.filename
    assert "\\" not in upload.filename


def test_stage_quarantined_upload_batch_reserves_full_batch_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_store_module, "KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY", 2)
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)

    uploads = store.stage_quarantined_knowledge_upload_batch(
        source_id="ks_local_index",
        uploads=(
            KnowledgeUploadStagingInput(
                filename="first.md",
                content_type="text/markdown",
                content=b"# First\n",
            ),
            KnowledgeUploadStagingInput(
                filename="second.md",
                content_type="text/markdown",
                content=b"# Second\n",
            ),
        ),
        actor="local-user",
    )

    assert [upload.filename for upload in uploads] == ["first.md", "second.md"]
    assert store.count_reserved_knowledge_document_slots("ks_local_index") == 2
    assert store.list_quarantined_knowledge_uploads("ks_local_index") == uploads
    assert [
        store.quarantined_knowledge_upload_bytes_path(upload).read_bytes()
        for upload in uploads
    ] == [b"# First\n", b"# Second\n"]

    with pytest.raises(ProofAgentError) as exc:
        store.stage_quarantined_knowledge_upload_batch(
            source_id="ks_local_index",
            uploads=(
                KnowledgeUploadStagingInput(
                    filename="third.md",
                    content_type="text/markdown",
                    content=b"# Third\n",
                ),
            ),
            actor="local-user",
        )

    assert exc.value.code == "PA_INGESTION_004"
    assert store.list_quarantined_knowledge_uploads("ks_local_index") == uploads


def test_stage_quarantined_upload_batch_rejects_more_than_50_files(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)

    with pytest.raises(ProofAgentError) as exc:
        store.stage_quarantined_knowledge_upload_batch(
            source_id="ks_local_index",
            uploads=tuple(
                KnowledgeUploadStagingInput(
                    filename=f"policy-{index}.md",
                    content_type="text/markdown",
                    content=b"# Policy\n",
                )
                for index in range(51)
            ),
            actor="local-user",
        )

    assert exc.value.code == "PA_INGESTION_002"
    assert store.list_quarantined_knowledge_uploads("ks_local_index") == []


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
    claimed = _claim_upload(store)

    document, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed.claim_token,
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
    claimed = _claim_upload(store)

    rejected = store.reject_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        claim_token=claimed.claim_token,
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
    claimed = _claim_upload(store)

    def interrupt_marker_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated marker interruption")

    monkeypatch.setattr(store, "_write_upload_promotion_marker", interrupt_marker_write)
    with pytest.raises(OSError, match="marker interruption"):
        store.accept_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            parsed_document=parsed,
            claim_token=claimed.claim_token,
        )
    monkeypatch.undo()

    document, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed.claim_token,
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
    claimed = _claim_upload(store)
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
            claim_token=claimed.claim_token,
        )
    monkeypatch.undo()

    document, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed.claim_token,
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
    claimed = _claim_upload(store)

    with pytest.raises(ProofAgentError) as exc:
        store.accept_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            parsed_document=parsed,
            claim_token=claimed.claim_token,
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
    claimed = _claim_upload(store)
    _, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed.claim_token,
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
    claimed = _claim_upload(store)

    _, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed.claim_token,
    )

    assert job.artifact_build_spec.declared_ingestion_model is None


def test_quarantine_claim_renewal_requires_matching_token_and_expired_claim_is_reclaimable(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store)
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )

    first = store.claim_next_quarantined_knowledge_upload(source_id=upload.source_id)

    assert first is not None
    assert first.state == "processing"
    assert first.attempt_count == 1
    assert first.claim_token is not None
    assert first.lease_expires_at is not None
    assert store.claim_next_quarantined_knowledge_upload(source_id=upload.source_id) is None

    renewed = store.renew_quarantined_knowledge_upload_claim(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        claim_token=first.claim_token,
        lease_seconds=600,
    )
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at > first.lease_expires_at

    with pytest.raises(ProofAgentError) as exc:
        store.renew_quarantined_knowledge_upload_claim(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            claim_token="claim_stale",
        )
    assert exc.value.code == "PA_INGESTION_004"

    store._write_quarantined_knowledge_upload(
        renewed.model_copy(update={"lease_expires_at": "2000-01-01T00:00:00Z"})
    )
    reclaimed = store.claim_next_quarantined_knowledge_upload(source_id=upload.source_id)

    assert reclaimed is not None
    assert reclaimed.attempt_count == 2
    assert reclaimed.claim_token != first.claim_token


def test_stale_quarantine_claim_cannot_accept_or_reject_after_recovery(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store, params=_local_index_params())
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    first = store.claim_next_quarantined_knowledge_upload(source_id=upload.source_id)
    assert first is not None
    assert first.claim_token is not None
    store._write_quarantined_knowledge_upload(
        first.model_copy(update={"lease_expires_at": "2000-01-01T00:00:00Z"})
    )
    reclaimed = store.claim_next_quarantined_knowledge_upload(source_id=upload.source_id)
    assert reclaimed is not None
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )

    with pytest.raises(ProofAgentError) as accept_exc:
        store.accept_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            parsed_document=parsed,
            claim_token=first.claim_token,
        )
    with pytest.raises(ProofAgentError) as reject_exc:
        store.reject_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            claim_token=first.claim_token,
            error_code="PA_INGESTION_002",
            error_message="stale",
        )

    assert accept_exc.value.code == "PA_INGESTION_004"
    assert reject_exc.value.code == "PA_INGESTION_004"


def test_ingestion_job_is_not_claimable_until_promotion_marker_exists(
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
    claimed = _claim_upload(store)
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
            claim_token=claimed.claim_token,
        )

    assert len(store.list_knowledge_ingestion_jobs(upload.source_id)) == 1
    assert store.claim_next_knowledge_ingestion_job(source_id=upload.source_id) is None


def test_ingestion_job_claim_renews_reclaims_and_counts_against_source_limit(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    params = {**_local_index_params(), "worker_concurrency": 1}
    _create_local_index_source(store, params=params)
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    upload_claim = _claim_upload(store)
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )
    document, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=upload_claim.claim_token,
    )

    first = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)

    assert first is not None
    assert first.state == "processing"
    assert first.attempt_count == 1
    assert first.claim_token is not None
    assert first.lease_expires_at is not None
    projected_document = store.get_knowledge_document(
        source_id=document.source_id,
        document_id=document.document_id,
    )
    assert projected_document is not None
    assert projected_document.state == "processing"
    store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="queued.md",
        content_type="text/markdown",
        content=b"# Queued\n",
        actor="local-user",
    )
    assert store.claim_next_knowledge_worker_task().task is None

    renewed = store.renew_knowledge_ingestion_job_claim(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=first.claim_token,
        lease_seconds=600,
    )
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at > first.lease_expires_at

    with pytest.raises(ProofAgentError) as exc:
        store.renew_knowledge_ingestion_job_claim(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token="claim_stale",
        )
    assert exc.value.code == "PA_INGESTION_004"

    store._write_knowledge_ingestion_job(
        renewed.model_copy(update={"lease_expires_at": "2000-01-01T00:00:00Z"})
    )
    reclaimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)

    assert reclaimed is not None
    assert reclaimed.attempt_count == 2
    assert reclaimed.claim_token != first.claim_token


def test_unified_claim_selects_oldest_ready_task_across_queues(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(store, source_id="ks_upload")
    _create_local_index_source(store, source_id="ks_job", params=_local_index_params())
    oldest_upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_upload",
        filename="oldest.md",
        content_type="text/markdown",
        content=b"# Oldest\n",
        actor="local-user",
    )
    job_upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_job",
        filename="job.md",
        content_type="text/markdown",
        content=b"# Job\n",
        actor="local-user",
    )
    job_claim = _claim_upload(store, source_id="ks_job")
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(job_upload),
        filename=job_upload.filename,
        content_type=job_upload.content_type,
    )
    store.accept_quarantined_knowledge_upload(
        source_id=job_upload.source_id,
        upload_id=job_upload.upload_id,
        parsed_document=parsed,
        claim_token=job_claim.claim_token,
    )

    selection = store.claim_next_knowledge_worker_task()

    assert selection.task is not None
    assert selection.task.kind == "quarantine_validation"
    assert selection.task.upload is not None
    assert selection.task.upload.upload_id == oldest_upload.upload_id


def test_unified_claim_skips_capped_source_and_reports_malformed_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_local_index_source(
        store,
        source_id="ks_capped",
        params={"worker_concurrency": 1},
    )
    _create_local_index_source(store, source_id="ks_malformed")
    _create_local_index_source(store, source_id="ks_eligible")
    for source_id in ("ks_capped", "ks_capped", "ks_malformed", "ks_eligible"):
        store.stage_quarantined_knowledge_upload(
            source_id=source_id,
            filename=f"{source_id}.md",
            content_type="text/markdown",
            content=b"# Policy\n",
            actor="local-user",
        )
    capped = store.claim_next_quarantined_knowledge_upload(source_id="ks_capped")
    assert capped is not None
    source_path = tmp_path / "knowledge_sources" / "ks_malformed" / "source.json"
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload["params"]["worker_concurrency"] = 0
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    selection = store.claim_next_knowledge_worker_task()

    assert selection.task is not None
    assert selection.task.upload is not None
    assert selection.task.upload.source_id == "ks_eligible"
    assert len(selection.diagnostics) == 1
    assert selection.diagnostics[0].source_id == "ks_malformed"
    assert selection.diagnostics[0].code == "PA_INGESTION_001"


def test_complete_ingestion_job_persists_ready_artifact_reference(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    document, job = _promote_markdown_job(store)
    claimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert claimed is not None
    assert claimed.claim_token is not None

    completed = store.complete_knowledge_ingestion_job(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=claimed.claim_token,
        artifact_path="knowledge_artifacts/content/config",
    )
    projected_document = store.get_knowledge_document(
        source_id=document.source_id,
        document_id=document.document_id,
    )

    assert completed.state == "ready"
    assert completed.artifact_path == "knowledge_artifacts/content/config"
    assert completed.completed_at is not None
    assert completed.claim_token is None
    assert projected_document is not None
    assert projected_document.state == "ready"
    assert projected_document.artifact_path == completed.artifact_path


def test_defer_ingestion_job_waits_five_seconds_without_counting_build_failure(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    document, job = _promote_markdown_job(store)
    claimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert claimed is not None
    assert claimed.claim_token is not None

    deferred = store.defer_knowledge_ingestion_job(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=claimed.claim_token,
    )
    projected_document = store.get_knowledge_document(
        source_id=document.source_id,
        document_id=document.document_id,
    )

    assert deferred.state == "queued"
    assert deferred.next_attempt_at is not None
    assert deferred.auto_retry_count == 0
    assert deferred.attempt_count == 1
    assert deferred.claim_token is None
    assert projected_document is not None
    assert projected_document.state == "queued"
    assert store.claim_next_knowledge_ingestion_job(source_id=job.source_id) is None

    store._write_knowledge_ingestion_job(
        deferred.model_copy(update={"next_attempt_at": "2000-01-01T00:00:00Z"})
    )
    reclaimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)

    assert reclaimed is not None
    assert reclaimed.attempt_count == 2
    assert reclaimed.auto_retry_count == 0


def test_reschedule_ingestion_job_allows_two_auto_retries_then_fails(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    document, job = _promote_markdown_job(store)

    for expected_retry_count in (1, 2):
        claimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
        assert claimed is not None
        assert claimed.claim_token is not None
        job = store.reschedule_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=claimed.claim_token,
            error_code="PA_INGESTION_003",
            error_message="Temporary model timeout.",
            retry_delay_seconds=0,
        )
        assert job.state == "queued"
        assert job.auto_retry_count == expected_retry_count
        assert job.last_error_code == "PA_INGESTION_003"
        assert job.next_attempt_at is not None

    claimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert claimed is not None
    assert claimed.claim_token is not None
    failed = store.reschedule_knowledge_ingestion_job(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=claimed.claim_token,
        error_code="PA_INGESTION_003",
        error_message="Temporary model timeout.",
        retry_delay_seconds=0,
    )
    projected_document = store.get_knowledge_document(
        source_id=document.source_id,
        document_id=document.document_id,
    )

    assert failed.state == "failed"
    assert failed.auto_retry_count == 3
    assert failed.attempt_count == 3
    assert failed.error_code == "PA_INGESTION_003"
    assert failed.completed_at is not None
    assert projected_document is not None
    assert projected_document.state == "failed"


def test_reschedule_ingestion_job_defaults_to_thirty_then_one_hundred_twenty_second_backoff(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _, job = _promote_markdown_job(store)
    first_claim = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert first_claim is not None
    assert first_claim.claim_token is not None

    first_retry_started = datetime.now(UTC)
    first_retry = store.reschedule_knowledge_ingestion_job(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=first_claim.claim_token,
        error_code="PA_INGESTION_003",
        error_message="Temporary model timeout.",
    )

    assert first_retry.next_attempt_at is not None
    first_retry_at = datetime.fromisoformat(first_retry.next_attempt_at.replace("Z", "+00:00"))
    assert timedelta(seconds=29) <= first_retry_at - first_retry_started <= timedelta(seconds=31)

    store._write_knowledge_ingestion_job(
        first_retry.model_copy(update={"next_attempt_at": "2000-01-01T00:00:00Z"})
    )
    second_claim = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert second_claim is not None
    assert second_claim.claim_token is not None
    second_retry_started = datetime.now(UTC)
    second_retry = store.reschedule_knowledge_ingestion_job(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=second_claim.claim_token,
        error_code="PA_INGESTION_003",
        error_message="Temporary model timeout.",
    )

    assert second_retry.next_attempt_at is not None
    second_retry_at = datetime.fromisoformat(second_retry.next_attempt_at.replace("Z", "+00:00"))
    assert (
        timedelta(seconds=119) <= second_retry_at - second_retry_started <= timedelta(seconds=121)
    )


def test_stale_job_claim_cannot_commit_and_failure_does_not_persist_traceback(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _, job = _promote_markdown_job(store)
    first = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert first is not None
    assert first.claim_token is not None
    store._write_knowledge_ingestion_job(
        first.model_copy(update={"lease_expires_at": "2000-01-01T00:00:00Z"})
    )
    reclaimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert reclaimed is not None
    assert reclaimed.claim_token is not None

    with pytest.raises(ProofAgentError) as complete_exc:
        store.complete_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=first.claim_token,
            artifact_path="stale",
        )
    with pytest.raises(ProofAgentError) as defer_exc:
        store.defer_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=first.claim_token,
        )
    with pytest.raises(ProofAgentError) as reschedule_exc:
        store.reschedule_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=first.claim_token,
            error_code="PA_INGESTION_003",
            error_message="stale",
        )
    with pytest.raises(ProofAgentError) as fail_exc:
        store.fail_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=first.claim_token,
            error_code="PA_INGESTION_003",
            error_message="stale",
        )

    assert complete_exc.value.code == "PA_INGESTION_004"
    assert defer_exc.value.code == "PA_INGESTION_004"
    assert reschedule_exc.value.code == "PA_INGESTION_004"
    assert fail_exc.value.code == "PA_INGESTION_004"

    failed = store.fail_knowledge_ingestion_job(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=reclaimed.claim_token,
        error_code="PA_INGESTION_003",
        error_message="Traceback (most recent call last):\nsecret stack detail",
    )

    assert failed.state == "failed"
    assert failed.error_message == "Local Index artifact build failed."
    assert "Traceback" not in failed.error_message


def test_retry_failed_ingestion_job_returns_job_and_document_to_queue(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    document, job = _promote_markdown_job(store)
    claimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert claimed is not None
    assert claimed.claim_token is not None
    failed = store.fail_knowledge_ingestion_job(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=claimed.claim_token,
        error_code="PA_INGESTION_001",
        error_message="Missing model credential environment variable(s): DEEPSEEK_API_KEY",
    )

    retried = store.retry_failed_knowledge_ingestion_job(
        source_id=failed.source_id,
        job_id=failed.job_id,
    )
    projected_document = store.get_knowledge_document(
        source_id=document.source_id,
        document_id=document.document_id,
    )
    reclaimed = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)

    assert retried.state == "queued"
    assert retried.error_code is None
    assert retried.error_message is None
    assert retried.completed_at is None
    assert retried.last_error_code == "PA_INGESTION_001"
    assert retried.last_error_message == "Missing model credential environment variable(s): DEEPSEEK_API_KEY"
    assert projected_document is not None
    assert projected_document.state == "queued"
    assert projected_document.error_code is None
    assert projected_document.error_message is None
    assert reclaimed is not None
    assert reclaimed.job_id == job.job_id


def test_retry_ingestion_job_rejects_non_failed_state(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _, job = _promote_markdown_job(store)

    with pytest.raises(ProofAgentError) as exc:
        store.retry_failed_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
        )

    assert exc.value.code == "PA_INGESTION_004"
    assert "cannot be retried from state queued" in exc.value.message


def test_complete_ingestion_job_rejects_non_processing_state(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _, job = _promote_markdown_job(store)

    with pytest.raises(ProofAgentError) as exc:
        store.complete_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token="claim_missing",
            artifact_path="knowledge_artifacts/content/config",
        )

    assert exc.value.code == "PA_INGESTION_004"
