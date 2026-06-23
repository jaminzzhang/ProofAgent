# ReAct Planner Structured Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support ReAct Planner structured output through automatic provider transport selection while abstracting repeated `parameters_schema` construction.

**Architecture:** Add a small provider-neutral Structured Model Output Schema interface in the model contracts and keep `ModelFunctionSchema` compatible. Put JSON Schema construction behind a focused contract helper module, then let the OpenAI-compatible adapter render the schema either as provider-native tool-call arguments or ordinary JSON response format. ReAct Planner and final-answer request builders consume the same helper without owning provider transport details.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, pytest, existing Proof Agent ModelProvider protocol.

---

### Task 1: Structured Output Contract And Schema Helpers

**Files:**
- Modify: `proof_agent/contracts/model.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `proof_agent/contracts/structured_output.py`
- Create: `tests/test_model_structured_output.py`

- [ ] **Step 1: Write the failing schema behavior tests**

Create `tests/test_model_structured_output.py` with three public-interface tests:

```python
from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    ModelFunctionSchema,
    ModelStructuredOutputSchema,
    StructuredOutputTransport,
    ReActActionType,
)
from proof_agent.contracts.structured_output import (
    final_answer_structured_output_schema,
    react_action_proposal_structured_output_schema,
)
from proof_agent.control.workflow.harness_helpers import build_model_request


def test_structured_output_schema_defaults_to_auto_transport() -> None:
    schema = ModelStructuredOutputSchema(
        name="submit_test",
        parameters_schema={"type": "object"},
    )

    assert schema.transport == StructuredOutputTransport.AUTO
    assert schema.model_dump(mode="json")["parameters_schema"] == {"type": "object"}


def test_model_function_schema_remains_backward_compatible() -> None:
    schema = ModelFunctionSchema(
        name="submit_test",
        parameters_schema={"type": "object"},
    )

    assert isinstance(schema, ModelStructuredOutputSchema)
    assert schema.transport == StructuredOutputTransport.AUTO


def test_react_action_proposal_schema_narrows_eligible_actions() -> None:
    schema = react_action_proposal_structured_output_schema(
        frozenset({ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE})
    )

    assert schema.name == "submit_react_action_proposal"
    assert schema.strict is True
    assert schema.parameters_schema["required"] == (
        "action_type",
        "parameters",
        "target_tool_name",
    )
    assert schema.parameters_schema["properties"]["action_type"]["enum"] == (
        "generate_final_answer",
        "refuse",
    )


def test_final_answer_model_request_uses_shared_structured_output_schema() -> None:
    request = build_model_request(
        question="What is covered?",
        evidence=(
            EvidenceChunk(
                source="Policy",
                content="Covered inpatient claims require invoices.",
                status=EvidenceStatus.ACCEPTED,
                citation="policy.md#L1",
            ),
        ),
        provider="deterministic",
        model="answer-demo",
    )

    assert request.function_schema == final_answer_structured_output_schema()
    assert request.function_schema is not None
    assert request.function_schema.name == "submit_final_answer"
    assert request.function_schema.parameters_schema["required"] == (
        "message",
        "citations",
    )
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_structured_output.py -q
```

Expected: FAIL because `ModelStructuredOutputSchema`, `StructuredOutputTransport`, and `proof_agent.contracts.structured_output` do not exist.

- [ ] **Step 3: Add the minimal contract surface**

In `proof_agent/contracts/model.py`, add:

```python
class StructuredOutputTransport(str, Enum):
    AUTO = "auto"
    TOOL_CALL = "tool_call"
    JSON = "json"


