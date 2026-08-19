"""Tests for the Local Agent Configuration Store."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from proof_agent.capabilities.tools.mcp_discovery import (
    MCPDiscoveredTool,
    discover_mcp_tools,
    import_mcp_tool_contract,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
)
from proof_agent.errors import ProofAgentError


def _bundle(name: str = "enterprise_qa") -> ContractBundle:
    return ContractBundle(
        agent_yaml=f"name: {name}\n",
        policy_yaml="rules: []\n",
        tools_yaml="tools: {}\n",
    )


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
