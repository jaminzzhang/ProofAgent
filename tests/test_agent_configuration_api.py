"""Integration tests for the Agent Configuration API."""

import base64
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
import yaml

import proof_agent.configuration.local_store as local_store_module
import proof_agent.delivery.configuration_api as configuration_api_module
import proof_agent.capabilities.knowledge.http_json as http_json_module
from proof_agent.capabilities.knowledge.ingestion import parse_quarantined_upload
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
    ContractBundle,
    EnvironmentModelCredentialReference,
    KnowledgeArtifactBuildSpec,
    KnowledgeDocument,
    KnowledgeIngestionJob,
    ReceiptOutcome,
    RunResult,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.app import create_app
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
)


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
    )
    return TestClient(app)


class _StaticOperatorIdentityProvider:
    def __init__(self, permissions: set[OperatorPermission]) -> None:
        self._permissions = permissions

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id="test-operator",
            display_name="Test Operator",
            permissions=frozenset(self._permissions),
        )


def _client_with_operator_permissions(
    tmp_path: Path,
    permissions: set[OperatorPermission],
) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
    )
    app.state.operator_identity_provider = _StaticOperatorIdentityProvider(permissions)
    return TestClient(app)


def _import_enterprise_qa(client: TestClient) -> dict:
    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
        },
    )
    assert response.status_code == 200
    return response.json()


def _import_react_enterprise_qa(client: TestClient) -> dict:
    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml",
        },
    )
    assert response.status_code == 200
    return response.json()


def _import_react_enterprise_qa_v3(client: TestClient) -> dict:
    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_list_config_agents_empty(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/config/agents")

    assert response.status_code == 200
    assert response.json() == {"data": [], "meta": {"total": 0}}


def test_agent_config_read_requires_agent_view_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(tmp_path, set())

    response = client.get("/api/config/agents")

    assert response.status_code == 403
    assert response.json()["detail"] == "Operator lacks required permission: agent.view"


def test_agent_config_import_rejects_request_body_actor(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
            "actor": "spoofed-operator",
        },
    )

    assert response.status_code == 422


def test_agent_config_import_requires_agent_edit_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.AGENT_VIEW},
    )

    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Operator lacks required permission: agent.edit"


def test_agent_config_import_uses_operator_identity_for_audit(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.AGENT_EDIT, OperatorPermission.AGENT_VIEW},
    )

    draft = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
        },
    )

    assert draft.status_code == 200
    assert draft.json()["created_by"] == "test-operator"


def test_agent_config_validation_requires_agent_validate_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.AGENT_EDIT, OperatorPermission.AGENT_VIEW},
    )
    draft = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
        },
    ).json()

    response = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={"question": "What is the reimbursement rule for travel meals?"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Operator lacks required permission: agent.validate"


def test_agent_config_publish_requires_agent_publish_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.AGENT_EDIT, OperatorPermission.AGENT_VIEW},
    )
    draft = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
        },
    ).json()

    response = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Operator lacks required permission: agent.publish"


def test_tool_source_descriptors_include_brave_search(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/config/tool-source-descriptors")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["provider"] == "brave_search"
    assert data[0]["exposed_tool_contracts"] == ["untrusted_web_search"]
    assert data[0]["credential_env_vars"] == ["BRAVE_SEARCH_API_KEY"]
    assert data[0]["supports_validation"] is True


def test_tool_source_read_requires_view_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(tmp_path, set())

    response = client.get("/api/config/tool-source-descriptors")

    assert response.status_code == 403
    assert response.json()["detail"] == "Operator lacks required permission: tool_source.view"


def test_tool_source_create_rejects_request_body_actor(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/config/tool-sources",
        json={
            "source_id": "tool_brave_default",
            "name": "Brave Search Default",
            "source_type": "search_vendor",
            "provider": "brave_search",
            "tool_contract_ids": ["untrusted_web_search"],
            "credential_env_ref": "BRAVE_SEARCH_API_KEY",
            "params": {"timeout_seconds": 8, "default_max_results": 3},
            "actor": "spoofed-operator",
        },
    )

    assert response.status_code == 422


def test_tool_source_create_requires_edit_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.TOOL_SOURCE_VIEW},
    )

    response = client.post(
        "/api/config/tool-sources",
        json={
            "source_id": "tool_brave_default",
            "name": "Brave Search Default",
            "source_type": "search_vendor",
            "provider": "brave_search",
            "tool_contract_ids": ["untrusted_web_search"],
            "credential_env_ref": "BRAVE_SEARCH_API_KEY",
            "params": {"timeout_seconds": 8, "default_max_results": 3},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Operator lacks required permission: tool_source.edit"


def test_tool_source_create_accepts_operator_identity_boundary(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.TOOL_SOURCE_EDIT, OperatorPermission.TOOL_SOURCE_VIEW},
    )

    response = client.post(
        "/api/config/tool-sources",
        json={
            "source_id": "tool_brave_default",
            "name": "Brave Search Default",
            "source_type": "search_vendor",
            "provider": "brave_search",
            "tool_contract_ids": ["untrusted_web_search"],
            "credential_env_ref": "BRAVE_SEARCH_API_KEY",
            "params": {"timeout_seconds": 8, "default_max_results": 3},
        },
    )

    assert response.status_code == 200
    assert response.json()["source_id"] == "tool_brave_default"
    audit_payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "config" / "configuration_audit").glob("*.json"))
    ]
    assert audit_payloads[0]["operation"] == "created"
    assert audit_payloads[0]["actor"] == "test-operator"
    assert audit_payloads[0]["metadata"]["source_id"] == "tool_brave_default"


def test_tool_source_archive_requires_archive_permission(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    created = setup_client.post(
        "/api/config/tool-sources",
        json={
            "source_id": "tool_brave_default",
            "name": "Brave Search Default",
            "source_type": "search_vendor",
            "provider": "brave_search",
            "tool_contract_ids": ["untrusted_web_search"],
            "credential_env_ref": "BRAVE_SEARCH_API_KEY",
            "params": {"timeout_seconds": 8, "default_max_results": 3},
        },
    )
    assert created.status_code == 200
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.TOOL_SOURCE_VIEW},
    )

    response = client.post(
        "/api/config/tool-sources/tool_brave_default/archive",
        json={"reason": "Rotate vendor."},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Operator lacks required permission: tool_source.archive"


def test_tool_source_api_manages_dashboard_connection_lifecycle(tmp_path: Path) -> None:
    client = _client(tmp_path)

    created = client.post(
        "/api/config/tool-sources",
        json={
            "source_id": "tool_brave_default",
            "name": "Brave Search Default",
            "source_type": "search_vendor",
            "provider": "brave_search",
            "tool_contract_ids": ["untrusted_web_search"],
            "credential_env_ref": "BRAVE_SEARCH_API_KEY",
            "params": {"timeout_seconds": 8, "default_max_results": 3},
        },
    )
    listed = client.get("/api/config/tool-sources")
    updated = client.patch(
        "/api/config/tool-sources/tool_brave_default",
        json={
            "name": "Brave Search Production",
            "params": {"timeout_seconds": 12, "default_max_results": 4},
        },
    )
    archived = client.post(
        "/api/config/tool-sources/tool_brave_default/archive",
        json={"reason": "Rotate vendor."},
    )
    restored = client.post(
        "/api/config/tool-sources/tool_brave_default/restore",
        json={"reason": "Rollback vendor change."},
    )

    assert created.status_code == 200
    assert created.json()["credential_env_ref"] == "BRAVE_SEARCH_API_KEY"
    assert created.json()["config_revision"] == 1
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1
    assert updated.status_code == 200
    assert updated.json()["config_revision"] == 2
    assert updated.json()["params"]["timeout_seconds"] == 12
    assert archived.status_code == 200
    assert archived.json()["lifecycle_state"] == "ARCHIVED"
    assert restored.status_code == 200
    assert restored.json()["lifecycle_state"] == "ACTIVE"


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
        },
    )
    assert response.status_code == 200
    return response.json()


