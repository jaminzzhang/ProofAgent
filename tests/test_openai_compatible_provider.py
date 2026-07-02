import sys
from types import SimpleNamespace

import pytest

from proof_agent.capabilities.models.openai_compatible import OpenAICompatibleModelProvider
from proof_agent.capabilities.react.planner import _planner_function_schema
from proof_agent.contracts import (
    EffectiveToolProposalScope,
    ModelConfig,
    ModelFunctionSchema,
    ModelMessage,
    ModelRequest,
    ModelRole,
    ReActActionType,
    ToolProposalInterface,
    ToolProposalParameter,
    ToolProposalParameterSource,
)
from proof_agent.errors import ProofAgentError


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


def test_openai_compatible_provider_requests_json_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create),
            )

        def _create(self, **payload: object) -> object:
            calls["payload"] = payload
            return SimpleNamespace(
                id="chatcmpl_json",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"ok": true}'),
                        finish_reason="stop",
                    )
                ],
                usage=None,
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

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="openai_compatible",
            name="gpt-test",
            params={"api_key_env": "PROOF_AGENT_OPENAI_KEY"},
        )
    )
    provider.generate(
        ModelRequest(
            provider="openai_compatible",
            model="gpt-test",
            messages=(ModelMessage(role=ModelRole.USER, content="json"),),
            response_format="json",
        )
    )

    assert calls["payload"]["response_format"] == {"type": "json_object"}


def test_openai_compatible_provider_forces_function_schema_and_reads_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create),
            )

        def _create(self, **payload: object) -> object:
            calls["payload"] = payload
            return SimpleNamespace(
                id="chatcmpl_tool",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        arguments=(
                                            '{"action_type":"generate_final_answer",'
                                            '"parameters":{}}'
                                        )
                                    )
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
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

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="openai_compatible",
            name="gpt-test",
            params={"api_key_env": "PROOF_AGENT_OPENAI_KEY"},
        )
    )
    response = provider.generate(
        ModelRequest(
            provider="openai_compatible",
            model="gpt-test",
            messages=(ModelMessage(role=ModelRole.USER, content="plan"),),
            response_format="json",
            function_schema=ModelFunctionSchema(
                name="submit_react_action_proposal",
                description="Submit one governed planner action.",
                parameters_schema={
                    "type": "object",
                    "required": ["action_type", "parameters"],
                    "additionalProperties": False,
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "enum": ["generate_final_answer", "refuse"],
                        },
                        "parameters": {"type": "object"},
                    },
                },
            ),
        )
    )

    assert calls["payload"]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "submit_react_action_proposal",
                "description": "Submit one governed planner action.",
                "parameters": {
                    "type": "object",
                    "required": ["action_type", "parameters"],
                    "additionalProperties": False,
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "enum": ["generate_final_answer", "refuse"],
                        },
                        "parameters": {"type": "object"},
                    },
                },
                "strict": True,
            },
        }
    ]
    assert calls["payload"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_react_action_proposal"},
    }
    assert "response_format" not in calls["payload"]
    assert response.content == '{"action_type":"generate_final_answer","parameters":{}}'


def test_openai_compatible_provider_prefers_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                id="chatcmpl_timeout",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="answer"),
                        finish_reason="stop",
                    )
                ],
                usage=None,
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

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="openai_compatible",
            name="gpt-test",
            params={
                "api_key_env": "PROOF_AGENT_OPENAI_KEY",
                "timeout_seconds": 20,
            },
        )
    )

    provider.generate(
        ModelRequest(
            provider="openai_compatible",
            model="gpt-test",
            messages=(ModelMessage(role=ModelRole.USER, content="user"),),
            timeout_seconds=3,
        )
    )

    assert calls["client"]["timeout"] == 3


def test_openai_compatible_provider_preserves_safe_api_error_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProviderAPIError(RuntimeError):
        status_code = 400
        body = {
            "error": {
                "type": "invalid_request_error",
                "code": "model_not_found",
                "message": "raw provider message may contain request details",
            }
        }

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create),
            )

        def _create(self, **payload: object) -> object:
            _ = payload
            raise ProviderAPIError("raw provider failure text")

    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(
            APIError=ProviderAPIError,
            APITimeoutError=TimeoutError,
            AuthenticationError=PermissionError,
            OpenAI=FakeOpenAI,
        ),
    )
    monkeypatch.setenv("PROOF_AGENT_OPENAI_KEY", "test-key")

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="openai_compatible",
            name="gpt-test",
            params={"api_key_env": "PROOF_AGENT_OPENAI_KEY"},
        )
    )

    with pytest.raises(ProofAgentError) as exc:
        provider.generate(
            ModelRequest(
                provider="openai_compatible",
                model="gpt-test",
                messages=(ModelMessage(role=ModelRole.USER, content="user"),),
            )
        )

    assert exc.value.code == "PA_MODEL_002"
    assert "upstream status 400" in exc.value.message
    assert "invalid_request_error" in exc.value.message
    assert "model_not_found" in exc.value.message
    assert "raw provider message" not in exc.value.message
    assert "model name" in exc.value.fix


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


