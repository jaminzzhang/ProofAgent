"""Tests for Local Index candidate snapshot projection and freeze lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
        claim_token=claim_token,
        claimed_at="2026-06-02T00:00:00Z" if claim_token else None,
        lease_expires_at="2999-06-02T00:00:00Z" if claim_token else None,
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
    )


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
