from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any

from proof_agent.contracts import ModelFunctionSchema, ModelRequest, ModelResponse, TokenUsage
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError


_DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"
_DEEPSEEK_STANDARD_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_BETA_BASE_URL = "https://api.deepseek.com/beta"
_DEEPSEEK_ENDPOINT_MODES = {"beta", "standard"}
_PROVIDER_DEFAULTS: dict[str, dict[str, str | None]] = {
    "openai_compatible": {"api_key_env": _DEFAULT_API_KEY_ENV, "base_url": None},
    "openai": {"api_key_env": _DEFAULT_API_KEY_ENV, "base_url": None},
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": _DEEPSEEK_STANDARD_BASE_URL,
    },
}


class OpenAICompatibleModelProvider:
    def __init__(
        self,
        *,
        provider_name: str = "openai_compatible",
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        timeout_seconds: float | None = None,
        default_temperature: float | None = None,
        default_max_output_tokens: int | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._model_name = model_name
        self._api_key = api_key
        self._base_url = base_url
        self._organization = organization
        self._project = project
        self._timeout_seconds = timeout_seconds
        self._default_temperature = default_temperature
        self._default_max_output_tokens = default_max_output_tokens

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> OpenAICompatibleModelProvider:
        if model_config.provider is None or model_config.name is None:
            raise ProofAgentError(
                "PA_MODEL_001",
                "openai_compatible model config requires provider and name.",
                "Resolve shared/custom model configuration before constructing the provider.",
            )
        params = dict(model_config.params)
        allowed = {
            "api_key_env",
            "base_url",
            "base_url_env",
            "organization_env",
            "project_env",
            "temperature",
            "max_output_tokens",
            "timeout_seconds",
            "deepseek_endpoint_mode",
        }
        unsupported = sorted(set(params).difference(allowed))
        if unsupported:
            raise ProofAgentError(
                "PA_MODEL_001",
                f"unsupported openai_compatible param(s): {', '.join(unsupported)}",
                "Use only documented model.params keys for openai_compatible.",
            )
        provider_defaults = _PROVIDER_DEFAULTS.get(
            model_config.provider,
            _PROVIDER_DEFAULTS["openai_compatible"],
        )
        api_key_env = str(params.get("api_key_env", provider_defaults["api_key_env"]))
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ProofAgentError(
                "PA_MODEL_003",
                f"missing API key environment variable: {api_key_env}",
                f"Set {api_key_env} or switch model.provider to deterministic.",
            )
        base_url = _base_url_from_params(params, provider_defaults["base_url"])
        deepseek_endpoint_mode = _deepseek_endpoint_mode(
            params.get("deepseek_endpoint_mode")
        )
        resolved_base_url = _deepseek_base_url_for_endpoint_mode(
            provider_name=model_config.provider,
            base_url=str(base_url) if base_url else None,
            endpoint_mode=deepseek_endpoint_mode,
        )
        organization = _env_value(params.get("organization_env"))
        project = _env_value(params.get("project_env"))
        timeout_seconds = (
            float(params["timeout_seconds"]) if "timeout_seconds" in params else None
        )
        return cls(
            provider_name=model_config.provider,
            model_name=model_config.name,
            api_key=api_key,
            base_url=resolved_base_url,
            organization=organization,
            project=project,
            timeout_seconds=timeout_seconds,
            default_temperature=float(params["temperature"])
            if "temperature" in params
            else None,
            default_max_output_tokens=int(params["max_output_tokens"])
            if "max_output_tokens" in params
            else None,
        )

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        text = " ".join(message.content for message in request.messages)
        return max(1, len(text) // 4)

    def generate(self, request: ModelRequest) -> ModelResponse:
        try:
            from openai import (
                APIError,
                APITimeoutError,
                AuthenticationError,
                OpenAI,
            )
        except ImportError as exc:
            raise ProofAgentError(
                "PA_MODEL_001",
                "openai package is required for openai_compatible provider.",
                'Install with: pip install "proof-agent[openai]".',
            ) from exc

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=request.timeout_seconds
            if request.timeout_seconds is not None
            else self._timeout_seconds,
            organization=self._organization,
            project=self._project,
        )
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
        }
        if request.function_schema is not None:
            payload.update(
                _function_tool_payload(
                    request.function_schema,
                    provider_name=self.provider_name,
                    base_url=self._base_url,
                )
            )
        elif request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        temperature = request.temperature
        if temperature is None:
            temperature = self._default_temperature
        if temperature is not None:
            payload["temperature"] = temperature
        max_tokens = request.max_output_tokens
        if max_tokens is None:
            max_tokens = self._default_max_output_tokens
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            response = client.chat.completions.create(**payload)
        except AuthenticationError as exc:
            raise ProofAgentError(
                "PA_MODEL_003",
                "model provider authentication failed.",
                "Check the configured API key environment variable.",
            ) from exc
        except APITimeoutError as exc:
            raise ProofAgentError(
                "PA_MODEL_004",
                "model provider request timed out.",
                "Increase timeout_seconds or retry later.",
            ) from exc
        except APIError as exc:
            raise ProofAgentError(
                "PA_MODEL_002",
                "model provider API error.",
                "Retry later or inspect provider status.",
            ) from exc

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        token_usage = None
        if usage is not None:
            token_usage = TokenUsage(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=getattr(usage, "total_tokens", None),
            )
        return ModelResponse(
            content=_extract_choice_content(choice),
            provider_name=self.provider_name,
            model_name=self.model_name,
            token_usage=token_usage,
            finish_reason=choice.finish_reason,
            raw_response_id=getattr(response, "id", None),
        )


