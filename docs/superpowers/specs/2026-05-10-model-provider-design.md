# ModelProvider Design

Date: 2026-05-10

## Goal

Add a `ModelProvider` abstraction that replaces the hard-coded `DeterministicProvider` call in the orchestrator with a pluggable provider system. First iteration supports OpenAI and Anthropic alongside the existing deterministic provider. Every model call passes through a policy gate, emits trace events, and reports token usage in the Governance Receipt.

## Approach

Protocol + Registry + Factory. Mirrors the existing `KnowledgeProvider` pattern. Each provider is a standalone adapter that implements the `ModelProvider` Protocol. A registry maps provider name strings to concrete classes. A factory resolves the manifest's `ModelConfig` to a live provider instance. Framework SDK types stay inside provider adapters and never leak into contracts, policy, trace, or receipt models.

## Design

### 1. Protocol and Contracts

**New file: `proof_agent/contracts/model.py`**

```python
class TokenUsage(FrozenModel):
    input_tokens: int
    output_tokens: int


class ModelResponse(FrozenModel):
    content: str
    refusal_reason: str | None = None
    token_usage: TokenUsage | None = None
    provider_name: str
    model_name: str
    finish_reason: str | None = None   # "stop", "length", "content_filter"
```

**New file: `proof_agent/providers/protocol.py`**

```python
from collections.abc import Iterator

class ModelProvider(Protocol):
    def generate(self, prompt: str, *, system: str = "") -> ModelResponse: ...
    def stream(self, prompt: str, *, system: str = "") -> Iterator[ModelResponse]: ...
    @property
    def provider_name(self) -> str: ...
    @property
    def model_name(self) -> str: ...
```

- `ModelResponse` inherits `FrozenModel` (immutable, consistent with all other contracts).
- `TokenUsage` is its own contract so it can appear independently in trace events.
- `Iterator` imported from `collections.abc`, consistent with `_base.py`.
- `stream()` yields `ModelResponse` chunks. The final chunk carries `token_usage` and `finish_reason`; intermediate chunks have `token_usage=None`.
- `refusal_reason` captures provider-side content filtering (distinct from harness policy refusal).
- `generate()` and `stream()` share the same signature: `prompt` + optional `system` strings. No message array abstraction; that stays inside each provider adapter.
- Each provider implements a `from_config(cls, model_config: ModelConfig) -> Self` class method that handles its own key resolution and construction. This keeps provider-specific logic inside the provider and avoids hard-coded `if` branching in the factory.

### 2. Provider Implementations

**Directory: `proof_agent/providers/`**

```
providers/
├── __init__.py              # exports resolve_provider()
├── protocol.py              # ModelProvider Protocol
├── registry.py              # provider name → class mapping
├── deterministic.py         # wraps existing DeterministicProvider
├── openai_provider.py       # OpenAI adapter
└── anthropic_provider.py    # Anthropic adapter
```

**DeterministicModelProvider:** Wraps the existing `demo/deterministic_provider.py`. `generate()` delegates to `DeterministicProvider.answer()`, returns `ModelResponse` with no token usage. `stream()` yields a single chunk (identical to `generate()`). No network, no API key. `demo/deterministic_provider.py` is not modified. Implements `from_config(cls, model_config) -> Self` — no key resolution needed, just wraps the config.

**OpenAIModelProvider:** Uses the `openai` SDK. Constructor takes `model_name`, `api_key`, optional `base_url`. `from_config()` reads `OPENAI_API_KEY` from environment, raises `PA_MODEL_003` if missing. `generate()` calls `client.chat.completions.create()`, maps the response to `ModelResponse` with token usage from `response.usage`. `stream()` calls `client.chat.completions.create(stream=True)`, accumulates content chunks, and emits the final chunk with accumulated usage. Catches `openai.APIError`, `openai.AuthenticationError`, `openai.APITimeoutError` and wraps them in `ProofAgentError`.

