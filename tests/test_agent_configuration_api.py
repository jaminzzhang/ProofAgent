"""Integration tests for the Agent Configuration API."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
import yaml

import proof_agent.bootstrap.composition as bootstrap_composition
import proof_agent.delivery.configuration_api as configuration_api_module
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    ContractBundle,
    ModelResponse,
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


def _configuration_store(client: TestClient) -> LocalAgentConfigurationStore:
    return client.app.state.agent_configuration_store


class _StaticOperatorIdentityProvider:
    def __init__(
        self,
        permissions: set[OperatorPermission],
        *,
        operator_id: str = "test-operator",
    ) -> None:
        self._permissions = permissions
        self._operator_id = operator_id

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id=self._operator_id,
            display_name="Test Operator",
            permissions=frozenset(self._permissions),
        )


def _client_with_operator_permissions(
    tmp_path: Path,
    permissions: set[OperatorPermission],
    *,
    operator_id: str = "test-operator",
) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
    )
    app.state.operator_identity_provider = _StaticOperatorIdentityProvider(
        permissions,
        operator_id=operator_id,
    )
    return TestClient(app)


def _import_enterprise_qa(client: TestClient) -> dict:
    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
        },
    )
    assert response.status_code == 200
    return response.json()


def _import_react_enterprise_qa(client: TestClient) -> dict:
    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
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


class _RawEvidenceAnswerProvider:
    provider_name = "deterministic"
    model_name = "raw-evidence-answer"

    def estimate_tokens(self, request: object) -> int | None:
        _ = request
        return None

    def generate(self, request: object) -> ModelResponse:
        _ = request
        return ModelResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
            content=json.dumps(
                {
                    "message": (
                        "Travel meals are reimbursed up to 50 USD per day when the "
                        "employee provides receipts.\nQuestions about travel meal "
                        "reimbursement must cite this policy section."
                    ),
                    "citations": ["customer-support-policy.md#travel-meals:L3-L7"],
                },
            ),
        )


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
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
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
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
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
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
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
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
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
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
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
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
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

    response = client.get(f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/skills")

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
    assert pack["capability_refs"]["policy_rule_refs"] == ["answering.require_retrieval"]
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

    response = client.get(f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}/skills")

    assert response.status_code == 200
    payload = response.json()
    assert payload["configuration_issues"][0]["code"] == "PA_CONFIG_002"
    assert (
        "unknown Business Flow Skill Pack knowledge_binding_refs"
        in (payload["configuration_issues"][0]["message"])
    )
    assert "general_insurance_knowledge" in payload["configuration_issues"][0]["message"]
    pack = next(item for item in payload["packs"] if item["id"] == "general_insurance_specialist")
    assert "general_insurance_knowledge" in pack["capability_refs"]["knowledge_binding_refs"]
    repaired = client.patch(
        f"/api/config/agents/{draft.agent_id}/drafts/{draft.draft_id}"
        "/skills/business-flows/general_insurance_specialist",
        json={"knowledge_binding_refs": []},
    )

    assert repaired.status_code == 200
    assert repaired.json()["configuration_issues"] == []


def test_fetch_config_draft_skills_projects_v3_addendum_slots_when_disabled(
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
    assert [slot["stage_id"] for slot in payload["addendum_slots"]] == [
        "plan",
        "retrieval_review",
        "tool_review",
        "model_answer",
    ]
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
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
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
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
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
                    "task_instructions": ["Prefer retrieval before answering claim questions."],
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
            "task_instructions": ["Prefer retrieval before answering claim questions."],
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
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
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



def test_import_agent_package_creates_draft_and_list_entry(tmp_path: Path) -> None:
    client = _client(tmp_path)

    draft = _import_enterprise_qa(client)
    listed = client.get("/api/config/agents")

    assert draft["agent_id"] == "react_enterprise_qa_v3"
    assert draft["draft_id"].startswith("draft_")
    assert draft["display_name"] == "react_enterprise_qa_v3"
    assert listed.status_code == 200
    assert listed.json()["data"][0]["agent_id"] == "react_enterprise_qa_v3"
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
    assert contract.json()["agent_yaml"].startswith("name: react_enterprise_qa_v3")
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
    assert (
        "unknown Business Flow Skill Pack knowledge_binding_refs"
        in (updated.json()["detail"]["message"])
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

    response = client.get("/api/config/workflow-templates/react_enterprise_qa_v3")

    assert response.status_code == 200
    body = response.json()
    assert body["descriptor_version"] == "react_enterprise_qa.v3"
    assert body["stages"][0]["id"] == "intent_resolution"
    assert body["stages"][1]["successors"] == [
        "clarification",
        "retrieval_review",
        "tool_review",
        "response",
    ]


@pytest.mark.parametrize(
    "removed_template",
    ("enterprise_qa", "react_enterprise_qa", "react_enterprise_qa_v2"),
)
def test_removed_workflow_template_descriptor_fails_closed(
    tmp_path: Path,
    removed_template: str,
) -> None:
    response = _client(tmp_path).get(f"/api/config/workflow-templates/{removed_template}")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PA_CONFIG_002"
    assert "react_enterprise_qa_v3" in response.json()["detail"]["fix"]


def test_update_workflow_stages_persists_valid_stage_config(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa(client)

    response = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-stages",
        json={
            "template_descriptor_version": "react_enterprise_qa.v3",
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
    assert raw["workflow"]["template_descriptor_version"] == "react_enterprise_qa.v3"
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
            "template_descriptor_version": "react_enterprise_qa.v3",
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
        "include_agent_purpose": (
            "Answer enterprise knowledge questions through the governed Controlled "
            "ReAct Loop (ADR-0032): observation actions return to plan under a "
            "dual-axis budget and deterministic Convergence Check."
        )
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
    assert (
        "workflow stage prompt contains forbidden governance override language"
        in response.json()["detail"]["message"]
    )


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
    assert [stage["stage_id"] for stage in payload["stage_results"]] == [
        "intent_resolution",
        "memory_read",
        "tool_proposal_scope",
        "plan",
        "retrieval_review",
        "retrieval",
        "tool_proposal_scope",
        "plan",
        "model_answer",
        "memory",
        "response",
    ]
    assert payload["llm_interactions"]
    assert payload["llm_interactions"][0]["stage_id"] == "model_answer"
    assert payload["llm_interactions"][0]["request_json"]["messages"]


def test_validate_v3_draft_full_capture_records_model_answer_failure_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bootstrap_composition,
        "resolve_provider",
        lambda _config: _RawEvidenceAnswerProvider(),
    )
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
    diagnostic = payload["failure_diagnostics"][0]
    assert diagnostic["stage_id"] == "model_answer"
    assert diagnostic["event_type"] == "final_answer_validation_failed"
    assert diagnostic["error_code"] == "final_answer_adequacy_failed"
    assert diagnostic["role"] == "final_answer"
    assert diagnostic["contract_name"] == "FinalAnswerOutput"
    assert "raw_evidence_dump" in diagnostic["violation_codes"]
    assert payload["llm_interactions"][0]["stage_id"] == "model_answer"
    assert "Questions about travel meal reimbursement" not in json.dumps(diagnostic)
    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert "Questions about travel meal reimbursement" not in json.dumps(detail.json())


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


def test_validate_draft_maps_model_provider_error_to_upstream_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    def fake_execute_agent_package_run(request: Any) -> RunResult:
        _ = request
        raise ProofAgentError(
            "PA_MODEL_002",
            "model provider API error (upstream status 400).",
            (
                "Check the configured provider, model name, base_url, endpoint mode, "
                "and structured-output support before retrying."
            ),
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

    assert validation.status_code == 502
    assert validation.json()["detail"]["code"] == "PA_MODEL_002"


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


def test_validation_run_full_capture_records_gated_v3_artifact(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_enterprise_qa(client)
    update = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-stages",
        json={
            "template_descriptor_version": "react_enterprise_qa.v3",
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
    assert body["links"]["validation_capture"] == (f"/api/runs/{body['run_id']}/validation-capture")

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
    assert payload["source"]["template_name"] == "react_enterprise_qa_v3"
    assert payload["stage_prompt_values"]
    assert payload["stage_prompt_values"][0]["stage_label"]
    assert payload["context_configuration"]
    assert payload["context_applications"]
    plan_context = next(
        item for item in payload["context_applications"] if item["summary"]["stage_id"] == "plan"
    )
    assert plan_context["summary"]["business_context_length"] == len("Insurance servicing context.")
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
    effective = published.json()["effective_workflow_stage_configuration"]
    assert effective["template_name"] == "react_enterprise_qa_v3"
    assert effective["template_descriptor_version"] == "react_enterprise_qa.v3"
    assert [stage["id"] for stage in effective["stages"]] == [
        "intent_resolution",
        "plan",
        "clarification",
        "retrieval_review",
        "retrieval",
        "model_answer",
        "memory",
        "response",
    ]
    assert effective["capabilities"]["tools"] == {"enabled": False, "file": None}

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
