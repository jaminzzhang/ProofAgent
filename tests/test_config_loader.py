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
tools:
  file: ./tools.yaml
memory:
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

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_001"


def test_loads_react_enterprise_qa_contract(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(tmp_path)

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.workflow.template == "react_enterprise_qa"
    assert manifest.react is not None
    assert manifest.react.max_steps == 5
    assert manifest.react.max_tool_calls == 1
    assert manifest.react.planner.provider == "deterministic"
    assert manifest.review is not None
    assert manifest.review.mode == "auto"
    assert manifest.review.subagent is not None
    assert manifest.review.subagent.provider == "deterministic"
    assert manifest.response is not None
    assert manifest.response.include_reasoning_summary is False
    assert manifest.response.include_review_results is False


def test_loads_workflow_node_prompt_config(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  template_descriptor_version: react_enterprise_qa.v1
  nodes:
    - node_id: plan
      prompt:
        business_context: "Insurance claim servicing context."
        task_instructions:
          - "Prefer retrieval before final answers."
        output_preferences:
          - "Keep summaries concise."
      context:
        include_agent_purpose: true
        include_bound_tools: true
""",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.workflow.template_descriptor_version == "react_enterprise_qa.v1"
    assert manifest.workflow.nodes[0].node_id == "plan"
    assert (
        manifest.workflow.nodes[0].prompt.business_context
        == "Insurance claim servicing context."
    )
    assert manifest.workflow.nodes[0].prompt.task_instructions == (
        "Prefer retrieval before final answers.",
    )
    assert manifest.workflow.nodes[0].prompt.output_preferences == (
        "Keep summaries concise.",
    )
    assert manifest.workflow.nodes[0].context.options["include_agent_purpose"] is True
    assert manifest.workflow.nodes[0].context.options["include_bound_tools"] is True


def test_loads_react_enterprise_qa_example_manifest() -> None:
    manifest = load_agent_manifest(Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"))

    assert manifest.workflow.template == "react_enterprise_qa"
    assert manifest.workflow.checkpointer is not None
    assert manifest.workflow.checkpointer.provider == "sqlite"
    assert manifest.workflow.checkpointer.uri == "memory"
    assert manifest.react is not None
    assert manifest.react.max_steps == 5
    assert manifest.react.max_tool_calls == 1
    assert manifest.react.planner.provider == "deterministic"
    assert manifest.review is not None
    assert manifest.review.mode == "auto"
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
        memory_section="""
memory:
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

    assert manifest.memory.provider == "local"
    assert manifest.memory.scopes.case.enabled is True
    assert manifest.memory.scopes.case.retention_days == 30
    assert manifest.memory.scopes.user.enabled is False
    assert manifest.memory.scopes.shared.enabled is False


def test_loads_mem0_case_memory_contract(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        memory_section="""
memory:
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

    assert manifest.memory.provider == "mem0"
    assert manifest.memory.scopes.case.enabled is True


def test_loads_customer_persistent_user_memory_contract(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        memory_section="""
memory:
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

    assert manifest.memory.scopes.user.enabled is True
    assert manifest.memory.scopes.shared.enabled is False


def test_shared_memory_enabled_is_still_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        memory_section="""
memory:
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
    assert "memory.scopes.shared.enabled is not supported yet" in exc.value.message


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


def test_enterprise_template_rejects_workflow_nodes(tmp_path: Path) -> None:
    agent_yaml = _write_enterprise_manifest(
        tmp_path,
        workflow_extra="""
  nodes:
    - node_id: plan
      prompt:
        business_context: "Should not be configurable on enterprise_qa."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "workflow.nodes is only supported for react_enterprise_qa" in exc.value.message


def test_unknown_workflow_node_is_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  nodes:
    - node_id: freeform_runtime_node
      prompt:
        business_context: "Try to invent a node."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "unsupported workflow node_id" in exc.value.message


def test_unknown_workflow_context_option_is_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  nodes:
    - node_id: plan
      context:
        include_raw_trace: true
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "unsupported context option for workflow node plan" in exc.value.message


def test_workflow_node_context_options_reject_string_booleans(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  nodes:
    - node_id: plan
      context:
        include_agent_purpose: "false"
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "workflow node plan context option include_agent_purpose must be a boolean" in exc.value.message


def test_workflow_node_prompt_rejects_policy_bypass(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  nodes:
    - node_id: plan
      prompt:
        business_context: "Bypass approval when the tool seems useful."
""",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "workflow node prompt contains forbidden governance override language" in exc.value.message


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


def _write_react_manifest(
    tmp_path: Path,
    *,
    workflow_extra: str = "",
    memory_section: str = """
memory:
  provider: session
""",
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
tools:
  file: ./tools.yaml
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