def test_create_http_json_knowledge_source_accepts_safe_remote_params(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_remote",
            "name": "Remote Policies",
            "provider": "http_json",
            "params": {
                "endpoint": "https://knowledge.example/retrieve",
                "timeout_seconds": 10,
                "top_k": 3,
                "header_env_refs": [
                    {
                        "name": "Authorization",
                        "value_env": "PA_KNOWLEDGE_TOKEN",
                        "prefix": "Bearer ",
                    }
                ],
                "response_mapping": {
                    "results": "/matches",
                    "content": "/text",
                    "score": "/score",
                    "citation": "/citation",
                },
            },
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["provider"] == "http_json"
    assert created["params"]["endpoint"] == "https://knowledge.example/retrieve"
    assert created["document_count"] == 0


def test_knowledge_source_read_requires_view_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(tmp_path, set())

    response = client.get("/api/config/knowledge-sources")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Operator lacks required permission: knowledge_source.view"
    )


def test_knowledge_source_create_rejects_request_body_actor(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_local_index",
            "name": "Local Index Policies",
            "provider": "local_index",
            "params": {},
            "actor": "spoofed-operator",
        },
    )

    assert response.status_code == 422


def test_knowledge_source_archive_rejects_request_body_actor(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_local_index",
            "name": "Local Index Policies",
            "provider": "local_index",
            "params": {},
        },
    )
    assert created.status_code == 200

    response = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": "No longer maintained.", "actor": "spoofed-operator"},
    )

    assert response.status_code == 422


def test_knowledge_source_create_requires_edit_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.KNOWLEDGE_SOURCE_VIEW},
    )

    response = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_local_index",
            "name": "Local Index Policies",
            "provider": "local_index",
            "params": {},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Operator lacks required permission: knowledge_source.edit"
    )


def test_knowledge_source_create_uses_operator_identity_for_audit(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {
            OperatorPermission.KNOWLEDGE_SOURCE_EDIT,
            OperatorPermission.KNOWLEDGE_SOURCE_VIEW,
        },
    )

    response = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_local_index",
            "name": "Local Index Policies",
            "provider": "local_index",
            "params": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["source_id"] == "ks_local_index"


def test_knowledge_source_publication_requires_publish_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {
            OperatorPermission.KNOWLEDGE_SOURCE_EDIT,
            OperatorPermission.KNOWLEDGE_SOURCE_VIEW,
        },
    )

    response = client.post(
        "/api/config/knowledge-sources/ks_local_index/publication/validate",
        json={"smoke_query": "policy"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Operator lacks required permission: knowledge_source.publish"
    )


def test_knowledge_source_archive_requires_archive_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {
            OperatorPermission.KNOWLEDGE_SOURCE_EDIT,
            OperatorPermission.KNOWLEDGE_SOURCE_VIEW,
        },
    )

    response = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": "No longer maintained."},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Operator lacks required permission: knowledge_source.archive"
    )


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
        },
    )


def _batch_upload(
    client: TestClient,
    *,
    source_id: str = "ks_local_index",
    documents: list[dict[str, object]] | None = None,
) -> object:
    payload_documents = documents or [
        {
            "filename": "first.md",
            "content_type": "text/markdown",
            "content_base64": base64.b64encode(b"# First\n").decode("ascii"),
        },
        {
            "filename": "second.md",
            "content_type": "text/markdown",
            "content_base64": base64.b64encode(b"# Second\n").decode("ascii"),
        },
    ]
    return client.post(
        f"/api/config/knowledge-sources/{source_id}/documents/batch",
        json={"documents": payload_documents},
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


def test_stage_quarantined_upload_preserves_unicode_filename(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    uploaded = _upload(
        client,
        filename="../理赔 条款.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4\nsample",
    )
    uploads = client.get("/api/config/knowledge-sources/ks_local_index/quarantined-uploads")

    assert uploaded.status_code == 200
    assert uploaded.json()["filename"] == "理赔_条款.pdf"
    assert uploads.json()["data"][0]["filename"] == "理赔_条款.pdf"


def test_knowledge_source_lifecycle_routes_archive_restore_eligibility_and_delete(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    missing_reason = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={},
    )
    blank_reason = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": " "},
    )
    active_eligibility = client.get(
        "/api/config/knowledge-sources/ks_local_index/deletion-eligibility"
    )
    active_delete = client.request(
        "DELETE",
        "/api/config/knowledge-sources/ks_local_index",
        json={"reason": "Created by mistake."},
    )
    archived = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": "No longer maintained."},
    )
    archived_eligibility = client.get(
        "/api/config/knowledge-sources/ks_local_index/deletion-eligibility"
    )
    restored = client.post(
        "/api/config/knowledge-sources/ks_local_index/restore",
        json={"reason": "Needed again."},
    )
    archived_again = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": "Created by mistake."},
    )
    deleted = client.request(
        "DELETE",
        "/api/config/knowledge-sources/ks_local_index",
        json={"reason": "Created by mistake."},
    )

    assert missing_reason.status_code == 422
    assert blank_reason.status_code == 400
    assert blank_reason.json()["detail"]["code"] == "PA_CONFIG_001"
    assert active_eligibility.status_code == 200
    assert active_eligibility.json()["eligible"] is False
    assert active_eligibility.json()["blockers"] == ["source_not_archived"]
    assert active_delete.status_code == 400
    assert active_delete.json()["detail"]["code"] == "PA_CONFIG_002"
    assert archived.status_code == 200
    assert archived.json()["lifecycle_state"] == "ARCHIVED"
    assert archived_eligibility.status_code == 200
    assert archived_eligibility.json()["eligible"] is True
    assert archived_eligibility.json()["blockers"] == []
    assert restored.status_code == 200
    assert restored.json()["lifecycle_state"] == "ACTIVE"
    assert archived_again.status_code == 200
    assert archived_again.json()["lifecycle_state"] == "ARCHIVED"
    assert deleted.status_code == 200
    assert deleted.json()["eligible"] is True
    assert client.get("/api/config/knowledge-sources/ks_local_index").status_code == 404