def _function_tool_payload(
    function_schema: ModelFunctionSchema,
    *,
    provider_name: str,
    base_url: str | None,
) -> dict[str, Any]:
    function_payload: dict[str, Any] = {
        "name": function_schema.name,
        "description": function_schema.description,
        "parameters": function_schema.model_dump(mode="json")["parameters_schema"],
    }
    if function_schema.strict and _supports_strict_function_schema(
        provider_name=provider_name,
        base_url=base_url,
    ):
        function_payload["strict"] = True
    payload: dict[str, Any] = {
        "tools": [{"type": "function", "function": function_payload}],
        "tool_choice": {
            "type": "function",
            "function": {"name": function_schema.name},
        },
    }
    if _is_deepseek_provider(provider_name=provider_name, base_url=base_url):
        payload["extra_body"] = {"thinking": {"type": "disabled"}}
    return payload


def _supports_strict_function_schema(*, provider_name: str, base_url: str | None) -> bool:
    normalized_base_url = (base_url or "").rstrip("/")
    if _is_deepseek_provider(provider_name=provider_name, base_url=base_url):
        return normalized_base_url.endswith("/beta")
    return True


def _is_deepseek_provider(*, provider_name: str, base_url: str | None) -> bool:
    normalized_base_url = (base_url or "").rstrip("/")
    return provider_name == "deepseek" or "api.deepseek.com" in normalized_base_url


def _deepseek_endpoint_mode(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "beta"
    endpoint_mode = str(value).strip().lower()
    if endpoint_mode not in _DEEPSEEK_ENDPOINT_MODES:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported deepseek_endpoint_mode: {value}",
            "Use deepseek_endpoint_mode beta or standard.",
        )
    return endpoint_mode


def _deepseek_base_url_for_endpoint_mode(
    *,
    provider_name: str,
    base_url: str | None,
    endpoint_mode: str,
) -> str | None:
    if not _is_deepseek_provider(provider_name=provider_name, base_url=base_url):
        return base_url

    normalized_base_url = (base_url or "").rstrip("/")
    if normalized_base_url not in {
        "",
        _DEEPSEEK_STANDARD_BASE_URL,
        _DEEPSEEK_BETA_BASE_URL,
    }:
        return base_url

    if endpoint_mode == "standard":
        return _DEEPSEEK_STANDARD_BASE_URL
    return _DEEPSEEK_BETA_BASE_URL


def _extract_choice_content(choice: Any) -> str:
    message = _get_value(choice, "message")
    for tool_call in _get_value(message, "tool_calls") or ():
        function = _get_value(tool_call, "function")
        arguments = _get_value(function, "arguments")
        if arguments:
            return str(arguments)
    return str(_get_value(message, "content") or "")


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _env_value(env_name: Any) -> str | None:
    if not env_name:
        return None
    return os.environ.get(str(env_name))


def _base_url_from_params(
    params: dict[str, Any],
    default_base_url: str | None,
) -> str | None:
    if "base_url" in params:
        return str(params["base_url"]) if params["base_url"] else None
    if "base_url_env" in params:
        return os.environ.get(str(params["base_url_env"]))
    return default_base_url
