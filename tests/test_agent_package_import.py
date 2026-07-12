"""Tests for importing reviewable Agent Packages into Draft Agents."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest
import yaml

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.errors import ProofAgentError


def test_import_agent_package_creates_draft_without_modifying_source(tmp_path: Path) -> None:
    fixture_dir = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3")
    manifest_path = fixture_dir / "agent.yaml"
    before_agent_yaml = manifest_path.read_text(encoding="utf-8")
    policy_path = fixture_dir / "policy.yaml"
    before_policy_yaml = policy_path.read_text(encoding="utf-8")
    store = LocalAgentConfigurationStore(tmp_path / "config")

    draft = import_agent_package(manifest_path, store=store, actor="local-user")

    assert draft.agent_id == "react_enterprise_qa_v3"
    assert draft.display_name == "react_enterprise_qa_v3"
    assert "Controlled ReAct Loop" in draft.purpose
    assert draft.contract_bundle.agent_yaml == before_agent_yaml
    assert draft.contract_bundle.policy_yaml == before_policy_yaml
    assert draft.contract_bundle.tools_yaml == ""
    assert "knowledge/customer-support-policy.md" in draft.contract_bundle.extra_files
    assert manifest_path.read_text(encoding="utf-8") == before_agent_yaml
    assert policy_path.read_text(encoding="utf-8") == before_policy_yaml


def test_import_preserves_advanced_sections_for_contract_view(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")

    draft = import_agent_package(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
        store=store,
        actor="local-user",
    )

    assert draft.agent_id == "react_enterprise_qa_v3"
    assert draft.contract_bundle.advanced_fields["react"]["max_steps"] == 5
    assert draft.contract_bundle.advanced_fields["review"]["mode"] == "auto"
    assert draft.contract_bundle.advanced_fields["response"]["include_review_results"] is False


def test_compile_draft_agent_writes_valid_agent_package(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
        store=store,
        actor="local-user",
    )

    package_dir = compile_draft_agent(draft, tmp_path / "compiled")

    assert (package_dir / "agent.yaml").read_text(
        encoding="utf-8"
    ) == draft.contract_bundle.agent_yaml
    assert (package_dir / "policy.yaml").read_text(
        encoding="utf-8"
    ) == draft.contract_bundle.policy_yaml
    assert (package_dir / "tools.yaml").read_text(encoding="utf-8") == ""
    assert (package_dir / "knowledge" / "customer-support-policy.md").exists()

    manifest = load_agent_manifest(package_dir / "agent.yaml")

    assert manifest.name == "react_enterprise_qa_v3"
    assert manifest.package_knowledge_sources[0].provider == "local_markdown"
    assert (
        manifest.knowledge_bindings[0].source_ref.source_id
        == manifest.package_knowledge_sources[0].source_id
    )


def test_import_rejects_local_python_tool_handlers(tmp_path: Path) -> None:
    package_dir = tmp_path / "agent"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        package_dir,
    )
    manifest_path = package_dir / "agent.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["capabilities"]["tools"] = {"enabled": True, "file": "./tools.yaml"}
    raw["react"]["max_tool_calls"] = 1
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    (package_dir / "tools.yaml").write_text(
        """
tools:
  - name: unsafe_local_tool
    handler: ./tools.py:run
    risk_level: low
    requires_approval: false
    read_only: true
    allowed_parameters: []
    denied_parameters: []
""",
        encoding="utf-8",
    )
    (package_dir / "tools.py").write_text("def run(parameters): return {}\n", encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        import_agent_package(
            manifest_path,
            store=LocalAgentConfigurationStore(tmp_path / "config"),
            actor="local-user",
        )

    assert exc.value.code == "PA_TOOL_001"