def test_validation_warns_and_publish_rejects_archived_shared_model_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    store = _configuration_store(client)
    monkeypatch.setenv("DEMO_MODEL_KEY", "demo-key")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    store.create_model_connection(
        connection_id="model_archived_answer",
        display_name="Archived Answer",
        provider="deterministic",
        model_identifier="demo",
        credential_ref=EnvironmentModelCredentialReference(name="DEMO_MODEL_KEY"),
        actor="operator",
    )
    store.archive_model_connection(
        connection_id="model_archived_answer",
        actor="operator",
        reason="Archive before publication.",
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer questions.",
        contract_bundle=ContractBundle(
            agent_yaml=f"""
name: enterprise_qa
purpose: "Answer questions."
workflow:
  runtime: langgraph
  template: enterprise_qa
package_knowledge_sources:
  - source_id: ks_local
    name: Local Knowledge
    provider: local_markdown
    params:
      path: {tmp_path / "knowledge"}
knowledge_bindings:
  - binding_id: kb_local
    source_ref:
      scope: package
      source_id: ks_local
retrieval:
  strategy: single_step
model:
  model_source: shared
  connection_id: model_archived_answer
policy:
  file: {tmp_path / "policy.yaml"}
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
audit:
  trace_path: {tmp_path / "runs" / "trace.jsonl"}
  receipt_path: {tmp_path / "runs" / "governance_receipt.md"}
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        actor="operator",
    )
    validation = client.post(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/validate",
        json={"question": "What is the policy?"},
    )

    assert validation.status_code == 200
    validation_body = validation.json()
    assert validation_body["warnings"] == [
        {
            "code": "model_connection_archived",
            "connection_id": "model_archived_answer",
            "role": "final_answer",
            "message": "Shared Model Connection is archived: model_archived_answer.",
        }
    ]
    assert validation_body["publish_blockers"] == [
        {
            "code": "archived_model_connection",
            "connection_id": "model_archived_answer",
            "role": "final_answer",
            "message": (
                "Publish is blocked while Shared Model Connection "
                "model_archived_answer is archived."
            ),
        }
    ]
    loaded = client.get(f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}")
    assert loaded.json()["validation_records"][0]["warnings"] == validation_body["warnings"]
    assert (
        loaded.json()["validation_records"][0]["publish_blockers"]
        == validation_body["publish_blockers"]
    )

    response = client.post(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/publish",
        json={"validation_run_id": validation_body["run_id"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PA_CONFIG_002"
    assert "model_archived_answer" in response.json()["detail"]["message"]


def test_fetch_config_draft_skills_projects_runtime_ordered_pack(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    store = _configuration_store(client)
    (tmp_path / "knowledge").mkdir()
    draft = store.create_draft(
        agent_id="skill_pack_agent",
        display_name="Skill Pack Agent",
        purpose="Configure stage-scoped skills.",
        contract_bundle=ContractBundle(
            agent_yaml=f"""
name: skill_pack_agent
purpose: "Configure stage-scoped skills."
workflow:
  runtime: langgraph
  template: react_enterprise_qa_v2
  stages:
    - id: plan
      prompt:
        business_context: "Base plan context."
        task_instructions:
          - "Use governed planning."
package_knowledge_sources:
  - source_id: ks_local
    name: Local Knowledge
    provider: local_markdown
    params:
      path: {tmp_path / "knowledge"}
knowledge_bindings:
  - binding_id: kb_local
    source_ref:
      scope: package
      source_id: ks_local
retrieval:
  strategy: agentic
  max_steps: 2
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: ./skills/claims.yaml
        default: true
react:
  max_steps: 2
  planner:
    provider: deterministic
    name: demo
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
            policy_yaml="""
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answers require evidence."
""",
            tools_yaml="tools: []\n",
            extra_files={
                "skills/claims.yaml": """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - "claim status"
stage_prompt_addenda:
  plan:
    business_context: "Claims stage context."
    task_instructions:
      - "Prefer retrieval before answering claim process questions."
  model_answer:
    output_preferences:
      - "Separate operator-facing answer from external wording."
knowledge_binding_refs:
  - kb_local
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission:
  min_confidence: 0.6
""",
                "knowledge/claims.md": "# Claims\nClaims require evidence.\n",
            },
        ),
        actor="operator",
    )

    response = client.get(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/skills"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["configuration_issues"] == []
    assert payload["addendum_slots"] == [
        {"stage_id": "plan", "stage_label": "Plan"},
        {"stage_id": "retrieval_review", "stage_label": "Retrieval Review"},
        {"stage_id": "tool_review", "stage_label": "Tool Review"},
        {"stage_id": "model_answer", "stage_label": "Model Answer"},
    ]
    pack = payload["packs"][0]
    assert pack["id"] == "claims_qa"
    assert pack["default"] is True
    assert pack["definition"] == "skills/claims.yaml"
    assert pack["routing_admission"]["intent_patterns"] == ["claim status"]
    assert pack["routing_admission"]["admission"]["min_confidence"] == 0.6
    assert pack["capability_refs"]["knowledge_binding_refs"] == ["kb_local"]
    assert pack["capability_refs"]["policy_rule_refs"] == [
        "answering.require_retrieval"
    ]
    stages = {stage["stage_id"]: stage for stage in pack["stage_addenda"]}
    assert set(stages) == {"plan", "retrieval_review", "tool_review", "model_answer"}
    assert stages["plan"]["configured"] is True
    assert stages["plan"]["prompt"]["business_context"] == "Claims stage context."
    assert stages["plan"]["prompt"]["task_instructions"] == [
        "Prefer retrieval before answering claim process questions."
    ]
    assert stages["plan"]["preview"]["merge_mode"] == "append"
    assert stages["plan"]["preview"]["business_context"] == (
        "Base plan context.\n\nClaims stage context."
    )
    assert stages["plan"]["preview"]["task_instructions"] == [
        "Use governed planning.",
        "Prefer retrieval before answering claim process questions.",
    ]
    assert stages["retrieval_review"]["configured"] is False
    assert pack["coverage"] == {
        "configured_stage_ids": ["plan", "model_answer"],
        "missing_stage_ids": ["retrieval_review", "tool_review"],
    }


def test_fetch_config_draft_skills_reports_missing_refs_without_blocking_list(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    store = _configuration_store(client)
    imported = client.post(
        "/api/config/agents/import",
        json={"manifest_path": "examples/agent_management_insurance_specialist/agent.yaml"},
    ).json()
    draft = store.get_draft(imported["agent_id"], imported["draft_id"])
    assert draft is not None
    raw_agent_yaml = yaml.safe_load(draft.contract_bundle.agent_yaml)
    raw_agent_yaml["knowledge_bindings"] = [
        binding
        for binding in raw_agent_yaml["knowledge_bindings"]
        if binding["binding_id"] != "general_insurance_knowledge"
    ]
    store.update_draft(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        actor="test-operator",
        contract_bundle=ContractBundle(
            agent_yaml=yaml.safe_dump(raw_agent_yaml, sort_keys=False),
            policy_yaml=draft.contract_bundle.policy_yaml,
            tools_yaml=draft.contract_bundle.tools_yaml,
            extra_files=draft.contract_bundle.extra_files,
            advanced_fields=draft.contract_bundle.advanced_fields,
        ),
    )

    response = client.get(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/skills"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["configuration_issues"][0]["code"] == "PA_CONFIG_002"
    assert "unknown Business Flow Skill Pack knowledge_binding_refs" in (
        payload["configuration_issues"][0]["message"]
    )
    assert "general_insurance_knowledge" in payload["configuration_issues"][0]["message"]
    pack = next(
        item for item in payload["packs"] if item["id"] == "general_insurance_specialist"
    )
    assert "general_insurance_knowledge" in pack["capability_refs"]["knowledge_binding_refs"]
    repaired = client.patch(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}"
        "/skills/business-flows/general_insurance_specialist",
        json={"knowledge_binding_refs": []},
    )

    assert repaired.status_code == 200
    assert repaired.json()["configuration_issues"] == []


def test_fetch_config_draft_skills_handles_template_without_addendum_slots(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    response = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/skills"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["addendum_slots"] == []
    assert payload["packs"] == []


def test_create_config_draft_skill_pack_writes_package_local_definition(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    store = _configuration_store(client)
    draft = store.create_draft(
        agent_id="skill_pack_agent",
        display_name="Skill Pack Agent",
        purpose="Configure stage-scoped skills.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: skill_pack_agent
purpose: "Configure stage-scoped skills."
workflow:
  runtime: langgraph
  template: react_enterprise_qa_v2
package_knowledge_sources: []
knowledge_bindings: []
retrieval:
  strategy: agentic
  max_steps: 2
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
react:
  max_steps: 2
  planner:
    provider: deterministic
    name: demo
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        actor="operator",
    )

    response = client.post(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/skills/business-flows",
        json={
            "id": "claims_qa",
            "label": "Claims QA",
            "description": "Governed routing addenda for claim questions.",
            "intent_patterns": ["claim status"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert [pack["id"] for pack in payload["packs"]] == ["claims_qa"]
    assert payload["packs"][0]["definition"] == "skills/claims_qa.yaml"
    contract = client.get(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/contract"
    ).json()
    agent_yaml = yaml.safe_load(contract["agent_yaml"])
    assert agent_yaml["capabilities"]["skills"] == {
        "enabled": True,
        "business_flows": [
            {
                "id": "claims_qa",
                "definition": "./skills/claims_qa.yaml",
            }
        ],
    }
    assert "skills/claims_qa.yaml" in contract["extra_files"]
    definition = yaml.safe_load(contract["extra_files"]["skills/claims_qa.yaml"])
    assert definition["schema_version"] == "business_flow_skill_pack.v1"
    assert definition["stage_prompt_addenda"] == {}
    assert definition["intent_patterns"] == ["claim status"]


def test_update_config_draft_skill_pack_rewrites_definition(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    store = _configuration_store(client)
    draft = store.create_draft(
        agent_id="skill_pack_agent",
        display_name="Skill Pack Agent",
        purpose="Configure stage-scoped skills.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: skill_pack_agent
purpose: "Configure stage-scoped skills."
workflow:
  runtime: langgraph
  template: react_enterprise_qa_v2
package_knowledge_sources: []
knowledge_bindings: []
retrieval:
  strategy: agentic
  max_steps: 2
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: ./skills/claims.yaml
react:
  max_steps: 2
  planner:
    provider: deterministic
    name: demo
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
            extra_files={
                "skills/claims.yaml": """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - "claim status"
intent_taxonomy_refs: []
stage_prompt_addenda: {}
knowledge_binding_refs: []
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission: {}
""",
            },
        ),
        actor="operator",
    )

    response = client.patch(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/skills/business-flows/claims_qa",
        json={
            "label": "Claims QA Updated",
            "intent_patterns": ["claim status", "claim documents"],
            "stage_prompt_addenda": {
                "plan": {
                    "task_instructions": [
                        "Prefer retrieval before answering claim questions."
                    ],
                }
            },
            "admission": {"min_confidence": 0.7},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    pack = payload["packs"][0]
    assert pack["label"] == "Claims QA Updated"
    assert pack["routing_admission"]["intent_patterns"] == [
        "claim status",
        "claim documents",
    ]
    assert pack["routing_admission"]["admission"]["min_confidence"] == 0.7
    stages = {stage["stage_id"]: stage for stage in pack["stage_addenda"]}
    assert stages["plan"]["configured"] is True
    assert stages["plan"]["prompt"]["task_instructions"] == [
        "Prefer retrieval before answering claim questions."
    ]
    contract = client.get(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/contract"
    ).json()
    definition = yaml.safe_load(contract["extra_files"]["skills/claims.yaml"])
    assert definition["label"] == "Claims QA Updated"
    assert definition["intent_patterns"] == ["claim status", "claim documents"]
    assert definition["stage_prompt_addenda"] == {
        "plan": {
            "task_instructions": [
                "Prefer retrieval before answering claim questions."
            ],
            "output_preferences": [],
        }
    }


def test_delete_config_draft_skill_pack_removes_binding_and_definition(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    store = _configuration_store(client)
    draft = store.create_draft(
        agent_id="skill_pack_agent",
        display_name="Skill Pack Agent",
        purpose="Configure stage-scoped skills.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: skill_pack_agent
purpose: "Configure stage-scoped skills."
workflow:
  runtime: langgraph
  template: react_enterprise_qa_v2
package_knowledge_sources: []
knowledge_bindings: []
retrieval:
  strategy: agentic
  max_steps: 2
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: ./skills/claims.yaml
react:
  max_steps: 2
  planner:
    provider: deterministic
    name: demo
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
            extra_files={
                "skills/claims.yaml": """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns: []
intent_taxonomy_refs: []
stage_prompt_addenda: {}
knowledge_binding_refs: []
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission: {}
""",
            },
        ),
        actor="operator",
    )

    response = client.delete(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/skills/business-flows/claims_qa"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["packs"] == []
    contract = client.get(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/contract"
    ).json()
    agent_yaml = yaml.safe_load(contract["agent_yaml"])
    assert agent_yaml["capabilities"]["skills"] == {
        "enabled": False,
        "business_flows": [],
    }
    assert "skills/claims.yaml" not in contract["extra_files"]


def test_knowledge_source_routes_map_invalid_source_id_to_structured_error(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    detail = client.get("/api/config/knowledge-sources/%20bad")
    documents = client.get("/api/config/knowledge-sources/%20bad/documents")

    assert detail.status_code == 400
    assert detail.json()["detail"]["code"] == "PA_CONFIG_001"
    assert documents.status_code == 400
    assert documents.json()["detail"]["code"] == "PA_CONFIG_001"


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    (
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/documents",
            {
                "filename": "policy.md",
                "content_type": "text/markdown",
                "content_base64": base64.b64encode(b"# Policy\n").decode("ascii"),
            },
        ),
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/documents/batch",
            {
                "documents": [
                    {
                        "filename": "policy.md",
                        "content_type": "text/markdown",
                        "content_base64": base64.b64encode(b"# Policy\n").decode("ascii"),
                    }
                ],
            },
        ),
        (
            "PATCH",
            "/api/config/knowledge-sources/ks_local_index/documents/doc_missing/routing-metadata",
            {"routing_metadata": {"title": "Policy"}},
        ),
        (
            "GET",
            "/api/config/knowledge-sources/ks_local_index/candidate-snapshot",
            None,
        ),
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/validate-foundation",
            {},
        ),
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
            {"validation_id": "ksvalidation_missing"},
        ),
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/publication/validate",
            {"smoke_query": "policy"},
        ),
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/publication/publish",
            {
                "validation_id": "kspubval_missing",
                "change_note": "Publish policy.",
            },
        ),
    ),
)
def test_archived_knowledge_source_rejects_publication_bound_routes(
    tmp_path: Path,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    archived = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": "No longer maintained."},
    )
    assert archived.status_code == 200

    response = client.request(method, path, json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Knowledge Source is archived."


def test_candidate_validation_and_freeze_management_api_lifecycle(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    _write_compatible_ready_document(client)

    candidate = client.get("/api/config/knowledge-sources/ks_local_index/candidate-snapshot")
    validation = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/validate-foundation",
        json={},
    )
    assert validation.status_code == 200
    frozen = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
        json={"validation_id": validation.json()["validation_id"]},
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


def test_source_publication_validation_and_publish_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_store_module,
        "validate_local_index_publication_smoke",
        lambda **_: LocalIndexPublicationSmokeResult(candidate_count=1, citation_count=1),
    )
    client = _client(tmp_path)
    _create_local_index_source(client)
    _write_compatible_ready_document(client)
    foundation = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/validate-foundation",
        json={},
    )
    frozen = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
        json={"validation_id": foundation.json()["validation_id"]},
    )

    validation = client.post(
        "/api/config/knowledge-sources/ks_local_index/publication/validate",
        json={"smoke_query": "What does the policy require?"},
    )
    published = client.post(
        "/api/config/knowledge-sources/ks_local_index/publication/publish",
        json={
            "validation_id": validation.json()["validation_id"],
            "change_note": "Initial production publication.",
        },
    )
    source = client.get("/api/config/knowledge-sources/ks_local_index")
    validations = client.get("/api/config/knowledge-sources/ks_local_index/publication-validations")
    publications = client.get("/api/config/knowledge-sources/ks_local_index/publications")

    assert frozen.status_code == 200
    assert validation.status_code == 200
    assert validation.json()["status"] == "passed"
    assert validation.json()["snapshot_id"] == frozen.json()["snapshot_id"]
    assert published.status_code == 200
    assert published.json()["snapshot_id"] == frozen.json()["snapshot_id"]
    assert published.json()["change_note"] == "Initial production publication."
    assert source.json()["published_snapshot_id"] == frozen.json()["snapshot_id"]
    assert source.json()["publication_count"] == 1
    assert validations.json() == {"data": [validation.json()], "meta": {"total": 1}}
    assert publications.json() == {"data": [published.json()], "meta": {"total": 1}}


def test_http_json_source_publication_validation_and_publish_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http_json_module,
        "_send_http_json_request",
        lambda request: {
            "protocol_version": "proof-agent.remote-retrieval.v1",
            "results": [
                {
                    "content": "Remote policy evidence.",
                    "score": 0.92,
                    "citation": "https://knowledge.example/policies#remote",
                }
            ],
        },
    )
    client = _client(tmp_path)
    created = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_remote",
            "name": "Remote Policies",
            "provider": "http_json",
            "params": {
                "endpoint": "https://knowledge.example/retrieve",
                "top_k": 2,
            },
        },
    )

    validation = client.post(
        "/api/config/knowledge-sources/ks_remote/publication/validate",
        json={"smoke_query": "What does the remote policy require?"},
    )
    published = client.post(
        "/api/config/knowledge-sources/ks_remote/publication/publish",
        json={
            "validation_id": validation.json()["validation_id"],
            "change_note": "Publish remote policy API.",
        },
    )
    source = client.get("/api/config/knowledge-sources/ks_remote")
    validations = client.get("/api/config/knowledge-sources/ks_remote/publication-validations")
    publications = client.get("/api/config/knowledge-sources/ks_remote/publications")

    assert created.status_code == 200
    assert validation.status_code == 200
    assert validation.json()["resource_kind"] == "remote_config"
    assert validation.json()["resource_id"].startswith("ksremote_")
    assert validation.json()["snapshot_id"] is None
    assert validation.json()["candidate_count"] == 1
    assert validation.json()["citation_count"] == 1
    assert published.status_code == 200
    assert published.json()["resource_kind"] == "remote_config"
    assert published.json()["resource_id"] == validation.json()["resource_id"]
    assert published.json()["snapshot_id"] is None
    assert published.json()["document_count"] == 0
    assert source.json()["published_snapshot_id"] == validation.json()["resource_id"]
    assert source.json()["publication_count"] == 1
    assert validations.json() == {"data": [validation.json()], "meta": {"total": 1}}
    assert publications.json() == {"data": [published.json()], "meta": {"total": 1}}


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


