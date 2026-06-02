"""Integration tests for the Agent Configuration API."""

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import yaml

import proof_agent.configuration.local_store as local_store_module
import proof_agent.delivery.configuration_api as configuration_api_module
from proof_agent.capabilities.knowledge.ingestion import parse_quarantined_upload
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
from proof_agent.observability.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
    )
    return TestClient(app)


def _import_enterprise_qa(client: TestClient) -> dict:
    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
            "actor": "test-user",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_list_config_agents_empty(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/config/agents")

    assert response.status_code == 200
    assert response.json() == {"data": [], "meta": {"total": 0}}


def _create_local_index_source(
    client: TestClient,
    *,
    source_id: str = "ks_local_index",
    params: dict[str, object] | None = None,
) -> dict:
    response = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": source_id,
            "name": "Local Index Policies",
            "provider": "local_index",
            "params": params or {},
            "actor": "operator",
        },
    )
    assert response.status_code == 200
    return response.json()


def _upload(
    client: TestClient,
    *,
    source_id: str = "ks_local_index",
    filename: str = "travel-policy.md",
    content_type: str = "text/markdown",
    content: bytes = b"# Travel policy\n",
) -> object:
    return client.post(
        f"/api/config/knowledge-sources/{source_id}/documents",
        json={
            "filename": filename,
            "content_type": content_type,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "actor": "operator",
        },
    )


def _configuration_store(client: TestClient) -> LocalAgentConfigurationStore:
    return client.app.state.agent_configuration_store


def _write_compatible_ready_document(
    client: TestClient,
    *,
    document_id: str = "doc_policy",
) -> KnowledgeDocument:
    store = _configuration_store(client)
    artifact_path = f"artifacts/{document_id}/fingerprint"
    document = KnowledgeDocument(
        document_id=document_id,
        source_id="ks_local_index",
        revision_id=f"rev_{document_id}",
        filename=f"{document_id}.md",
        content_type="text/markdown",
        content_hash="a" * 64,
        size_bytes=10,
        state="ready",
        storage_path=(
            f"knowledge_sources/ks_local_index/documents/{document_id}/"
            f"revisions/rev_{document_id}/original.bin"
        ),
        ingestion_job_id=f"job_{document_id}",
        artifact_path=artifact_path,
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
    )
    job = KnowledgeIngestionJob(
        job_id=f"job_{document_id}",
        source_id="ks_local_index",
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
        artifact_path=artifact_path,
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
    )
    store._write_knowledge_document(document)
    store._write_knowledge_ingestion_job(job)
    published_artifact_path = store.root_dir / artifact_path
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


def test_create_local_index_knowledge_source_and_stage_quarantined_upload(tmp_path: Path) -> None:
    client = _client(tmp_path)

    created = _create_local_index_source(
        client,
        params={"index_path": "./indexes/policies"},
    )
    uploaded = _upload(
        client,
        filename="travel-policy.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4\nsample",
    )
    listed = client.get("/api/config/knowledge-sources")
    documents = client.get("/api/config/knowledge-sources/ks_local_index/documents")
    uploads = client.get("/api/config/knowledge-sources/ks_local_index/quarantined-uploads")

    assert created["source_id"] == "ks_local_index"
    assert created["provider"] == "local_index"
    assert created["source_draft_version_id"].startswith("ksdraft_")
    assert created["latest_snapshot_id"] is None
    assert created["published_snapshot_id"] is None
    assert uploaded.status_code == 200
    assert uploaded.json()["upload_id"].startswith("upload_")
    assert uploaded.json()["state"] == "queued"
    assert listed.json()["data"][0]["source_id"] == "ks_local_index"
    assert listed.json()["data"][0]["document_count"] == 0
    assert listed.json()["data"][0]["ready_document_count"] == 0
    assert documents.json() == {"data": [], "meta": {"total": 0}}
    assert uploads.json()["data"][0]["filename"] == "travel-policy.pdf"


