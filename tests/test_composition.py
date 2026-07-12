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


def test_compose_harness_invocation_resolves_v3_dependencies() -> None:
    invocation = compose_harness_invocation(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )

    assert invocation.manifest.name == "react_enterprise_qa_v3"
    assert invocation.template.name == "react_enterprise_qa_v3"
    assert invocation.model_provider.provider_name == "deterministic"
    assert invocation.knowledge_provider.provider_name == "local_markdown"
    assert invocation.tool_gateway.tools == {}
    assert invocation.react_planner is not None
    assert invocation.review_subagent is not None

    memory = invocation.create_memory()
    memory_result = memory.write({"summary": "Question: sample"})
    assert memory_result.status == "passed"


def test_unknown_workflow_template_fails_from_registry() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_workflow_template("unknown_template")

    assert exc.value.code == "PA_CONFIG_002"


def test_react_workflow_template_resolves_from_registry() -> None:
    template = resolve_workflow_template("react_enterprise_qa_v3")

    assert template.name == "react_enterprise_qa_v3"


def test_compose_harness_invocation_resolves_react_dependencies() -> None:
    invocation = compose_harness_invocation(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )

    assert invocation.template.name == "react_enterprise_qa_v3"
    assert invocation.react_planner is not None
    assert invocation.review_subagent is not None


def test_compose_harness_invocation_loads_business_flow_skill_packs(
    tmp_path: Path,
) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "claims.md").write_text(
        "# Claims\nClaims questions require evidence-backed answers.\n",
        encoding="utf-8",
    )
    (tmp_path / "policy.yaml").write_text(
        """
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answers require evidence."
""",
        encoding="utf-8",
    )
    pack_dir = tmp_path / "skill_packs"
    pack_dir.mkdir()
    (pack_dir / "claims.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - "claim status"
stage_prompt_addenda:
  plan:
    task_instructions:
      - "Prefer retrieval before answering claim process questions."
knowledge_binding_refs:
  - kb_local
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission:
  min_confidence: 0.6
""",
        encoding="utf-8",
    )
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: skill_pack_composition
purpose: "Compose Business Flow Skill Packs."
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
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
        definition: ./skill_packs/claims.yaml
        default: true
react:
  planner:
    provider: deterministic
    name: demo
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    invocation = compose_harness_invocation(agent_yaml)

    assert len(invocation.business_flow_skill_packs) == 1
    skill_pack = invocation.business_flow_skill_packs[0]
    assert skill_pack.id == "claims_qa"
    assert skill_pack.label == "Claims QA"
    assert skill_pack.stage_prompt_addenda["plan"].task_instructions == (
        "Prefer retrieval before answering claim process questions.",
    )
    assert skill_pack.knowledge_binding_refs == ("kb_local",)
    assert skill_pack.policy_rule_refs == ("answering.require_retrieval",)
    assert skill_pack.admission.min_confidence == 0.6


def test_compose_harness_invocation_rejects_unknown_business_flow_knowledge_refs(
    tmp_path: Path,
) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "claims.md").write_text(
        "# Claims\nClaims questions require evidence-backed answers.\n",
        encoding="utf-8",
    )
    (tmp_path / "policy.yaml").write_text(
        """
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answers require evidence."
""",
        encoding="utf-8",
    )
    pack_dir = tmp_path / "skill_packs"
    pack_dir.mkdir()
    (pack_dir / "claims.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - "claim status"
stage_prompt_addenda: {}
knowledge_binding_refs:
  - missing_binding
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission: {}
""",
        encoding="utf-8",
    )
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: skill_pack_unknown_ref
purpose: "Reject unknown Business Flow Skill Pack refs."
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
react:
  planner:
    provider: deterministic
    name: demo
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
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: ./skill_packs/claims.yaml
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        compose_harness_invocation(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "unknown Business Flow Skill Pack knowledge_binding_refs" in exc.value.message
    assert "missing_binding" in exc.value.message


def test_compose_harness_invocation_rejects_unknown_business_flow_policy_refs(
    tmp_path: Path,
) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "claims.md").write_text(
        "# Claims\nClaims questions require evidence-backed answers.\n",
        encoding="utf-8",
    )
    (tmp_path / "policy.yaml").write_text(
        """
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answers require evidence."
""",
        encoding="utf-8",
    )
    pack_dir = tmp_path / "skill_packs"
    pack_dir.mkdir()
    (pack_dir / "claims.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - "claim status"
stage_prompt_addenda: {}
knowledge_binding_refs:
  - kb_local
tool_contract_refs: []
policy_rule_refs:
  - missing.policy.rule
validator_refs: []
admission: {}
""",
        encoding="utf-8",
    )
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: skill_pack_unknown_policy_ref
purpose: "Reject unknown Business Flow Skill Pack policy refs."
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
react:
  planner:
    provider: deterministic
    name: demo
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
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: ./skill_packs/claims.yaml
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        compose_harness_invocation(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "unknown Business Flow Skill Pack policy_rule_refs" in exc.value.message
    assert "missing.policy.rule" in exc.value.message


def test_compose_harness_invocation_rejects_business_flow_tool_refs_when_tools_disabled(
    tmp_path: Path,
) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "claims.md").write_text(
        "# Claims\nClaims questions require evidence-backed answers.\n",
        encoding="utf-8",
    )
    (tmp_path / "policy.yaml").write_text(
        """
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answers require evidence."
""",
        encoding="utf-8",
    )
    pack_dir = tmp_path / "skill_packs"
    pack_dir.mkdir()
    (pack_dir / "claims.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - "claim status"
stage_prompt_addenda: {}
knowledge_binding_refs:
  - kb_local
tool_contract_refs:
  - customer_lookup
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission: {}
""",
        encoding="utf-8",
    )
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: skill_pack_disabled_tool_ref
purpose: "Reject tool refs when tools are disabled."
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
react:
  planner:
    provider: deterministic
    name: demo
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
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: ./skill_packs/claims.yaml
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        compose_harness_invocation(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "tool_contract_refs require capabilities.tools.enabled" in exc.value.message


def test_compose_harness_invocation_rejects_unknown_business_flow_validator_refs(
    tmp_path: Path,
) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "claims.md").write_text(
        "# Claims\nClaims questions require evidence-backed answers.\n",
        encoding="utf-8",
    )
    (tmp_path / "policy.yaml").write_text(
        """
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answers require evidence."
""",
        encoding="utf-8",
    )
    pack_dir = tmp_path / "skill_packs"
    pack_dir.mkdir()
    (pack_dir / "claims.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - "claim status"
stage_prompt_addenda: {}
knowledge_binding_refs:
  - kb_local
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs:
  - missing_validator
admission: {}
""",
        encoding="utf-8",
    )
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: skill_pack_unknown_validator_ref
purpose: "Reject unknown Business Flow Skill Pack validator refs."
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
react:
  planner:
    provider: deterministic
    name: demo
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
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: ./skill_packs/claims.yaml
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        compose_harness_invocation(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "unknown Business Flow Skill Pack validator_refs" in exc.value.message
    assert "missing_validator" in exc.value.message


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
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
react:
  planner:
    provider: deterministic
    name: demo
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
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
react:
  planner:
    provider: deterministic
    name: demo
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
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
react:
  planner:
    provider: deterministic
    name: demo
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
