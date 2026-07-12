"""Tests for the Local Agent Configuration Store."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from proof_agent.capabilities.knowledge.ingestion import ParsedKnowledgeDocument, ParserMetadata
from proof_agent.capabilities.tools.mcp_discovery import (
    MCPDiscoveredTool,
    discover_mcp_tools,
    import_mcp_tool_contract,
)
from proof_agent.configuration.file_locking import locked as file_locked
from proof_agent.configuration.local_store import (
    KnowledgeUploadStagingInput,
    LocalAgentConfigurationStore,
)
from proof_agent.contracts import (
    AgentValidationRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    KnowledgeArtifactBuildSpec,
    KnowledgeIngestionJob,
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourcePublicationRecord,
    KnowledgeSourceSnapshotManifest,
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.errors import ProofAgentError


def _bundle(name: str = "enterprise_qa") -> ContractBundle:
    return ContractBundle(
        agent_yaml=f"name: {name}\n",
        policy_yaml="rules: []\n",
        tools_yaml="tools: {}\n",
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _create_source(
    store: LocalAgentConfigurationStore,
    *,
    source_id: str = "ks_policy",
) -> KnowledgeSource:
    return store.create_knowledge_source(
        source_id=source_id,
        name="Policies",
        provider="local_index",
        params={"index_path": "./indexes/policies"},
        actor="operator",
    )


def _publish_source_fixture(
    store: LocalAgentConfigurationStore,
    source: KnowledgeSource,
    *,
    snapshot_id: str = "kssnapshot_001",
) -> KnowledgeSource:
    source_draft_version_id = source.source_draft_version_id or "ksdraft_fixture"
    snapshot = KnowledgeSourceSnapshotManifest(
        schema_version="local_index.snapshot.v2",
        snapshot_id=snapshot_id,
        source_id=source.source_id,
        state="READY",
        validation_level="foundation",
        source_draft_version_id=source_draft_version_id,
        candidate_digest=f"digest_{snapshot_id}",
        foundation_validation_id=f"ksvalidation_{snapshot_id}",
        documents=(),
        created_at="2026-06-05T00:00:00Z",
        created_by="operator",
    )
    publication = KnowledgeSourcePublicationRecord(
        publication_id=f"kspub_{snapshot_id}",
        source_id=source.source_id,
        resource_kind="local_index_snapshot",
        resource_id=snapshot.snapshot_id,
        snapshot_id=snapshot.snapshot_id,
        source_draft_version_id=source_draft_version_id,
        validation_id=f"kspubval_{snapshot_id}",
        change_note="Fixture publication.",
        published_at="2026-06-05T00:01:00Z",
        published_by="publisher",
        document_count=0,
        smoke_query="policy",
        smoke_result_summary={"candidate_count": 0, "citation_count": 0},
    )
    store._write_knowledge_source_snapshot(snapshot)
    store._write_knowledge_source_publication(publication)
    published = source.model_copy(update={"published_snapshot_id": snapshot.snapshot_id})
    store._write_knowledge_source(published)
    return published


def _configuration_audit_payloads(root: Path) -> list[dict[str, object]]:
    audit_root = root / "configuration_audit"
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(audit_root.glob("*.json"))
    ]


def _parsed_markdown_document() -> ParsedKnowledgeDocument:
    return ParsedKnowledgeDocument(
        text="# Policy\n",
        page_count=None,
        parser_metadata=ParserMetadata(
            adapter="markdown",
            adapter_contract_version="test",
            library_version=None,
            fingerprint_identity="markdown:test",
        ),
    )


def _stage_and_claim_upload(
    store: LocalAgentConfigurationStore,
    source_id: str,
) -> tuple[str, str]:
    upload = store.stage_quarantined_knowledge_upload(
        source_id=source_id,
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="operator",
    )
    claimed = store.claim_next_quarantined_knowledge_upload(source_id=source_id)
    assert claimed is not None
    assert claimed.claim_token is not None
    assert claimed.upload_id == upload.upload_id
    return upload.upload_id, claimed.claim_token


def test_create_update_and_list_draft_agents(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_bundle(),
        actor="local-user",
    )
    updated = store.update_draft(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        display_name="Enterprise QA Draft",
        purpose="Updated purpose.",
        actor="editor",
    )

    loaded = store.get_draft(draft.agent_id, draft.draft_id)
    drafts = store.list_drafts("enterprise_qa")

    assert loaded == updated
    assert loaded is not None
    assert loaded.display_name == "Enterprise QA Draft"
    assert loaded.purpose == "Updated purpose."
    assert loaded.updated_by == "editor"
    assert [item.draft_id for item in drafts] == [draft.draft_id]
    assert [audit.operation.value for audit in loaded.operation_audit] == ["imported", "updated"]


def test_publish_creates_immutable_version_and_active_pointer(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_bundle(),
        actor="local-user",
    )

    version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
    )
    active = store.get_active_version("enterprise_qa")

    assert active is not None
    assert active.version_id == version.version_id
    assert version.validation_run_id == "run_validation_001"
    assert version.contract_bundle.agent_yaml == "name: enterprise_qa\n"

    version_dir = tmp_path / "agents" / "enterprise_qa" / "versions" / version.version_id
    assert (version_dir / "agent.yaml").read_text(encoding="utf-8") == "name: enterprise_qa\n"
    assert (version_dir / "policy.yaml").read_text(encoding="utf-8") == "rules: []\n"
    assert (version_dir / "tools.yaml").read_text(encoding="utf-8") == "tools: {}\n"
    assert (
        json.loads((version_dir / "publication.json").read_text(encoding="utf-8"))[
            "validation_run_id"
        ]
        == "run_validation_001"
    )


def test_publish_version_freezes_effective_workflow_stage_configuration(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    draft = store.create_draft(
        agent_id="react_enterprise_qa_v3",
        display_name="ReAct Enterprise QA V3",
        purpose="Answer governed questions.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: react_enterprise_qa_v3
purpose: "Answer governed questions."
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
  stages:
    - id: plan
      prompt:
        business_context: "Claims context."
      context:
        include_agent_purpose: true
    - id: memory
      context:
        include_memory_scope: true
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        actor="local-user",
    )

    version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
    )

    snapshot = version.effective_workflow_stage_configuration
    assert snapshot is not None
    assert snapshot.template_name == "react_enterprise_qa_v3"
    assert snapshot.template_descriptor_version == "react_enterprise_qa.v3"
    availability = version.workflow_stage_availability
    assert availability is not None
    assert availability.template_name == "react_enterprise_qa_v3"
    assert availability.template_descriptor_version == "react_enterprise_qa.v3"
    assert availability.is_available("plan") is True
    assert availability.is_available("tool_review") is False
    assert availability.is_available("tool") is False
    assert snapshot.capabilities == {
        "tools": {"enabled": False, "file": None},
        "memory": {"enabled": True, "provider": "session", "scopes": {}},
    }
    stages_by_id = {stage.id: stage for stage in snapshot.stages}
    assert set(stages_by_id) >= {"plan", "memory", "response"}
    assert "tool_review" not in stages_by_id
    assert "tool" not in stages_by_id
    assert stages_by_id["plan"].prompt == {
        "business_context": "Claims context.",
        "task_instructions": [],
        "output_preferences": [],
    }
    assert stages_by_id["plan"].context == {"include_agent_purpose": True}
    assert "include_bound_tools" not in stages_by_id["plan"].available_context_options
    assert stages_by_id["memory"].context == {"include_memory_scope": True}

    publication = json.loads(
        (
            tmp_path
            / "agents"
            / "react_enterprise_qa_v3"
            / "versions"
            / version.version_id
            / "publication.json"
        ).read_text(encoding="utf-8")
    )
    assert "plan" in {
        stage["stage_id"] for stage in publication["workflow_stage_availability"]["stages"]
    }
    assert "plan" in {
        stage["id"] for stage in publication["effective_workflow_stage_configuration"]["stages"]
    }


def test_publish_version_rejects_unavailable_workflow_stage_configuration(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    draft = store.create_draft(
        agent_id="react_enterprise_qa_v3",
        display_name="ReAct Enterprise QA V3",
        purpose="Answer governed questions.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: react_enterprise_qa_v3
purpose: "Answer governed questions."
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
  stages:
    - id: tool_review
      prompt:
        business_context: "Tool context."
capabilities:
  tools:
    enabled: false
  memory:
    enabled: false
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "unavailable workflow stage configuration" in blocked.value.message


def test_publish_version_rejects_archived_mcp_tool_source_binding(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    store.archive_tool_source(
        source_id="tool_mcp_claims_http",
        actor="operator",
        reason="No longer maintained.",
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="name: enterprise_qa\n",
            policy_yaml="rules: []\n",
            tools_yaml="""
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id, customer_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id, customer_id]
    result_schema:
      type: object
      required: [claim_id, status]
    summary_fields: [claim_id, status]
    result_authority: authoritative_read
