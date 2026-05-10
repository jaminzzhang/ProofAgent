# ModelProvider Design

Date: 2026-05-10

## Goal

Add a `ModelProvider` abstraction that replaces the hard-coded `DeterministicProvider` call in the orchestrator with a pluggable, auditable remote model layer.

The supported provider names are:

- `deterministic`
- `openai_compatible`
- `azure_openai`
- `anthropic`

First implementation scope:

- Implement `deterministic`.
- Implement `openai_compatible`.
- Define config contracts, validation messages, and test placeholders for `azure_openai` and `anthropic`.
- Do not integrate Azure OpenAI or Anthropic SDKs yet.

Every model call must pass through the Harness control path: evidence policy, `before_answer`, `before_model_call`, model trace events, output validators, final output, and Governance Receipt.

## Design Principles

1. **Harness stays in control.** The model generates text, but it does not decide routing, tool execution, memory writes, policy outcomes, or final acceptance.
2. **Deterministic demo remains API-key-free.** `proof-agent demo` must continue to run without network access or provider SDKs.
3. **Provider SDKs stay inside adapters.** OpenAI-compatible, Azure, and Anthropic client objects must not leak into contracts, policy, workflow, trace, or receipt code.
4. **Failures are auditable where possible.** Missing SDKs, missing API keys, provider errors, and timeouts should emit `model_error` after trace initialization unless config validation fails before the run can start.
5. **Remote output is untrusted.** Model content must pass schema, safety, and citation/evidence validation before `_finalize()`.
6. **Configuration is explicit but not secret-bearing.** `agent.yaml` may name env var keys, endpoints, and provider params. It must never contain raw API keys, bearer tokens, or secrets.

## Approach

Use Protocol + Registry + Factory, mirroring the existing `KnowledgeProvider` pattern.

Each provider is a standalone adapter that implements a `ModelProvider` Protocol. A registry maps provider names to provider classes. A factory resolves `ModelConfig` into a live provider instance. The contract layer defines provider-neutral request and response models.

This gives us one stable boundary:

```text
workflow/orchestrator
  -> providers.resolve_provider(ModelConfig)
  -> ModelProvider.generate(ModelRequest)
  -> ModelResponse
```

## 1. Provider Contracts

**New file: `proof_agent/contracts/model.py`**

```python
from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class ModelRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelMessage(FrozenModel):
    role: ModelRole
    content: str
    name: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class TokenUsage(FrozenModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int | None = None


class ModelRequest(FrozenModel):
    messages: tuple[ModelMessage, ...]
    provider: str
    model: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int | None = None
    stream: bool = False
    response_format: Literal["text", "json"] = "text"
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    evidence_sources: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class ModelResponse(FrozenModel):
    content: str
    provider_name: str
    model_name: str
    refusal_reason: str | None = None
    token_usage: TokenUsage | None = None
    finish_reason: str | None = None
    raw_response_id: str | None = None
```

Why `ModelRequest` instead of `prompt: str, system: str`:

- It supports system/user/assistant/tool messages without changing the provider protocol later.
- It gives output validators access to evidence source metadata.
- It keeps provider params typed at the Harness boundary.
- It makes trace payloads easier to produce without passing raw prompt text around loosely.

The request still keeps content as plain strings. Multimodal inputs, tool-call messages, JSON schema output, and provider-native reasoning controls are out of first implementation scope.

## 2. Provider Protocol

**New file: `proof_agent/providers/protocol.py`**

```python
from typing import Protocol, Self

from proof_agent.contracts import ModelRequest, ModelResponse
from proof_agent.contracts.manifest import ModelConfig


class ModelProvider(Protocol):
    @classmethod
    def from_config(cls, model_config: ModelConfig) -> Self: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def estimate_tokens(self, request: ModelRequest) -> int | None: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...
```

No streaming method in first implementation. `ModelRequest.stream` exists so policy context and trace payloads can represent the intent, but v1 provider adapters may reject `stream=True` with `PA_MODEL_001` or `PA_MODEL_002` until streaming is implemented.

