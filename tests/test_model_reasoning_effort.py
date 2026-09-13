from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.models.openai_compatible import OpenAICompatibleModelProvider
from proof_agent.contracts import ModelFunctionSchema, ModelMessage, ModelRequest, ModelRole
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.errors import ProofAgentError


class RecordingClient:
    def __init__(self, message: dict[str, Any] | None = None) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.message = message or {"content": "answer"}

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        self.payloads.append(json.loads(body or b"{}"))
        return GuardedHttpResponse(
            status_code=200,
            headers={},
            body=json.dumps({"choices": [{"message": self.message}]}).encode(),
        )


def request(**changes: Any) -> ModelRequest:
    return ModelRequest.model_validate({
        "provider": "openai", "model": "gpt-5.2",
        "messages": [ModelMessage(role=ModelRole.USER, content="answer")],
        **changes,
    })


def test_request_reasoning_effort_is_typed_and_not_silently_ignored() -> None:
    assert request(reasoning_effort="high").reasoning_effort == "high"
    with pytest.raises(ValidationError, match="reasoning_effort"):
        request(reasoning_effort="unlimited")


def test_config_effort_reaches_guarded_transport_and_request_overrides_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROOF_AGENT_MODE", "development")
    monkeypatch.setenv("EFFORT_TEST_API_KEY", "synthetic-test-key")
    client = RecordingClient()
    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(provider="openai", name="gpt-5.2", params={
            "api_key_env": "EFFORT_TEST_API_KEY", "reasoning_effort": "medium",
        }),
        guarded_http_client=client,
    )
    provider.generate(request())
    provider.generate(request(reasoning_effort="off", max_output_tokens=100))
    assert client.payloads[0]["reasoning_effort"] == "medium"
    assert client.payloads[1]["reasoning_effort"] == "none"
    assert client.payloads[1]["max_completion_tokens"] == 100
    assert "max_tokens" not in client.payloads[1]


def schema() -> ModelFunctionSchema:
    return ModelFunctionSchema(name="submit_answer", parameters_schema={
        "type": "object", "additionalProperties": False,
        "properties": {"answer": {"type": "string"}}, "required": ["answer"],
    })


def function_message(name: str = "submit_answer") -> dict[str, Any]:
    return {"tool_calls": [{"type": "function", "function": {
        "name": name, "arguments": '{"answer":"accepted"}',
    }}], "reasoning_content": "PRIVATE_REASONING_MUST_NOT_ESCAPE"}


@pytest.mark.parametrize("effort,effective", [
    ("low", "low"), ("medium", "high"), ("high", "high"),
    ("xhigh", "high"), ("max", "max"),
])
def test_deepseek_thinking_function_schema_keeps_bounded_output_contract(
    effort: str, effective: str,
) -> None:
    client = RecordingClient(function_message())
    provider = OpenAICompatibleModelProvider(
        provider_name="deepseek", model_name="deepseek-flash", api_key="synthetic",
        base_url="https://api.deepseek.com/beta", guarded_http_client=client,
    )
    result = provider.generate(request(reasoning_effort=effort, function_schema=schema()))
    assert result.content == '{"answer":"accepted"}'
    assert "PRIVATE_REASONING" not in result.model_dump_json()
    payload = client.payloads[0]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == effective
    assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["function"]["strict"] is True


@pytest.mark.parametrize("message", [
    {"content": '{"answer":"not a function"}'},
    function_message("wrong_function"),
    {"tool_calls": function_message()["tool_calls"] * 2},
    {"tool_calls": [{"type": "function", "function": {"name": "submit_answer"}}]},
])
def test_deepseek_thinking_rejects_unbound_or_multiple_outputs(message: dict[str, Any]) -> None:
    client = RecordingClient(message)
    provider = OpenAICompatibleModelProvider(
        provider_name="deepseek", model_name="deepseek-flash", api_key="synthetic",
        guarded_http_client=client,
    )
    with pytest.raises(ProofAgentError, match="PA_MODEL_002"):
        provider.generate(request(reasoning_effort="high", function_schema=schema()))


