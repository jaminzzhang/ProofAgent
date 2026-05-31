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
    assert manifest.knowledge_sources[0].provider == "local_markdown"
    assert manifest.knowledge_sources[0].params["path"].name == "knowledge"
    assert manifest.knowledge_bindings[0].source_id == manifest.knowledge_sources[0].source_id
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
knowledge_sources:
  - source_id: ks_local
    name: Local Knowledge
    provider: local_markdown
    params:
      path: ./knowledge
knowledge_bindings:
  - binding_id: kb_local
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

    assert manifest.knowledge_sources[0].source_id == "ks_local"
    assert manifest.knowledge_sources[0].provider == "local_markdown"
    assert manifest.knowledge_sources[0].params["path"] == (tmp_path / "knowledge").resolve()
    assert manifest.knowledge_bindings[0].binding_id == "kb_local"
    assert manifest.knowledge_bindings[0].source_id == "ks_local"
    assert manifest.knowledge_bindings[0].alias == "policy_docs"
    assert manifest.knowledge_bindings[0].failure_mode == "required"
    assert manifest.knowledge_bindings[0].fusion_weight == 1.25
    assert manifest.knowledge_bindings[0].top_k == 2


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


def _write_react_manifest(
    tmp_path: Path,
    *,
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
