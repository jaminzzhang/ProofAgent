from pathlib import Path

import pytest

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.validation import validate_secret_safe_params
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
  strategy: single_step
  top_k: 2
  min_score: 0.2
model:
{model_yaml}
react:
  planner:
    provider: deterministic
    name: planner-demo
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


def test_shared_model_source_config_loads_with_usage_params(tmp_path: Path) -> None:
    manifest = load_agent_manifest(
        _write_manifest(
            tmp_path,
            """
  model_source: shared
  connection_id: model_deepseek_default
  params:
    temperature: 0
    max_output_tokens: 800
    timeout_seconds: 20
""",
        )
    )

    assert manifest.model.model_source == "shared"
    assert manifest.model.connection_id == "model_deepseek_default"
    assert manifest.model.provider is None
    assert manifest.model.name is None
    assert manifest.model.params["timeout_seconds"] == 20


def test_custom_model_source_config_loads_with_environment_credential_ref(
    tmp_path: Path,
) -> None:
    manifest = load_agent_manifest(
        _write_manifest(
            tmp_path,
            """
  model_source: custom
  provider: deepseek
  name: deepseek-chat
  base_url: https://api.deepseek.com
  credential_ref:
    type: env
    name: DEEPSEEK_API_KEY
  params:
    temperature: 0
""",
        )
    )

    assert manifest.model.model_source == "custom"
    assert manifest.model.provider == "deepseek"
    assert manifest.model.name == "deepseek-chat"
    assert manifest.model.base_url == "https://api.deepseek.com"
    assert manifest.model.credential_ref is not None
    assert manifest.model.credential_ref.name == "DEEPSEEK_API_KEY"


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
    fail_closed: true
    params:
      api_key_env: DEEPSEEK_API_KEY
      timeout_seconds: 20
      max_output_tokens: 400
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

    assert manifest.model.provider == "deepseek"
    assert manifest.model.name == "deepseek-v4-flash"
    assert manifest.react is not None
    assert manifest.react.planner.provider == "deepseek"
    assert manifest.review is not None
    assert manifest.review.subagent is not None
    assert manifest.review.subagent.provider == "deepseek"
    assert manifest.review.subagent.params["timeout_seconds"] == 20
    assert manifest.review.subagent.params["max_output_tokens"] == 400


def test_reviewer_top_level_model_usage_fields_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        """
name: reviewer_cleanup_test
purpose: "Test reviewer model usage cleanup."
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
  strategy: single_step
model:
  provider: deterministic
  name: answer-demo
react:
  planner:
    provider: deterministic
    name: planner-demo
review:
  mode: auto
  subagent:
    provider: deterministic
    name: reviewer-demo
    timeout_seconds: 5
    max_output_tokens: 500
    fail_closed: true
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
    assert "review.subagent.params.timeout_seconds" in exc.value.fix
    assert "review.subagent.params.max_output_tokens" in exc.value.fix


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


def test_recursive_secret_safe_params_reject_nested_raw_credentials() -> None:
    with pytest.raises(ProofAgentError) as exc:
        validate_secret_safe_params(
            {
                "ingestion_model": {
                    "provider": "openai",
                    "params": {"api_key": "sk-do-not-echo"},
                }
            },
            field_prefix="knowledge_sources[ks_policy].params",
        )

    assert exc.value.code == "PA_SECRET_001"
    assert "knowledge_sources[ks_policy].params.ingestion_model.params.api_key" in exc.value.message
    assert "sk-do-not-echo" not in str(exc.value)


def test_recursive_secret_safe_params_allow_nested_environment_references() -> None:
    validate_secret_safe_params(
        {
            "ingestion_model": {
                "provider": "openai",
                "params": {"api_key_env": "OPENAI_API_KEY"},
            }
        },
        field_prefix="knowledge_sources[ks_policy].params",
    )