@pytest.mark.parametrize("effort", [None, "off"])
def test_deepseek_default_and_explicit_off_preserve_named_tool_choice(effort: str | None) -> None:
    client = RecordingClient(function_message())
    provider = OpenAICompatibleModelProvider(
        provider_name="deepseek", model_name="deepseek-flash", api_key="synthetic",
        guarded_http_client=client,
    )
    provider.generate(request(reasoning_effort=effort, function_schema=schema()))
    payload = client.payloads[0]
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload
    assert payload["tool_choice"]["function"]["name"] == "submit_answer"


@pytest.mark.parametrize("provider_name,model_name,base_url,effort", [
    ("openai", "gpt-4o", None, "high"),
    ("openai", "gpt-5", None, "off"),
    ("openai", "gpt-5.1", None, "xhigh"),
    ("openai", "gpt-5.2", None, "max"),
    ("openai", "gpt-5.2-future", None, "high"),
    ("deepseek", "deepseek-chat", None, "high"),
    ("openai_compatible", "gpt-5.2", "https://unknown.example/v1", "high"),
    ("openai_compatible", "deepseek-flash", "https://api.deepseek.com.evil.test", "high"),
    ("openai_compatible", "deepseek-flash", "https://unknown.example/api.deepseek.com", "high"),
])
def test_unsupported_effort_provider_or_model_fails_before_transport(
    provider_name: str, model_name: str, base_url: str | None, effort: str,
) -> None:
    client = RecordingClient()
    provider = OpenAICompatibleModelProvider(
        provider_name=provider_name, model_name=model_name, api_key="synthetic",
        base_url=base_url, guarded_http_client=client,
    )
    with pytest.raises(ProofAgentError, match="PA_MODEL_001"):
        provider.generate(request(reasoning_effort=effort))
    assert client.payloads == []


@pytest.mark.parametrize("model_name,effort", [
    ("gpt-5", "low"), ("gpt-5.1", "high"), ("gpt-5.2", "xhigh"),
    ("gpt-5.4", "high"), ("gpt-5.5", "xhigh"), ("gpt-6-astra", "max"),
])
def test_documented_openai_effort_reaches_transport(model_name: str, effort: str) -> None:
    client = RecordingClient()
    provider = OpenAICompatibleModelProvider(
        provider_name="openai", model_name=model_name, api_key="synthetic",
        guarded_http_client=client,
    )
    provider.generate(request(reasoning_effort=effort))
    assert client.payloads[0]["reasoning_effort"] == effort


@pytest.mark.parametrize("provider_name,model_name", [
    ("openai", "gpt-5.2"), ("deepseek", "deepseek-flash"),
])
def test_reasoning_rejects_ineffective_temperature_combination(
    provider_name: str, model_name: str,
) -> None:
    client = RecordingClient()
    provider = OpenAICompatibleModelProvider(
        provider_name=provider_name, model_name=model_name, api_key="synthetic",
        guarded_http_client=client, default_temperature=0.3,
    )
    with pytest.raises(ProofAgentError, match="temperature"):
        provider.generate(request(reasoning_effort="high"))
    assert client.payloads == []


def test_public_resolution_reports_deepseek_effective_effort() -> None:
    from proof_agent.capabilities.models.reasoning import resolve_reasoning_effort

    resolution = resolve_reasoning_effort(
        provider_name="deepseek", model_name="deepseek-flash", effort="xhigh",
    )
    assert resolution is not None
    assert resolution.requested_effort == "xhigh"
    assert resolution.effective_effort == "high"
    assert resolution.thinking_enabled is True