def test_batch_upload_stages_all_documents_in_one_response(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    uploaded = _batch_upload(client)

    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert payload["meta"] == {"total": 2}
    assert [upload["filename"] for upload in payload["data"]] == ["first.md", "second.md"]
    assert [upload["state"] for upload in payload["data"]] == ["queued", "queued"]
    store_uploads = _configuration_store(client).list_quarantined_knowledge_uploads(
        "ks_local_index"
    )
    assert [upload.filename for upload in store_uploads] == ["first.md", "second.md"]


def test_batch_upload_rejects_invalid_member_without_staging_any_file(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)

    uploaded = _batch_upload(
        client,
        documents=[
            {
                "filename": "first.md",
                "content_type": "text/markdown",
                "content_base64": base64.b64encode(b"# First\n").decode("ascii"),
            },
            {
                "filename": "broken.md",
                "content_type": "text/markdown",
                "content_base64": "not-valid-base64",
            },
        ],
    )

    assert uploaded.status_code == 400
    assert _configuration_store(client).list_quarantined_knowledge_uploads("ks_local_index") == []


def test_batch_upload_reserves_full_batch_capacity_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_store_module, "KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY", 2)
    client = _client(tmp_path)
    _create_local_index_source(client)
    store = _configuration_store(client)
    store.add_knowledge_document(
        source_id="ks_local_index",
        filename="existing.md",
        content_type="text/markdown",
        content=b"# Existing\n",
        state="ready",
        actor="operator",
    )

    uploaded = _batch_upload(client)

    assert uploaded.status_code == 503
    assert uploaded.json()["detail"]["code"] == "PA_INGESTION_004"
    assert store.list_quarantined_knowledge_uploads("ks_local_index") == []


