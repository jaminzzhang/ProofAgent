# LLM Role Boundaries And Harness-Normalized Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real LLM-backed ReAct planning and Harness review while preserving Proof Agent's governed execution, deterministic demo path, and fail-closed output normalization.

**Architecture:** Keep `model`, `react.planner`, and `review.subagent` as separate role-specific Agent Contract sections that share the existing Model Provider Registry. Add bounded JSON normalization for planner and reviewer outputs, add role-aware model trace payloads, and ensure every model-produced control value is validated as a Proof Agent contract before it can affect workflow, tool, review, or answer behavior.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, existing `ModelProvider` protocol, OpenAI-compatible chat completions, LangGraph runtime, JSONL trace, pytest, Ruff, mypy.

---

## Decisions Already Recorded

- Domain language updated in `CONTEXT.md`.
- ADR added: `docs/adr/0005-llm-role-boundaries-and-harness-normalized-output.md`.
- `Business Agent AI Core` covers final answer generation and ReAct planning.
- `Harness Decision Assistance` covers Harness review behavior.
- No top-level `ai_core` field is added to the Agent Contract.
- Final answer model, LLM ReAct Planner, and LLM Harness Review Subagent share the Model Provider Registry but are separate configured instances.
- Provider names describe external model channels, not Proof Agent roles.
- Planner and reviewer model outputs use the Model Output JSON Contract.
- Provider-native tool call payloads must not execute tools directly.
- Invalid planner, reviewer, or answer model output is a Model Output Normalization Failure and fails closed.
- V1 planner, reviewer, and final answer model calls are non-streaming.
- Planner and reviewer core prompts are Harness Control Prompts owned by Proof Agent.
- Planner and reviewer inputs are Structured Control Context, not raw transcript, raw evidence dump, secrets, or arbitrary prompt overrides.
- `before_answer` remains governed by deterministic evidence, citation, and output validators; Harness Decision Assistance may advise but cannot override failed validators.

## Non-Goals

- Do not introduce `ai_core` as a new Agent Contract section.
- Do not add role-specific provider names such as `llm_planner` or `llm_review`.
- Do not allow provider-native tool calls to bypass `ReActActionProposal`, `PolicyEngine`, or `ToolGateway`.
- Do not stream model output in V1.
- Do not expose raw prompts, raw model outputs, raw chain-of-thought, secrets, or raw evidence content in trace payloads.
- Do not modify `docs/zh/`.

## File Map

### Contracts And Shared Model Utilities

- Modify `proof_agent/contracts/model.py`
  - Add `ModelCallRole` enum with `final_answer`, `react_planner`, and `harness_review`.
- Modify `proof_agent/contracts/trace.py`
  - Add `MODEL_OUTPUT_NORMALIZATION_FAILED = "model_output_normalization_failed"`.
- Modify `proof_agent/contracts/__init__.py`
  - Export `ModelCallRole`.
- Create `proof_agent/capabilities/models/normalization.py`
  - Define `ModelOutputNormalizationError`.
  - Extract a single JSON object from full JSON content or fenced JSON content.
  - Validate extracted JSON through a supplied Pydantic contract type.

### Provider Layer

- Modify `proof_agent/capabilities/models/openai_compatible.py`
  - Honor `ModelRequest.response_format == "json"` by sending `response_format: {"type": "json_object"}`.
  - Keep existing text behavior unchanged.
- Modify provider tests in `tests/test_openai_compatible_provider.py`.

### Planner Role

- Modify `proof_agent/capabilities/react/planner.py`
  - Keep `DeterministicReActPlanner`.
  - Add `LLMReActPlanner`.
  - Resolve non-deterministic planner configs through `resolve_provider(ModelConfig(...))`.
  - Build a Harness Control Prompt and Structured Control Context.
  - Request `response_format="json"` and parse `ReActActionProposal`.
- Modify `proof_agent/capabilities/react/__init__.py`
  - Export `LLMReActPlanner`.
- Modify `proof_agent/runtime/react_graph.py`
  - Fail closed when planner output normalization fails.
  - Emit `model_request`, `model_response`, and `model_output_normalization_failed` events with `role: "react_planner"` for LLM-backed planning.
- Modify tests in `tests/test_react_planner.py` and `tests/test_workflow_react_enterprise_qa.py`.

### Review Role

- Modify `proof_agent/capabilities/review/subagent.py`
  - Keep `DeterministicHarnessReviewSubagent`.
  - Add `LLMHarnessReviewSubagent`.
  - Resolve non-deterministic reviewer configs through `resolve_provider(ModelConfig(...))`.
  - Build a Harness Control Prompt and Structured Control Context.
  - Request `response_format="json"` and parse `ReviewDecision`.
- Modify `proof_agent/capabilities/review/__init__.py`
  - Export `LLMHarnessReviewSubagent`.