""",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "Tool Source tool_mcp_claims_http is archived" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []
    assert store.get_active_version(draft.agent_id) is None


def test_publish_version_rejects_mcp_action_tool_without_idempotency_key(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("create_service_ticket",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="name: enterprise_qa\n",
            policy_yaml="rules: []\n",
            tools_yaml="""
tools:
  - name: create_service_ticket
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: ticket.create
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: high
    requires_approval: true
    read_only: false
    allowed_parameters: [subject, customer_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [subject, customer_id]
    result_schema:
      type: object
      required: [ticket_id]
    summary_fields: [ticket_id]
    side_effect_class: create_ticket
""",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
        )

    assert blocked.value.code == "PA_TOOL_001"
    assert "MCP action tools require idempotency_key" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []
    assert store.get_active_version(draft.agent_id) is None


def test_publish_version_requires_mcp_tool_source_publication_validation(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="name: enterprise_qa\n",
            policy_yaml="rules: []\n",
            tools_yaml="""
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id, customer_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id, customer_id]
    result_schema:
      type: object
      required: [claim_id, status]
    summary_fields: [claim_id, status]
    result_authority: authoritative_read
""",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "passed MCP Tool Source publication validation" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []
    assert store.get_active_version(draft.agent_id) is None


def test_mcp_tool_source_publication_validation_allows_agent_publish(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    imported_preview = discover_mcp_tools(
        store.get_tool_source("tool_mcp_claims_http"),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )
    tool_contract = import_mcp_tool_contract(
        imported_preview,
        mcp_tool_name="claim.status.lookup",
        contract_name="claim_status_lookup",
        tool_source_id="tool_mcp_claims_http",
        risk_level="medium",
        read_only=True,
        requires_approval=False,
        allowed_parameters=("claim_id",),
        denied_parameters=("access_token",),
        result_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["claim_id", "status"],
        },
        summary_fields=("claim_id", "status"),
        result_authority="authoritative_read",
        imported_at="2026-06-20T00:00:00Z",
    )
    validation = store.validate_mcp_tool_source_publication(
        source_id="tool_mcp_claims_http",
        tool_contracts=(tool_contract,),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        actor="operator",
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="name: enterprise_qa\n",
            policy_yaml="rules: []\n",
            tools_yaml=yaml.safe_dump({"tools": [tool_contract]}, sort_keys=False),
        ),
        actor="local-user",
    )

    version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
    )

    assert validation.validation_id.startswith("mcptspubval_")
    assert validation.source_id == "tool_mcp_claims_http"
    assert validation.config_revision == 1
    assert validation.contract_snapshot_digests == (
        tool_contract["mcp_contract_snapshot"]["digest"],
    )
    assert store.list_mcp_tool_source_publication_validations("tool_mcp_claims_http") == [
        validation
    ]
    assert version.validation_run_id == "run_validation_001"
    active = store.get_active_version("enterprise_qa")
    assert active is not None
    assert active.version_id == version.version_id


def test_publish_version_rejects_stale_mcp_tool_source_publication_validation(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    imported_preview = discover_mcp_tools(
        store.get_tool_source("tool_mcp_claims_http"),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )
    tool_contract = import_mcp_tool_contract(
        imported_preview,
        mcp_tool_name="claim.status.lookup",
        contract_name="claim_status_lookup",
        tool_source_id="tool_mcp_claims_http",
        risk_level="medium",
        read_only=True,
        requires_approval=False,
        allowed_parameters=("claim_id",),
        denied_parameters=("access_token",),
        result_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["claim_id", "status"],
        },
        summary_fields=("claim_id", "status"),
        result_authority="authoritative_read",
        imported_at="2026-06-20T00:00:00Z",
    )
    store.validate_mcp_tool_source_publication(
        source_id="tool_mcp_claims_http",
        tool_contracts=(tool_contract,),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        actor="operator",
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )
    store.update_tool_source(
        source_id="tool_mcp_claims_http",
        actor="operator",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
            "timeout_seconds": 8,
        },
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="name: enterprise_qa\n",
            policy_yaml="rules: []\n",
            tools_yaml=yaml.safe_dump({"tools": [tool_contract]}, sort_keys=False),
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "stale MCP Tool Source publication validation" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []
    assert store.get_active_version(draft.agent_id) is None


def test_publish_version_requires_mcp_validation_for_bound_contract_snapshot(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    imported_preview = discover_mcp_tools(
        store.get_tool_source("tool_mcp_claims_http"),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )
    validated_contract = import_mcp_tool_contract(
        imported_preview,
        mcp_tool_name="claim.status.lookup",
        contract_name="claim_status_lookup",
        tool_source_id="tool_mcp_claims_http",
        risk_level="medium",
        read_only=True,
        requires_approval=False,
        allowed_parameters=("claim_id",),
        denied_parameters=("access_token",),
        result_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["claim_id", "status"],
        },
        summary_fields=("claim_id", "status"),
        result_authority="authoritative_read",
        imported_at="2026-06-20T00:00:00Z",
    )
    bound_contract = import_mcp_tool_contract(
        imported_preview,
        mcp_tool_name="claim.status.lookup",
        contract_name="claim_status_lookup",
        tool_source_id="tool_mcp_claims_http",
        risk_level="medium",
        read_only=True,
        requires_approval=False,
        allowed_parameters=("claim_id",),
        denied_parameters=("access_token",),
        result_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "status": {"type": "string"},
                "updated_at": {"type": "string"},
            },
            "required": ["claim_id", "status", "updated_at"],
        },
        summary_fields=("claim_id", "status"),
        result_authority="authoritative_read",
        imported_at="2026-06-20T00:00:00Z",
    )
    store.validate_mcp_tool_source_publication(
        source_id="tool_mcp_claims_http",
        tool_contracts=(validated_contract,),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        actor="operator",
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="name: enterprise_qa\n",
            policy_yaml="rules: []\n",
            tools_yaml=yaml.safe_dump({"tools": [bound_contract]}, sort_keys=False),
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "does not cover MCP Tool Contract snapshot" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []
    assert store.get_active_version(draft.agent_id) is None


def test_records_sensitive_validation_capture_artifact_with_default_ttl(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    artifact = store.record_sensitive_validation_capture_artifact(
        run_id="run_validation",
        draft_id="draft_001",
        payload={
            "trace_summary": [
                {
                    "event_type": "workflow_stage_context_applied",
                    "status": "ok",
                    "payload_keys": ["stage_id", "context_summary"],
                }
            ],
            "result_summary": {"outcome": "ANSWERED_WITH_CITATIONS"},
            "raw_prompt": "Never persist me.",
            "raw_context": {"secret": "Never persist me."},
            "raw_tool_payloads": [{"authorization": "Bearer secret"}],
            "complete_provider_responses": [{"content": "Never persist me."}],
            "runtime_state_dicts": [{"messages": ["Never persist me."]}],
        },
        actor="validator",
    )

    created_at = datetime.fromisoformat(artifact.created_at.replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(artifact.expires_at.replace("Z", "+00:00"))
    stored_payload = store.read_sensitive_validation_capture_payload(artifact.capture_id)
    stored_metadata = store.get_sensitive_validation_capture_artifact(artifact.capture_id)
    for_run = store.get_sensitive_validation_capture_artifact_for_run("run_validation")

    assert artifact.capture_id.startswith("vcap_")
    assert artifact.run_id == "run_validation"
    assert artifact.draft_id == "draft_001"
    assert artifact.retention_class == "sensitive_validation_capture"
    assert artifact.created_by == "validator"
    assert artifact.retain_for_audit is False
    assert (expires_at - created_at).total_seconds() == pytest.approx(604800, abs=5)
    assert artifact.redaction_metadata["secrets"] == "redacted"
    assert artifact.exclusion_metadata["raw_chain_of_thought"] == "excluded"
    assert artifact.exclusion_metadata["raw_tool_payloads"] == "excluded"
    assert artifact.exclusion_metadata["complete_provider_responses"] == "excluded"
    assert artifact.exclusion_metadata["runtime_state_dicts"] == "excluded"
    assert stored_metadata == artifact
    assert for_run == artifact
    assert stored_payload is not None
    assert stored_payload["trace_summary"][0]["event_type"] == "workflow_stage_context_applied"

    capture_file = tmp_path / artifact.artifact_path
    stored = json.loads(capture_file.read_text(encoding="utf-8"))
    assert stored["metadata"]["capture_id"] == artifact.capture_id
    assert stored["payload"] == stored_payload
    stored_text = json.dumps(stored["payload"])
    assert "Never persist me." not in stored_text
    assert "Bearer secret" not in stored_text


def test_sensitive_validation_capture_artifact_writes_readable_unicode(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    artifact = store.record_sensitive_validation_capture_artifact(
        run_id="run_validation_unicode",
        draft_id="draft_unicode",
        payload={
            "result_summary": {
                "outcome": "ANSWERED_WITH_CITATIONS",
                "final_output": "中文回答",
            },
            "llm_interactions": [
                {
                    "stage_id": "intent_resolution",
                    "request_json": {"messages": [{"content": "详细介绍优缺点"}]},
                    "response_json": {"user_goal": "了解客户影响"},
                }
            ],
        },
        actor="validator",
    )

    capture_file = tmp_path / artifact.artifact_path
    capture_text = capture_file.read_text(encoding="utf-8")

    assert "中文回答" in capture_text
    assert "详细介绍优缺点" in capture_text
    assert "了解客户影响" in capture_text
    assert "\\u4e2d\\u6587" not in capture_text


def test_publish_version_rejects_archived_resolved_shared_source_inside_store_lock(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="local-user",
    )
    source = _create_source(store)
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
                bindings=(
                    ResolvedKnowledgeBinding(
                        binding_id="kb_policy",
                        source_scope="shared",
                        source_id=source.source_id,
                        source_version_id="kssnapshot_001",
                        provider="local_index",
                    ),
                )
            ),
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "archived" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []
    assert store.get_active_version(draft.agent_id) is None


def test_publish_version_rejects_shared_source_draft_without_resolved_bindings(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_knowledge_source(
        source_id="ks_policy",
        name="Policies",
        provider="local_index",
        params={"index_path": "./indexes/policies"},
        actor="operator",
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "Revalidate" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []


def test_publish_version_rejects_incomplete_resolved_shared_bindings(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_knowledge_source(
        source_id="ks_policy",
        name="Policies",
        provider="local_index",
        params={"index_path": "./indexes/policies"},
        actor="operator",
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(bindings=()),
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "Revalidate" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []


def test_publish_version_rejects_resolved_shared_binding_source_mismatch(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_knowledge_source(
        source_id="ks_policy",
        name="Policies",
        provider="local_index",
        params={"index_path": "./indexes/policies"},
        actor="operator",
    )
    store.create_knowledge_source(
        source_id="ks_other",
        name="Other",
        provider="local_index",
        params={"index_path": "./indexes/other"},
        actor="operator",
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
                bindings=(
                    ResolvedKnowledgeBinding(
                        binding_id="kb_policy",
                        source_scope="shared",
                        source_id="ks_other",
                        source_version_id="kssnapshot_001",
                        provider="local_index",
                    ),
                )
            ),
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "Revalidate" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []


def test_publish_version_rejects_unpublished_resolved_shared_source(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
                bindings=(
                    ResolvedKnowledgeBinding(
                        binding_id="kb_policy",
                        source_scope="shared",
                        source_id=source.source_id,
                        source_version_id="kssnapshot_001",
                        provider="local_index",
                    ),
                )
            ),
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "not published" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []


@pytest.mark.parametrize("source_version_id", ["", "kssnapshot_bogus"])
def test_publish_version_rejects_resolved_shared_binding_version_mismatch(
    tmp_path: Path,
    source_version_id: str,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _publish_source_fixture(store, _create_source(store))
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
                bindings=(
                    ResolvedKnowledgeBinding(
                        binding_id="kb_policy",
                        source_scope="shared",
                        source_id=source.source_id,
                        source_version_id=source_version_id,
                        provider="local_index",
                    ),
                )
            ),
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "Revalidate" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []


def test_publish_version_rejects_resolved_shared_binding_provider_mismatch(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _publish_source_fixture(store, _create_source(store))
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
                bindings=(
                    ResolvedKnowledgeBinding(
                        binding_id="kb_policy",
                        source_scope="shared",
                        source_id=source.source_id,
                        source_version_id=source.published_snapshot_id or "",
                        provider="http_json",
                    ),
                )
            ),
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "Revalidate" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []


def test_publish_version_rejects_unexpected_resolved_shared_binding(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _publish_source_fixture(store, _create_source(store))
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_bundle(),
        actor="local-user",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="run_validation_001",
            actor="publisher",
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
                bindings=(
                    ResolvedKnowledgeBinding(
                        binding_id="kb_policy",
                        source_scope="shared",
                        source_id=source.source_id,
                        source_version_id=source.published_snapshot_id or "",
                        provider="local_index",
                    ),
                )
            ),
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "Revalidate" in blocked.value.message
    assert store.list_versions(draft.agent_id) == []


def test_rollback_changes_active_pointer_without_mutating_versions(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_bundle("enterprise_qa"),
        actor="local-user",
    )
    version_one = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
    )
    updated_draft = store.update_draft(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        contract_bundle=_bundle("enterprise_qa_v2"),
        actor="editor",
    )
    version_two = store.publish_version(
        agent_id=updated_draft.agent_id,
        draft_id=updated_draft.draft_id,
        validation_run_id="run_validation_002",
        actor="publisher",
    )

    rollback = store.rollback_active_version(
        agent_id="enterprise_qa",
        version_id=version_one.version_id,
        actor="publisher",
    )

    assert rollback.version_id == version_one.version_id
    assert rollback.rollback_from_version_id == version_two.version_id
    assert store.get_active_version("enterprise_qa") == rollback
    assert store.get_version("enterprise_qa", version_one.version_id) == version_one
    assert store.get_version("enterprise_qa", version_two.version_id) == version_two
    assert (
        tmp_path / "agents" / "enterprise_qa" / "versions" / version_two.version_id / "agent.yaml"
    ).read_text(encoding="utf-8") == "name: enterprise_qa_v2\n"


def test_list_versions_returns_newest_first_with_version_id_tiebreaker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_bundle("enterprise_qa"),
        actor="local-user",
    )

    # Control published_at via _now so the test is deterministic without sleeps.
    # _now is called several times per publish (published_at, audit, active
    # pointer), so return a strictly increasing value per call. publish_version
    # captures published_at before the other calls, so each published version's
    # published_at is strictly greater than the previous one.
    from proof_agent.configuration import local_store as store_module

    counter = {"n": 0}

    def _fake_now() -> str:
        counter["n"] += 1
        return f"2026-07-01T{counter['n']:02d}:00:00.000000Z"

    monkeypatch.setattr(store_module, "_now", _fake_now, raising=True)

    first = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
    )
    second = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_002",
        actor="publisher",
    )
    third = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_003",
        actor="publisher",
    )

    listed = store.list_versions(draft.agent_id)
    assert [version.version_id for version in listed] == [
        third.version_id,
        second.version_id,
        first.version_id,
    ]


def test_list_versions_breaks_published_at_ties_by_version_id_ascending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_bundle("enterprise_qa"),
        actor="local-user",
    )

    from proof_agent.configuration import local_store as store_module

    # Same published_at for both publishes -> tie broken by version_id ascending.
    monkeypatch.setattr(
        store_module,
        "_now",
        lambda: "2026-07-01T01:00:00.000000Z",
        raising=True,
    )

    one = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
    )
    two = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_002",
        actor="publisher",
    )

    listed = store.list_versions(draft.agent_id)
    # version_id values are random; sort the pair for a stable assertion.
    expected = sorted([one.version_id, two.version_id])
    assert [version.version_id for version in listed] == expected


def test_create_list_and_store_knowledge_source_documents(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    source = store.create_knowledge_source(
        source_id="ks_local_index",
        name="Local Index Policies",
        provider="local_index",
        params={
            "index_path": "./indexes/policies",
        },
        actor="local-user",
    )
    document = store.add_knowledge_document(
        source_id=source.source_id,
        filename="travel-policy.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4\nsample",
        state="queued",
        provider_document_id=None,
        actor="local-user",
    )

    loaded = store.get_knowledge_source(source.source_id)
    documents = store.list_knowledge_documents(source.source_id)

    assert loaded == source
    assert source.lifecycle_state is KnowledgeSourceLifecycleState.ACTIVE
    assert store.list_knowledge_sources() == [source]
    assert documents == [document]
    assert document.document_id.startswith("doc_")
    assert document.revision_id.startswith("rev_")
    assert document.source_id == source.source_id
    assert document.filename == "travel-policy.pdf"
    assert document.content_hash
    assert document.provider_document_id is None
    assert store.knowledge_document_original_path(document).read_bytes() == b"%PDF-1.4\nsample"


def test_create_knowledge_source_sets_active_lifecycle_state(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    source = store.create_knowledge_source(
        source_id="ks_policy",
        name="Policies",
        provider="local_markdown",
        params={"path": "./knowledge"},
        actor="operator",
    )

    assert source.lifecycle_state is KnowledgeSourceLifecycleState.ACTIVE


def test_reading_legacy_source_without_lifecycle_state_defaults_active_and_persists(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source_dir = tmp_path / "knowledge_sources" / "ks_legacy"
    source_dir.mkdir(parents=True)
    (source_dir / "source.json").write_text(
        json.dumps(
            {
                "source_id": "ks_legacy",
                "name": "Legacy",
                "provider": "local_markdown",
                "params": {},
                "created_at": "2026-06-05T00:00:00Z",
                "updated_at": "2026-06-05T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    source = store.get_knowledge_source("ks_legacy")

    assert source is not None
    assert source.lifecycle_state is KnowledgeSourceLifecycleState.ACTIVE
    assert (
        json.loads((source_dir / "source.json").read_text(encoding="utf-8"))["lifecycle_state"]
        == "ACTIVE"
    )


def test_get_knowledge_source_reference_summary_counts_persisted_references(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = store.create_knowledge_source(
        source_id="ks_policy",
        name="Policies",
        provider="local_index",
        params={"index_path": "./indexes/policies"},
        actor="operator",
    )
    assert source.source_draft_version_id is not None
    source = _publish_source_fixture(store, source)
    _publish_source_fixture(
        store,
        _create_source(store, source_id="ks_other"),
        snapshot_id="kssnapshot_other",
    )
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
  - binding_id: kb_package_ignored
    source_ref:
      scope: package
      source_id: ks_policy
  - binding_id: kb_other_ignored
    source_ref:
      scope: shared
      source_id: ks_other
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="operator",
    )
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
        resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
            bindings=(
                ResolvedKnowledgeBinding(
                    binding_id="kb_policy",
                    source_scope="shared",
                    source_id=source.source_id,
                    source_version_id="kssnapshot_001",
                    provider="local_index",
                ),
                ResolvedKnowledgeBinding(
                    binding_id="kb_package_same_id_ignored",
                    source_scope="package",
                    source_id=source.source_id,
                    source_version_id="package_source_001",
                    provider="local_index",
                ),
                ResolvedKnowledgeBinding(
                    binding_id="kb_other_ignored",
                    source_scope="shared",
                    source_id="ks_other",
                    source_version_id="kssnapshot_other",
                    provider="local_index",
                ),
            )
        ),
    )
    document = store.add_knowledge_document(
        source_id=source.source_id,
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy",
        state="queued",
        actor="operator",
    )
    store.stage_quarantined_knowledge_upload(
        source_id=source.source_id,
        filename="draft.md",
        content_type="text/markdown",
        content=b"# Draft",
        actor="operator",
    )
    job = KnowledgeIngestionJob(
        job_id="job_001",
        source_id=source.source_id,
        document_id=document.document_id,
        revision_id=document.revision_id,
        state="queued",
        ingestion_config_fingerprint="fingerprint_001",
        artifact_build_spec=KnowledgeArtifactBuildSpec(
            provider="local_index",
            engine_name="test-engine",
            engine_version="1",
            parser_fingerprint_identity="parser-v1",
            content_hash=document.content_hash,
            parsed_text_sha256="parsed_text_sha256",
        ),
        created_at="2026-06-05T00:02:00Z",
        updated_at="2026-06-05T00:02:00Z",
    )
    _write_json(
        tmp_path
        / "knowledge_sources"
        / source.source_id
        / "ingestion_jobs"
        / job.job_id
        / "job.json",
        job.model_dump(mode="json"),
    )

    summary = store.get_knowledge_source_reference_summary(source.source_id)

    assert summary.source_id == source.source_id
    assert summary.draft_agent_binding_count == 1
    assert summary.published_agent_version_count == 1
    assert summary.publication_count == 1
    assert summary.snapshot_count == 1
    assert summary.document_count == 1
    assert summary.quarantined_upload_count == 1
    assert summary.ingestion_job_count == 1
    assert summary.audit_retention_blocked is False


def test_record_configuration_operation_writes_global_audit_file(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    audit = ConfigurationOperationAudit(
        operation_id="op_physical_delete_001",
        operation=ConfigurationOperation.PHYSICAL_DELETED,
        actor="operator",
        created_at="2026-06-05T00:00:00Z",
        summary="Recorded physical deletion decision.",
        metadata={"source_id": "ks_policy"},
    )

    store.record_configuration_operation(audit)

    audit_path = tmp_path / "configuration_audit" / "op_physical_delete_001.json"
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload == audit.model_dump(mode="json")


def test_record_configuration_operation_rejects_escaped_operation_id(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    sentinel = outside_dir / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    audit = ConfigurationOperationAudit(
        operation_id="../outside/escaped",
        operation=ConfigurationOperation.PHYSICAL_DELETED,
        actor="operator",
        created_at="2026-06-05T00:00:00Z",
        summary="Attempt escaped audit write.",
        metadata={"source_id": "ks_policy"},
    )

    with pytest.raises(ProofAgentError) as invalid_audit:
        store.record_configuration_operation(audit)

    assert invalid_audit.value.code == "PA_CONFIG_001"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (outside_dir / "escaped.json").exists()


def test_blocker_producing_mutations_acquire_store_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    source = _publish_source_fixture(store, source)
    expected_lock_path = tmp_path / ".locks" / "store.lock"
    lock_calls: list[Path] = []

    def tracking_locked(path: Path, *, timeout_seconds: float) -> object:
        lock_calls.append(path)
        return file_locked(path, timeout_seconds=timeout_seconds)

    def assert_locked_once() -> None:
        assert lock_calls == [expected_lock_path]
        lock_calls.clear()

    monkeypatch.setattr("proof_agent.configuration.local_store.locked", tracking_locked)

    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="operator",
    )
    assert_locked_once()

    store.update_draft(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        actor="operator",
        contract_bundle=_bundle("enterprise_qa_v2"),
    )
    assert_locked_once()

    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
    )
    assert_locked_once()

    store.record_validation(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        actor="validator",
        record=AgentValidationRecord(
            validation_id="validation_001",
            draft_id=draft.draft_id,
            run_id="run_validation_001",
            status="passed",
            created_at="2026-06-05T00:00:00Z",
        ),
    )
    assert_locked_once()

    store.add_knowledge_document(
        source_id=source.source_id,
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy",
        state="queued",
        actor="operator",
    )
    assert_locked_once()


def test_archive_source_requires_reason_and_does_not_change_draft_version(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)

    with pytest.raises(ProofAgentError) as missing_reason:
        store.archive_knowledge_source(
            source_id=source.source_id,
            actor="operator",
            reason="",
        )

    assert missing_reason.value.code == "PA_CONFIG_001"

    archived = store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    assert archived.lifecycle_state is KnowledgeSourceLifecycleState.ARCHIVED
    assert archived.source_draft_version_id == source.source_draft_version_id

    with pytest.raises(ProofAgentError) as already_archived:
        store.archive_knowledge_source(
            source_id=source.source_id,
            actor="operator",
            reason="Second archive attempt.",
        )

    assert already_archived.value.code == "PA_CONFIG_002"
    audit_payloads = _configuration_audit_payloads(tmp_path)
    assert any(
        payload["operation"] == ConfigurationOperation.ARCHIVED.value
        and payload["metadata"]
        == {
            "source_id": source.source_id,
            "reason": "No longer maintained.",
        }
        for payload in audit_payloads
    )


def test_restore_source_keeps_draft_version_and_requires_archived_state(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)

    with pytest.raises(ProofAgentError) as active_restore:
        store.restore_knowledge_source(source_id=source.source_id, actor="operator")

    assert active_restore.value.code == "PA_CONFIG_002"
    archived = store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    restored = store.restore_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="Needed again.",
    )

    assert restored.lifecycle_state is KnowledgeSourceLifecycleState.ACTIVE
    assert restored.source_draft_version_id == archived.source_draft_version_id
    audit_payloads = _configuration_audit_payloads(tmp_path)
    assert any(
        payload["operation"] == ConfigurationOperation.RESTORED.value
        and payload["metadata"]
        == {
            "source_id": source.source_id,
            "reason": "Needed again.",
        }
        for payload in audit_payloads
    )


@pytest.mark.parametrize(
    "operation_name",
    (
        "stage_upload_batch",
        "add_document",
        "update_routing_metadata",
        "validate_candidate_snapshot_foundation",
        "freeze_candidate_snapshot",
        "validate_publication",
        "publish_source",
    ),
)
def test_archived_source_rejects_direct_publication_bound_mutations(
    tmp_path: Path,
    operation_name: str,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    with pytest.raises(ProofAgentError) as blocked:
        if operation_name == "stage_upload_batch":
            store.stage_quarantined_knowledge_upload_batch(
                source_id=source.source_id,
                uploads=(
                    KnowledgeUploadStagingInput(
                        filename="policy.md",
                        content_type="text/markdown",
                        content=b"# Policy\n",
                    ),
                ),
                actor="operator",
            )
        elif operation_name == "add_document":
            store.add_knowledge_document(
                source_id=source.source_id,
                filename="policy.md",
                content_type="text/markdown",
                content=b"# Policy\n",
                state="queued",
                actor="operator",
            )
        elif operation_name == "update_routing_metadata":
            store.update_knowledge_document_routing_metadata(
                source_id=source.source_id,
                document_id="doc_missing",
                routing_metadata={"title": "Policy"},
                actor="operator",
            )
        elif operation_name == "validate_candidate_snapshot_foundation":
            store.validate_candidate_knowledge_source_snapshot_foundation(
                source_id=source.source_id,
                actor="validator",
            )
        elif operation_name == "freeze_candidate_snapshot":
            store.freeze_candidate_knowledge_source_snapshot(
                source_id=source.source_id,
                validation_id="ksvalidation_missing",
                actor="operator",
            )
        elif operation_name == "validate_publication":
            store.validate_local_index_source_publication(
                source_id=source.source_id,
                smoke_query="policy",
                actor="validator",
            )
        elif operation_name == "publish_source":
            store.publish_knowledge_source(
                source_id=source.source_id,
                validation_id="kspubval_missing",
                change_note="Publish policy.",
                actor="operator",
            )
        else:  # pragma: no cover - parametrization guard
            raise AssertionError(f"Unknown operation: {operation_name}")

    assert blocked.value.code == "PA_CONFIG_002"
    assert "archived" in blocked.value.message


def test_archived_source_worker_tasks_are_not_claimed(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    upload_source = _create_source(store, source_id="ks_upload")
    store.stage_quarantined_knowledge_upload(
        source_id=upload_source.source_id,
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="operator",
    )
    store.archive_knowledge_source(
        source_id=upload_source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )
    job_source = _create_source(store, source_id="ks_job")
    upload_id, claim_token = _stage_and_claim_upload(store, job_source.source_id)
    _, job = store.accept_quarantined_knowledge_upload(
        source_id=job_source.source_id,
        upload_id=upload_id,
        parsed_document=_parsed_markdown_document(),
        claim_token=claim_token,
    )
    store.archive_knowledge_source(
        source_id=job_source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    upload_claim = store.claim_next_quarantined_knowledge_upload(source_id=upload_source.source_id)
    job_claim = store.claim_next_knowledge_ingestion_job(source_id=job.source_id)
    unified_claim = store.claim_next_knowledge_worker_task()

    assert upload_claim is None
    assert job_claim is None
    assert unified_claim.task is None


def test_archived_source_rejects_accepting_claimed_upload(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    upload_id, claim_token = _stage_and_claim_upload(store, source.source_id)
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.accept_quarantined_knowledge_upload(
            source_id=source.source_id,
            upload_id=upload_id,
            parsed_document=_parsed_markdown_document(),
            claim_token=claim_token,
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "archived" in blocked.value.message
    assert store.list_knowledge_documents(source.source_id) == []
    assert store.list_knowledge_ingestion_jobs(source.source_id) == []


def test_archived_source_rejects_renewing_claimed_upload(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    upload_id, claim_token = _stage_and_claim_upload(store, source.source_id)
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.renew_quarantined_knowledge_upload_claim(
            source_id=source.source_id,
            upload_id=upload_id,
            claim_token=claim_token,
        )

    assert blocked.value.code == "PA_CONFIG_002"
    assert "archived" in blocked.value.message


def test_archived_source_rejects_completing_claimed_ingestion_job_without_draft_advance(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    upload_id, upload_claim_token = _stage_and_claim_upload(store, source.source_id)
    document, job = store.accept_quarantined_knowledge_upload(
        source_id=source.source_id,
        upload_id=upload_id,
        parsed_document=_parsed_markdown_document(),
        claim_token=upload_claim_token,
    )
    claimed_job = store.claim_next_knowledge_ingestion_job(source_id=source.source_id)
    assert claimed_job is not None
    assert claimed_job.claim_token is not None
    before_archive = store.get_knowledge_source(source.source_id)
    assert before_archive is not None
    source_draft_version_id = before_archive.source_draft_version_id
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    with pytest.raises(ProofAgentError) as blocked:
        store.complete_knowledge_ingestion_job(
            source_id=source.source_id,
            job_id=job.job_id,
            claim_token=claimed_job.claim_token,
            artifact_path="knowledge_artifacts/content/config",
        )

    stored_source = store.get_knowledge_source(source.source_id)
    stored_document = store.get_knowledge_document(
        source_id=source.source_id,
        document_id=document.document_id,
    )
    stored_job = store.get_knowledge_ingestion_job(
        source_id=source.source_id,
        job_id=job.job_id,
    )
    assert blocked.value.code == "PA_CONFIG_002"
    assert "archived" in blocked.value.message
    assert stored_source is not None
    assert stored_source.source_draft_version_id == source_draft_version_id
    assert stored_document is not None
    assert stored_document.state == "processing"
    assert stored_document.artifact_path is None
    assert stored_job is not None
    assert stored_job.state == "processing"
    assert stored_job.artifact_path is None


def test_physical_deletion_rejects_active_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)

    with pytest.raises(ProofAgentError) as missing_reason:
        store.physically_delete_knowledge_source(
            source_id=source.source_id,
            actor="operator",
            reason=" ",
        )

    assert missing_reason.value.code == "PA_CONFIG_001"
    eligibility = store.get_knowledge_source_deletion_eligibility(source.source_id)
    assert eligibility.eligible is False
    assert eligibility.blockers == ("source_not_archived",)

    with pytest.raises(ProofAgentError) as active_delete:
        store.physically_delete_knowledge_source(
            source_id=source.source_id,
            actor="operator",
            reason="Created by mistake.",
        )

    assert active_delete.value.code == "PA_CONFIG_002"
    assert store.get_knowledge_source(source.source_id) == source


def test_physical_deletion_rejects_archived_source_with_reference_blockers(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    source = _publish_source_fixture(store, source)
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="operator",
    )
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_001",
        actor="publisher",
        resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
            bindings=(
                ResolvedKnowledgeBinding(
                    binding_id="kb_policy",
                    source_scope="shared",
                    source_id=source.source_id,
                    source_version_id="kssnapshot_001",
                    provider="local_index",
                ),
            )
        ),
    )
    document = store.add_knowledge_document(
        source_id=source.source_id,
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy",
        state="queued",
        actor="operator",
    )
    store.stage_quarantined_knowledge_upload(
        source_id=source.source_id,
        filename="draft.md",
        content_type="text/markdown",
        content=b"# Draft",
        actor="operator",
    )
    job = KnowledgeIngestionJob(
        job_id="job_001",
        source_id=source.source_id,
        document_id=document.document_id,
        revision_id=document.revision_id,
        state="queued",
        ingestion_config_fingerprint="fingerprint_001",
        artifact_build_spec=KnowledgeArtifactBuildSpec(
            provider="local_index",
            engine_name="test-engine",
            engine_version="1",
            parser_fingerprint_identity="parser-v1",
            content_hash=document.content_hash,
            parsed_text_sha256="parsed_text_sha256",
        ),
        created_at="2026-06-05T00:02:00Z",
        updated_at="2026-06-05T00:02:00Z",
    )
    _write_json(
        tmp_path
        / "knowledge_sources"
        / source.source_id
        / "ingestion_jobs"
        / job.job_id
        / "job.json",
        job.model_dump(mode="json"),
    )
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    eligibility = store.get_knowledge_source_deletion_eligibility(source.source_id)

    assert eligibility.eligible is False
    assert eligibility.blockers == (
        "draft_agent_bindings",
        "published_agent_versions",
        "publications",
        "snapshots",
        "documents",
        "quarantined_uploads",
        "ingestion_jobs",
    )

    with pytest.raises(ProofAgentError) as blocked_delete:
        store.physically_delete_knowledge_source(
            source_id=source.source_id,
            actor="operator",
            reason="Created by mistake.",
        )

    assert blocked_delete.value.code == "PA_CONFIG_002"
    assert store.get_knowledge_source(source.source_id) is not None


def test_physical_deletion_rejects_escaped_source_id_without_deleting_outside(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    (tmp_path / "knowledge_sources").mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    sentinel = outside_dir / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    _write_json(
        outside_dir / "source.json",
        {
            "source_id": "../outside",
            "name": "Escaped Source",
            "provider": "local_index",
            "lifecycle_state": KnowledgeSourceLifecycleState.ARCHIVED.value,
            "params": {"index_path": "./indexes/policies"},
            "created_at": "2026-06-05T00:00:00Z",
            "updated_at": "2026-06-05T00:00:00Z",
            "source_draft_version_id": "ksdraft_escaped",
        },
    )

    with pytest.raises(ProofAgentError) as invalid_delete:
        store.physically_delete_knowledge_source(
            source_id="../outside",
            actor="operator",
            reason="Created by mistake.",
        )

    assert invalid_delete.value.code == "PA_CONFIG_001"
    assert sentinel.read_text(encoding="utf-8") == "keep"

    with pytest.raises(ProofAgentError) as invalid_eligibility:
        store.get_knowledge_source_deletion_eligibility("../outside")

    assert invalid_eligibility.value.code == "PA_CONFIG_001"


def test_physical_deletion_removes_empty_archived_source_and_keeps_global_audit(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="Created by mistake.",
    )
    source_dir = tmp_path / "knowledge_sources" / source.source_id

    deleted_eligibility = store.physically_delete_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="Created by mistake.",
    )

    assert deleted_eligibility.eligible is True
    assert deleted_eligibility.blockers == ()
    assert deleted_eligibility.lifecycle_state is KnowledgeSourceLifecycleState.ARCHIVED
    assert not source_dir.exists()
    assert store.get_knowledge_source(source.source_id) is None

    physical_delete_audits = [
        payload
        for payload in _configuration_audit_payloads(tmp_path)
        if payload["operation"] == ConfigurationOperation.PHYSICAL_DELETED.value
    ]
    assert len(physical_delete_audits) == 1
    assert physical_delete_audits[0]["metadata"] == {
        "source_id": source.source_id,
        "reason": "Created by mistake.",
        "blockers": [],
        "reference_summary": {
            "source_id": source.source_id,
            "draft_agent_binding_count": 0,
            "published_agent_version_count": 0,
            "publication_count": 0,
            "snapshot_count": 0,
            "document_count": 0,
            "quarantined_upload_count": 0,
            "ingestion_job_count": 0,
            "audit_retention_blocked": False,
        },
    }


def test_physical_deletion_writes_global_audit_before_removing_source_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="Created by mistake.",
    )
    source_dir = tmp_path / "knowledge_sources" / source.source_id

    class RmtreeSentinel(Exception):
        pass

    def fake_rmtree(path: str | Path, *args: object, **kwargs: object) -> None:
        assert Path(path) == source_dir
        physical_delete_audits = [
            payload
            for payload in _configuration_audit_payloads(tmp_path)
            if payload["operation"] == ConfigurationOperation.PHYSICAL_DELETED.value
        ]
        assert len(physical_delete_audits) == 1
        raise RmtreeSentinel

    monkeypatch.setattr("proof_agent.configuration.local_store.shutil.rmtree", fake_rmtree)

    with pytest.raises(RmtreeSentinel):
        store.physically_delete_knowledge_source(
            source_id=source.source_id,
            actor="operator",
            reason="Created by mistake.",
        )

    assert source_dir.exists()