## 3. Provider Implementations

**Directory: `proof_agent/providers/`**

```text
providers/
├── __init__.py                    # exports resolve_provider()
├── protocol.py                    # ModelProvider Protocol
├── registry.py                    # provider name -> class mapping
├── deterministic.py               # implemented in phase 1
├── openai_compatible.py           # implemented in phase 1
├── azure_openai.py                # config contract + validation placeholder only
└── anthropic.py                   # config contract + validation placeholder only
```

### `deterministic`

Wraps the existing `proof_agent/demo/deterministic_provider.py`.

- `from_config()` requires no env vars.
- `estimate_tokens()` returns `None`.
- `generate()` delegates to `DeterministicProvider.answer()` using the final user message content.
- Returns `ModelResponse(provider_name="deterministic", model_name=model_config.name, token_usage=None)`.
- No network, no SDK, no API key.
- Existing deterministic provider file remains unchanged.

### `openai_compatible`

Uses the `openai` Python SDK against Chat Completions-compatible endpoints.

This deliberately chooses the Chat Completions surface for compatibility with OpenAI-compatible providers such as OpenAI, DeepSeek, Qwen-compatible gateways, OpenRouter, and local OpenAI-compatible servers. OpenAI-native future work may add a separate `openai_responses` provider if Responses API features become necessary.

Config resolution:

- `api_key_env`, default `OPENAI_API_KEY`
- `base_url_env`, default `OPENAI_BASE_URL`
- `base_url`, optional non-secret literal endpoint
- `organization_env`, optional
- `project_env`, optional
- `timeout_seconds`, optional
- `temperature`, optional
- `max_output_tokens`, optional

Behavior:

- Missing `openai` package raises `PA_MODEL_001` with install hint.
- Missing API key raises `PA_MODEL_003`.
- `generate()` calls `client.chat.completions.create()`.
- Provider maps usage into `TokenUsage`.
- Provider maps finish reason into `ModelResponse.finish_reason`.
- Provider wraps SDK exceptions into `ProofAgentError`.
- Provider never returns raw SDK response objects.

Official context: OpenAI currently recommends Responses API for new OpenAI-native projects, while Chat Completions remains supported and is the common compatibility surface for non-OpenAI providers.

### `azure_openai`

Configuration contract and validation placeholder only in first implementation.

The provider name is accepted by docs and config examples, but `resolve_provider()` raises a clear `PA_MODEL_001` until the adapter is implemented:

```text
azure_openai provider is defined but not implemented yet.
Install/implementation support is planned after openai_compatible.
```

Expected future config:

- `endpoint_env`, default `AZURE_OPENAI_ENDPOINT`
- `api_key_env`, default `AZURE_OPENAI_API_KEY`
- `api_version`
- `deployment`
- `timeout_seconds`
- `temperature`
- `max_output_tokens`

No Azure SDK dependency is added in first implementation.

### `anthropic`

Configuration contract and validation placeholder only in first implementation.

The provider name is accepted by docs and config examples, but `resolve_provider()` raises a clear `PA_MODEL_001` until the adapter is implemented:

```text
anthropic provider is defined but not implemented yet.
```

Expected future config:

- `api_key_env`, default `ANTHROPIC_API_KEY`
- `base_url_env`, optional
- `anthropic_version`, default future adapter value
- `timeout_seconds`
- `temperature`
- `max_output_tokens`

No Anthropic SDK dependency is added in first implementation.

## 4. Registry, Factory, and Config

**Registry (`proof_agent/providers/registry.py`):**

```python
_PROVIDER_MAP: dict[str, type[ModelProvider]] = {
    "deterministic": DeterministicModelProvider,
    "openai_compatible": OpenAICompatibleModelProvider,
    "azure_openai": AzureOpenAIPlaceholderProvider,
    "anthropic": AnthropicPlaceholderProvider,
}
```