**AnthropicProvider:** Same structure using the `anthropic` SDK. Constructor takes `model_name`, `api_key`. `from_config()` reads `ANTHROPIC_API_KEY` from environment, raises `PA_MODEL_003` if missing. `generate()` calls `client.messages.create()`, maps content from `response.content[0].text` and usage from `response.usage`. `stream()` uses `client.messages.stream()`. Catches `anthropic.APIError`, `anthropic.AuthenticationError`, `anthropic.APITimeoutError` and wraps them.

**Error codes:**

| Code | Meaning |
|------|---------|
| `PA_MODEL_001` | Unsupported provider name (already exists) |
| `PA_MODEL_002` | Provider API error (rate limit, server error) |
| `PA_MODEL_003` | Authentication failure (missing/invalid API key) |
| `PA_MODEL_004` | Provider timeout |

Callers never see provider-specific exception types.

### 3. Registry, Factory, and Config Changes

**Registry (`providers/registry.py`):**

```python
_PROVIDER_MAP: dict[str, type] = {
    "deterministic": DeterministicModelProvider,
    "openai": OpenAIModelProvider,
    "anthropic": AnthropicModelProvider,
}
```

Adding a provider = one line in this dict + one file in the directory.

**Factory (`providers/__init__.py`):**

```python
def resolve_provider(model_config: ModelConfig) -> ModelProvider:
    cls = _PROVIDER_MAP.get(model_config.provider)
    if cls is None:
        raise ProofAgentError("PA_MODEL_001", ...)
    return cls.from_config(model_config)
```

API key validation happens inside each provider's `from_config()` method at resolution time (fail early, before any policy evaluation or trace writing). Provider-specific construction logic (key resolution, client initialization) stays inside each provider class.

**ModelConfig change (`contracts/manifest.py`):**

```python
class ModelConfig(FrozenModel):
    provider: str                              # "deterministic" | "openai" | "anthropic"
    name: str                                  # "demo" | "gpt-4o" | "claude-sonnet-4-20250514"
    params: FrozenDict | None = None           # provider-specific overrides (temperature, max_tokens)
```

`params` is optional and opaque. Each provider reads what it needs. No typed per-provider config schemas in the contract layer. The `params` field is intentionally omitted from `required_nested["model"]` in `config/validation.py` because it is optional.

**Validation change (`config/validation.py`):**

```python
# Replaces hard-coded "deterministic" gate
supported = {"deterministic", "openai", "anthropic"}
if manifest.model.provider not in supported:
    raise ProofAgentError(
        "PA_MODEL_001",
        f"unsupported model provider: {manifest.model.provider}",
        f"Supported providers: {', '.join(sorted(supported))}",
    )
```

### 4. Policy Gate and Trace Events

**New enforcement point: `before_model_call`**

Added to the `EnforcementPoint` enum in `contracts/policy.py`:

```python
class EnforcementPoint(str, Enum):
    BEFORE_RETRIEVAL = "before_retrieval"
    BEFORE_ANSWER = "before_answer"
    BEFORE_TOOL_CALL = "before_tool_call"
    BEFORE_MEMORY_WRITE = "before_memory_write"
    BEFORE_MODEL_CALL = "before_model_call"    # NEW
```

The `PolicyEngine._evaluate_rule()` dispatch in `policy/engine.py` gains a corresponding `_evaluate_before_model_call()` method.

This gates the actual LLM invocation. It does not replace `before_answer`:

- `before_answer` — "is there enough evidence to justify an answer?" (no model involved)
- `before_model_call` — "may we invoke the model to generate that answer?" (model-specific: cost limits, provider allowlisting, rate limiting)

A policy YAML can deny at `before_model_call` to block expensive model calls even when evidence is sufficient.

**New trace events:**

Added to the `TraceEventType` enum in `contracts/trace.py`:

```python
class TraceEventType(str, Enum):
    # ... existing 18 members ...
    MODEL_REQUEST = "model_request"      # NEW
    MODEL_RESPONSE = "model_response"    # NEW
```