def test_update_document_routing_metadata_updates_candidate_snapshot(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    document = _write_compatible_ready_document(client)

    updated = client.patch(
        f"/api/config/knowledge-sources/ks_local_index/documents/{document.document_id}/routing-metadata",
        json={
            "routing_metadata": {
                "title": "Claims Policy",
                "description": "Inpatient claim rules",
                "tags": ["claims", "inpatient"],
                "document_type": "policy",
            },
        },
    )
    candidate = client.get("/api/config/knowledge-sources/ks_local_index/candidate-snapshot")

    assert updated.status_code == 200
    assert updated.json()["routing_metadata"] == {
        "title": "Claims Policy",
        "description": "Inpatient claim rules",
        "tags": ["claims", "inpatient"],
        "document_type": "policy",
    }
    assert candidate.status_code == 200
    assert (
        candidate.json()["included_documents"][0]["routing_metadata"]
        == updated.json()["routing_metadata"]
    )


def test_update_document_routing_metadata_rejects_unknown_field(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client)
    document = _write_compatible_ready_document(client)

    updated = client.patch(
        f"/api/config/knowledge-sources/ks_local_index/documents/{document.document_id}/routing-metadata",
        json={
            "routing_metadata": {"unknown": "claims"},
        },
    )

    assert updated.status_code == 400
    assert updated.json()["detail"]["code"] == "PA_CONFIG_001"


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


def test_retry_failed_ingestion_job_endpoint_returns_job_to_queue(tmp_path: Path) -> None:
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
    claimed_upload = store.claim_next_quarantined_knowledge_upload()
    assert claimed_upload is not None
    assert claimed_upload.claim_token is not None
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )
    document, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed_upload.claim_token,
    )
    claimed_job = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    assert claimed_job is not None
    assert claimed_job.claim_token is not None
    store.fail_knowledge_ingestion_job(
        source_id=job.source_id,
        job_id=job.job_id,
        claim_token=claimed_job.claim_token,
        error_code="PA_INGESTION_001",
        error_message="Missing model credential environment variable(s): DEEPSEEK_API_KEY",
    )

    response = client.post(
        f"/api/config/knowledge-sources/ks_local_index/ingestion-jobs/{job.job_id}/retry",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "queued"
    assert response.json()["error_code"] is None
    updated_document = store.get_knowledge_document(
        source_id=document.source_id,
        document_id=document.document_id,
    )
    assert updated_document is not None
    assert updated_document.state == "queued"
    assert updated_document.error_code is None


def test_retry_ingestion_job_endpoint_rejects_non_failed_job(tmp_path: Path) -> None:
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
    claimed_upload = store.claim_next_quarantined_knowledge_upload()
    assert claimed_upload is not None
    assert claimed_upload.claim_token is not None
    parsed = parse_quarantined_upload(
        store.quarantined_knowledge_upload_bytes_path(upload),
        filename=upload.filename,
        content_type=upload.content_type,
    )
    _, job = store.accept_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
        parsed_document=parsed,
        claim_token=claimed_upload.claim_token,
    )

    response = client.post(
        f"/api/config/knowledge-sources/ks_local_index/ingestion-jobs/{job.job_id}/retry",
        json={},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "PA_INGESTION_004"
    assert "cannot be retried from state queued" in response.json()["detail"]["message"]


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
        json={"validation_id": "ksvalidation_missing"},
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
        json={},
    )
    assert validation.status_code == 200
    store = _configuration_store(client)
    store._advance_source_draft_version_unlocked(
        "ks_local_index",
        updated_at="2026-06-02T01:00:00Z",
    )

    frozen = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
        json={"validation_id": validation.json()["validation_id"]},
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
            {},
        ),
        (
            "POST",
            "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
            "freeze_candidate_knowledge_source_snapshot",
            {"validation_id": "ksvalidation_001"},
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
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == f"Unsupported knowledge provider: {provider}"


def test_bind_shared_knowledge_source_to_agent_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    _publish_local_index_source(client, monkeypatch)

    bound = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/knowledge-bindings",
        json={
            "source_id": "ks_local_index",
            "alias": "policies",
            "failure_mode": "advisory",
            "fusion_weight": 0.75,
            "top_k": 3,
        },
    )
    loaded = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )

    assert bound.status_code == 200
    parsed = yaml.safe_load(bound.json()["agent_yaml"])
    assert "knowledge_sources" not in parsed
    assert parsed["package_knowledge_sources"]
    assert any(
        binding["source_ref"]["scope"] == "package" for binding in parsed["knowledge_bindings"]
    )
    assert any(
        binding["source_ref"] == {"scope": "shared", "source_id": "ks_local_index"}
        and binding["alias"] == "policies"
        and binding["failure_mode"] == "advisory"
        and binding["fusion_weight"] == 0.75
        and binding["top_k"] == 3
        for binding in parsed["knowledge_bindings"]
    )
    assert loaded.json()["agent_yaml"] == bound.json()["agent_yaml"]