- Modify `proof_agent/control/workflow/react_enterprise_qa.py`
  - Let `review_action` receive reviewer output normalization failures through the existing fail-closed path.
  - Emit `model_request`, `model_response`, and `model_output_normalization_failed` events with `role: "harness_review"` for LLM-backed review.
- Modify tests in `tests/test_review_subagent.py` and `tests/test_policy_engine.py`.

### Final Answer Trace Consistency

- Modify `proof_agent/control/workflow/orchestrator.py`
  - Add `role: "final_answer"` and `response_format` to final answer model trace payloads.
- Modify `proof_agent/runtime/react_graph.py`
  - Add `role: "final_answer"` and `response_format` to final answer model trace payloads.
- Modify `tests/test_trace_model_events.py`.

### Examples And Documentation

- Create `examples/react_enterprise_qa/agent.llm.yaml`
  - Demonstrate independent `model`, `react.planner`, and `review.subagent` configuration using `openai_compatible`.
- Modify `docs/technical-design.md`
  - Document LLM role boundaries and Harness-normalized output.
- Modify `docs/developer-guide.md`
  - Document provider configuration for final answer, planner, and reviewer roles.
- Modify `docs/development-progress.md`
  - Record the implementation status.

---

## Task 1: Add Model Call Role And JSON Normalizer

**Files:**
- Modify: `proof_agent/contracts/model.py`
- Modify: `proof_agent/contracts/trace.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `proof_agent/capabilities/models/normalization.py`
- Test: `tests/test_model_output_normalization.py`
- Test: `tests/test_model_contracts.py`

- [ ] **Step 1: Write failing tests for roles and normalization**

Create `tests/test_model_output_normalization.py`:

```python
from __future__ import annotations

import pytest

from proof_agent.capabilities.models.normalization import (
    ModelOutputNormalizationError,
    parse_model_contract,
)
from proof_agent.contracts import ReActActionProposal, ReActActionType


VALID_PROPOSAL_JSON = """
{
  "action_id": "act_1",
  "action_type": "plan_retrieval",
  "reasoning_summary": {
    "goal": "Find policy evidence before answering.",
    "observations": ["The question asks for a policy-backed answer."],
    "candidate_actions": ["plan_retrieval"],
    "selected_action": "plan_retrieval",
    "rationale_summary": "Evidence is required before final answer generation.",
    "risk_flags": [],
    "required_evidence": ["policy evidence"]
  },
  "parameters": {"query": "travel meal reimbursement rule"},
  "target_tool_name": null,
  "risk_level": "low"
}
"""