def test_candidate_validation_and_freeze_management_api_lifecycle(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    _write_compatible_ready_document(client)

    candidate = client.get("/api/config/knowledge-sources/ks_local_index/candidate-snapshot")
    validation = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/validate-foundation",
        json={"actor": "validator"},
    )
    assert validation.status_code == 200
    frozen = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
        json={"validation_id": validation.json()["validation_id"], "actor": "operator"},
    )
    assert frozen.status_code == 200
    snapshots = client.get("/api/config/knowledge-sources/ks_local_index/snapshots")
    detail = client.get(
        f"/api/config/knowledge-sources/ks_local_index/snapshots/{frozen.json()['snapshot_id']}"
    )
    source = client.get("/api/config/knowledge-sources/ks_local_index")

    assert candidate.status_code == 200
    assert candidate.json()["included_documents"][0]["document_id"] == "doc_policy"
    assert validation.json()["validation_level"] == "foundation"
    assert frozen.json()["schema_version"] == "local_index.snapshot.v2"
    assert frozen.json()["state"] == "READY"
    assert snapshots.json() == {"data": [frozen.json()], "meta": {"total": 1}}
    assert detail.json() == frozen.json()
    assert source.json()["latest_snapshot_id"] == frozen.json()["snapshot_id"]
    assert source.json()["published_snapshot_id"] is None


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("unsupported.exe", "application/octet-stream", b"MZ"),
        ("mismatch.md", "application/pdf", b"# Markdown\n"),
        ("invalid.md", "text/markdown", b"\xff"),
        ("malformed.pdf", "application/pdf", b"not-a-pdf"),
    ],
)
def test_upload_stages_format_failures_for_asynchronous_rejection(
    tmp_path: Path,
    filename: str,
    content_type: str,
    content: bytes,
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    uploaded = _upload(
        client,
        filename=filename,
        content_type=content_type,
        content=content,
    )

    assert uploaded.status_code == 200
    assert uploaded.json()["state"] == "queued"
    assert _configuration_store(client).list_knowledge_documents("ks_local_index") == []


@pytest.mark.parametrize(
    "content_base64",
    [
        "not-valid-base64",
        "",
    ],
)
def test_upload_rejects_invalid_or_empty_base64_without_quarantine_record(
    tmp_path: Path,
    content_base64: str,
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    uploaded = client.post(
        "/api/config/knowledge-sources/ks_local_index/documents",
        json={
            "filename": "policy.md",
            "content_type": "text/markdown",
            "content_base64": content_base64,
            "actor": "operator",
        },
    )

    assert uploaded.status_code in {400, 422}
    assert _configuration_store(client).list_quarantined_knowledge_uploads("ks_local_index") == []


def test_upload_rejects_oversized_encoded_envelope_before_decoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    encoded = base64.b64encode(b"four").decode("ascii")
    monkeypatch.setattr(configuration_api_module, "MAX_UPLOAD_BYTES", 3)

    def fail_decode(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("oversized envelope must fail before base64 decode")

    monkeypatch.setattr(configuration_api_module.base64, "b64decode", fail_decode)

    uploaded = client.post(
        "/api/config/knowledge-sources/ks_local_index/documents",
        json={
            "filename": "policy.md",
            "content_type": "text/markdown",
            "content_base64": encoded,
            "actor": "operator",
        },
    )

    assert uploaded.status_code == 400
    assert "encoded upload envelope" in uploaded.json()["detail"]
    assert _configuration_store(client).list_quarantined_knowledge_uploads("ks_local_index") == []


def test_upload_rejects_decoded_content_over_byte_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    monkeypatch.setattr(configuration_api_module, "MAX_UPLOAD_BYTES", 4)

    uploaded = _upload(client, content=b"12345")

    assert uploaded.status_code == 400
    assert "exceeds 4 bytes" in uploaded.json()["detail"]
    assert _configuration_store(client).list_quarantined_knowledge_uploads("ks_local_index") == []


def test_upload_capacity_counts_pending_quarantine_reservations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_store_module, "KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY", 1)
    client = _client(tmp_path)
    _create_local_index_source(client)
    assert _upload(client, filename="first.md").status_code == 200

    blocked = _upload(client, filename="second.md")

    assert blocked.status_code == 503
    assert blocked.json()["detail"]["code"] == "PA_INGESTION_004"
    assert (
        len(_configuration_store(client).list_quarantined_knowledge_uploads("ks_local_index")) == 1
    )


def test_rejected_upload_releases_capacity_while_retaining_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_store_module, "KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY", 1)
    client = _client(tmp_path)
    _create_local_index_source(client)
    rejected_response = _upload(
        client,
        filename="unsupported.exe",
        content_type="application/octet-stream",
        content=b"MZ",
    )
    assert rejected_response.status_code == 200
    store = _configuration_store(client)
    upload = store.list_quarantined_knowledge_uploads("ks_local_index")[0]
    claimed = store.claim_next_quarantined_knowledge_upload()
    assert claimed is not None
    assert claimed.claim_token is not None
    rejected = store.reject_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        claim_token=claimed.claim_token,
        error_code="PA_INGESTION_002",
        error_message="Knowledge upload type is not supported.",
    )

    accepted = _upload(client, filename="replacement.md")

    assert accepted.status_code == 200
    assert rejected.expires_at is not None
    assert store.quarantined_knowledge_upload_bytes_path(rejected).exists()