@pytest.mark.parametrize(
    ("provider_name", "model_name", "api_key_env", "base_url"),
    [
        ("openai", "gpt-4.1-mini", "OPENAI_API_KEY", None),
        ("deepseek", "deepseek-v4-flash", "DEEPSEEK_API_KEY", "https://api.deepseek.com/beta"),
    ],
)
def test_openai_compatible_named_provider_aliases_use_provider_defaults(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    model_name: str,
    api_key_env: str,
    base_url: str | None,
) -> None:
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
                id="chatcmpl_alias",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="answer"),
                        finish_reason="stop",
                    )
                ],
                usage=None,
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
    monkeypatch.setenv(api_key_env, "test-key")

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(provider=provider_name, name=model_name)
    )
    response = provider.generate(
        ModelRequest(
            provider=provider_name,
            model=model_name,
            messages=(ModelMessage(role=ModelRole.USER, content="user"),),
        )
    )

    assert provider.provider_name == provider_name
    assert provider.model_name == model_name
    assert response.provider_name == provider_name
    assert calls["client"]["api_key"] == "test-key"
    assert calls["client"]["base_url"] == base_url


def test_deepseek_provider_alias_allows_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            calls["client"] = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create),
            )

        def _create(self, **payload: object) -> object:
            return SimpleNamespace(
                id="chatcmpl_alias",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="answer"),
                        finish_reason="stop",
                    )
                ],
                usage=None,
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
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek-proxy.example/v1")

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="deepseek",
            name="deepseek-v4-pro",
            params={"base_url_env": "DEEPSEEK_BASE_URL"},
        )
    )
    provider.generate(
        ModelRequest(
            provider="deepseek",
            model="deepseek-v4-pro",
            messages=(ModelMessage(role=ModelRole.USER, content="user"),),
        )
    )

    assert calls["client"]["base_url"] == "https://deepseek-proxy.example/v1"