def test_parse_model_contract_accepts_full_json_object() -> None:
    proposal = parse_model_contract(
        content=VALID_PROPOSAL_JSON,
        contract_type=ReActActionProposal,
        role="react_planner",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meal reimbursement rule"


def test_parse_model_contract_accepts_fenced_json_object() -> None:
    proposal = parse_model_contract(
        content=f"```json\n{VALID_PROPOSAL_JSON}\n```",
        contract_type=ReActActionProposal,
        role="react_planner",
    )

    assert proposal.action_id == "act_1"


def test_parse_model_contract_rejects_natural_language() -> None:
    with pytest.raises(ModelOutputNormalizationError) as exc:
        parse_model_contract(
            content="I should retrieve policy evidence first.",
            contract_type=ReActActionProposal,
            role="react_planner",
        )

    assert exc.value.role == "react_planner"
    assert exc.value.error_code == "model_output_json_parse_failed"


def test_parse_model_contract_rejects_invalid_contract_shape() -> None:
    with pytest.raises(ModelOutputNormalizationError) as exc:
        parse_model_contract(
            content='{"action_id": "act_1", "action_type": "unknown"}',
            contract_type=ReActActionProposal,
            role="react_planner",
        )

    assert exc.value.error_code == "model_output_contract_validation_failed"
```

Add to `tests/test_model_contracts.py`:

```python
from proof_agent.contracts import ModelCallRole, TraceEventType


def test_model_call_roles_are_stable_trace_values() -> None:
    assert ModelCallRole.FINAL_ANSWER.value == "final_answer"
    assert ModelCallRole.REACT_PLANNER.value == "react_planner"
    assert ModelCallRole.HARNESS_REVIEW.value == "harness_review"


def test_trace_event_type_includes_model_output_normalization_failure() -> None:
    assert (
        TraceEventType.MODEL_OUTPUT_NORMALIZATION_FAILED.value
        == "model_output_normalization_failed"
    )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_output_normalization.py tests/test_model_contracts.py -v
```

Expected: tests fail because `ModelCallRole`, `MODEL_OUTPUT_NORMALIZATION_FAILED`, and `proof_agent.capabilities.models.normalization` do not exist.

- [ ] **Step 3: Add role and trace contracts**

In `proof_agent/contracts/model.py`, add:

```python
class ModelCallRole(str, Enum):
    FINAL_ANSWER = "final_answer"
    REACT_PLANNER = "react_planner"
    HARNESS_REVIEW = "harness_review"
```

In `proof_agent/contracts/trace.py`, add this enum member near the other model events:

```python
MODEL_OUTPUT_NORMALIZATION_FAILED = "model_output_normalization_failed"
```

In `proof_agent/contracts/__init__.py`, export `ModelCallRole` with the other model contracts:

```python
from proof_agent.contracts.model import (
    ModelCallRole,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    TokenUsage,
)
```

- [ ] **Step 4: Add bounded JSON normalization**

Create `proof_agent/capabilities/models/normalization.py`:

```python
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError


ContractT = TypeVar("ContractT", bound=BaseModel)

_FENCED_JSON_RE = re.compile(r"```(?:json)?\\s*(\\{.*?\\})\\s*```", re.DOTALL)


class ModelOutputNormalizationError(ValueError):
    def __init__(
        self,
        *,
        role: str,
        error_code: str,
        message: str,
        raw_content_length: int,
    ) -> None:
        super().__init__(message)
        self.role = role
        self.error_code = error_code
        self.raw_content_length = raw_content_length


def parse_model_contract(
    *,
    content: str,
    contract_type: type[ContractT],
    role: str,
) -> ContractT:
    raw = _extract_single_json_object(content, role=role)
    try:
        return contract_type.model_validate(raw)
    except ValidationError as exc:
        raise ModelOutputNormalizationError(
            role=role,
            error_code="model_output_contract_validation_failed",
            message=f"Model output did not match {contract_type.__name__}.",
            raw_content_length=len(content),
        ) from exc


def _extract_single_json_object(content: str, *, role: str) -> dict[str, object]:
    stripped = content.strip()
    candidates = [stripped]
    fenced = _FENCED_JSON_RE.findall(content)
    candidates.extend(fenced)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
        raise ModelOutputNormalizationError(
            role=role,
            error_code="model_output_json_not_object",
            message="Model output JSON must be a single object.",
            raw_content_length=len(content),
        )
    raise ModelOutputNormalizationError(
        role=role,
        error_code="model_output_json_parse_failed",
        message="Model output did not contain a valid JSON object.",
        raw_content_length=len(content),
    )
```

- [ ] **Step 5: Run tests and verify pass**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_output_normalization.py tests/test_model_contracts.py -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/contracts/model.py proof_agent/contracts/trace.py proof_agent/contracts/__init__.py proof_agent/capabilities/models/normalization.py tests/test_model_output_normalization.py tests/test_model_contracts.py
git commit -m "feat: add model output normalization contracts"
```

## Task 2: Honor JSON Response Format In OpenAI-Compatible Providers

**Files:**
- Modify: `proof_agent/capabilities/models/openai_compatible.py`
- Test: `tests/test_openai_compatible_provider.py`

- [ ] **Step 1: Write failing provider JSON-mode test**

Add to `tests/test_openai_compatible_provider.py`:

```python
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
```

- [ ] **Step 2: Run provider tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_openai_compatible_provider.py -v
```

Expected: the new test fails because `response_format` is not sent to the fake OpenAI client.

- [ ] **Step 3: Add JSON response format mapping**

In `proof_agent/capabilities/models/openai_compatible.py`, after the payload is initialized, add:

```python
if request.response_format == "json":
    payload["response_format"] = {"type": "json_object"}
```

Keep the existing text request payload unchanged when `request.response_format == "text"`.

- [ ] **Step 4: Run provider tests and verify pass**

Run:

```bash
uv run --extra dev python -m pytest tests/test_openai_compatible_provider.py -v
```

Expected: all selected provider tests pass.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/models/openai_compatible.py tests/test_openai_compatible_provider.py
git commit -m "feat: request json response format from openai compatible providers"
```

## Task 3: Add LLM ReAct Planner

**Files:**
- Modify: `proof_agent/capabilities/react/planner.py`
- Modify: `proof_agent/capabilities/react/__init__.py`
- Test: `tests/test_react_planner.py`

- [ ] **Step 1: Write failing planner tests**

Add to `tests/test_react_planner.py`:

```python
from proof_agent.capabilities.react import LLMReActPlanner
from proof_agent.contracts import ModelResponse, ReActPlannerConfig


class FakePlannerProvider:
    provider_name = "openai_compatible"
    model_name = "planner-test"

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    def estimate_tokens(self, request):
        return 42

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            content=self.content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


VALID_PLANNER_OUTPUT = """
{
  "action_id": "act_llm_1",
  "action_type": "plan_retrieval",
  "reasoning_summary": {
    "goal": "Find policy evidence before answering.",
    "observations": ["The request needs enterprise policy evidence."],
    "candidate_actions": ["plan_retrieval"],
    "selected_action": "plan_retrieval",
    "rationale_summary": "Retrieval is required before final answer generation.",
    "risk_flags": [],
    "required_evidence": ["policy evidence"]
  },
  "parameters": {"query": "travel meal reimbursement rule"},
  "target_tool_name": null,
  "risk_level": "low"
}
"""


def test_llm_react_planner_uses_model_provider_and_json_contract() -> None:
    provider = FakePlannerProvider(VALID_PLANNER_OUTPUT)
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(
            provider="openai_compatible",
            name="planner-test",
            params={"temperature": 0},
        ),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meal reimbursement rule"
    assert provider.requests[0].response_format == "json"
    assert provider.requests[0].stream is False


def test_resolve_react_planner_uses_llm_adapter_for_registered_model_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakePlannerProvider(VALID_PLANNER_OUTPUT)
    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.resolve_provider",
        lambda config: provider,
    )

    planner = resolve_react_planner(
        ReActPlannerConfig(provider="openai_compatible", name="planner-test")
    )

    assert isinstance(planner, LLMReActPlanner)


def test_llm_react_planner_rejects_invalid_model_output() -> None:
    provider = FakePlannerProvider("I will retrieve first.")
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    with pytest.raises(Exception) as exc:
        planner.plan(
            question="What is the reimbursement rule for travel meals?",
            system_prompt="Use governed ReAct planning.",
            context_summary="No prior context.",
        )

    assert "Model output did not contain a valid JSON object" in str(exc.value)
```

- [ ] **Step 2: Run planner tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_react_planner.py -v
```

Expected: tests fail because `LLMReActPlanner` is not defined and `resolve_react_planner` rejects non-deterministic providers.

- [ ] **Step 3: Add LLM planner implementation**

In `proof_agent/capabilities/react/planner.py`, add imports:

```python
import json
from collections.abc import Mapping
from typing import Any

from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.capabilities.models.normalization import parse_model_contract
from proof_agent.contracts import ModelMessage, ModelRequest, ModelRole
from proof_agent.contracts.manifest import ModelConfig
```

Add this class below `DeterministicReActPlanner`:

```python
class LLMReActPlanner:
    def __init__(
        self,
        *,
        config: ReActPlannerConfig,
        model_provider: ModelProvider | None = None,
    ) -> None:
        self.config = config
        self.model_provider = model_provider or resolve_provider(
            ModelConfig(
                provider=config.provider,
                name=config.name,
                params=config.params,
            )
        )

    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
    ) -> ReActActionProposal:
        request = ModelRequest(
            provider=self.model_provider.provider_name,
            model=self.model_provider.model_name,
            messages=(
                ModelMessage(role=ModelRole.SYSTEM, content=_planner_control_prompt()),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        {
                            "question": question,
                            "system_prompt_summary": system_prompt,
                            "context_summary": context_summary,
                            "allowed_actions": [action.value for action in ReActActionType],
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                ),
            ),
            response_format="json",
            stream=False,
            metadata={"role": "react_planner", "question": question},
        )
        response = self.model_provider.generate(request)
        return parse_model_contract(
            content=response.content,
            contract_type=ReActActionProposal,
            role="react_planner",
        )
