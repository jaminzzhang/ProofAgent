from pathlib import Path

import pytest

from proof_agent.bootstrap import compose_harness_invocation
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    EnvironmentModelCredentialReference,
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


def test_compose_harness_invocation_resolves_enterprise_qa_dependencies() -> None:
    invocation = compose_harness_invocation(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml")
    )

    assert invocation.manifest.name == "enterprise_qa"
    assert invocation.template.name == "enterprise_qa"
    assert invocation.model_provider.provider_name == "deterministic"
    assert invocation.knowledge_provider.provider_name == "local_markdown"
    assert "customer_lookup" in invocation.tool_gateway.tools
    assert invocation.react_planner is None
    assert invocation.review_subagent is None

    memory = invocation.create_memory()
    memory_result = memory.write({"summary": "Question: sample"})
    assert memory_result.status == "passed"


def test_unknown_workflow_template_fails_from_registry() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_workflow_template("unknown_template")

    assert exc.value.code == "PA_CONFIG_002"


def test_react_workflow_template_resolves_from_registry() -> None:
    template = resolve_workflow_template("react_enterprise_qa")

    assert template.name == "react_enterprise_qa"


def test_compose_harness_invocation_resolves_react_dependencies() -> None:
    invocation = compose_harness_invocation(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
    )

    assert invocation.template.name == "react_enterprise_qa"
    assert invocation.react_planner is not None
    assert invocation.review_subagent is not None


def test_compose_harness_invocation_blends_multiple_knowledge_bindings(tmp_path: Path) -> None:
    source_one = tmp_path / "knowledge_one"
    source_two = tmp_path / "knowledge_two"
    source_one.mkdir()
    source_two.mkdir()
    (source_one / "alpha.md").write_text(
        "# Alpha\nAlpha travel meals need receipts.\n", encoding="utf-8"
    )
    (source_two / "beta.md").write_text(
        "# Beta\nBeta support policy needs receipts.\n", encoding="utf-8"
    )
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: blended_qa
purpose: "Blend two knowledge sources."
workflow:
  runtime: langgraph
  template: enterprise_qa
package_knowledge_sources:
  - source_id: ks_alpha
    name: Alpha Knowledge
    provider: local_markdown
    params:
      path: ./knowledge_one
  - source_id: ks_beta
    name: Beta Knowledge
    provider: local_markdown
    params:
      path: ./knowledge_two
knowledge_bindings:
  - binding_id: kb_alpha
    source_ref:
      scope: package
      source_id: ks_alpha
    fusion_weight: 1.0
  - binding_id: kb_beta
    source_ref:
      scope: package
      source_id: ks_beta
    fusion_weight: 1.0
retrieval:
  strategy: single_step
  top_k: 4
  min_score: 0.1
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
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    invocation = compose_harness_invocation(agent_yaml)
    chunks = invocation.knowledge_provider.retrieve("alpha beta receipts", top_k=4)

    assert invocation.knowledge_provider.provider_name == "mixed"
    assert {chunk.source_id for chunk in chunks} == {"ks_alpha", "ks_beta"}
    assert {chunk.binding_id for chunk in chunks} == {"kb_alpha", "kb_beta"}
    assert all(chunk.fusion_rank is not None for chunk in chunks)
    assert all(chunk.admission_score is not None for chunk in chunks)


def test_compose_harness_invocation_accepts_precomputed_resolved_bindings(
    tmp_path: Path,
) -> None:
    source_one = tmp_path / "knowledge_one"
    source_one.mkdir()
    (source_one / "alpha.md").write_text(
        "# Alpha\nAlpha travel meals need receipts.\n", encoding="utf-8"
    )
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: precomputed_qa
purpose: "Use precomputed resolved Knowledge bindings."
workflow:
  runtime: langgraph
  template: enterprise_qa
package_knowledge_sources: []
knowledge_bindings:
  - binding_id: kb_alpha
    source_ref:
      scope: shared
      source_id: ks_alpha
retrieval:
  strategy: single_step
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
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )
    resolved = ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeBinding(
                binding_id="kb_alpha",
                source_scope="shared",
                source_id="ks_alpha",
                source_version_id="snapshot_001",
                provider="local_markdown",
                provider_params={"path": source_one},
                failure_mode="required",
                fusion_weight=1.0,
            ),
        )
    )

    invocation = compose_harness_invocation(
        agent_yaml,
        resolved_knowledge_bindings=resolved,
    )

    assert invocation.resolved_knowledge_bindings == resolved
    assert invocation.knowledge_provider.provider_name == "local_markdown"


def test_compose_harness_invocation_resolves_retrieval_model_connections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODEL_KEY", "test-key")
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "policy.md").write_text(
        "# Policy\nTravel meals need receipts.\n", encoding="utf-8"
    )
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: retrieval_model_connection_qa
purpose: "Resolve retrieval control-plane models."
workflow:
  runtime: langgraph
  template: enterprise_qa
package_knowledge_sources:
  - source_id: ks_local
    name: Local Knowledge
    provider: local_markdown
    params:
      path: ./knowledge
knowledge_bindings:
  - binding_id: kb_local
    source_ref:
      scope: package
      source_id: ks_local
retrieval:
  strategy: agentic
  max_steps: 3
  planner_model:
    model_source: shared
    connection_id: model_retrieval
    params:
      timeout_seconds: 3
  evaluator_model:
    model_source: shared
    connection_id: model_retrieval
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
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_model_connection(
        connection_id="model_retrieval",
        display_name="Retrieval Model",
        provider="deterministic",
        model_identifier="retrieval-model",
        credential_ref=EnvironmentModelCredentialReference(name="DEMO_MODEL_KEY"),
        timeout_seconds=9,
        actor="operator",
    )

    invocation = compose_harness_invocation(agent_yaml, configuration_store=store)

    assert invocation.retrieval_planner_model is not None
    assert invocation.retrieval_planner_model.name == "retrieval-model"
    assert invocation.retrieval_planner_model.params["timeout_seconds"] == 3
    assert invocation.retrieval_evaluator_model is not None
    assert invocation.retrieval_evaluator_model.params["timeout_seconds"] == 9
    roles = {record.role.value for record in invocation.model_resolution_records}
    assert {"final_answer", "retrieval_planner", "retrieval_evaluator"}.issubset(roles)