def test_update_model_contract_after_binding_shared_source_preserves_package_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    _publish_local_index_source(client, monkeypatch)
    bound = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/knowledge-bindings",
        json={
            "source_id": "ks_local_index",
            "failure_mode": "required",
            "fusion_weight": 1.0,
        },
    )
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    ).json()
    raw_agent_yaml = yaml.safe_load(contract["agent_yaml"])
    raw_agent_yaml["model"]["name"] = "demo-updated"

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract",
        json={"agent_yaml": yaml.safe_dump(raw_agent_yaml, sort_keys=False)},
    )

    assert bound.status_code == 200
    assert updated.status_code == 200
    parsed = yaml.safe_load(updated.json()["agent_yaml"])
    assert parsed["model"]["name"] == "demo-updated"
    assert parsed["package_knowledge_sources"]
    assert any(
        binding["source_ref"]["scope"] == "package" for binding in parsed["knowledge_bindings"]
    )
    assert any(
        binding["source_ref"]["scope"] == "shared" for binding in parsed["knowledge_bindings"]
    )


def test_update_model_contract_preserves_existing_mixed_package_and_shared_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    _publish_local_index_source(client, monkeypatch)
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    ).json()
    raw_agent_yaml = yaml.safe_load(contract["agent_yaml"])
    raw_agent_yaml["knowledge_bindings"].append(
        {
            "binding_id": "ks_local_index_binding",
            "source_ref": {"scope": "shared", "source_id": "ks_local_index"},
            "failure_mode": "required",
            "fusion_weight": 1.0,
        }
    )
    raw_agent_yaml["model"]["name"] = "demo-updated"

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract",
        json={"agent_yaml": yaml.safe_dump(raw_agent_yaml, sort_keys=False)},
    )

    assert updated.status_code == 200
    parsed = yaml.safe_load(updated.json()["agent_yaml"])
    assert parsed["model"]["name"] == "demo-updated"
    assert parsed["package_knowledge_sources"]
    assert any(
        binding["source_ref"]["scope"] == "package" for binding in parsed["knowledge_bindings"]
    )
    assert any(
        binding["source_ref"]["scope"] == "shared" for binding in parsed["knowledge_bindings"]
    )


def test_bind_shared_knowledge_source_keeps_business_flow_skill_refs_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = client.post(
        "/api/config/agents/import",
        json={"manifest_path": "examples/agent_management_insurance_specialist/agent.yaml"},
    ).json()
    _publish_local_index_source(client, monkeypatch)

    bound = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/knowledge-bindings",
        json={
            "source_id": "ks_local_index",
            "alias": "supplemental",
            "failure_mode": "advisory",
            "fusion_weight": 0.5,
        },
    )
    skills = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/skills"
    )

    assert bound.status_code == 200
    parsed = yaml.safe_load(bound.json()["agent_yaml"])
    binding_ids = {binding["binding_id"] for binding in parsed["knowledge_bindings"]}
    assert "general_insurance_knowledge" in binding_ids
    assert "ks_local_index_binding" in binding_ids
    assert skills.status_code == 200
    assert {
        pack["id"] for pack in skills.json()["packs"]
    } >= {"general_insurance_specialist", "agent_basic_law_consultation"}


def test_bind_unpublished_knowledge_source_to_agent_draft_is_rejected(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    _create_local_index_source(client)

    bound = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/knowledge-bindings",
        json={"source_id": "ks_local_index"},
    )

    assert bound.status_code == 400
    assert "published" in bound.text


def test_bind_archived_knowledge_source_to_agent_draft_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    _publish_local_index_source(client, monkeypatch)
    archived = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": "No longer maintained."},
    )

    bound = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/knowledge-bindings",
        json={"source_id": "ks_local_index"},
    )

    assert archived.status_code == 200
    assert bound.status_code == 400
    assert bound.json()["detail"] == "Knowledge Source is archived."


def test_validate_draft_with_archived_shared_source_returns_structured_400(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    _publish_local_index_source(client, monkeypatch)
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    ).json()
    raw_agent_yaml = yaml.safe_load(contract["agent_yaml"])
    raw_agent_yaml["package_knowledge_sources"] = []
    raw_agent_yaml["knowledge_bindings"] = [
        {
            "binding_id": "kb_shared",
            "source_ref": {"scope": "shared", "source_id": "ks_local_index"},
            "failure_mode": "required",
            "fusion_weight": 1.0,
        }
    ]
    updated_contract = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract",
        json={
            "agent_yaml": yaml.safe_dump(raw_agent_yaml, sort_keys=False),
        },
    )
    archived = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": "No longer maintained."},
    )

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={"question": "Can I use this source?"},
    )

    assert updated_contract.status_code == 200
    assert archived.status_code == 200
    assert validation.status_code == 400
    assert validation.json()["detail"]["code"] == "PA_CONFIG_002"
    assert "archived" in validation.json()["detail"]["message"]


def test_update_contract_view_rejects_archived_shared_source_binding_without_persisting(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    created = _create_local_index_source(client)
    archived = client.post(
        "/api/config/knowledge-sources/ks_local_index/archive",
        json={"reason": "No longer maintained."},
    )
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    ).json()
    raw_agent_yaml = yaml.safe_load(contract["agent_yaml"])
    raw_agent_yaml["package_knowledge_sources"] = []
    raw_agent_yaml["knowledge_bindings"] = [
        {
            "binding_id": "kb_archived_raw",
            "source_ref": {"scope": "shared", "source_id": "ks_local_index"},
            "failure_mode": "required",
            "fusion_weight": 1.0,
        }
    ]
    updated_yaml = yaml.safe_dump(raw_agent_yaml, sort_keys=False)

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract",
        json={"agent_yaml": updated_yaml},
    )
    loaded = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )

    assert created["lifecycle_state"] == "ACTIVE"
    assert archived.status_code == 200
    assert updated.status_code == 400
    assert updated.json()["detail"]["code"] == "PA_CONFIG_002"
    assert "archived" in updated.json()["detail"]["message"]
    assert "kb_archived_raw" not in loaded.json()["agent_yaml"]


