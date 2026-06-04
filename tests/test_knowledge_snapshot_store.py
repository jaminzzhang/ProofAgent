"""Tests for Local Index candidate snapshot projection and freeze lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_agent.capabilities.knowledge.ingestion.artifacts import (
    ARTIFACT_META_FILENAME,
    REQUIRED_LLAMA_INDEX_FILES,
    local_index_artifact_metadata,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    KnowledgeArtifactBuildSpec,
    KnowledgeDocument,
    KnowledgeIngestionJob,
)
from proof_agent.errors import ProofAgentError


def _create_source(
    store: LocalAgentConfigurationStore,
    *,
    source_id: str = "ks_policy",
    provider: str = "local_index",
) -> None:
    store.create_knowledge_source(
        source_id=source_id,
        name=source_id,
        provider=provider,
        params={},
        actor="operator",
    )


def _document(
    *,
    document_id: str,
    state: str,
    artifact_path: str | None = None,
    source_id: str = "ks_policy",
    created_at: str = "2026-06-02T00:00:00Z",
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        source_id=source_id,
        revision_id=f"rev_{document_id}",
        filename=f"{document_id}.md",
        content_type="text/markdown",
        content_hash=document_id.removeprefix("doc_").ljust(64, "a")[:64],
        size_bytes=10,
        state=state,
        storage_path=(
            f"knowledge_sources/{source_id}/documents/{document_id}/"
            f"revisions/rev_{document_id}/original.bin"
        ),
        ingestion_job_id=f"job_{document_id}",
        artifact_path=artifact_path,
        created_at=created_at,
        updated_at=created_at,
    )


def _job(
    document: KnowledgeDocument,
    *,
    state: str,
    claim_token: str | None = None,
    artifact_path: str | None = None,
) -> KnowledgeIngestionJob:
    return KnowledgeIngestionJob(
        job_id=f"job_{document.document_id}",
        source_id=document.source_id,
        document_id=document.document_id,
        revision_id=document.revision_id,
        state=state,
        ingestion_config_fingerprint="fingerprint",
        artifact_build_spec=KnowledgeArtifactBuildSpec(
            provider="local_index",
            engine_name="llama-index-tree",
            engine_version="llama-index-tree@0.14.22",
            parser_fingerprint_identity="markdown:utf-8:v1",
            content_hash=document.content_hash,
            parsed_text_sha256="b" * 64,
        ),
        artifact_path=artifact_path,
        claim_token=claim_token,
        claimed_at="2026-06-02T00:00:00Z" if claim_token else None,
        lease_expires_at="2999-06-02T00:00:00Z" if claim_token else None,
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
    )


def _write_compatible_ready_document(
    store: LocalAgentConfigurationStore,
    tmp_path: Path,
    *,
    document_id: str,
    source_id: str = "ks_policy",
) -> KnowledgeDocument:
    artifact_path = f"artifacts/{document_id}/fingerprint"
    document = _document(
        source_id=source_id,
        document_id=document_id,
        state="ready",
        artifact_path=artifact_path,
    )
    job = _job(document, state="ready", artifact_path=artifact_path)
    store._write_knowledge_document(document)
    store._write_knowledge_ingestion_job(job)
    published_artifact_path = tmp_path / artifact_path
    published_artifact_path.mkdir(parents=True)
    for filename in REQUIRED_LLAMA_INDEX_FILES:
        (published_artifact_path / filename).write_text("{}", encoding="utf-8")
    (published_artifact_path / ARTIFACT_META_FILENAME).write_text(
        json.dumps(
            local_index_artifact_metadata(
                build_spec=job.artifact_build_spec,
                ingestion_config_fingerprint=job.ingestion_config_fingerprint,
            )
        ),
        encoding="utf-8",
    )
    return document


def test_source_creation_mints_draft_token_without_snapshot_pointers(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)

    source = store.get_knowledge_source("ks_policy")

    assert source is not None
    assert source.source_draft_version_id is not None
    assert source.source_draft_version_id.startswith("ksdraft_")
    assert source.latest_snapshot_id is None
    assert source.published_snapshot_id is None


def test_candidate_read_normalizes_legacy_source_token_under_lock(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    source_path = tmp_path / "knowledge_sources" / "ks_policy" / "source.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload.pop("source_draft_version_id")
    source_path.write_text(json.dumps(payload), encoding="utf-8")

    candidate = store.get_candidate_knowledge_source_snapshot("ks_policy")
    persisted = store.get_knowledge_source("ks_policy")

    assert candidate.source_draft_version_id.startswith("ksdraft_")
    assert persisted is not None
    assert persisted.source_draft_version_id == candidate.source_draft_version_id


def test_candidate_projection_contains_sorted_ready_documents_and_excluded_counts(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    documents = (
        _document(
            document_id="doc_beta",
            state="ready",
            artifact_path="artifacts/beta/fingerprint",
            created_at="2026-06-02T00:00:00Z",
        ),
        _document(document_id="doc_queued", state="queued"),
        _document(document_id="doc_processing", state="processing"),
        _document(document_id="doc_failed", state="failed"),
        _document(document_id="doc_archived", state="archived"),
        _document(
            document_id="doc_alpha",
            state="ready",
            artifact_path="artifacts/alpha/fingerprint",
            created_at="2026-06-02T00:01:00Z",
        ),
    )
    for document in documents:
        store._write_knowledge_document(document)

    first = store.get_candidate_knowledge_source_snapshot("ks_policy")
    second = store.get_candidate_knowledge_source_snapshot("ks_policy")

    assert [document.document_id for document in first.included_documents] == [
        "doc_alpha",
        "doc_beta",
    ]
    assert first.queued_document_count == 1
    assert first.processing_document_count == 1
    assert first.failed_document_count == 1
    assert first.archived_document_count == 1
    assert first.required_reingestion_count == 0
    assert first.candidate_digest == second.candidate_digest

    changed = documents[-1].model_copy(update={"filename": "changed.md"})
    store._write_knowledge_document(changed)

    assert (
        store.get_candidate_knowledge_source_snapshot("ks_policy").candidate_digest
        != first.candidate_digest
    )


def test_candidate_projection_rejects_non_local_index_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store, provider="local_markdown")

    with pytest.raises(ProofAgentError) as exc:
        store.get_candidate_knowledge_source_snapshot("ks_policy")

    assert exc.value.code == "PA_INGESTION_001"


def test_candidate_projection_rejects_ready_document_without_artifact_reference(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    store._write_knowledge_document(_document(document_id="doc_missing", state="ready"))

    with pytest.raises(ProofAgentError) as exc:
        store.get_candidate_knowledge_source_snapshot("ks_policy")

    assert exc.value.code == "PA_INGESTION_001"


def test_ready_job_completion_advances_source_draft_token(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    document = _document(document_id="doc_policy", state="processing")
    job = _job(document, state="processing", claim_token="claim_owned")
    store._write_knowledge_document(document)
    store._write_knowledge_ingestion_job(job)
    before = store.get_knowledge_source("ks_policy")
    assert before is not None

    store.complete_knowledge_ingestion_job(
        source_id="ks_policy",
        job_id=job.job_id,
        claim_token="claim_owned",
        artifact_path="artifacts/policy/fingerprint",
    )

    after = store.get_knowledge_source("ks_policy")
    assert after is not None
    assert after.source_draft_version_id != before.source_draft_version_id


def test_document_routing_metadata_update_advances_source_draft_token_and_candidate(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    document = _write_compatible_ready_document(
        store,
        tmp_path,
        document_id="doc_policy",
    )
    before = store.get_knowledge_source("ks_policy")
    assert before is not None

    updated = store.update_knowledge_document_routing_metadata(
        source_id="ks_policy",
        document_id=document.document_id,
        routing_metadata={
            "title": "Claims Policy",
            "description": "Inpatient claim rules",
            "tags": ["claims", "inpatient", ""],
            "document_type": "policy",
        },
        actor="operator",
    )
    candidate = store.get_candidate_knowledge_source_snapshot("ks_policy")
    after = store.get_knowledge_source("ks_policy")

    assert after is not None
    assert after.source_draft_version_id != before.source_draft_version_id
    assert updated.routing_metadata == {
        "title": "Claims Policy",
        "description": "Inpatient claim rules",
        "tags": ["claims", "inpatient"],
        "document_type": "policy",
    }
    assert candidate.included_documents[0].routing_metadata == updated.routing_metadata


def test_document_routing_metadata_update_rejects_unknown_fields_without_draft_change(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    document = _write_compatible_ready_document(
        store,
        tmp_path,
        document_id="doc_policy",
    )
    before = store.get_knowledge_source("ks_policy")
    assert before is not None

    with pytest.raises(ProofAgentError) as exc:
        store.update_knowledge_document_routing_metadata(
            source_id="ks_policy",
            document_id=document.document_id,
            routing_metadata={"unknown": "claims"},
            actor="operator",
        )

    after = store.get_knowledge_source("ks_policy")
    assert after is not None
    assert after.source_draft_version_id == before.source_draft_version_id
    assert exc.value.code == "PA_CONFIG_001"


def test_non_membership_upload_transitions_do_not_advance_source_draft_token(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    before = store.get_knowledge_source("ks_policy")
    assert before is not None
    upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_policy",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="operator",
    )
    claimed = store.claim_next_quarantined_knowledge_upload(source_id="ks_policy")
    assert claimed is not None
    assert claimed.claim_token is not None
    store.renew_quarantined_knowledge_upload_claim(
        source_id="ks_policy",
        upload_id=upload.upload_id,
        claim_token=claimed.claim_token,
    )
    store.reject_quarantined_knowledge_upload(
        source_id="ks_policy",
        upload_id=upload.upload_id,
        claim_token=claimed.claim_token,
        error_code="PA_INGESTION_002",
        error_message="Rejected.",
    )

    after = store.get_knowledge_source("ks_policy")
    assert after is not None
    assert after.source_draft_version_id == before.source_draft_version_id


def test_non_ready_job_transitions_do_not_advance_source_draft_token(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    before = store.get_knowledge_source("ks_policy")
    assert before is not None
    document = _document(document_id="doc_policy", state="queued")
    job = _job(document, state="queued")
    store._write_knowledge_document(document)
    store._write_knowledge_ingestion_job(job)

    claimed = store._claim_knowledge_ingestion_job_unlocked(job, lease_seconds=300)
    assert claimed.claim_token is not None
    renewed = store.renew_knowledge_ingestion_job_claim(
        source_id="ks_policy",
        job_id=job.job_id,
        claim_token=claimed.claim_token,
    )
    assert renewed.claim_token is not None
    store.defer_knowledge_ingestion_job(
        source_id="ks_policy",
        job_id=job.job_id,
        claim_token=renewed.claim_token,
    )

    retry_document = document.model_copy(update={"state": "processing"})
    retry_job = _job(retry_document, state="processing", claim_token="claim_retry")
    store._write_knowledge_document(retry_document)
    store._write_knowledge_ingestion_job(retry_job)
    store.reschedule_knowledge_ingestion_job(
        source_id="ks_policy",
        job_id=retry_job.job_id,
        claim_token="claim_retry",
        error_code="PA_INGESTION_003",
        error_message="Temporary failure.",
        retry_delay_seconds=0,
    )

    failed_document = document.model_copy(update={"state": "processing"})
    failed_job = _job(failed_document, state="processing", claim_token="claim_fail")
    store._write_knowledge_document(failed_document)
    store._write_knowledge_ingestion_job(failed_job)
    store.fail_knowledge_ingestion_job(
        source_id="ks_policy",
        job_id=failed_job.job_id,
        claim_token="claim_fail",
        error_code="PA_INGESTION_003",
        error_message="Permanent failure.",
    )

    after = store.get_knowledge_source("ks_policy")
    assert after is not None
    assert after.source_draft_version_id == before.source_draft_version_id


def test_foundation_validation_persists_passed_candidate_record(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _write_compatible_ready_document(store, tmp_path, document_id="doc_policy")

    validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="operator",
    )

    assert validation.validation_id.startswith("ksvalidation_")
    assert validation.source_id == "ks_policy"
    assert validation.validation_level == "foundation"
    assert validation.status == "passed"
    assert validation.document_count == 1
    assert validation.required_reingestion_count == 0
    validation_path = (
        tmp_path
        / "knowledge_sources"
        / "ks_policy"
        / "snapshot_validations"
        / f"{validation.validation_id}.json"
    )
    assert json.loads(validation_path.read_text(encoding="utf-8"))["candidate_digest"] == (
        validation.candidate_digest
    )


@pytest.mark.parametrize(
    "invalid_candidate",
    (
        "empty",
        "escaped_path",
        "missing_artifact",
        "missing_job",
        "mismatched_job_artifact",
        "incompatible_artifact",
    ),
)
def test_foundation_validation_rejects_invalid_candidate_without_persisting_record(
    tmp_path: Path,
    invalid_candidate: str,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    if invalid_candidate != "empty":
        document = _document(
            document_id="doc_policy",
            state="ready",
            artifact_path=(
                "../outside"
                if invalid_candidate == "escaped_path"
                else "artifacts/doc_policy/fingerprint"
            ),
        )
        store._write_knowledge_document(document)
        if invalid_candidate != "missing_job":
            job = _job(
                document,
                state="ready",
                artifact_path=(
                    "artifacts/other/fingerprint"
                    if invalid_candidate == "mismatched_job_artifact"
                    else document.artifact_path
                ),
            )
            store._write_knowledge_ingestion_job(job)
        if invalid_candidate == "incompatible_artifact":
            artifact_path = tmp_path / "artifacts" / "doc_policy" / "fingerprint"
            artifact_path.mkdir(parents=True)
            (artifact_path / ARTIFACT_META_FILENAME).write_text("{}", encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.validate_candidate_knowledge_source_snapshot_foundation(
            source_id="ks_policy",
            actor="operator",
        )

    assert exc.value.code == "PA_INGESTION_001"
    validation_root = tmp_path / "knowledge_sources" / "ks_policy" / "snapshot_validations"
    assert not validation_root.exists() or list(validation_root.iterdir()) == []


def test_freeze_persists_multi_document_manifest_and_latest_preview_pointer(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _write_compatible_ready_document(store, tmp_path, document_id="doc_beta")
    _write_compatible_ready_document(store, tmp_path, document_id="doc_alpha")
    validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )

    manifest = store.freeze_candidate_knowledge_source_snapshot(
        source_id="ks_policy",
        validation_id=validation.validation_id,
        actor="operator",
    )
    source = store.get_knowledge_source("ks_policy")

    assert manifest.snapshot_id.startswith("kssnapshot_")
    assert manifest.schema_version == "local_index.snapshot.v2"
    assert manifest.state == "READY"
    assert manifest.validation_level == "foundation"
    assert [document.document_id for document in manifest.documents] == [
        "doc_alpha",
        "doc_beta",
    ]
    assert source is not None
    assert source.latest_snapshot_id == manifest.snapshot_id
    assert source.published_snapshot_id is None
    assert store.get_knowledge_source_snapshot(
        source_id="ks_policy",
        snapshot_id=manifest.snapshot_id,
    ) == manifest
    assert store.list_knowledge_source_snapshots("ks_policy") == [manifest]


def test_freeze_reuses_manifest_after_repeat_validation(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _write_compatible_ready_document(store, tmp_path, document_id="doc_policy")
    first_validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )
    first = store.freeze_candidate_knowledge_source_snapshot(
        source_id="ks_policy",
        validation_id=first_validation.validation_id,
        actor="operator",
    )
    second_validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )

    second = store.freeze_candidate_knowledge_source_snapshot(
        source_id="ks_policy",
        validation_id=second_validation.validation_id,
        actor="operator",
    )

    assert second == first
    assert second.foundation_validation_id == first_validation.validation_id
    assert store.list_knowledge_source_snapshots("ks_policy") == [first]


def test_freeze_rejects_unknown_validation_id(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)

    with pytest.raises(KeyError):
        store.freeze_candidate_knowledge_source_snapshot(
            source_id="ks_policy",
            validation_id="ksvalidation_missing",
            actor="operator",
        )


@pytest.mark.parametrize("conflict", ("source", "token", "digest"))
def test_freeze_rejects_stale_or_corrupted_validation(
    tmp_path: Path,
    conflict: str,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    document = _write_compatible_ready_document(store, tmp_path, document_id="doc_policy")
    validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )
    if conflict == "source":
        validation_path = (
            tmp_path
            / "knowledge_sources"
            / "ks_policy"
            / "snapshot_validations"
            / f"{validation.validation_id}.json"
        )
        payload = json.loads(validation_path.read_text(encoding="utf-8"))
        payload["source_id"] = "ks_other"
        validation_path.write_text(json.dumps(payload), encoding="utf-8")
    elif conflict == "token":
        store._advance_source_draft_version_unlocked(
            "ks_policy",
            updated_at="2026-06-02T01:00:00Z",
        )
    else:
        store._write_knowledge_document(document.model_copy(update={"filename": "changed.md"}))

    with pytest.raises(ProofAgentError) as exc:
        store.freeze_candidate_knowledge_source_snapshot(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            actor="operator",
        )

    assert exc.value.code == "PA_INGESTION_005"


def test_freeze_normalizes_malformed_validation_record(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _write_compatible_ready_document(store, tmp_path, document_id="doc_policy")
    validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )
    validation_path = (
        tmp_path
        / "knowledge_sources"
        / "ks_policy"
        / "snapshot_validations"
        / f"{validation.validation_id}.json"
    )
    validation_path.write_text("{", encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.freeze_candidate_knowledge_source_snapshot(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            actor="operator",
        )

    assert exc.value.code == "PA_INGESTION_005"


def test_freeze_rejects_incompatible_existing_deterministic_manifest(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _write_compatible_ready_document(store, tmp_path, document_id="doc_policy")
    validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )
    manifest = store.freeze_candidate_knowledge_source_snapshot(
        source_id="ks_policy",
        validation_id=validation.validation_id,
        actor="operator",
    )
    manifest_path = (
        tmp_path
        / "knowledge_sources"
        / "ks_policy"
        / "snapshots"
        / manifest.snapshot_id
        / "snapshot.json"
    )
    manifest_path.write_text("{", encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.freeze_candidate_knowledge_source_snapshot(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            actor="operator",
        )

    assert exc.value.code == "PA_INGESTION_005"


def test_freeze_rejects_shape_valid_but_changed_existing_manifest(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _write_compatible_ready_document(store, tmp_path, document_id="doc_policy")
    validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )
    manifest = store.freeze_candidate_knowledge_source_snapshot(
        source_id="ks_policy",
        validation_id=validation.validation_id,
        actor="operator",
    )
    manifest_path = (
        tmp_path
        / "knowledge_sources"
        / "ks_policy"
        / "snapshots"
        / manifest.snapshot_id
        / "snapshot.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["documents"] = []
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.freeze_candidate_knowledge_source_snapshot(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            actor="operator",
        )

    assert exc.value.code == "PA_INGESTION_005"


def test_freeze_replay_repairs_pointer_after_manifest_write_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _write_compatible_ready_document(store, tmp_path, document_id="doc_policy")
    validation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )
    original_write_source = store._write_knowledge_source

    def fail_pointer_write(source: object) -> None:
        raise RuntimeError("simulated pointer write interruption")

    monkeypatch.setattr(store, "_write_knowledge_source", fail_pointer_write)
    with pytest.raises(RuntimeError):
        store.freeze_candidate_knowledge_source_snapshot(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            actor="operator",
        )
    monkeypatch.setattr(store, "_write_knowledge_source", original_write_source)

    assert len(store.list_knowledge_source_snapshots("ks_policy")) == 1
    source = store.get_knowledge_source("ks_policy")
    assert source is not None
    assert source.latest_snapshot_id is None

    replayed = store.freeze_candidate_knowledge_source_snapshot(
        source_id="ks_policy",
        validation_id=validation.validation_id,
        actor="operator",
    )

    repaired = store.get_knowledge_source("ks_policy")
    assert repaired is not None
    assert repaired.latest_snapshot_id == replayed.snapshot_id
