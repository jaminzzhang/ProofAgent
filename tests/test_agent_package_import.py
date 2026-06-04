"""Tests for importing reviewable Agent Packages into Draft Agents."""

from __future__ import annotations

from pathlib import Path

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore


def test_import_agent_package_creates_draft_without_modifying_source(tmp_path: Path) -> None:
    manifest_path = Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml")
    before_agent_yaml = manifest_path.read_text(encoding="utf-8")
    before_policy_yaml = Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/policy.yaml").read_text(encoding="utf-8")
    store = LocalAgentConfigurationStore(tmp_path / "config")

    draft = import_agent_package(manifest_path, store=store, actor="local-user")

    assert draft.agent_id == "enterprise_qa"
    assert draft.display_name == "enterprise_qa"
    assert draft.purpose == "Answer enterprise knowledge questions only when evidence supports the answer."
    assert draft.contract_bundle.agent_yaml == before_agent_yaml
    assert draft.contract_bundle.policy_yaml == before_policy_yaml
    assert draft.contract_bundle.tools_yaml.startswith("tools:")
    assert "knowledge/customer-support-policy.md" in draft.contract_bundle.extra_files
    assert manifest_path.read_text(encoding="utf-8") == before_agent_yaml
    assert Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/policy.yaml").read_text(encoding="utf-8") == before_policy_yaml


def test_import_preserves_advanced_sections_for_contract_view(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")

    draft = import_agent_package(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"),
        store=store,
        actor="local-user",
    )

    assert draft.agent_id == "react_enterprise_qa"
    assert draft.contract_bundle.advanced_fields["react"]["max_steps"] == 5
    assert draft.contract_bundle.advanced_fields["review"]["mode"] == "auto"
    assert draft.contract_bundle.advanced_fields["response"]["include_review_results"] is False


def test_compile_draft_agent_writes_valid_agent_package(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"), store=store, actor="local-user")

    package_dir = compile_draft_agent(draft, tmp_path / "compiled")

    assert (package_dir / "agent.yaml").read_text(encoding="utf-8") == draft.contract_bundle.agent_yaml
    assert (package_dir / "policy.yaml").read_text(encoding="utf-8") == draft.contract_bundle.policy_yaml
    assert (package_dir / "tools.yaml").read_text(encoding="utf-8") == draft.contract_bundle.tools_yaml
    assert (package_dir / "knowledge" / "customer-support-policy.md").exists()

    manifest = load_agent_manifest(package_dir / "agent.yaml")

    assert manifest.name == "enterprise_qa"
    assert manifest.package_knowledge_sources[0].provider == "local_markdown"
    assert manifest.knowledge_bindings[0].source_ref.source_id == manifest.package_knowledge_sources[0].source_id