def test_deepseek_function_schema_defaults_standard_base_url_to_beta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                id="chatcmpl_deepseek_tool",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        arguments='{"action_type":"plan_retrieval","parameters":{"query":"q"}}'
                                    )
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
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
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="deepseek",
            name="deepseek-v4-flash",
            params={"base_url": "https://api.deepseek.com"},
        )
    )
    response = provider.generate(
        ModelRequest(
            provider="deepseek",
            model="deepseek-v4-flash",
            messages=(ModelMessage(role=ModelRole.USER, content="plan"),),
            response_format="json",
            function_schema=ModelFunctionSchema(
                name="submit_react_action_proposal",
                parameters_schema={
                    "type": "object",
                    "required": ["action_type", "parameters"],
                    "additionalProperties": False,
                    "properties": {
                        "action_type": {"type": "string"},
                        "parameters": {
                            "type": "object",
                            "required": ["query"],
                            "additionalProperties": False,
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                },
            ),
        )
    )

    function_payload = calls["payload"]["tools"][0]["function"]
    assert calls["client"]["base_url"] == "https://api.deepseek.com/beta"
    assert calls["payload"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert function_payload["name"] == "submit_react_action_proposal"
    assert function_payload["strict"] is True
    assert calls["payload"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_react_action_proposal"},
    }
    assert "response_format" not in calls["payload"]
    assert response.content == '{"action_type":"plan_retrieval","parameters":{"query":"q"}}'


def test_deepseek_standard_endpoint_mode_omits_strict_beta_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                id="chatcmpl_deepseek_tool",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        arguments='{"action_type":"plan_retrieval","parameters":{"query":"q"}}'
                                    )
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
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
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="deepseek",
            name="deepseek-v4-flash",
            params={"deepseek_endpoint_mode": "standard"},
        )
    )
    provider.generate(
        ModelRequest(
            provider="deepseek",
            model="deepseek-v4-flash",
            messages=(ModelMessage(role=ModelRole.USER, content="plan"),),
            response_format="json",
            function_schema=ModelFunctionSchema(
                name="submit_react_action_proposal",
                parameters_schema={
                    "type": "object",
                    "required": ["action_type", "parameters"],
                    "additionalProperties": False,
                    "properties": {
                        "action_type": {"type": "string"},
                        "parameters": {
                            "type": "object",
                            "required": ["query"],
                            "additionalProperties": False,
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                },
            ),
        )
    )

    function_payload = calls["payload"]["tools"][0]["function"]
    assert calls["client"]["base_url"] == "https://api.deepseek.com"
    assert calls["payload"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "strict" not in function_payload


def test_deepseek_beta_function_schema_keeps_strict_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                id="chatcmpl_deepseek_beta_tool",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        arguments='{"action_type":"plan_retrieval","parameters":{"query":"q"}}'
                                    )
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
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
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="deepseek",
            name="deepseek-v4-flash",
            params={"base_url": "https://api.deepseek.com/beta"},
        )
    )
    provider.generate(
        ModelRequest(
            provider="deepseek",
            model="deepseek-v4-flash",
            messages=(ModelMessage(role=ModelRole.USER, content="plan"),),
            response_format="json",
            function_schema=ModelFunctionSchema(
                name="submit_react_action_proposal",
                parameters_schema={
                    "type": "object",
                    "required": ["action_type", "parameters"],
                    "additionalProperties": False,
                    "properties": {
                        "action_type": {"type": "string"},
                        "parameters": {
                            "type": "object",
                            "required": ["query"],
                            "additionalProperties": False,
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                },
            ),
        )
    )

    assert calls["client"]["base_url"] == "https://api.deepseek.com/beta"
    assert calls["payload"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls["payload"]["tools"][0]["function"]["strict"] is True


def test_deepseek_beta_omits_strict_for_incompatible_planner_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                id="chatcmpl_deepseek_planner_tool",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        arguments='{"action_type":"plan_retrieval","parameters":{"query":"q"},"target_tool_name":null}'
                                    )
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
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
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="deepseek",
            name="deepseek-v4-flash",
            params={"base_url": "https://api.deepseek.com/beta"},
        )
    )
    provider.generate(
        ModelRequest(
            provider="deepseek",
            model="deepseek-v4-flash",
            messages=(ModelMessage(role=ModelRole.USER, content="plan"),),
            response_format="json",
            function_schema=_planner_function_schema(
                frozenset(
                    {
                        ReActActionType.GENERATE_FINAL_ANSWER,
                        ReActActionType.PLAN_RETRIEVAL,
                    }
                )
            ),
        )
    )

    function_payload = calls["payload"]["tools"][0]["function"]
    assert calls["client"]["base_url"] == "https://api.deepseek.com/beta"
    assert calls["payload"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert function_payload["name"] == "submit_react_action_proposal"
    assert "strict" not in function_payload


def test_deepseek_beta_omits_strict_for_scoped_planner_oneof_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                id="chatcmpl_deepseek_scoped_planner_tool",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        arguments='{"action_type":"propose_tool_call","parameters":{"claim_id":"CLM-001"},"target_tool_name":"claim_status_lookup"}'
                                    )
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
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
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    effective_scope = EffectiveToolProposalScope(
        run_id="run_scope",
        plan_round=0,
        schema_digest="sha256:scope",
        tool_interfaces=(
            ToolProposalInterface(
                tool_contract_id="claim_status_lookup",
                purpose="claim status lookup",
                risk_level="medium",
                read_only=True,
                requires_approval=False,
                semantic_result_summary="Returns claim status.",
                parameters=(
                    ToolProposalParameter(
                        name="claim_id",
                        required=True,
                        value_type="string",
                        value_source=ToolProposalParameterSource.USER_SUPPLIED,
                    ),
                ),
            ),
        ),
    )
    provider = OpenAICompatibleModelProvider.from_config(
        ModelConfig(
            provider="deepseek",
            name="deepseek-v4-flash",
            params={"base_url": "https://api.deepseek.com/beta"},
        )
    )
    provider.generate(
        ModelRequest(
            provider="deepseek",
            model="deepseek-v4-flash",
            messages=(ModelMessage(role=ModelRole.USER, content="plan"),),
            response_format="json",
            function_schema=_planner_function_schema(
                frozenset({ReActActionType.PROPOSE_TOOL_CALL}),
                effective_tool_proposal_scope=effective_scope,
            ),
        )
    )

    function_payload = calls["payload"]["tools"][0]["function"]
    assert calls["client"]["base_url"] == "https://api.deepseek.com/beta"
    assert "oneOf" in function_payload["parameters"]["properties"]["parameters"]
    assert "strict" not in function_payload


@pytest.mark.parametrize(
    ("provider_name", "model_name", "api_key_env"),
    [
        ("openai", "gpt-4.1-mini", "OPENAI_API_KEY"),
        ("deepseek", "deepseek-v4-flash", "DEEPSEEK_API_KEY"),
    ],
)
def test_named_provider_aliases_require_their_default_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    model_name: str,
    api_key_env: str,
) -> None:
    monkeypatch.delenv(api_key_env, raising=False)

    with pytest.raises(ProofAgentError) as exc:
        OpenAICompatibleModelProvider.from_config(
            ModelConfig(provider=provider_name, name=model_name)
        )

    assert exc.value.code == "PA_MODEL_003"
    assert api_key_env in exc.value.message


def test_deepseek_endpoint_mode_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    with pytest.raises(ProofAgentError) as exc:
        OpenAICompatibleModelProvider.from_config(
            ModelConfig(
                provider="deepseek",
                name="deepseek-v4-flash",
                params={"deepseek_endpoint_mode": "preview"},
            )
        )

    assert exc.value.code == "PA_MODEL_001"
    assert "deepseek_endpoint_mode" in exc.value.message