This brings the total to 20 v1 event types. The normative Trace Event Contract document (`docs/concepts/trace-event-contract.md`) must be updated accordingly.

`MODEL_REQUEST` payload:

```python
{
    "provider": "openai",
    "model": "gpt-4o",
    "prompt_length": 142,
    "system_prompt_length": 58,
    "stream": false,
}
```

`MODEL_RESPONSE` payload:

```python
{
    "provider": "openai",
    "model": "gpt-4o",
    "finish_reason": "stop",
    "content_length": 87,
    "token_usage": {"input_tokens": 52, "output_tokens": 34},
}
```

Payloads carry lengths (character counts), not full text. Prompts and responses may contain sensitive data. Character counts give auditors size information without redaction risk. For streaming, `MODEL_REQUEST` fires once before the stream starts, `MODEL_RESPONSE` fires once after completion with accumulated usage.

### 5. Orchestrator Integration and Governance Receipt

**Updated execution flow:**

```
 1. load_agent_manifest(agent_yaml)
 2. resolve_provider(manifest.model)              ← NEW (fail-fast)
 3. TraceWriter(trace_path, run_id)
 4. trace.emit("run_started")
 5. trace.emit("manifest_loaded")
 6. PolicyEngine.from_file(...)
 7. policy.evaluate("before_retrieval", ...)
 8. KnowledgeProvider.retrieve(...)
 9. evaluate_evidence(...)
10. trace.emit("evidence_evaluation")
11. policy.evaluate("before_answer", ...)
12. policy.evaluate("before_model_call", ...)     ← NEW
13. trace.emit("model_request", ...)              ← NEW
14. provider.generate(prompt, system=system)      ← NEW (was DeterministicProvider hard-coded)
15. trace.emit("model_response", ...)             ← NEW
16. [tool approval flow unchanged]
17. SessionMemory.write(...)
18. _finalize() → receipt, return RunResult
```

Provider resolution fails fast (step 2) before any trace writing. If API key is missing or provider name is unsupported, the run aborts immediately.

Steps 12-15 (before_model_call, model_request, provider.generate, model_response) are only reached in the standard answer path — not in the tool-required question path, which branches before `before_answer` is evaluated. This matches current behavior where `DeterministicProvider().answer()` is never called for tool-required questions.

**WorkflowState additions (`contracts/run.py`):**

```python
class WorkflowState(FrozenModel):
    # ... existing fields ...
    model_provider: str | None = None      # "openai"
    model_name: str | None = None          # "gpt-4o"
    token_usage: TokenUsage | None = None
```

Since `WorkflowState` is a `FrozenModel`, these fields can only be set at construction time. The orchestrator constructs a new `WorkflowState` via `state.model_copy(update={"model_provider": ..., "model_name": ..., "token_usage": ...})` after the model response is received, consistent with the project's immutable update pattern.

**Governance Receipt addition:**

New "Model Usage" section between "Policy Decisions" and "Tool Approvals":

```markdown
## Model Usage

| Field | Value |
|-------|-------|
| Provider | openai |
| Model | gpt-4o |
| Input Tokens | 52 |
| Output Tokens | 34 |
| Finish Reason | stop |
```

For deterministic runs: `Provider: deterministic`, `Tokens: N/A`.

The Jinja2 template at `proof_agent/audit/templates/governance_receipt.md.j2` must be updated to render this section. The `_build_context()` function in `receipt.py` must extract `model_request`/`model_response` events from the trace and add model usage data to the template context.

**`agent.yaml` examples:**

```yaml
# Deterministic (unchanged)
model:
  provider: deterministic
  name: demo

# OpenAI
model:
  provider: openai
  name: gpt-4o

# Anthropic
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
```

### 6. Dependencies and Test Strategy

