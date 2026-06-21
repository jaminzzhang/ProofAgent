from pathlib import Path

import pytest

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.errors import ProofAgentError


def test_load_valid_enterprise_qa_manifest() -> None:
    manifest = load_agent_manifest(Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"))
    assert manifest.name == "enterprise_qa"
    assert manifest.workflow.runtime == "langgraph"
    assert manifest.workflow.checkpointer is not None
    assert manifest.workflow.checkpointer.provider == "sqlite"
    assert manifest.workflow.checkpointer.uri == "memory"
    assert manifest.package_knowledge_sources[0].provider == "local_markdown"
    assert manifest.package_knowledge_sources[0].params["path"].name == "knowledge"
    assert manifest.knowledge_bindings[0].source_ref.scope == "package"
    assert (
        manifest.knowledge_bindings[0].source_ref.source_id
        == manifest.package_knowledge_sources[0].source_id
    )
    assert manifest.retrieval.strategy == "single_step"
    assert manifest.retrieval.top_k == 2
    assert manifest.retrieval.min_score == 0.2


def test_load_valid_react_enterprise_qa_v2_manifest() -> None:
    manifest = load_agent_manifest(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2/agent.yaml")
    )

    assert manifest.name == "react_enterprise_qa_v2"
    assert manifest.workflow.template == "react_enterprise_qa_v2"
    assert manifest.workflow.template_descriptor_version == "react_enterprise_qa.v2"
    assert manifest.react is not None
    assert manifest.react.planner.provider == "deterministic"


def test_loads_business_flow_skill_pack_bindings(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    pack_dir = tmp_path / "skill_packs"
    pack_dir.mkdir()
    pack_definition = pack_dir / "claims.yaml"
    pack_definition.write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claims questions.
intent_patterns:
  - "claim status"
stage_prompt_addenda: {}
knowledge_binding_refs:
  - kb_local
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission: {}
""",
        encoding="utf-8",
    )
    agent_yaml.write_text(
        """
name: skill_pack_manifest
purpose: "Load package-local business flow skill pack bindings."
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
    admission:
      route_min_confidence: 0.72
    business_flows:
      - id: claims_qa
        definition: ./skill_packs/claims.yaml
        default: true
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.capabilities.skills.enabled is True
    assert manifest.capabilities.skills.admission.route_min_confidence == 0.72
    assert len(manifest.capabilities.skills.business_flows) == 1
    binding = manifest.capabilities.skills.business_flows[0]
    assert binding.id == "claims_qa"
    assert binding.definition == pack_definition.resolve()
    assert binding.default is True


def test_rejects_unknown_skills_admission_field(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    pack_dir = tmp_path / "skill_packs"
    pack_dir.mkdir()
    (pack_dir / "claims.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claims questions.
stage_prompt_addenda: {}
admission: {}
""",
        encoding="utf-8",
    )
    agent_yaml.write_text(
        """
name: invalid_skill_admission_manifest
purpose: "Reject misplaced Skill Pack admission fields."
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
    admission:
      route_min_confidence: 0.72
      candidate_min_confidence: 0.5
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
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_SCHEMA_001"
    assert "candidate_min_confidence" in exc.value.message


def test_rejects_business_flow_skill_packs_when_skills_disabled(
    tmp_path: Path,
) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    pack_dir = tmp_path / "skill_packs"
    pack_dir.mkdir()
    (pack_dir / "claims.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claims questions.
stage_prompt_addenda: {}
admission: {}
""",
        encoding="utf-8",
    )
    agent_yaml.write_text(
        """
name: disabled_skill_pack_manifest
purpose: "Reject configured Skill Packs when skills are disabled."
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
    enabled: false
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
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "business_flows cannot be set when skills are disabled" in exc.value.message


def test_rejects_missing_business_flow_skill_pack_definition(
    tmp_path: Path,
) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: missing_skill_pack_manifest
purpose: "Reject missing Skill Pack definitions."
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
        definition: ./skill_packs/missing.yaml
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "capabilities.skills.business_flows[claims_qa].definition does not exist" in (
        exc.value.message
    )


def test_loads_source_owned_knowledge_bindings(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: source_owned
purpose: "Source-owned knowledge config."
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
    alias: policy_docs
    failure_mode: required
    fusion_weight: 1.25
    top_k: 2
retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2
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

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.package_knowledge_sources[0].source_id == "ks_local"
    assert manifest.package_knowledge_sources[0].provider == "local_markdown"
    assert manifest.package_knowledge_sources[0].params["path"] == (tmp_path / "knowledge").resolve()
    assert manifest.knowledge_bindings[0].binding_id == "kb_local"
    assert manifest.knowledge_bindings[0].source_ref.scope == "package"
    assert manifest.knowledge_bindings[0].source_ref.source_id == "ks_local"
    assert manifest.knowledge_bindings[0].alias == "policy_docs"
    assert manifest.knowledge_bindings[0].failure_mode == "required"
    assert manifest.knowledge_bindings[0].fusion_weight == 1.25
    assert manifest.knowledge_bindings[0].top_k == 2


def test_legacy_knowledge_sources_field_is_rejected(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: legacy_source_field
purpose: "Legacy source field should be rejected."
workflow:
  runtime: langgraph
  template: enterprise_qa
knowledge_sources:
  - source_id: ks_local
    name: Local Knowledge
    provider: local_markdown
    params:
      path: ./knowledge
knowledge_bindings:
  - binding_id: kb_local
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
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "package_knowledge_sources" in exc.value.fix
    assert "source_ref" in exc.value.fix


@pytest.mark.parametrize("legacy_provider", ["pageindex", "local_vector"])
def test_legacy_knowledge_providers_are_rejected(tmp_path: Path, legacy_provider: str) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "index").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        f"""
name: legacy_provider
purpose: "Legacy provider should be rejected."
workflow:
  runtime: langgraph
  template: enterprise_qa
package_knowledge_sources:
  - source_id: ks_legacy
    name: Legacy Knowledge
    provider: {legacy_provider}
    params:
      endpoint_env: PAGEINDEX_BASE_URL
      document_id: doc_enterprise_policy
      index_path: ./index
      collection_name: legacy
      embedding_model: all-MiniLM-L6-v2
knowledge_bindings:
  - binding_id: kb_legacy
    source_ref:
      scope: package
      source_id: ks_legacy
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

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_KNOWLEDGE_001"
    assert f"unsupported knowledge provider: {legacy_provider}" in exc.value.message
    assert "local_index" in exc.value.fix
    assert "pageindex" not in exc.value.fix
    assert "local_vector" not in exc.value.fix


def test_http_json_knowledge_source_loads_with_safe_remote_params(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: http_json_manifest
purpose: "Load remote HTTP JSON knowledge."
workflow:
  runtime: langgraph
  template: enterprise_qa
package_knowledge_sources:
  - source_id: ks_remote
    name: Remote Policies
    provider: http_json
    params:
      endpoint: https://knowledge.example/retrieve
      timeout_seconds: 10
      top_k: 3
      header_env_refs:
        - name: Authorization
          value_env: PA_KNOWLEDGE_TOKEN
          prefix: "Bearer "
      response_mapping:
        results: /matches
        content: /text
        score: /score
        citation: /citation
knowledge_bindings:
  - binding_id: kb_remote
    source_ref:
      scope: package
      source_id: ks_remote
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

    manifest = load_agent_manifest(agent_yaml)

    source = manifest.package_knowledge_sources[0]
    assert source.provider == "http_json"
    assert source.params["endpoint"] == "https://knowledge.example/retrieve"
    assert source.params["header_env_refs"][0]["value_env"] == "PA_KNOWLEDGE_TOKEN"
    assert source.params["response_mapping"]["results"] == "/matches"


def test_local_index_knowledge_source_loads_with_v2_paths(tmp_path: Path) -> None:
    agent_yaml = _write_local_index_manifest(
        tmp_path,
        params="""
      snapshot_path: ./config/knowledge_sources/ks_policy/snapshots/kssnapshot_001
      artifact_root: ./config
      document_selection_budget: 12
""",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.package_knowledge_sources[0].provider == "local_index"
    assert manifest.package_knowledge_sources[0].params["snapshot_path"] == (
        tmp_path / "config" / "knowledge_sources" / "ks_policy" / "snapshots" / "kssnapshot_001"
    ).resolve()
    assert manifest.package_knowledge_sources[0].params["artifact_root"] == (tmp_path / "config").resolve()
    assert manifest.package_knowledge_sources[0].params["document_selection_budget"] == 12


def test_local_index_historical_index_path_is_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_local_index_manifest(
        tmp_path,
        params="""
      index_path: ./indexes/policies
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "snapshot_path" in exc.value.fix
    assert "artifact_root" in exc.value.fix


@pytest.mark.parametrize("document_selection_budget", [0, 21, "8", True])
def test_local_index_document_selection_budget_rejects_invalid_values(
    tmp_path: Path, document_selection_budget: object
) -> None:
    agent_yaml = _write_local_index_manifest(
        tmp_path,
        params=f"""
      snapshot_path: ./config/knowledge_sources/ks_policy/snapshots/kssnapshot_001
      artifact_root: ./config
      document_selection_budget: {document_selection_budget!r}
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "document_selection_budget" in exc.value.message
    assert "document_selection_budget" in exc.value.fix


@pytest.mark.parametrize(
    ("field_name", "invalid_yaml_value"),
    [
        ("snapshot_path", "123"),
        ("snapshot_path", "[./snapshots/kssnapshot_001]"),
        ("artifact_root", "123"),
        ("artifact_root", "{path: ./artifacts}"),
    ],
)
def test_local_index_paths_reject_non_path_values(
    tmp_path: Path, field_name: str, invalid_yaml_value: str
) -> None:
    snapshot_path = "./config/knowledge_sources/ks_policy/snapshots/kssnapshot_001"
    artifact_root = "./config"
    if field_name == "snapshot_path":
        snapshot_path = invalid_yaml_value
    else:
        artifact_root = invalid_yaml_value
    agent_yaml = _write_local_index_manifest(
        tmp_path,
        params=f"""
      snapshot_path: {snapshot_path}
      artifact_root: {artifact_root}
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    expected_field = f"package_knowledge_sources[ks_local_index].params.{field_name}"
    assert exc.value.code == "PA_CONFIG_001"
    assert expected_field in exc.value.message
    assert expected_field in exc.value.fix


def _write_local_index_manifest(tmp_path: Path, *, params: str) -> Path:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        f"""
name: local_index_manifest
purpose: "Local index source config."
workflow:
  runtime: langgraph
  template: enterprise_qa
package_knowledge_sources:
  - source_id: ks_local_index
    name: Local Index Knowledge
    provider: local_index
    params:
{params}
knowledge_bindings:
  - binding_id: kb_local_index
    source_ref:
      scope: package
      source_id: ks_local_index
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
    return agent_yaml


def test_inline_knowledge_provider_is_rejected_after_direct_migration(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: broken
purpose: "Legacy inline knowledge config."
workflow:
  runtime: langgraph
  template: enterprise_qa
knowledge:
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
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "knowledge_bindings" in exc.value.message


def test_missing_policy_file_fails_fast(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: broken
purpose: "Broken manifest."
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
  strategy: single_step
  top_k: 2
  min_score: 0.2
model:
  provider: deterministic
  name: demo
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
""",
        encoding="utf-8",
    )
    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)
    assert exc.value.code == "PA_CONFIG_001"


def test_legacy_knowledge_path_is_rejected(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: broken
purpose: "Broken manifest."
workflow:
  runtime: langgraph
  template: enterprise_qa
knowledge:
  provider: local
  path: ./knowledge
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

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"


def test_loads_react_enterprise_qa_contract(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(tmp_path)

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.workflow.template == "react_enterprise_qa"
    assert manifest.react is not None
    assert manifest.react.max_steps == 5
    # max_plan_rounds defaults to max_steps when not declared (ADR-0032 alias).
    assert manifest.react.max_plan_rounds == 5
    assert manifest.react.max_tool_calls == 1
    assert manifest.react.planner.provider == "deterministic"
    assert manifest.review is not None
    assert manifest.review.mode == "auto"
    assert manifest.review.low_risk_fast_path is True
    assert manifest.review.subagent is not None
    assert manifest.review.subagent.provider == "deterministic"
    assert manifest.response is not None
    assert manifest.response.include_reasoning_summary is False
    assert manifest.response.include_review_results is False


def test_loads_react_review_low_risk_fast_path_override(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(tmp_path)
    agent_yaml.write_text(
        agent_yaml.read_text(encoding="utf-8").replace(
            "review:\n  mode: auto\n",
            "review:\n  mode: auto\n  low_risk_fast_path: false\n",
        ),
        encoding="utf-8",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.review is not None
    assert manifest.review.low_risk_fast_path is False


def test_loads_workflow_stage_prompt_config(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        workflow_extra="""
  template_descriptor_version: react_enterprise_qa.v1
  stages:
    - id: plan
      prompt:
        business_context: "Insurance claim servicing context."
        task_instructions:
          - "Prefer retrieval before final answers."
        output_preferences:
          - "Keep summaries concise."
      context:
        include_agent_purpose: true
""",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.workflow.template_descriptor_version == "react_enterprise_qa.v1"
    assert manifest.workflow.stages[0].id == "plan"
    assert manifest.capabilities.tools.enabled is False
    assert manifest.capabilities.memory.enabled is False
    assert (
        manifest.workflow.stages[0].prompt.business_context
        == "Insurance claim servicing context."
    )
    assert manifest.workflow.stages[0].prompt.task_instructions == (
        "Prefer retrieval before final answers.",
    )
    assert manifest.workflow.stages[0].prompt.output_preferences == (
        "Keep summaries concise.",
    )
    assert manifest.workflow.stages[0].context.options["include_agent_purpose"] is True


def test_rejects_legacy_workflow_nodes(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        workflow_extra="""
  nodes:
    - node_id: plan
      prompt:
        business_context: "Legacy workflow node config."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "workflow.nodes is not supported" in exc.value.message


def test_rejects_workflow_stage_node_id(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        workflow_extra="""
  stages:
    - node_id: plan
      prompt:
        business_context: "Legacy field."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_SCHEMA_001"
    assert "workflow.stages[].node_id is not supported; use id" in exc.value.message


def test_rejects_workflow_stage_stage_id(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        workflow_extra="""
  stages:
    - stage_id: plan
      prompt:
        business_context: "Ambiguous field."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_SCHEMA_001"
    assert "workflow.stages[].stage_id is not supported; use id" in exc.value.message


def test_rejects_legacy_top_level_tools(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        tools_section="""
tools:
  file: ./tools.yaml
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "top-level tools is not supported" in exc.value.message


def test_rejects_legacy_top_level_memory(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        memory_section="""
memory:
  provider: session
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "top-level memory is not supported" in exc.value.message


def test_react_template_requires_explicit_capability_enabled_flags(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        tools_section="",
        memory_section="",
        capabilities_section="""
capabilities:
  tools: {}
  memory:
    enabled: false
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"
    assert "missing capabilities.tools.enabled" in exc.value.message


def test_rejects_disabled_tools_with_active_config(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: false
    file: ./tools.yaml
  memory:
    enabled: false
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "capabilities.tools.file cannot be set when tools are disabled" in exc.value.message


def test_rejects_enabled_tools_without_valid_tool_contract(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: true
    file: ./tools.yaml
  memory:
    enabled: false
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "capabilities.tools requires at least one valid Tool Contract" in exc.value.message


def test_rejects_disabled_memory_with_active_config(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: false
  memory:
    enabled: false
    provider: session
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "capabilities.memory.provider cannot be set when memory is disabled" in exc.value.message


def test_rejects_enabled_memory_without_provider(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "capabilities.memory.provider is required when memory is enabled" in exc.value.message


def test_rejects_scoped_memory_with_no_enabled_scope(tmp_path: Path) -> None:
    agent_yaml = _write_react_stage_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: local
    scopes:
      case:
        enabled: false
      user:
        enabled: false
      shared:
        enabled: false
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "capabilities.memory.scopes requires at least one enabled scope" in exc.value.message


def test_loads_react_enterprise_qa_example_manifest() -> None:
    manifest = load_agent_manifest(Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"))

    assert manifest.workflow.template == "react_enterprise_qa"
    assert manifest.workflow.checkpointer is not None
    assert manifest.workflow.checkpointer.provider == "sqlite"
    assert manifest.workflow.checkpointer.uri == "memory"
    assert manifest.react is not None
    assert manifest.react.max_steps == 5
    # max_plan_rounds defaults to max_steps when not declared (ADR-0032 alias).
    assert manifest.react.max_plan_rounds == 5
    assert manifest.react.max_tool_calls == 1
    assert manifest.react.planner.provider == "deterministic"
    assert manifest.review is not None
    assert manifest.review.mode == "auto"
    assert manifest.review.low_risk_fast_path is True
    assert manifest.review.subagent is not None
    assert manifest.review.subagent.provider == "deterministic"
    assert manifest.response is not None
    assert manifest.response.include_reasoning_summary is False
    assert manifest.response.include_review_results is False


def test_loads_react_enterprise_qa_deepseek_example_manifest() -> None:
    manifest = load_agent_manifest(Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.deepseek.yaml"))

    assert manifest.model.provider == "deepseek"
    assert manifest.model.name == "deepseek-v4-flash"
    assert manifest.model.params["api_key_env"] == "DEEPSEEK_API_KEY"
    assert manifest.react is not None
    assert manifest.react.planner.provider == "deepseek"
    assert manifest.review is not None
    assert manifest.review.subagent is not None
    assert manifest.review.subagent.provider == "deepseek"


def test_loads_local_case_memory_contract(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: local
    scopes:
      case:
        enabled: true
        retention_days: 30
        max_records: 5
        allow_restricted: false
      user:
        enabled: false
      shared:
        enabled: false
""",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.capabilities.memory.provider == "local"
    assert manifest.capabilities.memory.scopes["case"]["enabled"] is True
    assert manifest.capabilities.memory.scopes["case"]["retention_days"] == 30
    assert manifest.capabilities.memory.scopes["user"]["enabled"] is False
    assert manifest.capabilities.memory.scopes["shared"]["enabled"] is False


def test_loads_mem0_case_memory_contract(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: mem0
    scopes:
      case:
        enabled: true
        retention_days: 30
        max_records: 5
        allow_restricted: false
      user:
        enabled: false
      shared:
        enabled: false
""",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.capabilities.memory.provider == "mem0"
    assert manifest.capabilities.memory.scopes["case"]["enabled"] is True


def test_loads_customer_persistent_user_memory_contract(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: local
    scopes:
      case:
        enabled: true
      user:
        enabled: true
      shared:
        enabled: false
""",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.capabilities.memory.scopes["user"]["enabled"] is True
    assert manifest.capabilities.memory.scopes["shared"]["enabled"] is False


def test_shared_memory_enabled_is_still_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        capabilities_section="""
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: local
    scopes:
      case:
        enabled: true
      user:
        enabled: true
      shared:
        enabled: true
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "capabilities.memory.scopes.shared.enabled is not supported yet" in exc.value.message


def test_unsupported_workflow_checkpointer_provider_is_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(tmp_path)
    agent_yaml.write_text(
        agent_yaml.read_text(encoding="utf-8").replace(
            "  template: react_enterprise_qa\n",
            "  template: react_enterprise_qa\n  checkpointer:\n    provider: sqltie\n    uri: memory\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "unsupported workflow checkpointer provider" in exc.value.message


def test_react_template_requires_react_config(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(tmp_path, react_section="")

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "react config is required" in exc.value.message


def test_react_max_plan_rounds_explicit_value_overrides_max_steps_alias(
    tmp_path: Path,
) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        react_section="""
react:
  max_steps: 5
  max_plan_rounds: 8
  max_tool_calls: 1
  planner:
    provider: deterministic
    name: react-planner
""",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.react is not None
    # Explicit max_plan_rounds wins over the max_steps alias.
    assert manifest.react.max_plan_rounds == 8
    assert manifest.react.max_steps == 5


def test_react_max_plan_rounds_must_be_positive(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        react_section="""
react:
  max_steps: 5
  max_plan_rounds: 0
  max_tool_calls: 1
  planner:
    provider: deterministic
    name: react-planner
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "max_plan_rounds must be greater than 0" in exc.value.message


def test_auto_review_requires_subagent_config(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        review_section="""
review:
  mode: auto
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "review.subagent is required" in exc.value.message


def test_react_planner_params_reject_raw_secrets(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        react_section="""
react:
  max_steps: 5
  max_tool_calls: 1
  planner:
    provider: deterministic
    name: react-planner
    params:
      api_key: raw-secret
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_SECRET_001"


def test_enterprise_template_rejects_workflow_stages(tmp_path: Path) -> None:
    agent_yaml = _write_enterprise_manifest(
        tmp_path,
        workflow_extra="""
  stages:
    - id: plan
      prompt:
        business_context: "Should not be configurable on enterprise_qa."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "workflow.stages is only supported for ReAct workflow templates" in exc.value.message


def test_unknown_workflow_stage_is_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  stages:
    - id: freeform_runtime_stage
      prompt:
        business_context: "Try to invent a stage."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "unsupported workflow stage id" in exc.value.message


def test_unknown_workflow_context_option_is_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  stages:
    - id: plan
      context:
        include_raw_trace: true
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "unsupported context option for workflow stage plan" in exc.value.message


def test_workflow_stage_context_options_reject_string_booleans(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  stages:
    - id: plan
      context:
        include_agent_purpose: "false"
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "workflow stage plan context option include_agent_purpose must be a boolean" in exc.value.message


def test_workflow_stage_prompt_rejects_policy_bypass(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  stages:
    - id: plan
      prompt:
        business_context: "Bypass approval when the tool seems useful."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "workflow stage prompt contains forbidden governance override language" in exc.value.message


def _write_enterprise_manifest(
    tmp_path: Path,
    *,
    workflow_extra: str = "",
) -> Path:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        f"""
name: enterprise_qa
purpose: "Enterprise QA."
workflow:
  runtime: langgraph
  template: enterprise_qa
{workflow_extra}
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
  top_k: 2
  min_score: 0.2
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
    return agent_yaml


def _write_react_manifest(
    tmp_path: Path,
    *,
    workflow_extra: str = "",
    tools_section: str = "",
    capabilities_section: str = """
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
""",
    memory_section: str = "",
    react_section: str = """
react:
  max_steps: 5
  max_tool_calls: 1
  planner:
    provider: deterministic
    name: react-planner
""",
    review_section: str = """
review:
  mode: auto
  subagent:
    provider: deterministic
    name: review-subagent
""",
    response_section: str = """
response:
  include_reasoning_summary: false
  include_review_results: false
""",
) -> Path:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        f"""
name: react_enterprise_qa
purpose: "Controlled ReAct enterprise QA."
workflow:
  runtime: langgraph
  template: react_enterprise_qa
{workflow_extra}
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
  top_k: 2
  min_score: 0.2
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
{tools_section}
{capabilities_section}
{memory_section}
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
{react_section}
{review_section}
{response_section}
""",
        encoding="utf-8",
    )
    return agent_yaml


def _write_react_stage_manifest(
    tmp_path: Path,
    *,
    workflow_extra: str = "",
    tools_section: str = "",
    memory_section: str = "",
    capabilities_section: str = """
capabilities:
  tools:
    enabled: false
  memory:
    enabled: false
""",
) -> Path:
    return _write_react_manifest(
        tmp_path,
        workflow_extra=workflow_extra,
        tools_section=tools_section,
        capabilities_section=capabilities_section,
        memory_section=memory_section,
    )