@pytest.mark.parametrize("effort", ["invalid", "", True, 3, {"level": "high"}])
def test_config_rejects_invalid_effort_values(
    effort: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROOF_AGENT_MODE", "development")
    monkeypatch.setenv("EFFORT_TEST_API_KEY", "synthetic-test-key")
    with pytest.raises(ProofAgentError, match="reasoning_effort"):
        OpenAICompatibleModelProvider.from_config(ModelConfig(
            provider="openai", name="gpt-5.2", params={
                "api_key_env": "EFFORT_TEST_API_KEY", "reasoning_effort": effort,
            },
        ))


@pytest.mark.parametrize("provider_name,model_name,effort", [
    ("openai", "gpt-5.2", "high"),
    ("deepseek", "deepseek-flash", "medium"),
])
def test_real_sdk_serializes_reasoning_payload_and_keeps_function_bound(
    monkeypatch: pytest.MonkeyPatch, provider_name: str, model_name: str, effort: str,
) -> None:
    import httpx

    openai = pytest.importorskip("openai")
    original_openai = openai.OpenAI
    payloads: list[dict[str, Any]] = []

    def handle(http_request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(http_request.content))
        return httpx.Response(200, json={
            "id": "synthetic-completion", "object": "chat.completion", "created": 0,
            "model": model_name,
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", **function_message(),
            }}],
        })

    with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: original_openai(
            **kwargs, http_client=http_client,
        ))
        provider = OpenAICompatibleModelProvider(
            provider_name=provider_name, model_name=model_name, api_key="synthetic",
            base_url=("https://api.deepseek.com/beta" if provider_name == "deepseek"
                      else "https://api.openai.com/v1"),
        )
        result = provider.generate(request(reasoning_effort=effort, function_schema=schema()))
    assert result.content == '{"answer":"accepted"}'
    assert "PRIVATE_REASONING" not in result.model_dump_json()
    assert payloads[0]["reasoning_effort"] == "high"
    if provider_name == "deepseek":
        assert payloads[0]["thinking"] == {"type": "enabled"}
        assert payloads[0]["tool_choice"] == "auto"
    else:
        assert payloads[0]["tool_choice"]["function"]["name"] == "submit_answer"


def test_deepseek_sdk_rejects_plain_text_when_thinking_expects_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    openai = pytest.importorskip("openai")
    original_openai = openai.OpenAI
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        "id": "synthetic", "object": "chat.completion", "created": 0,
        "model": "deepseek-flash", "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": '{"answer":"unbound"}'},
        }],
    }))) as http_client:
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: original_openai(
            **kwargs, http_client=http_client,
        ))
        provider = OpenAICompatibleModelProvider(
            provider_name="deepseek", model_name="deepseek-flash", api_key="synthetic",
            base_url="https://api.deepseek.com/beta",
        )
        with pytest.raises(ProofAgentError, match="PA_MODEL_002"):
            provider.generate(request(reasoning_effort="high", function_schema=schema()))


def test_reasoning_rejects_conflicting_declared_provider_and_official_endpoint() -> None:
    client = RecordingClient()
    provider = OpenAICompatibleModelProvider(
        provider_name="openai", model_name="gpt-5.2", api_key="synthetic",
        base_url="https://api.deepseek.com", guarded_http_client=client,
    )
    with pytest.raises(ProofAgentError, match="PA_MODEL_001"):
        provider.generate(request(reasoning_effort="high"))
    assert client.payloads == []


def test_explicit_effort_uses_resolved_official_url_despite_sdk_environment_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    openai = pytest.importorskip("openai")
    original_openai = openai.OpenAI
    urls: list[str] = []
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unknown.example/v1")

    def handle(http_request: httpx.Request) -> httpx.Response:
        urls.append(str(http_request.url))
        return httpx.Response(200, json={
            "id": "synthetic", "object": "chat.completion", "created": 0,
            "model": "gpt-5.2", "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "answer"},
            }],
        })

    with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: original_openai(
            **kwargs, http_client=http_client,
        ))
        provider = OpenAICompatibleModelProvider(
            provider_name="openai", model_name="gpt-5.2", api_key="synthetic",
        )
        provider.generate(request(reasoning_effort="high"))
    assert urls == ["https://api.openai.com/v1/chat/completions"]