Adding a real provider requires one adapter file, one registry entry, provider-specific tests, and docs.

**Factory (`proof_agent/providers/__init__.py`):**

```python
def resolve_provider(model_config: ModelConfig) -> ModelProvider:
    provider_cls = _PROVIDER_MAP.get(model_config.provider)
    if provider_cls is None:
        raise ProofAgentError("PA_MODEL_001", ...)
    return provider_cls.from_config(model_config)
```

Provider-specific key resolution, SDK import, client initialization, and params validation stay inside `from_config()`.

**ModelConfig (`proof_agent/contracts/manifest.py`):**

```python
class ModelConfig(FrozenModel):
    provider: str
    name: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)
```

`params` is opaque to the contract layer but not unchecked. Each provider must validate its accepted keys and reject unsupported or secret-looking fields.

Forbidden `model.params` keys:

- `api_key`
- `authorization`
- `bearer`
- `password`
- `secret`
- `access_token`
- `provider_api_key`

Provider-specific validators should reject those with `PA_SECRET_001`.

**Supported provider validation (`proof_agent/config/validation.py`):**

```python
supported = {"deterministic", "openai_compatible", "azure_openai", "anthropic"}
```

This validation checks provider names only. It does not prove that a placeholder provider is executable. Runtime resolution produces the clearer "configured but not implemented" message.

## 5. Policy Gate

Add a new enforcement point:

```python
class EnforcementPoint(str, Enum):
    BEFORE_RETRIEVAL = "before_retrieval"
    BEFORE_ANSWER = "before_answer"
    BEFORE_TOOL_CALL = "before_tool_call"
    BEFORE_MEMORY_WRITE = "before_memory_write"
    BEFORE_MODEL_CALL = "before_model_call"
```

`before_answer` and `before_model_call` are different gates:

- `before_answer`: Is there enough evidence and citation support to answer?
- `before_model_call`: Is this model invocation allowed under cost, provider, and runtime policy?

`before_model_call` receives this context:

```python
{
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "estimated_tokens": 612,
    "stream": False,
    "cost_class": "remote",
    "question": question,
    "accepted_evidence_count": 2,
    "citations_present": True,
}
```

Cost classes:

- `local`: deterministic and local model providers
- `remote`: network model providers
- `enterprise`: Azure or managed enterprise providers

The first implementation can support simple rule conditions:

- provider equals
- model equals
- cost_class equals
- estimated_tokens less than or equal to threshold
- stream equals

If no `before_model_call` rule matches, default allow follows the current `PolicyEngine` behavior.

## 6. Trace Events

Add three trace event types:

```python
class TraceEventType(str, Enum):
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    MODEL_ERROR = "model_error"
```

`model_request` payload:

```python
{
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "message_count": 2,
    "prompt_length": 1420,
    "system_prompt_length": 220,
    "estimated_tokens": 612,
    "stream": False,
    "cost_class": "remote",
}
```

`model_response` payload:

```python
{
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "finish_reason": "stop",
    "content_length": 420,
    "refusal_reason": None,
    "token_usage": {
        "input_tokens": 550,
        "output_tokens": 90,
        "total_tokens": 640,
    },
}
```

`model_error` payload:

```python
{
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "error_code": "PA_MODEL_004",
    "error_class": "timeout",
    "retryable": True,
    "message": "Provider request timed out.",
    "duration_ms": 30000,
}
```

Trace safety rules:

- Do not write raw prompts.
- Do not write raw responses.
- Do not write raw API keys, headers, authorization values, or provider error bodies.
- Do write lengths, provider names, model names, token usage, finish reason, and normalized error classes.
- Redaction must still run on all model event payloads.

## 7. Orchestrator Integration

Updated standard answer flow:

```text
 1. load_agent_manifest(agent_yaml)
 2. prepare trace paths and TraceWriter
 3. trace.emit("run_started")
 4. trace.emit("manifest_loaded")
 5. resolve_provider(manifest.model)
      - on error: trace.emit("model_error"), fail closed
 6. policy.evaluate("before_retrieval")
 7. KnowledgeProvider.retrieve(...)
 8. evaluate_evidence(...)
 9. policy.evaluate("before_answer")
10. if evidence/policy fail: refuse without model call
11. build ModelRequest from question + accepted evidence
12. provider.estimate_tokens(request)
13. policy.evaluate("before_model_call", context)
14. if denied: refuse/escalate without model call
15. trace.emit("model_request")
16. provider.generate(request)
      - on error: trace.emit("model_error"), fail closed
17. trace.emit("model_response")
18. validate_final_output_schema(...)
19. validate_no_secret_strings(...)
20. validate_citations_supported_by_evidence(...)
21. SessionMemory.write(...)
22. _finalize() -> receipt, RunResult
```

Tool-required flow stays separate for first implementation. It does not call a remote model unless a future design explicitly adds a post-tool generation step.

Provider resolution happens after trace initialization so most remote configuration failures can be audited. Manifest shape errors may still fail before trace creation because they prevent locating audit paths.

## 8. Output Validation After Model Response

Remote model output is not accepted directly.

After `ModelResponse` returns, the orchestrator must run:

1. `validate_final_output_schema(...)`
2. `validate_no_secret_strings(response.content)`
3. `validate_citations_supported_by_evidence(response.content, evidence)`

If any validator fails:

- emit a validator trace event with `status="blocked"`
- final outcome is a controlled refusal or escalation
- do not write unsafe model output as final answer
- receipt must show the blocked validator result

The citation validator can be a new file:

```text
proof_agent/validators/citations.py
```

Minimum first behavior:

- If final answer claims citations, each citation must match one of the accepted evidence sources.
- If the answer is expected to cite sources but no accepted evidence exists, fail.
- The validator should be deterministic and should not use LLM-as-judge.

## 9. Governance Receipt

Add a "Model Usage" section after "Policy Decisions":

```markdown
## Model Usage

| Field | Value |
|-------|-------|
| Provider | openai_compatible |
| Model | gpt-4o-mini |
| Cost Class | remote |
| Estimated Tokens | 612 |
| Input Tokens | 550 |
| Output Tokens | 90 |
| Finish Reason | stop |
```

If the provider is deterministic:

- Provider: `deterministic`
- Cost Class: `local`
- Tokens: `N/A`

If model resolution or generation fails:

- render provider/model if known
- render error code and normalized error class
- do not render raw provider error body

`proof_agent/audit/receipt.py` must extract `model_request`, `model_response`, and `model_error` events from the trace and pass normalized model usage data to the Jinja2 template.

## 10. Agent YAML Examples

Deterministic:

```yaml
model:
  provider: deterministic
  name: demo
```

OpenAI-compatible:

```yaml
model:
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key_env: OPENAI_API_KEY
    base_url_env: OPENAI_BASE_URL
    temperature: 0
    max_output_tokens: 800
    timeout_seconds: 30
```

OpenAI-compatible with literal non-secret endpoint:

```yaml
model:
  provider: openai_compatible
  name: deepseek-chat
  params:
    api_key_env: DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com/v1
    temperature: 0
    max_output_tokens: 800
```

Azure OpenAI placeholder:

```yaml
model:
  provider: azure_openai
  name: gpt-4o-mini
  params:
    endpoint_env: AZURE_OPENAI_ENDPOINT
    api_key_env: AZURE_OPENAI_API_KEY
    api_version: "2025-01-01-preview"
    deployment: proof-agent-demo
```

Anthropic placeholder:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
  params:
    api_key_env: ANTHROPIC_API_KEY
    max_output_tokens: 800
```

## 11. Dependencies

First implementation optional dependencies:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0.0", "ruff>=0.5.0", "mypy>=1.10.0"]
openai = ["openai>=1.30.0"]
all = ["proof-agent[openai]"]
```

No Azure or Anthropic SDK dependencies in first implementation.

Users who want `openai_compatible` install:

