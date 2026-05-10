import sys
from types import SimpleNamespace

import pytest

from proof_agent.contracts import ModelConfig, ModelMessage, ModelRequest, ModelRole
from proof_agent.errors import ProofAgentError
from proof_agent.providers.openai_compatible import OpenAICompatibleModelProvider


def test_openai_compatible_provider_maps_request_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            calls["client"] = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create),
            )

        def _create(self, **payload: object) -> object:
            calls["payload"] = payload
            return SimpleNamespace(
                id="chatcmpl_test",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="answer from model"),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
            )

    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(
            APIError=RuntimeError,
            APITimeoutError=TimeoutError,
            AuthenticationError=PermissionError,
            OpenAI=FakeOpenAI,
        ),
    )
    monkeypatch.setenv("PROOF_AGENT_OPENAI_KEY", "test-key")
    monkeypatch.setenv("PROOF_AGENT_OPENAI_ORG", "org-test")
    monkeypatch.setenv("PROOF_AGENT_OPENAI_PROJECT", "project-test")

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="openai_compatible",
            name="gpt-test",
            params={
                "api_key_env": "PROOF_AGENT_OPENAI_KEY",
                "base_url": "https://models.example.test/v1",
                "organization_env": "PROOF_AGENT_OPENAI_ORG",
                "project_env": "PROOF_AGENT_OPENAI_PROJECT",
                "temperature": 0.2,
                "max_output_tokens": 64,
                "timeout_seconds": 20,
            },
        )
    )

    response = provider.generate(
        ModelRequest(
            provider="openai_compatible",
            model="gpt-test",
            messages=(
                ModelMessage(role=ModelRole.SYSTEM, content="system"),
                ModelMessage(role=ModelRole.USER, content="user"),
            ),
            temperature=0.1,
            max_output_tokens=32,
        )
    )

    assert calls["client"] == {
        "api_key": "test-key",
        "base_url": "https://models.example.test/v1",
        "timeout": 20.0,
        "organization": "org-test",
        "project": "project-test",
    }
    assert calls["payload"] == {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        "temperature": 0.1,
        "max_tokens": 32,
    }
    assert response.content == "answer from model"
    assert response.token_usage is not None
    assert response.token_usage.total_tokens == 15
    assert response.raw_response_id == "chatcmpl_test"


def test_openai_compatible_provider_requires_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_OPENAI_KEY", raising=False)

    with pytest.raises(ProofAgentError) as exc:
        OpenAICompatibleModelProvider.from_config(
            ModelConfig(
                provider="openai_compatible",
                name="gpt-test",
                params={"api_key_env": "MISSING_OPENAI_KEY"},
            )
        )

    assert exc.value.code == "PA_MODEL_003"
    assert "MISSING_OPENAI_KEY" in exc.value.message