def test_staged_upload_atomically_publishes_bytes_and_record(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    uploaded = _upload(client)

    assert uploaded.status_code == 200
    store = _configuration_store(client)
    upload = store.list_quarantined_knowledge_uploads("ks_local_index")[0]
    uploads_root = (
        tmp_path / "config" / "knowledge_sources" / "ks_local_index" / "quarantined_uploads"
    )
    assert (
        store.quarantined_knowledge_upload_bytes_path(upload).read_bytes() == b"# Travel policy\n"
    )
    assert (uploads_root / upload.upload_id / "upload.json").exists()
    assert sorted(path.name for path in uploads_root.iterdir()) == [upload.upload_id]


def test_create_source_rejects_nested_raw_secret_but_allows_env_reference(tmp_path: Path) -> None:
    client = _client(tmp_path)

    rejected = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_secret",
            "name": "Secret",
            "provider": "local_index",
            "params": {
                "ingestion_model": {
                    "provider": "openai",
                    "name": "gpt-4.1-mini",
                    "params": {"api_key": "sk-do-not-store"},
                }
            },
        },
    )
    allowed = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_env",
            "name": "Env",
            "provider": "local_index",
            "params": {
                "ingestion_model": {
                    "provider": "openai",
                    "name": "gpt-4.1-mini",
                    "params": {"api_key_env": "OPENAI_API_KEY"},
                }
            },
        },
    )

    assert rejected.status_code == 400
    assert rejected.json()["detail"]["code"] == "PA_SECRET_001"
    assert "sk-do-not-store" not in rejected.text
    assert allowed.status_code == 200
    assert _configuration_store(client).get_knowledge_source("ks_secret") is None


def test_quarantine_and_job_read_endpoints_return_persisted_state(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(
        client,
        params={
            "ingestion_model": {
                "provider": "deterministic",
                "name": "ingestion-model",
            }
        },
    )
    uploaded = _upload(client).json()
    store = _configuration_store(client)
    upload = store.get_quarantined_knowledge_upload(
        source_id="ks_local_index",
        upload_id=uploaded["upload_id"],
    )
    assert upload is not None
    claimed = store.claim_next_quarantined_knowledge_upload()
    assert claimed is not None
    assert claimed.claim_token is not None
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )
    _, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed.claim_token,
    )

    uploads = client.get("/api/config/knowledge-sources/ks_local_index/quarantined-uploads")
    upload_detail = client.get(
        f"/api/config/knowledge-sources/ks_local_index/quarantined-uploads/{upload.upload_id}"
    )
    jobs = client.get("/api/config/knowledge-sources/ks_local_index/ingestion-jobs")
    job_detail = client.get(
        f"/api/config/knowledge-sources/ks_local_index/ingestion-jobs/{job.job_id}"
    )

    assert uploads.status_code == 200
    assert uploads.json()["data"][0]["state"] == "accepted"
    assert upload_detail.status_code == 200
    assert upload_detail.json()["upload_id"] == upload.upload_id
    assert jobs.status_code == 200
    assert jobs.json()["data"][0]["state"] == "queued"
    assert job_detail.status_code == 200
    assert job_detail.json()["job_id"] == job.job_id


@pytest.mark.parametrize(
    "path",
    [
        "/api/config/knowledge-sources/missing/candidate-snapshot",
        "/api/config/knowledge-sources/missing/snapshots",
        "/api/config/knowledge-sources/missing/snapshots/kssnapshot_missing",
        "/api/config/knowledge-sources/missing/quarantined-uploads",
        "/api/config/knowledge-sources/missing/quarantined-uploads/upload_missing",
        "/api/config/knowledge-sources/missing/ingestion-jobs",
        "/api/config/knowledge-sources/missing/ingestion-jobs/job_missing",
    ],
)
def test_ingestion_projection_endpoints_return_404_for_unknown_source(
    tmp_path: Path,
    path: str,
) -> None:
    client = _client(tmp_path)

    assert client.get(path).status_code == 404


