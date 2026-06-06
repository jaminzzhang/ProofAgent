from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    ContractBundle,
    EnvironmentModelCredentialReference,
    SharedModelConnectionLifecycleState,
)
from proof_agent.errors import ProofAgentError


def _configuration_audit_payloads(root: Path) -> list[dict[str, object]]:
    audit_root = root / "configuration_audit"
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(audit_root.glob("*.json"))
    ]


def _create_connection(
    store: LocalAgentConfigurationStore,
    *,
    connection_id: str = "model_deepseek_default",
) -> None:
    store.create_model_connection(
        connection_id=connection_id,
        display_name="DeepSeek Default",
        provider="deepseek",
        model_identifier="deepseek-chat",
        base_url="https://api.deepseek.com",
        credential_ref=EnvironmentModelCredentialReference(name="DEEPSEEK_API_KEY"),
        timeout_seconds=20,
        actor="operator",
    )


def _agent_yaml_with_shared_model(connection_id: str) -> str:
    return f"""
name: enterprise_qa
model:
  model_source: shared
  connection_id: {connection_id}
react:
  planner:
    model_source: shared
    connection_id: {connection_id}
review:
  subagent:
    model_source: shared
    connection_id: other_model
knowledge:
  ignored: true
"""


def test_create_list_get_and_persist_model_connection(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    created = store.create_model_connection(
        display_name="DeepSeek Default",
        provider="deepseek",
        model_identifier="deepseek-chat",
        credential_ref=EnvironmentModelCredentialReference(name="DEEPSEEK_API_KEY"),
        actor="operator",
    )
    explicit = store.create_model_connection(
        connection_id="model_openai_default",
        display_name="OpenAI Default",
        provider="openai",
        model_identifier="gpt-4.1-mini",
        credential_ref=EnvironmentModelCredentialReference(name="OPENAI_API_KEY"),
        actor="operator",
    )

    loaded = store.get_model_connection(created.connection_id)
    listed = store.list_model_connections()

    assert created.connection_id.startswith("model_")
    assert created.lifecycle_state is SharedModelConnectionLifecycleState.ACTIVE
    assert loaded == created
    assert [connection.connection_id for connection in listed] == [
        created.connection_id,
        explicit.connection_id,
    ]
    payload = json.loads(
        (tmp_path / "model_connections" / created.connection_id / "connection.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["credential_ref"] == {"type": "env", "name": "DEEPSEEK_API_KEY"}
    assert "api_key" not in payload


def test_model_connection_create_rejects_duplicate_and_unsafe_ids(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_connection(store)

    with pytest.raises(ValueError):
        _create_connection(store)

    with pytest.raises(ProofAgentError) as invalid_id:
        store.create_model_connection(
            connection_id="../escape",
            display_name="Escape",
            provider="deepseek",
            model_identifier="deepseek-chat",
            credential_ref=EnvironmentModelCredentialReference(name="DEEPSEEK_API_KEY"),
            actor="operator",
        )

    assert invalid_id.value.code == "PA_CONFIG_001"


def test_archive_restore_and_physical_delete_model_connection(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_connection(store)

    active_eligibility = store.get_model_connection_deletion_eligibility("model_deepseek_default")
    assert active_eligibility.eligible is False
    assert active_eligibility.blockers == ("connection_not_archived",)

    with pytest.raises(ProofAgentError) as active_delete:
        store.physically_delete_model_connection(
            connection_id="model_deepseek_default",
            actor="operator",
            reason="Cleanup test.",
        )
    assert active_delete.value.code == "PA_CONFIG_002"

    archived = store.archive_model_connection(
        connection_id="model_deepseek_default",
        actor="operator",
        reason="No longer used.",
    )
    restored = store.restore_model_connection(
        connection_id="model_deepseek_default",
        actor="operator",
    )
    archived_again = store.archive_model_connection(
        connection_id="model_deepseek_default",
        actor="operator",
        reason="Delete fixture.",
    )
    deleted = store.physically_delete_model_connection(
        connection_id="model_deepseek_default",
        actor="operator",
        reason="Delete fixture.",
    )

    assert archived.lifecycle_state is SharedModelConnectionLifecycleState.ARCHIVED
    assert restored.lifecycle_state is SharedModelConnectionLifecycleState.ACTIVE
    assert archived_again.lifecycle_state is SharedModelConnectionLifecycleState.ARCHIVED
    assert deleted.eligible is True
    assert store.get_model_connection("model_deepseek_default") is None
    physical_delete_audits = [
        payload
        for payload in _configuration_audit_payloads(tmp_path)
        if payload["operation"] == "physical_deleted"
    ]
    assert physical_delete_audits[0]["metadata"]["connection_id"] == "model_deepseek_default"


def test_model_connection_reference_summary_counts_configuration_references(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_connection(store)
    _create_connection(store, connection_id="other_model")
    draft = store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions.",
        contract_bundle=ContractBundle(
            agent_yaml=_agent_yaml_with_shared_model("model_deepseek_default"),
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
    )
    store.create_knowledge_source(
        source_id="ks_policy",
        name="Policies",
        provider="local_index",
        params={
            "snapshot_path": "./snapshots/policy",
            "artifact_root": "./artifacts",
            "ingestion_model": {
                "model_source": "shared",
                "connection_id": "model_deepseek_default",
            },
            "routing_model": {
                "model_source": "shared",
                "connection_id": "other_model",
            },
        },
        actor="operator",
    )

    summary = store.get_model_connection_reference_summary("model_deepseek_default")

    assert summary.draft_agent_reference_count == 2
    assert summary.published_agent_version_reference_count == 1
    assert summary.knowledge_source_reference_count == 1


def test_physical_delete_blocks_model_connection_with_references(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_connection(store)
    store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions.",
        contract_bundle=ContractBundle(
            agent_yaml=_agent_yaml_with_shared_model("model_deepseek_default"),
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="operator",
    )
    store.archive_model_connection(
        connection_id="model_deepseek_default",
        actor="operator",
        reason="Delete test.",
    )

    eligibility = store.get_model_connection_deletion_eligibility("model_deepseek_default")

    assert eligibility.eligible is False
    assert eligibility.blockers == ("draft_agent_references",)
    with pytest.raises(ProofAgentError) as blocked:
        store.physically_delete_model_connection(
            connection_id="model_deepseek_default",
            actor="operator",
            reason="Delete test.",
        )
    assert blocked.value.code == "PA_CONFIG_002"
