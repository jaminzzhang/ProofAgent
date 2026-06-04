from __future__ import annotations

from pathlib import Path

import pytest

from proof_agent.bootstrap.knowledge_resolution import PackageKnowledgeBindingResolver
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.errors import ProofAgentError


def test_package_resolver_resolves_package_source(tmp_path: Path) -> None:
    agent_yaml = _write_agent_manifest(tmp_path, source_ref_scope="package")

    resolved = PackageKnowledgeBindingResolver().resolve(load_agent_manifest(agent_yaml))

    binding = resolved.bindings[0]
    assert binding.binding_id == "kb_local"
    assert binding.source_scope == "package"
    assert binding.source_id == "ks_local"
    assert binding.source_version_id == "package"
    assert binding.provider == "local_markdown"
    assert binding.provider_params["path"] == (tmp_path / "knowledge").resolve()
    assert binding.alias == "policy_docs"
    assert binding.failure_mode == "required"
    assert binding.fusion_weight == 1.25
    assert binding.top_k == 2


def test_package_resolver_rejects_shared_source_ref(tmp_path: Path) -> None:
    agent_yaml = _write_agent_manifest(
        tmp_path,
        source_ref_scope="shared",
        package_sources_yaml="package_knowledge_sources: []",
    )

    with pytest.raises(ProofAgentError) as exc:
        PackageKnowledgeBindingResolver().resolve(load_agent_manifest(agent_yaml))

    assert exc.value.code == "PA_CONFIG_002"
    assert "Configuration Store resolver" in exc.value.fix


def _write_agent_manifest(
    tmp_path: Path,
    *,
    source_ref_scope: str,
    package_sources_yaml: str | None = None,
) -> Path:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    if package_sources_yaml is None:
        package_sources_yaml = """
package_knowledge_sources:
  - source_id: ks_local
    name: Local Knowledge
    provider: local_markdown
    params:
      path: ./knowledge
"""
    agent_yaml.write_text(
        f"""
name: resolver_test
purpose: "Resolve Knowledge bindings."
workflow:
  runtime: langgraph
  template: enterprise_qa
{package_sources_yaml}
knowledge_bindings:
  - binding_id: kb_local
    source_ref:
      scope: {source_ref_scope}
      source_id: ks_local
    alias: policy_docs
    failure_mode: required
    fusion_weight: 1.25
    top_k: 2
retrieval:
  strategy: single_step
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
tools:
  file: ./tools.yaml
memory:
  provider: session
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )
    return agent_yaml