def test_ingestion_projection_detail_endpoints_return_404_for_unknown_record(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    assert (
        client.get(
            "/api/config/knowledge-sources/ks_local_index/quarantined-uploads/upload_missing"
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/config/knowledge-sources/ks_local_index/ingestion-jobs/job_missing"
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/config/knowledge-sources/ks_local_index/snapshots/kssnapshot_missing"
        ).status_code
        == 404
    )


def test_snapshot_freeze_returns_404_for_unknown_validation_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    frozen = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
        json={"validation_id": "ksvalidation_missing", "actor": "operator"},
    )

    assert frozen.status_code == 404


def test_candidate_snapshot_rejects_non_local_index_source(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_markdown",
            "name": "Markdown",
            "provider": "local_markdown",
            "params": {"path": "./knowledge"},
            "actor": "operator",
        },
    )
    assert created.status_code == 200

    candidate = client.get("/api/config/knowledge-sources/ks_markdown/candidate-snapshot")

    assert candidate.status_code == 400
    assert candidate.json()["detail"]["code"] == "PA_INGESTION_001"


def test_snapshot_freeze_maps_stale_validation_to_409(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    _write_compatible_ready_document(client)
    validation = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/validate-foundation",
        json={"actor": "validator"},
    )
    assert validation.status_code == 200
    store = _configuration_store(client)
    store._advance_source_draft_version_unlocked(
        "ks_local_index",
        updated_at="2026-06-02T01:00:00Z",
    )

    frozen = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
        json={"validation_id": validation.json()["validation_id"], "actor": "operator"},
    )

    assert frozen.status_code == 409
    assert frozen.json()["detail"]["code"] == "PA_INGESTION_005"


@pytest.mark.parametrize(
    ("method", "path", "store_method", "payload"),
    (
        (
            "GET",
            "/api/config/knowledge-sources/ks_local_index/candidate-snapshot",
            "get_candidate_knowledge_source_snapshot",
            None,
        ),
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/validate-foundation",
            "validate_candidate_knowledge_source_snapshot_foundation",
            {"actor": "validator"},
        ),
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
            "freeze_candidate_knowledge_source_snapshot",
            {"validation_id": "ksvalidation_001", "actor": "operator"},
        ),
    ),
)
def test_snapshot_endpoints_map_store_lock_timeout_to_503_without_second_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    store_method: str,
    payload: dict[str, str] | None,
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    store = _configuration_store(client)
    calls = 0

    def fail_operation(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise ProofAgentError(
            "PA_INGESTION_004",
            "Knowledge ingestion state is busy.",
            "Retry later.",
        )

    monkeypatch.setattr(store, store_method, fail_operation)

    response = client.request(method, path, json=payload)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "PA_INGESTION_004"
    assert calls == 1


def test_upload_maps_store_lock_timeout_to_503_without_second_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    store = _configuration_store(client)
    staging_calls = 0

    def fail_staging(**kwargs: object) -> object:
        nonlocal staging_calls
        staging_calls += 1
        raise ProofAgentError(
            "PA_INGESTION_004",
            "Knowledge ingestion state is busy.",
            "Retry later.",
        )

    monkeypatch.setattr(store, "stage_quarantined_knowledge_upload", fail_staging)

    uploaded = _upload(client)

    assert uploaded.status_code == 503
    assert uploaded.json()["detail"]["code"] == "PA_INGESTION_004"
    assert staging_calls == 1


def test_legacy_knowledge_source_providers_are_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)

    for provider in ("pageindex", "local_vector"):
        response = client.post(
            "/api/config/knowledge-sources",
            json={
                "source_id": f"ks_{provider}",
                "name": f"Legacy {provider}",
                "provider": provider,
                "params": {},
                "actor": "operator",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == f"Unsupported knowledge provider: {provider}"


def test_bind_shared_knowledge_source_to_agent_draft(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    created = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_local_markdown",
            "name": "Local Markdown Policies",
            "provider": "local_markdown",
            "params": {
                "path": "./knowledge",
            },
            "actor": "operator",
        },
    )
    assert created.status_code == 200

    bound = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/knowledge-bindings",
        json={
            "source_id": "ks_local_markdown",
            "alias": "policies",
            "failure_mode": "advisory",
            "fusion_weight": 0.75,
            "top_k": 3,
            "actor": "operator",
        },
    )
    loaded = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )

    assert bound.status_code == 200
    parsed = yaml.safe_load(bound.json()["agent_yaml"])
    assert any(
        source["source_id"] == "ks_local_markdown" and source["provider"] == "local_markdown"
        for source in parsed["knowledge_sources"]
    )
    assert any(
        binding["source_id"] == "ks_local_markdown"
        and binding["alias"] == "policies"
        and binding["failure_mode"] == "advisory"
        and binding["fusion_weight"] == 0.75
        and binding["top_k"] == 3
        for binding in parsed["knowledge_bindings"]
    )
    assert loaded.json()["agent_yaml"] == bound.json()["agent_yaml"]