class ModelStructuredOutputSchema(FrozenModel):
    """Provider-neutral structured output schema for one model response."""

    name: str
    description: str = ""
    parameters_schema: Mapping[str, Any] = Field(default_factory=FrozenDict)
    strict: bool = True
    transport: StructuredOutputTransport = StructuredOutputTransport.AUTO

    @field_validator("parameters_schema", mode="after")
    @classmethod
    def freeze_parameters_schema(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("parameters_schema")
    def serialize_parameters_schema(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast("dict[str, Any]", _json_plain(value))


class ModelFunctionSchema(ModelStructuredOutputSchema):
    """Backward-compatible name for structured model output schemas."""
```

Keep `ModelRequest.function_schema` compatible by typing it as `ModelStructuredOutputSchema | None`.

- [ ] **Step 4: Export the new contract names**

In `proof_agent/contracts/__init__.py`, import and add to `__all__`:

```python
ModelStructuredOutputSchema,
StructuredOutputTransport,
```

- [ ] **Step 5: Add the schema helper module**

Create `proof_agent/contracts/structured_output.py` with public factories:

```python
from __future__ import annotations

from collections.abc import AbstractSet, Mapping
from typing import Any

from proof_agent.contracts.model import ModelStructuredOutputSchema
from proof_agent.contracts.react_workflow import ReActActionType

_PLANNER_FUNCTION_SCHEMA_NAME = "submit_react_action_proposal"
_FINAL_ANSWER_FUNCTION_SCHEMA_NAME = "submit_final_answer"


def closed_object_schema(
    *,
    required: tuple[str, ...],
    properties: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": dict(properties),
    }


def react_action_proposal_structured_output_schema(
    eligible_actions: AbstractSet[ReActActionType] | None,
) -> ModelStructuredOutputSchema:
    allowed_actions = _allowed_action_values(eligible_actions)
    return ModelStructuredOutputSchema(
        name=_PLANNER_FUNCTION_SCHEMA_NAME,
        description=(
            "Submit exactly one governed Proof Agent ReAct planner action proposal. "
            "Do not include final answer text or refusal prose in function arguments."
        ),
        parameters_schema=closed_object_schema(
            required=("action_type", "parameters", "target_tool_name"),
            properties={
                "action_type": {"type": "string", "enum": allowed_actions},
                "parameters": {
                    "anyOf": (
                        closed_object_schema(required=(), properties={}),
                        closed_object_schema(
                            required=("query",),
                            properties={"query": {"type": "string"}},
                        ),
                        closed_object_schema(
                            required=("missing_fields",),
                            properties={
                                "missing_fields": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                }
                            },
                        ),
                        closed_object_schema(
                            required=("customer_id", "policy_id"),
                            properties={
                                "customer_id": {"type": "string"},
                                "policy_id": {"type": "string"},
                            },
                        ),
                        closed_object_schema(
                            required=("query", "max_results"),
                            properties={
                                "query": {"type": "string"},
                                "max_results": {"type": "number"},
                            },
                        ),
                    )
                },
                "target_tool_name": {"type": ("string", "null")},
            },
        ),
        strict=True,
    )


def final_answer_structured_output_schema() -> ModelStructuredOutputSchema:
    return ModelStructuredOutputSchema(
        name=_FINAL_ANSWER_FUNCTION_SCHEMA_NAME,
        description=(
            "Submit the governed final answer. Put user-visible prose in message and "
            "put exact accepted evidence citation refs in citations."
        ),
        parameters_schema=closed_object_schema(
            required=("message", "citations"),
            properties={
                "message": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
        ),
        strict=True,
    )


def _allowed_action_values(
    eligible_actions: AbstractSet[ReActActionType] | None,
) -> tuple[str, ...]:
    actions = eligible_actions if eligible_actions is not None else frozenset(
        {
            ReActActionType.ASK_CLARIFICATION,
            ReActActionType.GENERATE_FINAL_ANSWER,
            ReActActionType.PLAN_RETRIEVAL,
            ReActActionType.PROPOSE_TOOL_CALL,
            ReActActionType.REFUSE,
        }
    )
    return tuple(action.value for action in sorted(actions, key=lambda item: item.value))
```

- [ ] **Step 6: Migrate final answer request construction**

In `proof_agent/control/workflow/harness_helpers.py`, import `final_answer_structured_output_schema`, set `function_schema=final_answer_structured_output_schema()`, and remove the private `_final_answer_function_schema` function.

- [ ] **Step 7: Run the focused test to verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_structured_output.py -q
```

Expected: PASS.

### Task 2: OpenAI-Compatible Automatic Transport Strategy

**Files:**
- Modify: `proof_agent/capabilities/models/openai_compatible.py`
- Modify: `tests/test_openai_compatible_provider.py`

- [ ] **Step 1: Write the failing JSON transport test**

Add this test after `test_openai_compatible_provider_forces_function_schema_and_reads_arguments` in `tests/test_openai_compatible_provider.py`:

```python
def test_openai_compatible_provider_uses_json_transport_for_structured_output_schema(
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
                id="chatcmpl_json_structured",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"action_type":"refuse","parameters":{}}'),
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
    response = provider.generate(
        ModelRequest(
            provider="openai_compatible",
            model="gpt-test",
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
                        "parameters": {"type": "object"},
                    },
                },
                transport="json",
            ),
        )
    )

    assert calls["payload"]["response_format"] == {"type": "json_object"}
    assert "tools" not in calls["payload"]
    assert "tool_choice" not in calls["payload"]
    assert response.content == '{"action_type":"refuse","parameters":{}}'
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_openai_compatible_provider.py::test_openai_compatible_provider_uses_json_transport_for_structured_output_schema -q
```

Expected: FAIL because the adapter still always sends `tools` for `function_schema`.

- [ ] **Step 3: Implement transport selection**

In `proof_agent/capabilities/models/openai_compatible.py`, import `StructuredOutputTransport` and change request rendering:

```python
if request.function_schema is not None:
    payload.update(
        _structured_output_payload(
            request.function_schema,
            provider_name=self.provider_name,
            base_url=self._base_url,
        )
    )
elif request.response_format == "json":
    payload["response_format"] = {"type": "json_object"}
```

Add:

```python
def _structured_output_payload(
    function_schema: ModelFunctionSchema,
    *,
    provider_name: str,
    base_url: str | None,
) -> dict[str, Any]:
    if function_schema.transport == StructuredOutputTransport.JSON:
        return {"response_format": {"type": "json_object"}}
    return _function_tool_payload(
        function_schema,
        provider_name=provider_name,
        base_url=base_url,
    )
```

Keep existing `AUTO` behavior as tool-call transport for OpenAI-compatible providers.

- [ ] **Step 4: Run OpenAI-compatible provider tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_openai_compatible_provider.py -q
```

Expected: PASS.

### Task 3: ReAct Planner Schema Migration

**Files:**
- Modify: `proof_agent/capabilities/react/planner.py`
- Modify: `tests/test_react_planner.py`

- [ ] **Step 1: Write the failing planner structured-schema test**

Update `test_llm_react_planner_sends_fixed_function_schema_for_action_shape` in `tests/test_react_planner.py` so it imports `react_action_proposal_structured_output_schema` and asserts:

```python
expected_schema = react_action_proposal_structured_output_schema(
    frozenset({ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE})
)
assert function_schema == expected_schema
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_react_planner.py::test_llm_react_planner_sends_fixed_function_schema_for_action_shape -q
```

Expected: FAIL until Planner uses the shared schema factory.

- [ ] **Step 3: Migrate Planner to the shared schema factory**

In `proof_agent/capabilities/react/planner.py`, import `react_action_proposal_structured_output_schema`, replace `_planner_function_schema(eligible_actions)` with `react_action_proposal_structured_output_schema(eligible_actions)`, and remove the private `_planner_function_schema` and `_PLANNER_FUNCTION_SCHEMA_NAME`.

- [ ] **Step 4: Run Planner tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_react_planner.py -q
```

Expected: PASS.

### Task 4: Final Verification And Refactor

**Files:**
- Review: all files touched by Tasks 1-3

- [ ] **Step 1: Run focused regression tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_structured_output.py tests/test_openai_compatible_provider.py tests/test_react_planner.py -q
```

Expected: PASS.

- [ ] **Step 2: Run formatting/lint safety check**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
git diff --check
```

Expected: PASS.

- [ ] **Step 3: Review the public interface**

Check that callers only need to know `ModelStructuredOutputSchema`, `ModelFunctionSchema`, `StructuredOutputTransport`, `react_action_proposal_structured_output_schema`, and `final_answer_structured_output_schema`. Keep any lower-level schema assembly helpers unimported outside the helper module unless a later caller needs them.
