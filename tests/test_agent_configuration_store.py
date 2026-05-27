"""Tests for the Local Agent Configuration Store."""

from __future__ import annotations

import json
from pathlib import Path

from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ContractBundle


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
    assert json.loads((version_dir / "publication.json").read_text(encoding="utf-8"))[
        "validation_run_id"
    ] == "run_validation_001"


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
        tmp_path
        / "agents"
        / "enterprise_qa"
        / "versions"
        / version_two.version_id
        / "agent.yaml"
    ).read_text(encoding="utf-8") == "name: enterprise_qa_v2\n"