def test_import_agent_package_creates_draft_and_list_entry(tmp_path: Path) -> None:
    client = _client(tmp_path)

    draft = _import_enterprise_qa(client)
    listed = client.get("/api/config/agents")

    assert draft["agent_id"] == "enterprise_qa"
    assert draft["draft_id"].startswith("draft_")
    assert draft["display_name"] == "enterprise_qa"
    assert listed.status_code == 200
    assert listed.json()["data"][0]["agent_id"] == "enterprise_qa"
    assert listed.json()["data"][0]["draft_count"] == 1
    assert listed.json()["data"][0]["active_version_id"] is None


def test_read_update_draft_and_contract_view(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}",
        json={
            "display_name": "Enterprise QA Workspace",
            "purpose": "Answer support policy questions with governed evidence.",
            "actor": "editor",
        },
    )
    loaded = client.get(f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}")
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )

    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Enterprise QA Workspace"
    assert loaded.status_code == 200
    assert loaded.json()["purpose"] == "Answer support policy questions with governed evidence."
    assert contract.status_code == 200
    assert contract.json()["agent_yaml"].startswith("name: enterprise_qa")
    assert contract.json()["policy_yaml"].startswith("rules:")
    assert "knowledge/customer-support-policy.md" in contract.json()["extra_files"]


def test_update_contract_view_revalidates_and_persists_agent_yaml(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    ).json()
    updated_yaml = contract["agent_yaml"].replace("  top_k: 2", "  top_k: 1")

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract",
        json={"agent_yaml": updated_yaml, "actor": "workflow-editor"},
    )

    assert updated.status_code == 200
    assert "  top_k: 1" in updated.json()["agent_yaml"]
    loaded = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )
    assert "  top_k: 1" in loaded.json()["agent_yaml"]


def test_validate_draft_runs_harness_as_validation_run(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "actor": "validator",
        },
    )

    assert validation.status_code == 200
    body = validation.json()
    assert body["run_id"].startswith("run_")
    assert body["run_purpose"] == "validation"
    assert body["agent_id"] == draft["agent_id"]
    assert body["draft_id"] == draft["draft_id"]

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["run_purpose"] == "validation"
    assert detail.json()["agent_id"] == draft["agent_id"]
    assert detail.json()["draft_id"] == draft["draft_id"]

    loaded = client.get(f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}")
    assert loaded.json()["validation_records"][0]["run_id"] == body["run_id"]


def test_publish_requires_validation_and_activates_version(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    blocked = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"actor": "publisher"},
    )
    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "actor": "validator",
        },
    )
    published = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation.json()["run_id"], "actor": "publisher"},
    )

    assert blocked.status_code == 400
    assert published.status_code == 200
    assert published.json()["version_id"].startswith("version_")
    assert published.json()["validation_run_id"] == validation.json()["run_id"]

    listed = client.get("/api/config/agents")
    assert listed.json()["data"][0]["active_version_id"] == published.json()["version_id"]


def test_rollback_switches_active_version(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    validation_one = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "actor": "validator",
        },
    )
    version_one = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation_one.json()["run_id"], "actor": "publisher"},
    ).json()["version_id"]
    client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}",
        json={"display_name": "Enterprise QA v2", "actor": "editor"},
    )
    validation_two = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "actor": "validator",
        },
    )
    version_two = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation_two.json()["run_id"], "actor": "publisher"},
    ).json()["version_id"]

    rollback = client.post(
        f"/api/config/agents/{draft['agent_id']}/versions/{version_one}/rollback",
        json={"actor": "publisher"},
    )

    assert rollback.status_code == 200
    assert rollback.json()["version_id"] == version_one
    assert rollback.json()["rollback_from_version_id"] == version_two
    assert client.get("/api/config/agents").json()["data"][0]["active_version_id"] == version_one