```

Add the Harness Control Prompt helper:

```python
def _planner_control_prompt() -> str:
    return (
        "You are the Proof Agent LLM ReAct Planner. "
        "Return exactly one JSON object matching ReActActionProposal. "
        "Use only allowed action_type values supplied in the user message. "
        "Do not return chain-of-thought, markdown commentary, tool results, or natural language. "
        "A proposed action is not approved and cannot execute until Harness policy admits it."
    )
```

Update `resolve_react_planner`:

```python
def resolve_react_planner(config: ReActPlannerConfig) -> ReActPlanner:
    if config.provider == "deterministic":
        return DeterministicReActPlanner()
    return LLMReActPlanner(config=config)
```

- [ ] **Step 4: Export LLM planner**

In `proof_agent/capabilities/react/__init__.py`, include `LLMReActPlanner`:

```python
from proof_agent.capabilities.react.planner import (
    DeterministicReActPlanner,
    LLMReActPlanner,
    ReActPlanner,
    resolve_react_planner,
)

__all__ = [
    "DeterministicReActPlanner",
    "LLMReActPlanner",
    "ReActPlanner",
    "resolve_react_planner",
]
```

- [ ] **Step 5: Run planner tests and verify pass**

Run:

```bash
uv run --extra dev python -m pytest tests/test_react_planner.py tests/test_model_output_normalization.py -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/react/planner.py proof_agent/capabilities/react/__init__.py tests/test_react_planner.py
git commit -m "feat: add llm react planner"
```

## Task 4: Fail Closed And Trace LLM Planner In ReAct Runtime

**Files:**
- Modify: `proof_agent/runtime/react_graph.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`
- Test: `tests/test_trace_model_events.py`

- [ ] **Step 1: Write failing runtime tests**

Add to `tests/test_workflow_react_enterprise_qa.py`:

```python
def test_llm_planner_invalid_output_fails_closed_with_trace(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def invalid_plan(self: object, **kwargs: object) -> ReActActionProposal:
        from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError

        raise ModelOutputNormalizationError(
            role="react_planner",
            error_code="model_output_json_parse_failed",
            message="Model output did not contain a valid JSON object.",
            raw_content_length=31,
        )

    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.DeterministicReActPlanner.plan",
        invalid_plan,
    )

    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "planner output failed validation" in result.final_output.lower()

    events = _trace_events(result.trace_path)
    failure = next(
        event
        for event in events
        if event["event_type"] == "model_output_normalization_failed"
    )
    assert failure["payload"]["role"] == "react_planner"
    assert failure["payload"]["error_code"] == "model_output_json_parse_failed"