**New dependencies:**

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0.0", "ruff>=0.5.0", "mypy>=1.10.0"]
openai = ["openai>=1.30.0"]
anthropic = ["anthropic>=0.30.0"]
all = ["proof-agent[openai,anthropic]"]
```

Provider SDKs are optional dependencies so the deterministic demo works out of the box without pulling in OpenAI/Anthropic packages. Users install `pip install proof-agent[openai]` or `pip install proof-agent[anthropic]` as needed. The factory validates that the required SDK is installed when resolving a provider and raises `PA_MODEL_001` with an actionable message (e.g., "Install with: pip install proof-agent[openai]") if it is missing.

**Test strategy:**

| Test file | What it verifies |
|-----------|-----------------|
| `test_model_contracts.py` | `ModelResponse` and `TokenUsage` immutability, field validation |
| `test_model_provider_registry.py` | resolve_provider for each name, unsupported provider raises PA_MODEL_001, missing API key raises PA_MODEL_003 |
| `test_deterministic_model_provider.py` | wraps existing DeterministicProvider, returns correct ModelResponse |
| `test_openai_provider.py` | generate/stream with mocked OpenAI client, token usage extraction, error wrapping |
| `test_anthropic_provider.py` | same pattern with mocked Anthropic client |
| `test_policy_before_model_call.py` | policy deny at `before_model_call` blocks generation |
| `test_trace_model_events.py` | MODEL_REQUEST/MODEL_RESPONSE emitted in correct order with right payloads |
| `test_receipt_model_usage.py` | receipt contains Model Usage section with token counts |

All real-provider tests use mocked SDK clients (no API key needed in CI). Deterministic provider tests use the real code path.

## Files Changed/Added

| Action | File |
|--------|------|
| New | `proof_agent/providers/__init__.py` |
| New | `proof_agent/providers/protocol.py` |
| New | `proof_agent/providers/registry.py` |
| New | `proof_agent/providers/deterministic.py` |
| New | `proof_agent/providers/openai_provider.py` |
| New | `proof_agent/providers/anthropic_provider.py` |
| New | `proof_agent/contracts/model.py` |
| New | `tests/test_model_contracts.py` |
| New | `tests/test_model_provider_registry.py` |
| New | `tests/test_deterministic_model_provider.py` |
| New | `tests/test_openai_provider.py` |
| New | `tests/test_anthropic_provider.py` |
| New | `tests/test_policy_before_model_call.py` |
| New | `tests/test_trace_model_events.py` |
| New | `tests/test_receipt_model_usage.py` |
| Modify | `proof_agent/contracts/__init__.py` (export TokenUsage, ModelResponse) |
| Modify | `proof_agent/contracts/manifest.py` (add `params` to ModelConfig) |
| Modify | `proof_agent/contracts/trace.py` (add MODEL_REQUEST, MODEL_RESPONSE to TraceEventType enum) |
| Modify | `proof_agent/contracts/run.py` (add model fields to WorkflowState) |
| Modify | `proof_agent/contracts/policy.py` (add BEFORE_MODEL_CALL to EnforcementPoint enum) |
| Modify | `proof_agent/policy/engine.py` (add before_model_call dispatch) |
| Modify | `proof_agent/errors.py` (add PA_MODEL_002, PA_MODEL_003, PA_MODEL_004 to ErrorCode enum) |
| Modify | `proof_agent/config/validation.py` (generalize provider gate) |
| Modify | `proof_agent/workflow/orchestrator.py` (inject provider, add gate + trace) |
| Modify | `proof_agent/audit/receipt.py` (extract model events, add to context) |
| Modify | `proof_agent/audit/templates/governance_receipt.md.j2` (add Model Usage section) |
| Modify | `docs/concepts/trace-event-contract.md` (add model_request, model_response to event table) |
| Modify | `pyproject.toml` (add openai, anthropic optional deps) |

## What Stays Unchanged

- `proof_agent/demo/deterministic_provider.py` — not modified, only wrapped
- `proof_agent/knowledge/` — no changes
- `proof_agent/tools/` — no changes
- `proof_agent/memory/` — no changes
- `proof_agent/compare/` — no changes
- All existing contracts remain backward-compatible (additive changes only)
