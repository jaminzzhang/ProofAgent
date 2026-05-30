"""Tests for Agent Configuration Workspace contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentValidationRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    KnowledgeSource,
    PublishedAgentVersion,
    ToolSource,
)


def _contract_bundle() -> ContractBundle:
    return ContractBundle(
        agent_yaml="name: enterprise_qa\n",
        policy_yaml="rules: []\n",
        tools_yaml="tools: {}\n",
        extra_files={"knowledge/README.md": "# Knowledge\n"},
        advanced_fields={"customer": {"adapter": "./customer_adapter.py"}},
    )


def test_contract_bundle_preserves_reviewable_files_and_advanced_fields() -> None:
    bundle = _contract_bundle()

    payload = bundle.model_dump(mode="json")

    assert payload["agent_yaml"].startswith("name:")
    assert payload["policy_yaml"] == "rules: []\n"
    assert payload["tools_yaml"] == "tools: {}\n"
    assert payload["extra_files"]["knowledge/README.md"] == "# Knowledge\n"
    assert payload["advanced_fields"]["customer"]["adapter"] == "./customer_adapter.py"


def test_draft_agent_is_editable_state_not_a_published_version() -> None:
    draft = DraftAgent(
        agent_id="enterprise_qa",
        draft_id="draft_001",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_contract_bundle(),
        created_at="2026-05-27T00:00:00Z",
        updated_at="2026-05-27T00:00:00Z",
        created_by="local-user",
        updated_by="local-user",
    )

    assert draft.agent_id == "enterprise_qa"
    assert draft.draft_id == "draft_001"
    assert draft.version_id is None
    assert draft.validation_records == ()


def test_published_agent_version_requires_validation_run_id() -> None:
    version = PublishedAgentVersion(
        agent_id="enterprise_qa",
        version_id="version_001",
        source_draft_id="draft_001",
        validation_run_id="run_validation_001",
        contract_bundle=_contract_bundle(),
        published_at="2026-05-27T00:05:00Z",
        published_by="local-user",
    )

    assert version.validation_run_id == "run_validation_001"
    assert version.source_draft_id == "draft_001"

    with pytest.raises(ValidationError):
        PublishedAgentVersion(
            agent_id="enterprise_qa",
            version_id="version_002",
            source_draft_id="draft_001",
            validation_run_id="",
            contract_bundle=_contract_bundle(),
            published_at="2026-05-27T00:06:00Z",
            published_by="local-user",
        )


def test_active_agent_version_points_at_immutable_version() -> None:
    active = ActiveAgentVersion(
        agent_id="enterprise_qa",
        version_id="version_001",
        activated_at="2026-05-27T00:10:00Z",
        activated_by="publisher",
        rollback_from_version_id="version_002",
    )

    assert active.version_id == "version_001"
    assert active.rollback_from_version_id == "version_002"


def test_sources_are_reusable_assets_not_agent_bindings() -> None:
    knowledge = KnowledgeSource(
        source_id="ks_local_docs",
        name="Local Docs",
        provider="local_markdown",
        params={"path": "./knowledge"},
        created_at="2026-05-27T00:00:00Z",
        updated_at="2026-05-27T00:00:00Z",
    )
    tool = ToolSource(
        source_id="ts_local_tools",
        name="Local Fixture Tools",
        source_type="local_handler_package",
        tool_contract_ids=("policy_status_lookup", "claim_status_lookup"),
        params={"root": "./tools"},
        created_at="2026-05-27T00:00:00Z",
        updated_at="2026-05-27T00:00:00Z",
    )

    assert knowledge.provider == "local_markdown"
    assert knowledge.params["path"] == "./knowledge"
    assert tool.tool_contract_ids == ("policy_status_lookup", "claim_status_lookup")


def test_validation_record_links_draft_to_governed_run() -> None:
    record = AgentValidationRecord(
        validation_id="validation_001",
        draft_id="draft_001",
        run_id="run_validation_001",
        status="passed",
        created_at="2026-05-27T00:00:00Z",
        summary="Contract validation and test run passed.",
    )

    assert record.run_id == "run_validation_001"
    assert record.errors == ()


def test_configuration_operation_audit_is_json_serializable() -> None:
    audit = ConfigurationOperationAudit(
        operation_id="op_001",
        operation=ConfigurationOperation.IMPORTED,
        actor="local-user",
        created_at="2026-05-27T00:00:00Z",
        summary="Imported proof_agent/evaluation/demo/fixtures/enterprise_qa.",
        metadata={"source_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"},
    )

    payload = audit.model_dump(mode="json")

    assert payload["operation"] == "imported"
    assert payload["metadata"]["source_path"] == "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"


def test_configuration_contracts_are_frozen() -> None:
    draft = DraftAgent(
        agent_id="enterprise_qa",
        draft_id="draft_001",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_contract_bundle(),
        created_at="2026-05-27T00:00:00Z",
        updated_at="2026-05-27T00:00:00Z",
        created_by="local-user",
        updated_by="local-user",
    )

    with pytest.raises(ValidationError):
        draft.display_name = "Changed"  # type: ignore[misc]
