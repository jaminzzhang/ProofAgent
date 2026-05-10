from pathlib import Path

import pytest

from proof_agent.config.loader import load_agent_manifest
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
knowledge:
  provider: local
  path: ./knowledge
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
