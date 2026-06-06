"""Tests for Knowledge Source publication records and pointers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import proof_agent.capabilities.knowledge.http_json as http_json_module
from proof_agent.capabilities.knowledge.ingestion.artifacts import (
    ARTIFACT_META_FILENAME,
    REQUIRED_LLAMA_INDEX_FILES,
    local_index_artifact_metadata,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.control.knowledge.source_publication import (
    LocalIndexPublicationSmokeResult,
)
from proof_agent.contracts import (
    EnvironmentModelCredentialReference,
    KnowledgeArtifactBuildSpec,
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeSourcePublicationValidation,
)
from proof_agent.errors import ProofAgentError


def test_validate_publication_requires_latest_snapshot(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)

    with pytest.raises(ProofAgentError) as exc:
        store.validate_local_index_source_publication(
            source_id="ks_policy",
            smoke_query="What does the policy require?",
            actor="operator",
        )

    assert exc.value.code == "PA_CONFIG_001"
    assert "latest_snapshot_id" in exc.value.message


def test_validate_publication_rejects_zero_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store_with_frozen_snapshot(tmp_path)

    monkeypatch.setattr(
        "proof_agent.configuration.local_store.validate_local_index_publication_smoke",
        lambda **_: LocalIndexPublicationSmokeResult(candidate_count=0, citation_count=0),
    )

    with pytest.raises(ProofAgentError) as exc:
        store.validate_local_index_source_publication(
            source_id="ks_policy",
            smoke_query="What does the policy require?",
            actor="operator",
        )

    assert exc.value.code == "PA_CONFIG_001"
    assert "evidence" in exc.value.message


def test_validate_publication_persists_passed_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store_with_frozen_snapshot(tmp_path)

    monkeypatch.setattr(
        "proof_agent.configuration.local_store.validate_local_index_publication_smoke",
        lambda **_: LocalIndexPublicationSmokeResult(candidate_count=1, citation_count=1),
    )

    validation = store.validate_local_index_source_publication(
        source_id="ks_policy",
        smoke_query="What does the policy require?",
        actor="operator",
    )

    source = store.get_knowledge_source("ks_policy")
    assert source is not None
    assert validation.validation_id.startswith("kspubval_")
    assert validation.source_id == "ks_policy"
    assert validation.snapshot_id == source.latest_snapshot_id
    assert validation.status == "passed"
    assert validation.candidate_count == 1
    assert validation.citation_count == 1
    assert store.list_knowledge_source_publication_validations("ks_policy") == [validation]


def test_publication_requires_change_note(tmp_path: Path) -> None:
    store, validation = _store_with_passed_publication_validation(tmp_path)

    with pytest.raises(ProofAgentError) as exc:
        store.publish_knowledge_source(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            change_note="",
            actor="operator",
        )

    assert exc.value.code == "PA_CONFIG_001"
    assert "change_note" in exc.value.message


def test_publish_writes_record_and_published_snapshot_pointer(tmp_path: Path) -> None:
    store, validation = _store_with_passed_publication_validation(tmp_path)

    record = store.publish_knowledge_source(
        source_id="ks_policy",
        validation_id=validation.validation_id,
        change_note="Initial publication.",
        actor="operator",
    )

    source = store.get_knowledge_source("ks_policy")
    assert source is not None
    assert source.published_snapshot_id == record.snapshot_id
    assert record.publication_id.startswith("kspub_")
    assert record.source_id == "ks_policy"
    assert record.snapshot_id == validation.snapshot_id


def test_http_json_publication_validates_and_publishes_remote_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_knowledge_source(
        source_id="ks_remote",
        name="Remote Policies",
        provider="http_json",
        params={"endpoint": "https://knowledge.example/retrieve", "top_k": 2},
        actor="operator",
    )
    monkeypatch.setattr(
        http_json_module,
        "_send_http_json_request",
        lambda request: {
            "protocol_version": "proof-agent.remote-retrieval.v1",
            "upstream_revision": "remote_rev_1",
            "results": [
                {
                    "content": "Remote policy evidence.",
                    "score": 0.88,
                    "citation": "https://knowledge.example/policies#remote",
                }
            ],
        },
    )

    validation = store.validate_http_json_source_publication(
        source_id="ks_remote",
        smoke_query="What does the remote policy require?",
        actor="validator",
    )
    record = store.publish_knowledge_source(
        source_id="ks_remote",
        validation_id=validation.validation_id,
        change_note="Publish remote policy API.",
        actor="operator",
    )
    source = store.get_knowledge_source("ks_remote")

    assert source is not None
    assert validation.resource_kind == "remote_config"
    assert validation.resource_id.startswith("ksremote_")
    assert validation.snapshot_id is None
    assert validation.candidate_count == 1
    assert validation.citation_count == 1
    assert record.resource_kind == "remote_config"
    assert record.resource_id == validation.resource_id
    assert record.snapshot_id is None
    assert source.published_snapshot_id == record.resource_id
    assert record.source_draft_version_id == validation.source_draft_version_id
    assert record.validation_id == validation.validation_id
    assert record.change_note == "Publish remote policy API."
    assert record.published_by == "operator"
    assert record.document_count == 0
    assert record.smoke_query == validation.smoke_query
    assert record.smoke_result_summary["candidate_count"] == 1
    assert store.list_knowledge_source_publications("ks_remote") == [record]


def test_reusing_publication_validation_conflicts(tmp_path: Path) -> None:
    store, validation = _store_with_passed_publication_validation(tmp_path)
    store.publish_knowledge_source(
        source_id="ks_policy",
        validation_id=validation.validation_id,
        change_note="Initial publication.",
        actor="operator",
    )

    with pytest.raises(ProofAgentError) as exc:
        store.publish_knowledge_source(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            change_note="Duplicate publication.",
            actor="operator",
        )

    assert exc.value.code == "PA_CONFIG_002"
    assert "already been published" in exc.value.message


def test_publish_rejects_archived_source_owned_model_connection(tmp_path: Path) -> None:
    store, validation = _store_with_passed_publication_validation(tmp_path)
    store.create_model_connection(
        connection_id="model_archived_routing",
        display_name="Archived Routing",
        provider="deterministic",
        model_identifier="routing",
        credential_ref=EnvironmentModelCredentialReference(name="DEMO_MODEL_KEY"),
        actor="operator",
    )
    store.archive_model_connection(
        connection_id="model_archived_routing",
        actor="operator",
        reason="Archive before publication.",
    )
    source = store.get_knowledge_source("ks_policy")
    assert source is not None
    store._write_knowledge_source(
        source.model_copy(
            update={
                "params": {
                    "routing_model": {
                        "model_source": "shared",
                        "connection_id": "model_archived_routing",
                    }
                }
            }
        )
    )

    with pytest.raises(ProofAgentError) as exc:
        store.publish_knowledge_source(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            change_note="Publish with archived model.",
            actor="operator",
        )

    assert exc.value.code == "PA_CONFIG_002"
    assert "model_archived_routing" in exc.value.message


def _store_with_passed_publication_validation(
    tmp_path: Path,
) -> tuple[LocalAgentConfigurationStore, KnowledgeSourcePublicationValidation]:
    store = _store_with_frozen_snapshot(tmp_path)
    source = store.get_knowledge_source("ks_policy")
    assert source is not None
    assert source.latest_snapshot_id is not None
    snapshot = store.get_knowledge_source_snapshot(
        source_id="ks_policy",
        snapshot_id=source.latest_snapshot_id,
    )
    assert snapshot is not None
    validation = KnowledgeSourcePublicationValidation(
        validation_id="kspubval_001",
        source_id="ks_policy",
        snapshot_id=snapshot.snapshot_id,
        source_draft_version_id=snapshot.source_draft_version_id,
        candidate_digest=snapshot.candidate_digest,
        status="passed",
        smoke_query="What does the policy require?",
        candidate_count=1,
        citation_count=1,
        created_at="2026-06-04T00:00:00Z",
        created_by="validator",
    )
    store._write_knowledge_source_publication_validation(validation)
    return store, validation


def _store_with_frozen_snapshot(tmp_path: Path) -> LocalAgentConfigurationStore:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _write_compatible_ready_document(store, tmp_path)
    foundation = store.validate_candidate_knowledge_source_snapshot_foundation(
        source_id="ks_policy",
        actor="validator",
    )
    snapshot = store.freeze_candidate_knowledge_source_snapshot(
        source_id="ks_policy",
        validation_id=foundation.validation_id,
        actor="operator",
    )
    assert snapshot.snapshot_id
    return store


def _create_source(store: LocalAgentConfigurationStore) -> None:
    store.create_knowledge_source(
        source_id="ks_policy",
        name="Policy Knowledge",
        provider="local_index",
        params={},
        actor="operator",
    )


def _write_compatible_ready_document(
    store: LocalAgentConfigurationStore,
    tmp_path: Path,
) -> None:
    document = KnowledgeDocument(
        document_id="doc_policy",
        source_id="ks_policy",
        revision_id="rev_policy",
        filename="policy.md",
        content_type="text/markdown",
        content_hash="a" * 64,
        size_bytes=10,
        state="ready",
        storage_path=(
            "knowledge_sources/ks_policy/documents/doc_policy/revisions/rev_policy/original.bin"
        ),
        ingestion_job_id="job_policy",
        artifact_path="artifacts/doc_policy/fingerprint",
        created_at="2026-06-04T00:00:00Z",
        updated_at="2026-06-04T00:00:00Z",
    )
    job = KnowledgeIngestionJob(
        job_id="job_policy",
        source_id="ks_policy",
        document_id=document.document_id,
        revision_id=document.revision_id,
        state="ready",
        ingestion_config_fingerprint="fingerprint",
        artifact_build_spec=KnowledgeArtifactBuildSpec(
            provider="local_index",
            engine_name="llama-index-tree",
            engine_version="llama-index-tree@0.14.22",
            parser_fingerprint_identity="markdown:utf-8:v1",
            content_hash=document.content_hash,
            parsed_text_sha256="b" * 64,
        ),
        artifact_path=document.artifact_path,
        created_at="2026-06-04T00:00:00Z",
        updated_at="2026-06-04T00:00:00Z",
    )
    store._write_knowledge_document(document)
    store._write_knowledge_ingestion_job(job)
    published_artifact_path = tmp_path / "artifacts" / "doc_policy" / "fingerprint"
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