```

Add to `tests/test_trace_model_events.py`:

```python
def test_final_answer_model_trace_includes_role_and_response_format(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    events = _read_events(result.trace_path)
    model_request = next(event for event in events if event["event_type"] == "model_request")

    assert model_request["payload"]["role"] == "final_answer"
    assert model_request["payload"]["response_format"] == "text"
```

- [ ] **Step 2: Run runtime tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_llm_planner_invalid_output_fails_closed_with_trace tests/test_trace_model_events.py::test_final_answer_model_trace_includes_role_and_response_format -v
```

Expected: tests fail because the runtime does not catch `ModelOutputNormalizationError` and final answer trace payloads do not include `role` or `response_format`.

- [ ] **Step 3: Catch planner normalization failures**

In `proof_agent/runtime/react_graph.py`, import:

```python
from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.contracts import ModelCallRole
```

Wrap the planner call in `plan_node`:

```python
try:
    proposal = invocation.react_planner.plan(
        question=state["question"],
        system_prompt="Use governed ReAct planning without raw chain-of-thought.",
        context_summary="",
    )
except ModelOutputNormalizationError as exc:
    trace.emit(
        "model_output_normalization_failed",
        status="blocked",
        payload={
            "role": exc.role,
            "error_code": exc.error_code,
            "message": str(exc),
            "raw_content_length": exc.raw_content_length,
        },
    )
    return _refusal("The planner output failed validation and the run was stopped.")
```

- [ ] **Step 4: Add final answer role trace fields in ReAct runtime**

In `proof_agent/runtime/react_graph.py`, update final answer `model_request` payload in `model_node`:

```python
"role": ModelCallRole.FINAL_ANSWER.value,
"response_format": model_request.response_format,
```

Keep `content` and `messages` out of the payload.

- [ ] **Step 5: Add final answer role trace fields in deterministic orchestrator**

In `proof_agent/control/workflow/orchestrator.py`, import `ModelCallRole` and update the `model_request` payload:

```python
"role": ModelCallRole.FINAL_ANSWER.value,
"response_format": model_request.response_format,
```

- [ ] **Step 6: Update the existing trace payload assertion**

In `tests/test_trace_model_events.py`, update the exact key set in `test_model_trace_events_do_not_store_raw_prompts_or_outputs` to include:

```python
"role",
"response_format",
```

- [ ] **Step 7: Run focused tests and verify pass**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_trace_model_events.py -v
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/runtime/react_graph.py proof_agent/control/workflow/orchestrator.py tests/test_workflow_react_enterprise_qa.py tests/test_trace_model_events.py
git commit -m "feat: fail closed on planner normalization failures"
```

## Task 5: Add LLM Harness Review Subagent

**Files:**
- Modify: `proof_agent/capabilities/review/subagent.py`
- Modify: `proof_agent/capabilities/review/__init__.py`
- Test: `tests/test_review_subagent.py`

- [ ] **Step 1: Write failing review subagent tests**

Add to `tests/test_review_subagent.py`:

```python
from proof_agent.capabilities.review import LLMHarnessReviewSubagent
from proof_agent.contracts import ModelResponse


class FakeReviewProvider:
    provider_name = "openai_compatible"
    model_name = "reviewer-test"

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    def estimate_tokens(self, request):
        return 21

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            content=self.content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


VALID_REVIEW_OUTPUT = """
{
  "review_id": "review.act_retrieve_1.before_retrieval_plan",
  "enforcement_point": "before_retrieval_plan",
  "suggested_decision": "allow",
  "reason": "The action proposes a low-risk retrieval plan.",
  "confidence": 0.86,
  "risk_flags": [],
  "subject_action_id": "act_retrieve_1",
  "metadata": {"provider": "openai_compatible"}
}
"""


def test_llm_harness_review_subagent_uses_json_contract(
    sample_action_proposal: ReActActionProposal,
) -> None:
    provider = FakeReviewProvider(VALID_REVIEW_OUTPUT)
    reviewer = LLMHarnessReviewSubagent(
        config=ReviewSubagentConfig(
            provider="openai_compatible",
            name="reviewer-test",
            timeout_seconds=5,
            max_output_tokens=500,
            fail_closed=True,
        ),
        model_provider=provider,
    )

    decision = reviewer.review(
        enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        action=sample_action_proposal,
        context={"accepted_evidence_count": 0},
    )

    assert decision.suggested_decision == PolicyDecisionType.ALLOW
    assert provider.requests[0].response_format == "json"
    assert provider.requests[0].stream is False


def test_resolve_review_subagent_uses_llm_adapter_for_registered_model_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeReviewProvider(VALID_REVIEW_OUTPUT)
    monkeypatch.setattr(
        "proof_agent.capabilities.review.subagent.resolve_provider",
        lambda config: provider,
    )

    reviewer = resolve_review_subagent(
        ReviewSubagentConfig(provider="openai_compatible", name="reviewer-test")
    )

    assert isinstance(reviewer, LLMHarnessReviewSubagent)
```

Replace the old `test_unsupported_review_provider_raises_coherent_error` assertion with an unsupported model-provider name:

```python
def test_unsupported_review_provider_raises_coherent_error() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_review_subagent(
            ReviewSubagentConfig(provider="missing_provider", name="remote-reviewer")
        )

    assert exc.value.code == "PA_MODEL_001"
    assert "unsupported model provider" in exc.value.message
```

- [ ] **Step 2: Run review tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_review_subagent.py -v
```

Expected: tests fail because `LLMHarnessReviewSubagent` is not defined and `resolve_review_subagent` rejects all non-deterministic providers with the old message.

- [ ] **Step 3: Add LLM review subagent implementation**

In `proof_agent/capabilities/review/subagent.py`, add imports:

```python
import json

from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.capabilities.models.normalization import parse_model_contract
from proof_agent.contracts import ModelMessage, ModelRequest, ModelRole
from proof_agent.contracts.manifest import ModelConfig
```

Add this class below `DeterministicHarnessReviewSubagent`:

```python
class LLMHarnessReviewSubagent:
    def __init__(
        self,
        *,
        config: ReviewSubagentConfig,
        model_provider: ModelProvider | None = None,
    ) -> None:
        self.config = config
        self.model_provider = model_provider or resolve_provider(
            ModelConfig(
                provider=config.provider,
                name=config.name,
                params=config.params,
            )
        )

    def review(
        self,
        *,
        enforcement_point: EnforcementPoint,
        action: ReActActionProposal,
        context: Mapping[str, Any],
    ) -> ReviewDecision:
        request = ModelRequest(
            provider=self.model_provider.provider_name,
            model=self.model_provider.model_name,
            messages=(
                ModelMessage(role=ModelRole.SYSTEM, content=_review_control_prompt()),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        {
                            "enforcement_point": EnforcementPoint(enforcement_point).value,
                            "action": action.model_dump(mode="json"),
                            "context": dict(context),
                            "allowed_decisions": [
                                decision.value for decision in PolicyDecisionType
                            ],
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                ),
            ),
            max_output_tokens=self.config.max_output_tokens,
            timeout_seconds=int(self.config.timeout_seconds),
            response_format="json",
            stream=False,
            metadata={
                "role": "harness_review",
                "enforcement_point": EnforcementPoint(enforcement_point).value,
                "subject_action_id": action.action_id,
            },
        )
        response = self.model_provider.generate(request)
        return parse_model_contract(
            content=response.content,
            contract_type=ReviewDecision,
            role="harness_review",
        )
```

Add the Harness Control Prompt helper:

```python
def _review_control_prompt() -> str:
    return (
        "You are the Proof Agent LLM Harness Review Subagent. "
        "Return exactly one JSON object matching ReviewDecision. "
        "Your decision is advisory only; PolicyEngine remains the final authority. "
        "Do not generate final user answers, chain-of-thought, markdown commentary, or tool results. "
        "Use fail-closed reasoning when the action or context is unsafe or underspecified."
    )
```

Update `resolve_review_subagent`:

```python
def resolve_review_subagent(config: ReviewSubagentConfig) -> HarnessReviewSubagent:
    if config.provider == "deterministic":
        return DeterministicHarnessReviewSubagent()
    return LLMHarnessReviewSubagent(config=config)
```

- [ ] **Step 4: Export LLM review subagent**

In `proof_agent/capabilities/review/__init__.py`, include `LLMHarnessReviewSubagent`:

```python
from proof_agent.capabilities.review.subagent import (
    DeterministicHarnessReviewSubagent,
    HarnessReviewSubagent,
    LLMHarnessReviewSubagent,
    resolve_review_subagent,
)

__all__ = [
    "DeterministicHarnessReviewSubagent",
    "HarnessReviewSubagent",
    "LLMHarnessReviewSubagent",
    "resolve_review_subagent",
]
```

- [ ] **Step 5: Run review tests and verify pass**

Run:

```bash
uv run --extra dev python -m pytest tests/test_review_subagent.py tests/test_policy_engine.py -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/review/subagent.py proof_agent/capabilities/review/__init__.py tests/test_review_subagent.py
git commit -m "feat: add llm harness review subagent"
```

## Task 6: Fail Closed And Trace LLM Review

**Files:**
- Modify: `proof_agent/control/workflow/react_enterprise_qa.py`
- Test: `tests/test_policy_engine.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`

- [ ] **Step 1: Write failing fail-closed review tests**

Add to `tests/test_workflow_react_enterprise_qa.py`:

```python
def test_review_normalization_failure_fails_closed_with_trace(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def invalid_review(self: object, **kwargs: object):
        from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError

        raise ModelOutputNormalizationError(
            role="harness_review",
            error_code="model_output_json_parse_failed",
            message="Model output did not contain a valid JSON object.",
            raw_content_length=29,
        )

    monkeypatch.setattr(
        "proof_agent.capabilities.review.subagent.DeterministicHarnessReviewSubagent.review",
        invalid_review,
    )

    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"

    events = _trace_events(result.trace_path)
    failure = next(
        event
        for event in events
        if event["event_type"] == "model_output_normalization_failed"
    )
    assert failure["payload"]["role"] == "harness_review"
    assert failure["payload"]["error_code"] == "model_output_json_parse_failed"
    policy = next(
        event
        for event in events
        if event["event_type"] == "policy_decision"
        and event["payload"]["policy_rule_id"].endswith(".fail_closed")
    )
    assert policy["payload"]["decision"] in {"deny", "require_approval"}
```

- [ ] **Step 2: Run fail-closed review test and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_review_normalization_failure_fails_closed_with_trace -v
```

Expected: test fails because `review_action` emits `review_error` but does not emit `model_output_normalization_failed`.

- [ ] **Step 3: Emit review normalization failure before fail-closed policy**

In `proof_agent/control/workflow/react_enterprise_qa.py`, import:

```python
from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
```

In `review_action`, add a specific exception branch before the generic `except Exception` branch:

```python
except ModelOutputNormalizationError as exc:
    final_decision = fail_closed_policy_decision(
        point,
        context,
        trace_event_id=trace_event_id,
        error_code=exc.error_code,
    )
    review_event = {
        "used_review": False,
        "final_decision": final_decision.decision.value,
        "overridden": False,
        "error_code": exc.error_code,
        "error_class": exc.__class__.__name__,
        "subject_action_id": proposal.action_id,
    }
    trace.emit(
        "model_output_normalization_failed",
        status="blocked",
        payload={
            "role": exc.role,
            "error_code": exc.error_code,
            "message": str(exc),
            "raw_content_length": exc.raw_content_length,
            "subject_action_id": proposal.action_id,
            "enforcement_point": point.value,
        },
    )
    trace.emit("review_error", status="error", payload=review_event)
    _emit_policy(trace, final_decision)
    return final_decision, review_event
```

Keep the existing generic exception branch for provider runtime errors and unexpected exceptions.

- [ ] **Step 4: Run focused tests and verify pass**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_policy_engine.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/control/workflow/react_enterprise_qa.py tests/test_workflow_react_enterprise_qa.py
git commit -m "feat: fail closed on review normalization failures"
```

## Task 7: Add LLM Example Agent And Documentation

**Files:**
- Create: `examples/react_enterprise_qa/agent.llm.yaml`
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`

- [ ] **Step 1: Add LLM-backed example Agent Contract**

Create `examples/react_enterprise_qa/agent.llm.yaml`:

```yaml
name: react_enterprise_qa_llm
purpose: "Answer enterprise knowledge questions through a governed ReAct workflow with LLM-backed planning and review."

workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    provider: sqlite
    uri: memory

knowledge:
  provider: local_markdown
  params:
    path: ./knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2

react:
  max_steps: 5
  max_tool_calls: 1
  record_reasoning_summary: true
  planner:
    provider: openai_compatible
    name: qwen-plus
    params:
      api_key_env: OPENAI_COMPATIBLE_API_KEY
      base_url_env: OPENAI_COMPATIBLE_BASE_URL
      temperature: 0
      max_output_tokens: 800
      timeout_seconds: 20

review:
  mode: auto
  subagent:
    provider: openai_compatible
    name: qwen-plus
    timeout_seconds: 10
    max_output_tokens: 500
    fail_closed: true
    params:
      api_key_env: OPENAI_COMPATIBLE_API_KEY
      base_url_env: OPENAI_COMPATIBLE_BASE_URL
      temperature: 0

response:
  include_reasoning_summary: false
  include_review_results: false

model:
  provider: openai_compatible
  name: qwen-plus
  params:
    api_key_env: OPENAI_COMPATIBLE_API_KEY
    base_url_env: OPENAI_COMPATIBLE_BASE_URL
    temperature: 0
    max_output_tokens: 800
    timeout_seconds: 20

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
```

- [ ] **Step 2: Add documentation paragraphs**

In `docs/technical-design.md`, add a section titled `LLM Role Boundaries` with this content:

```markdown
### LLM Role Boundaries

Proof Agent integrates real LLM behavior through role-specific model calls rather than a single autonomous model loop. The final answer model, LLM ReAct Planner, and LLM Harness Review Subagent all resolve providers through the shared Model Provider Registry, but each role is configured independently in `model`, `react.planner`, or `review.subagent`.

Planner and reviewer outputs must satisfy the Model Output JSON Contract. The Harness parses model output into `ReActActionProposal` or `ReviewDecision` before any output can affect workflow routing, policy review, tool execution, or final answer behavior. Provider-native tool calls are not executable control actions in V1; future provider-native payloads must first be converted into Harness-governed action proposals.
```

In `docs/developer-guide.md`, add a section titled `Configuring LLM-Backed Planning And Review` with this content:

```markdown
### Configuring LLM-Backed Planning And Review

Use the existing provider names to configure each model role. Provider names describe the external model channel; role semantics come from the Agent Contract section.

```yaml
model:
  provider: openai_compatible
  name: qwen-plus
  params:
    api_key_env: OPENAI_COMPATIBLE_API_KEY
    base_url_env: OPENAI_COMPATIBLE_BASE_URL

react:
  planner:
    provider: openai_compatible
    name: qwen-plus
    params:
      api_key_env: OPENAI_COMPATIBLE_API_KEY
      base_url_env: OPENAI_COMPATIBLE_BASE_URL
      temperature: 0

review:
  mode: auto
  subagent:
    provider: openai_compatible
    name: qwen-plus
    fail_closed: true
    params:
      api_key_env: OPENAI_COMPATIBLE_API_KEY
      base_url_env: OPENAI_COMPATIBLE_BASE_URL
      temperature: 0
```

Planner and reviewer prompts are Harness Control Prompts maintained by Proof Agent. Agent Contracts configure provider channel, model name, and provider parameters, but do not replace the control prompts in V1.
```

In `docs/development-progress.md`, add one bullet under current status:

```markdown
- LLM-backed ReAct planning and Harness review now use the shared Model Provider Registry with role-specific configuration, bounded JSON normalization, role-aware trace events, and fail-closed behavior for invalid model output.
```

- [ ] **Step 3: Run documentation and YAML checks**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py tests/test_composition.py -v
git diff --check
```

Expected: config/composition tests pass and `git diff --check` reports no whitespace errors.

- [ ] **Step 4: Commit**

```bash
git add examples/react_enterprise_qa/agent.llm.yaml docs/technical-design.md docs/developer-guide.md docs/development-progress.md
git commit -m "docs: document llm-backed planning and review"
```

## Task 8: Full Verification

**Files:**
- No source files changed in this task.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_model_output_normalization.py \
  tests/test_openai_compatible_provider.py \
  tests/test_react_planner.py \
  tests/test_review_subagent.py \
  tests/test_workflow_react_enterprise_qa.py \
  tests/test_trace_model_events.py \
  tests/test_policy_engine.py \
  -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run static checks**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
```

Expected: Ruff and mypy pass.

- [ ] **Step 3: Run deterministic demo path**

Run:

```bash
uv run --extra dev proof-agent run examples/react_enterprise_qa/agent.yaml
```

Expected: the deterministic ReAct demo remains no-network and produces `runs/latest/trace.jsonl` plus `runs/latest/governance_receipt.md`.

- [ ] **Step 4: Inspect trace for role-aware model events**

Run:

```bash
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
```

Expected: the receipt renders successfully. Inspect `runs/latest/trace.jsonl` and confirm final answer model events include `role: "final_answer"` and no raw prompts or raw outputs.

- [ ] **Step 5: Commit verification fixes if needed**

If verification changes source files, run:

```bash
git add proof_agent tests examples docs
git commit -m "fix: stabilize llm role verification"
```

Expected: no commit is created when verification does not require source changes.

---

## Self-Review

**Spec coverage:** The plan covers shared provider registry, independent role configs, LLM planner, LLM reviewer, bounded JSON normalization, fail-closed semantics, role-aware trace events, no streaming, OpenAI-compatible JSON response format, example YAML, and English docs.

**Placeholder scan:** The plan avoids placeholder markers and gives concrete files, tests, code snippets, commands, and expected outcomes.

**Type consistency:** The plan uses existing contract names where present: `ModelRequest`, `ModelResponse`, `ReActActionProposal`, `ReviewDecision`, `PolicyDecisionType`, `EnforcementPoint`, `TraceEventType`, `ReActPlannerConfig`, and `ReviewSubagentConfig`. New names introduced by the plan are defined before use: `ModelCallRole`, `ModelOutputNormalizationError`, `parse_model_contract`, `LLMReActPlanner`, and `LLMHarnessReviewSubagent`.
