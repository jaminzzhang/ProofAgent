from pathlib import Path

import pytest

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.errors import ProofAgentError


def _write_manifest(tmp_path: Path, model_yaml: str) -> Path:
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        f"""
name: model_test
purpose: "Test model config."
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
{model_yaml}
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


def test_openai_compatible_model_config_loads_with_params(tmp_path: Path) -> None:
    manifest = load_agent_manifest(
        _write_manifest(
            tmp_path,
            """
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key_env: OPENAI_API_KEY
    base_url_env: OPENAI_BASE_URL
    temperature: 0
    max_output_tokens: 800
""",
        )
    )

    assert manifest.model.provider == "openai_compatible"
    assert manifest.model.params["max_output_tokens"] == 800

    with pytest.raises(TypeError):
        manifest.model.params["max_output_tokens"] = 100


def test_deepseek_model_provider_loads_for_all_model_roles(tmp_path: Path) -> None:
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: deepseek_model_test
purpose: "Test DeepSeek model role config."
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    provider: sqlite
    uri: memory
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
  provider: deepseek
  name: deepseek-v4-flash
  params:
    api_key_env: DEEPSEEK_API_KEY
    temperature: 0
    max_output_tokens: 800
react:
  max_steps: 2
  max_tool_calls: 0
  record_reasoning_summary: true
  planner:
    provider: deepseek
    name: deepseek-v4-flash
    params:
      api_key_env: DEEPSEEK_API_KEY
      temperature: 0
review:
  mode: auto
  subagent:
    provider: deepseek
    name: deepseek-v4-flash
    timeout_seconds: 20
    max_output_tokens: 400
    fail_closed: true
    params:
      api_key_env: DEEPSEEK_API_KEY
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

    assert manifest.model.provider == "deepseek"
    assert manifest.model.name == "deepseek-v4-flash"
    assert manifest.react is not None
    assert manifest.react.planner.provider == "deepseek"
    assert manifest.review is not None
    assert manifest.review.subagent is not None
    assert manifest.review.subagent.provider == "deepseek"


def test_model_config_rejects_secret_looking_params(tmp_path: Path) -> None:
    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(
            _write_manifest(
                tmp_path,
                """
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key: sk-do-not-store
""",
            )
        )

    assert exc.value.code == "PA_SECRET_001"