def _publish_local_index_source(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_store_module,
        "validate_local_index_publication_smoke",
        lambda **_: LocalIndexPublicationSmokeResult(candidate_count=1, citation_count=1),
    )
    _create_local_index_source(
        client,
        params={"ingestion_model": {"provider": "deterministic", "name": "routing"}},
    )
    _write_compatible_ready_document(client)
    foundation = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/validate-foundation",
        json={},
    )
    assert foundation.status_code == 200
    frozen = client.post(
        "/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze",
        json={"validation_id": foundation.json()["validation_id"]},
    )
    assert frozen.status_code == 200
    validation = client.post(
        "/api/config/knowledge-sources/ks_local_index/publication/validate",
        json={"smoke_query": "What does the policy require?"},
    )
    assert validation.status_code == 200
    published = client.post(
        "/api/config/knowledge-sources/ks_local_index/publication/publish",
        json={
            "validation_id": validation.json()["validation_id"],
            "change_note": "Ready for Agent binding.",
        },
    )
    assert published.status_code == 200


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
        json={"agent_yaml": updated_yaml},
    )

    assert updated.status_code == 200
    assert "  top_k: 1" in updated.json()["agent_yaml"]
    loaded = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )
    assert "  top_k: 1" in loaded.json()["agent_yaml"]


def test_update_contract_view_rejects_removed_skill_pack_knowledge_binding(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    draft = client.post(
        "/api/config/agents/import",
        json={"manifest_path": "examples/agent_management_insurance_specialist/agent.yaml"},
    ).json()
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    ).json()
    raw_agent_yaml = yaml.safe_load(contract["agent_yaml"])
    raw_agent_yaml["knowledge_bindings"] = [
        binding
        for binding in raw_agent_yaml["knowledge_bindings"]
        if binding["binding_id"] != "general_insurance_knowledge"
    ]

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract",
        json={"agent_yaml": yaml.safe_dump(raw_agent_yaml, sort_keys=False)},
    )

    assert updated.status_code == 400
    assert updated.json()["detail"]["code"] == "PA_CONFIG_002"
    assert "unknown Business Flow Skill Pack knowledge_binding_refs" in (
        updated.json()["detail"]["message"]
    )
    assert "general_insurance_knowledge" in updated.json()["detail"]["message"]


def test_update_react_contract_view_preserves_reviewer_usage_params(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa(client)
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    ).json()
    raw_agent_yaml = yaml.safe_load(contract["agent_yaml"])

    assert "timeout_seconds" not in raw_agent_yaml["review"]["subagent"]
    assert "max_output_tokens" not in raw_agent_yaml["review"]["subagent"]
    assert raw_agent_yaml["review"]["subagent"]["params"]["timeout_seconds"] == 5
    assert raw_agent_yaml["review"]["subagent"]["params"]["max_output_tokens"] == 500

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract",
        json={"agent_yaml": contract["agent_yaml"]},
    )

    assert updated.status_code == 200