```bash
pip install "proof-agent[openai]"
```

The deterministic demo continues to work with the base install.

## 12. Test Strategy

| Test file | What it verifies |
|-----------|------------------|
| `tests/test_model_contracts.py` | `ModelRequest`, `ModelMessage`, `ModelResponse`, `TokenUsage` immutability and validation |
| `tests/test_model_provider_registry.py` | supported provider names, unsupported provider errors, placeholder provider messages |
| `tests/test_deterministic_model_provider.py` | wrapper delegates to existing deterministic answer behavior |
| `tests/test_openai_compatible_provider.py` | mocked OpenAI-compatible client, config params, token usage mapping, error wrapping |
| `tests/test_model_config_validation.py` | forbidden secret-looking params rejected, unknown params behavior documented |
| `tests/test_policy_before_model_call.py` | provider/model/token/stream/cost_class context can allow or deny generation |
| `tests/test_trace_model_events.py` | `model_request`, `model_response`, and `model_error` are emitted safely |
| `tests/test_receipt_model_usage.py` | receipt renders model usage and model errors without raw prompt/response |
| `tests/test_model_output_validators.py` | model output must pass schema, safety, and citation validation |

All remote-provider tests use mocked clients. No test requires a real API key or network call.

## 13. Files Changed or Added

| Action | File |
|--------|------|
| New | `proof_agent/contracts/model.py` |
| New | `proof_agent/providers/__init__.py` |
| New | `proof_agent/providers/protocol.py` |
| New | `proof_agent/providers/registry.py` |
| New | `proof_agent/providers/deterministic.py` |
| New | `proof_agent/providers/openai_compatible.py` |
| New | `proof_agent/providers/azure_openai.py` |
| New | `proof_agent/providers/anthropic.py` |
| New | `proof_agent/validators/citations.py` |
| New | `tests/test_model_contracts.py` |
| New | `tests/test_model_provider_registry.py` |
| New | `tests/test_deterministic_model_provider.py` |
| New | `tests/test_openai_compatible_provider.py` |
| New | `tests/test_model_config_validation.py` |
| New | `tests/test_policy_before_model_call.py` |
| New | `tests/test_trace_model_events.py` |
| New | `tests/test_receipt_model_usage.py` |
| New | `tests/test_model_output_validators.py` |
| Modify | `proof_agent/contracts/__init__.py` |
| Modify | `proof_agent/contracts/manifest.py` |
| Modify | `proof_agent/contracts/policy.py` |
| Modify | `proof_agent/contracts/trace.py` |
| Modify | `proof_agent/contracts/run.py` |
| Modify | `proof_agent/errors.py` |
| Modify | `proof_agent/config/manifest.py` |
| Modify | `proof_agent/config/validation.py` |
| Modify | `proof_agent/policy/engine.py` |
| Modify | `proof_agent/workflow/orchestrator.py` |
| Modify | `proof_agent/audit/receipt.py` |
| Modify | `proof_agent/audit/templates/governance_receipt.md.j2` |
| Modify | `proof_agent/cli.py` |
| Modify | `docs/concepts/trace-event-contract.md` |
| Modify | `docs/concepts/agent-contract.md` |
| Modify | `pyproject.toml` |

## 14. What Stays Unchanged

- `proof_agent/demo/deterministic_provider.py` remains unchanged.
- `proof_agent/knowledge/` remains unchanged except for using evidence sources in request construction.
- `proof_agent/tools/` remains unchanged.
- `proof_agent/memory/` remains unchanged.
- `proof_agent/compare/` remains unchanged in first implementation unless a later plan explicitly adds live-model comparison.
- `proof-agent demo` remains deterministic and API-key-free.

## 15. Deferred Work

- Real Azure OpenAI adapter.
- Real Anthropic adapter.
- Streaming responses.
- OpenAI Responses API-native provider.
- Structured output schema enforcement through provider-native JSON mode.
- LLM-as-judge quality evaluation.
- Cost accounting beyond token counts and cost class.