def test_workflow_template_descriptor_lists_stages(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/config/workflow-templates/react_enterprise_qa")

    assert response.status_code == 200
    body = response.json()
    assert body["descriptor_version"] == "react_enterprise_qa.v1"
    assert body["stages"][0]["id"] == "plan"
    assert body["stages"][0]["successors"] == [
        "clarification",
        "retrieval_review",
        "tool_review",
        "response",
    ]


def test_update_workflow_stages_persists_valid_stage_config(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa(client)

    response = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-stages",
        json={
            "template_descriptor_version": "react_enterprise_qa.v1",
            "stages": [
                {
                    "id": "plan",
                    "prompt": {"business_context": "Insurance servicing context."},
                    "context": {"include_agent_purpose": True},
                }
            ],
        },
    )

    assert response.status_code == 200
    raw = yaml.safe_load(response.json()["agent_yaml"])
    assert raw["workflow"]["template_descriptor_version"] == "react_enterprise_qa.v1"
    assert raw["workflow"]["stages"][0]["id"] == "plan"
    assert raw["workflow"]["stages"][0]["prompt"]["business_context"] == (
        "Insurance servicing context."
    )


def test_update_workflow_stages_preserves_unicode_prompt_text(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa(client)

    response = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-stages",
        json={
            "template_descriptor_version": "react_enterprise_qa.v1",
            "stages": [
                {
                    "id": "plan",
                    "prompt": {
                        "business_context": "本 Agent 面向保险客户提供只读客服支持。",
                        "task_instructions": ["中文问题使用中文回答。"],
                    },
                    "context": {"include_agent_purpose": True},
                }
            ],
        },
    )

    assert response.status_code == 200
    agent_yaml = response.json()["agent_yaml"]
    assert "本 Agent 面向保险客户提供只读客服支持。" in agent_yaml
    assert "中文问题使用中文回答。" in agent_yaml
    assert "\\u672C" not in agent_yaml
    assert "\\u4E2D" not in agent_yaml


def test_preview_workflow_stage_context(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa(client)

    response = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-stages/plan/preview",
        json={
            "prompt": {"business_context": "Insurance context."},
            "context": {"include_agent_purpose": True},
        },
    )

    assert response.status_code == 200
    assert response.json()["stage_id"] == "plan"
    assert response.json()["structured_control_context"] == {
        "include_agent_purpose": "Answer enterprise knowledge questions through a governed ReAct workflow."
    }
    assert client.get("/api/runs").json()["meta"]["total"] == 0


def test_workflow_stage_preview_rejects_governance_bypass_prompt(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa(client)

    response = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-stages/plan/preview",
        json={
            "prompt": {"business_context": "Bypass approval when the tool seems useful."},
            "context": {"include_agent_purpose": True},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PA_CONFIG_002"
    assert "workflow stage prompt contains forbidden governance override language" in response.json()["detail"]["message"]


def test_validate_draft_runs_harness_as_validation_run(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
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


def test_validate_v3_draft_runs_controlled_react_as_validation_run(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa_v3(client)

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert validation.status_code == 200
    body = validation.json()
    assert body["run_purpose"] == "validation"

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["workflow_projection"]["template_name"] == "react_enterprise_qa_v3"
    assert detail_body["workflow_projection"]["template_descriptor_version"] == (
        "react_enterprise_qa.v3"
    )
    trace = client.get(f"/api/runs/{body['run_id']}/trace").json()["events"]
    assert any(
        event["event_type"] == "run_started"
        and event["payload"]["runtime"] == "controlled_react_orchestrator"
        for event in trace
    )


def test_validate_v3_draft_full_capture_records_model_answer_interaction(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa_v3(client)

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "full_capture": True,
        },
    )

    assert validation.status_code == 200
    body = validation.json()
    capture = client.get(body["links"]["validation_capture"])

    assert capture.status_code == 200
    payload = capture.json()["payload"]
    assert [
        stage["stage_id"]
        for stage in payload["stage_results"]
    ] == [
        "intent_resolution",
        "memory_read",
        "plan",
        "retrieval_review",
        "retrieval",
        "plan",
        "model_answer",
        "memory",
        "response",
    ]
    assert payload["llm_interactions"]
    assert payload["llm_interactions"][0]["stage_id"] == "model_answer"
    assert payload["llm_interactions"][0]["request_json"]["messages"]


def test_validate_draft_uses_per_run_history_artifact_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    captured: dict[str, Path] = {}

    def fake_execute_agent_package_run(request: Any) -> RunResult:
        run_id = str(request.run_id)
        runs_dir = Path(request.runs_dir)
        captured["runs_dir"] = runs_dir
        runs_dir.mkdir(parents=True, exist_ok=True)
        trace_path = runs_dir / "trace.jsonl"
        receipt_path = runs_dir / "governance_receipt.md"
        trace_path.write_text(
            json.dumps({"event_type": "run_started", "run_id": run_id}) + "\n",
            encoding="utf-8",
        )
        receipt_path.write_text("# Receipt\n", encoding="utf-8")
        request.store.save_run_artifacts(
            run_id,
            trace_source=trace_path,
            receipt_source=receipt_path,
            question=str(request.question),
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            run_purpose=request.run_purpose,
            agent_id=request.agent_id,
            draft_id=request.draft_id,
        )
        return RunResult(
            final_output="ok",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            trace_path=trace_path,
            receipt_path=receipt_path,
        )

    monkeypatch.setattr(
        configuration_api_module,
        "execute_agent_package_run",
        fake_execute_agent_package_run,
    )

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={"question": "What is the reimbursement rule for travel meals?"},
    )

    assert validation.status_code == 200
    run_id = validation.json()["run_id"]
    expected_dir = tmp_path / "history" / run_id
    assert captured["runs_dir"] == expected_dir
    assert (expected_dir / "trace.jsonl").exists()
    assert not (tmp_path / "latest" / "trace.jsonl").exists()


def test_validation_run_defaults_to_summary_only_trace_capture(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert validation.status_code == 200
    body = validation.json()
    assert body["trace_capture"] == {
        "mode": "summary_only",
        "validation_capture": None,
    }
    assert set(body["links"]) == {"run_detail", "trace", "receipt"}

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["validation_capture_id"] is None


def test_validation_run_full_capture_records_gated_v2_artifact(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa(client)
    update = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-stages",
        json={
            "template_descriptor_version": "react_enterprise_qa.v1",
            "stages": [
                {
                    "id": "plan",
                    "prompt": {"business_context": "Insurance servicing context."},
                    "context": {"include_agent_purpose": True},
                }
            ],
        },
    )
    assert update.status_code == 200

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "full_capture": True,
            "retain_for_audit": True,
        },
    )

    assert validation.status_code == 200
    body = validation.json()
    assert body["trace_capture"]["mode"] == "full_capture"
    artifact = body["trace_capture"]["validation_capture"]
    assert artifact["capture_id"].startswith("vcap_")
    assert artifact["run_id"] == body["run_id"]
    assert artifact["draft_id"] == draft["draft_id"]
    assert artifact["retention_class"] == "sensitive_validation_capture"
    assert artifact["retain_for_audit"] is True
    assert body["links"]["validation_capture"] == (
        f"/api/runs/{body['run_id']}/validation-capture"
    )

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["validation_capture_id"] == artifact["capture_id"]
    loaded = client.get(f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}")
    assert loaded.status_code == 200
    assert loaded.json()["validation_records"][0]["validation_capture_id"] == artifact["capture_id"]

    capture = client.get(body["links"]["validation_capture"])
    assert capture.status_code == 200
    capture_body = capture.json()
    assert capture_body["metadata"]["capture_id"] == artifact["capture_id"]
    payload = capture_body["payload"]
    assert payload["capture_contract_version"] == "validation_capture.v2"
    assert set(payload) == {
        "capture_contract_version",
        "source",
        "stage_prompt_values",
        "context_configuration",
        "context_applications",
        "stage_results",
        "failure_diagnostics",
        "llm_interactions",
        "result_summary",
        "exclusions",
    }
    assert payload["source"]["run_id"] == body["run_id"]
    assert payload["source"]["draft_id"] == draft["draft_id"]
    assert payload["source"]["template_name"] == "react_enterprise_qa"
    assert payload["stage_prompt_values"]
    assert payload["stage_prompt_values"][0]["stage_label"]
    assert payload["context_configuration"]
    assert payload["context_applications"]
    assert payload["stage_results"]
    assert payload["failure_diagnostics"] == []
    assert payload["llm_interactions"]
    assert payload["llm_interactions"][0]["stage_id"] == "model_answer"
    assert payload["llm_interactions"][0]["request_json"]["messages"]
    assert payload["result_summary"]["outcome"] == body["outcome"]
    assert payload["result_summary"]["final_output"]
    assert "prompt_context_capture" not in payload
    assert "workflow_stage_configuration" not in payload
    assert "capability_configuration" not in payload
    assert "intermediate_result_summary" not in payload
    assert "trace_summary" not in payload
    payload_json = json.dumps(payload)
    assert '"raw_prompt":' not in payload_json
    assert '"raw_context":' not in payload_json


def test_validation_run_full_capture_failure_returns_trace_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    def reject_capture_payload(**_: object) -> dict[str, object]:
        raise ValueError("raw_prompt appeared in validation capture payload")

    monkeypatch.setattr(
        configuration_api_module,
        "_validation_capture_payload",
        reject_capture_payload,
    )

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "full_capture": True,
        },
    )

    assert validation.status_code == 200
    body = validation.json()
    assert body["outcome"] in {
        "ANSWERED_WITH_CITATIONS",
        "REFUSED_NO_EVIDENCE",
        "WAITING_FOR_APPROVAL",
    }
    assert body["trace_capture"]["mode"] == "full_capture"
    assert body["trace_capture"]["validation_capture"] is None
    assert body["trace_capture"]["capture_error"] == {
        "code": "VALIDATION_CAPTURE_REJECTED",
        "message": (
            "Validation capture artifact was not created because the v2 safety "
            "gate rejected unsafe fields."
        ),
        "retryable": False,
    }
    assert "validation_capture" not in body["links"]

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["validation_capture_id"] is None
    assert "raw_prompt" not in json.dumps(body)


def test_publish_requires_validation_and_activates_version(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    blocked = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={},
    )
    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
        },
    )
    published = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation.json()["run_id"]},
    )

    assert blocked.status_code == 400
    assert published.status_code == 200
    assert published.json()["version_id"].startswith("version_")
    assert published.json()["validation_run_id"] == validation.json()["run_id"]
    assert published.json()["effective_workflow_stage_configuration"] == {
        "template_name": "enterprise_qa",
        "template_descriptor_version": "enterprise_qa.v1",
        "stages": [
            {
                "id": "enterprise_qa",
                "label": "Enterprise QA",
                "description": "Evidence-backed deterministic Enterprise QA workflow summary.",
                "required": True,
                "model_bearing": False,
                "editable_prompt_fields": [],
                "available_context_options": [],
                "prompt": {
                    "business_context": "",
                    "task_instructions": [],
                    "output_preferences": [],
                },
                "context": {},
                "source_override": {"configured": False},
            }
        ],
        "capabilities": {
            "tools": {"enabled": True, "file": "./tools.yaml"},
            "memory": {"enabled": True, "provider": "session", "scopes": {}},
        },
    }

    listed = client.get("/api/config/agents")
    assert listed.json()["data"][0]["active_version_id"] == published.json()["version_id"]


def test_rollback_switches_active_version(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    validation_one = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
        },
    )
    version_one = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation_one.json()["run_id"]},
    ).json()["version_id"]
    client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}",
        json={"display_name": "Enterprise QA v2"},
    )
    validation_two = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
        },
    )
    version_two = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation_two.json()["run_id"]},
    ).json()["version_id"]

    rollback = client.post(
        f"/api/config/agents/{draft['agent_id']}/versions/{version_one}/rollback",
        json={},
    )

    assert rollback.status_code == 200
    assert rollback.json()["version_id"] == version_one
    assert rollback.json()["rollback_from_version_id"] == version_two
    assert client.get("/api/config/agents").json()["data"][0]["active_version_id"] == version_one
