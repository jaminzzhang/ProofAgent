# Controlled ReAct Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a governed ReAct workflow for Enterprise QA where user chat input is planned, reviewed, executed, and answered inside the Proof Agent Control Envelope.

**Architecture:** Add a separate `react_enterprise_qa` Workflow Template. A ReAct Planner produces structured Reasoning Summary and ReAct Action Proposal contracts; Auto Review Mode optionally runs a Harness Review Subagent on selected control nodes; PolicyEngine validates the review result and emits the final `policy_decision`. Trace records audit-safe ReAct and review facts, while final answers still require admitted evidence and validators.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, LangGraph StateGraph, Typer CLI, FastAPI, React/Vite/TypeScript, pytest, Ruff, mypy, deterministic no-key providers plus optional model-backed providers through existing ModelProvider adapters.

---

## Decisions Already Recorded

- Domain language updated in `CONTEXT.md`.
- ADR added: `docs/adr/0004-controlled-react-workflow-and-auto-review.md`.
- `enterprise_qa` remains the deterministic regression baseline.
- V1 adds `workflow.template: react_enterprise_qa`.
- ReAct planning records `Reasoning Summary`, never raw chain-of-thought.
- ReAct actions use a fixed enum: `ASK_CLARIFICATION`, `PLAN_RETRIEVAL`, `RUN_RETRIEVAL_STEP`, `PROPOSE_TOOL_CALL`, `GENERATE_FINAL_ANSWER`, `ESCALATE`, `STOP`.
- Harness Review Subagent runs only when `review.mode: auto`.
- Harness Review Subagent outputs a `Review Decision`; PolicyEngine validates it before emitting final `PolicyDecision`.
- V1 Auto Review Scope covers `before_retrieval_plan`, `before_retrieval_step`, `before_tool_call`, and `before_model_call`.
- `before_answer` remains deterministic evidence/citation governance.
- Review failure policy fails closed.
- Clarification uses outcome `WAITING_FOR_USER_CLARIFICATION` and continues through a new governed run with Controlled Conversation Context.
- Backend response projection can expose Reasoning Summary and review results only within Agent Contract limits.
- V1 requires a no-API-key deterministic ReAct demo.

## Non-Goals

- Do not replace `enterprise_qa`.
- Do not store raw chain-of-thought in trace, receipt, API responses, or UI state.
- Do not allow arbitrary model action names.
- Do not allow the Harness Review Subagent to generate final user answers.
- Do not let API request flags exceed Agent Contract response detail policy.
- Do not implement unlimited multi-tool autonomous loops in V1.
- Do not modify `docs/zh/`.

## File Map

### Contracts

- Create `proof_agent/contracts/react_workflow.py`
  - `ReActActionType`
  - `ReasoningSummary`
  - `ReActActionProposal`
  - `ReviewDecision`
  - `GovernanceDetails`
- Modify `proof_agent/contracts/manifest.py`
  - `ReActPlannerConfig`
  - `ReActConfig`
  - `ReviewSubagentConfig`
  - `ReviewConfig`
  - `ResponseConfig`
  - add optional `react`, `review`, and `response` fields to `AgentManifest`
- Modify `proof_agent/contracts/receipt.py`
  - add `WAITING_FOR_USER_CLARIFICATION`
- Modify `proof_agent/contracts/trace.py`
  - add ReAct/review/clarification event types
- Modify `proof_agent/contracts/dashboard.py`
  - add optional `reasoning_summary`, `review_results`, `governance_details`
- Modify `proof_agent/contracts/conversation.py`
  - allow conversation turns to retain `governance_details` when returned by chat APIs
- Modify `proof_agent/contracts/__init__.py`
  - export new contracts

### Bootstrap And Composition

- Modify `proof_agent/bootstrap/manifest.py`
  - parse `react`, `review`, and `response`
- Modify `proof_agent/bootstrap/validation.py`
  - accept `react_enterprise_qa`
  - validate ReAct and review config
  - validate response detail policy
- Modify `proof_agent/control/workflow/templates.py`
  - register `react_enterprise_qa`
- Modify `proof_agent/bootstrap/composition.py`
  - add optional `react_planner` and `review_subagent` to `HarnessInvocation`

### Capabilities

- Create `proof_agent/capabilities/react/__init__.py`
- Create `proof_agent/capabilities/react/planner.py`
  - `ReActPlanner` protocol
  - `ModelBackedReActPlanner`
  - `DeterministicReActPlanner`
  - `resolve_react_planner`
- Create `proof_agent/capabilities/review/__init__.py`
- Create `proof_agent/capabilities/review/subagent.py`
  - `HarnessReviewSubagent` protocol
  - `ModelBackedHarnessReviewSubagent`
  - `DeterministicHarnessReviewSubagent`
  - `resolve_review_subagent`

### Control Plane

- Modify `proof_agent/control/policy/engine.py`
  - add `evaluate_with_review`
  - add deterministic validation of `ReviewDecision`
  - add fail-closed matrix per enforcement point
- Create `proof_agent/control/policy/review.py`
  - review validation helpers
  - decision severity helpers
  - override/error metadata builders
- Create `proof_agent/control/workflow/react_enterprise_qa.py`
  - pure control helpers for ReAct loop, review, clarification, and final state mapping

### Runtime

- Create `proof_agent/runtime/react_graph.py`
  - `ReactHarnessGraphState`
  - `build_react_enterprise_qa_graph`
- Modify `proof_agent/runtime/langgraph_runner.py`
  - route `enterprise_qa` to existing graph
  - route `react_enterprise_qa` to new graph
  - keep finalization path shared

### Observability

- Modify `proof_agent/observability/audit/receipt.py`
  - include ReAct/review/clarification summaries
- Modify `proof_agent/observability/audit/templates/governance_receipt.md.j2`
  - add optional ReAct and Auto Review sections
- Modify `proof_agent/observability/storage/run_store.py`
  - extract reasoning summaries, review results, and clarification requests
- Modify `proof_agent/observability/api/serializers.py`
  - serialize governance detail projections

### Delivery API

- Modify `proof_agent/delivery/api.py`
  - add `include_governance_details` to chat run requests
  - cap returned details by Agent Contract `response`
  - return `governance_details` only when allowed
- Modify `proof_agent/delivery/published_agents.py`
  - add `react_enterprise_qa`

### Examples And Docs

- Create `examples/react_enterprise_qa/`
  - copy Enterprise QA knowledge/tools/policy fixtures
  - add `agent.yaml` with `react_enterprise_qa`, `react`, `review`, and `response`
  - add scenario questions
- Modify `docs/technical-design.md`
- Modify `docs/developer-guide.md`
- Modify `docs/development-progress.md`
- Modify `docs/concepts/agent-contract.md`
- Modify `docs/concepts/control-envelope.md`
- Modify `docs/concepts/policy-engine.md`
- Modify `docs/concepts/trace-event-contract.md`
- Modify `docs/concepts/governance-receipt-contract.md`
- Modify `docs/concepts/trust-boundaries.md`
- Modify `AGENTS-COMMON.md` only if commands or current status need agent-facing updates after implementation

### Frontend

- Modify `chat/src/api/types.ts`
- Modify `chat/src/api/client.ts`
- Modify `chat/src/components/OutcomeBadge.tsx`
- Modify `chat/src/pages/ChatPage.tsx`
- Modify `dashboard/src/api/types.ts`
- Modify `dashboard/src/pages/RunDetailPage.tsx`
- Add or modify dashboard tab/component for ReAct and review details if the existing timeline is not sufficient

---

## Task 1: Add ReAct And Review Contracts

**Files:**
- Create: `proof_agent/contracts/react_workflow.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `proof_agent/contracts/receipt.py`
- Modify: `proof_agent/contracts/trace.py`
- Test: `tests/test_react_contracts.py`
- Test: `tests/test_trace_model_events.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_react_contracts.py`:

```python
from proof_agent.contracts import (
    ReasoningSummary,
    ReActActionProposal,
    ReActActionType,
    ReviewDecision,
    PolicyDecisionType,
    EnforcementPoint,
)


def test_react_action_proposal_is_frozen_and_structured() -> None:
    summary = ReasoningSummary(
        goal="Answer an enterprise policy question with evidence.",
        observations=("Question asks about travel meals.",),
        candidate_actions=(ReActActionType.PLAN_RETRIEVAL,),
        selected_action=ReActActionType.PLAN_RETRIEVAL,
        rationale_summary="Need accepted travel policy evidence before answer.",
        risk_flags=(),
        required_evidence=("travel meal policy",),
    )
    proposal = ReActActionProposal(
        action_id="act_1",
        action_type=ReActActionType.PLAN_RETRIEVAL,
        reasoning_summary=summary,
        parameters={"query": "travel meal reimbursement rule"},
        target_tool_name=None,
        risk_level="low",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meal reimbursement rule"


def test_review_decision_is_advisory_policy_shape() -> None:
    decision = ReviewDecision(
        review_id="rev_1",
        enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        suggested_decision=PolicyDecisionType.ALLOW,
        reason="The plan stays inside the enterprise QA scope.",
        confidence=0.8,
        risk_flags=(),
        subject_action_id="act_1",
    )

    assert decision.suggested_decision == PolicyDecisionType.ALLOW
    assert decision.subject_action_id == "act_1"
```

Add trace enum assertions to `tests/test_trace_model_events.py`:

```python
def test_trace_event_types_include_react_review_events() -> None:
    values = {event.value for event in TraceEventType}
    assert "reasoning_summary" in values
    assert "action_proposal" in values
    assert "review_requested" in values
    assert "review_decision" in values
    assert "review_error" in values
    assert "review_overridden" in values
    assert "clarification_requested" in values
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_react_contracts.py tests/test_trace_model_events.py -v
```

Expected: imports or enum assertions fail because contracts are missing.

- [ ] **Step 3: Create `proof_agent/contracts/react_workflow.py`**

Implement:

```python
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.policy import EnforcementPoint, PolicyDecisionType


class ReActActionType(str, Enum):
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    PLAN_RETRIEVAL = "PLAN_RETRIEVAL"
    RUN_RETRIEVAL_STEP = "RUN_RETRIEVAL_STEP"
    PROPOSE_TOOL_CALL = "PROPOSE_TOOL_CALL"
    GENERATE_FINAL_ANSWER = "GENERATE_FINAL_ANSWER"
    ESCALATE = "ESCALATE"
    STOP = "STOP"


class ReasoningSummary(FrozenModel):
    goal: str
    observations: tuple[str, ...] = Field(default_factory=tuple)
    candidate_actions: tuple[ReActActionType, ...] = Field(default_factory=tuple)
    selected_action: ReActActionType
    rationale_summary: str
    risk_flags: tuple[str, ...] = Field(default_factory=tuple)
    required_evidence: tuple[str, ...] = Field(default_factory=tuple)


class ReActActionProposal(FrozenModel):
    action_id: str
    action_type: ReActActionType
    reasoning_summary: ReasoningSummary
    parameters: Mapping[str, Any] = Field(default_factory=FrozenDict)
    target_tool_name: str | None = None
    risk_level: str = "low"

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(cls, value: Any) -> Any:
        return freeze_value(value)


class ReviewDecision(FrozenModel):
    review_id: str
    enforcement_point: EnforcementPoint
    suggested_decision: PolicyDecisionType
    reason: str
    confidence: float
    risk_flags: tuple[str, ...] = Field(default_factory=tuple)
    subject_action_id: str
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class GovernanceDetails(FrozenModel):
    reasoning_summary: Mapping[str, Any] | None = None
    review_results: tuple[Mapping[str, Any], ...] = Field(default_factory=tuple)

    @field_validator("reasoning_summary", "review_results", mode="after")
    @classmethod
    def freeze_values(cls, value: Any) -> Any:
        if value is None:
            return None
        return freeze_value(value)
```

- [ ] **Step 4: Export contracts and extend enums**

Update `proof_agent/contracts/__init__.py` to export `ReActActionType`, `ReasoningSummary`, `ReActActionProposal`, `ReviewDecision`, and `GovernanceDetails`.

Update `proof_agent/contracts/receipt.py`:

```python
WAITING_FOR_USER_CLARIFICATION = "WAITING_FOR_USER_CLARIFICATION"
```

Update `proof_agent/contracts/trace.py`:

```python
REASONING_SUMMARY = "reasoning_summary"
ACTION_PROPOSAL = "action_proposal"
REVIEW_REQUESTED = "review_requested"
REVIEW_DECISION = "review_decision"
REVIEW_ERROR = "review_error"
REVIEW_OVERRIDDEN = "review_overridden"
CLARIFICATION_REQUESTED = "clarification_requested"
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_react_contracts.py tests/test_trace_model_events.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/contracts tests/test_react_contracts.py tests/test_trace_model_events.py
git commit -m "Add controlled ReAct contracts"
```

---

## Task 2: Extend Agent Contract For ReAct, Review, And Response Detail

**Files:**
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `proof_agent/control/workflow/templates.py`
- Test: `tests/test_config_loader.py`
- Test: `tests/test_composition.py`

- [ ] **Step 1: Write failing config tests**

Add to `tests/test_config_loader.py`:

```python
def test_loads_react_enterprise_qa_contract() -> None:
    manifest = load_agent_manifest(Path("examples/react_enterprise_qa/agent.yaml"))

    assert manifest.workflow.template == "react_enterprise_qa"
    assert manifest.react is not None
    assert manifest.react.max_steps == 5
    assert manifest.react.max_tool_calls == 1
    assert manifest.react.planner.provider == "deterministic"
    assert manifest.review is not None
    assert manifest.review.mode == "auto"
    assert manifest.review.subagent.provider == "deterministic"
    assert manifest.response is not None
    assert manifest.response.include_reasoning_summary is False
    assert manifest.response.include_review_results is False
```

Add validation tests:

```python
def test_react_template_requires_react_config(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    # write a valid manifest with workflow.template: react_enterprise_qa and no react section
    # expected error: PA_CONFIG_002 with "react config is required"


def test_auto_review_requires_subagent_config(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    # write a valid react manifest with review.mode: auto and no review.subagent
    # expected error: PA_CONFIG_002 with "review.subagent is required"
```

When writing the YAML bodies in these tests, use `examples/enterprise_qa` files as the source for policy/tools/knowledge paths and keep audit paths under `tmp_path`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_config_loader.py tests/test_composition.py -v
```

Expected: FAIL because manifest sections and template are not implemented.

- [ ] **Step 3: Add manifest config classes**

In `proof_agent/contracts/manifest.py`, add:

```python
class ReActPlannerConfig(FrozenModel):
    provider: str
    name: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class ReActConfig(FrozenModel):
    max_steps: int
    max_tool_calls: int = 1
    record_reasoning_summary: bool = True
    planner: ReActPlannerConfig


class ReviewSubagentConfig(FrozenModel):
    provider: str
    name: str
    timeout_seconds: float = 5.0
    max_output_tokens: int = 500
    fail_closed: bool = True
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class ReviewConfig(FrozenModel):
    mode: str = "rules_only"
    subagent: ReviewSubagentConfig | None = None


class ResponseConfig(FrozenModel):
    include_reasoning_summary: bool = False
    include_review_results: bool = False
```

Add optional fields to `AgentManifest`:

```python
react: ReActConfig | None = None
review: ReviewConfig | None = None
response: ResponseConfig | None = None
```

- [ ] **Step 4: Parse new manifest sections**

In `proof_agent/bootstrap/manifest.py`, add helpers:

```python
def _react_config_from_mapping(raw: Any) -> ReActConfig | None:
    if raw is None:
        return None
    return ReActConfig(
        max_steps=raw["max_steps"],
        max_tool_calls=raw.get("max_tool_calls", 1),
        record_reasoning_summary=raw.get("record_reasoning_summary", True),
        planner=ReActPlannerConfig(
            provider=raw["planner"]["provider"],
            name=raw["planner"]["name"],
            params=raw["planner"].get("params", {}),
        ),
    )
```

Add equivalent helpers for `ReviewConfig` and `ResponseConfig`. Keep raw secrets out of `params` by validating in `bootstrap/validation.py`.

- [ ] **Step 5: Validate ReAct config**

Rules:

- `workflow.template` may be `enterprise_qa` or `react_enterprise_qa`.
- `react_enterprise_qa` requires `react`.
- `react.max_steps > 0`.
- `react.max_tool_calls` must be `0` or `1` for V1.
- `react.planner.provider` must be `deterministic` or an existing model provider name.
- `review.mode` must be `rules_only` or `auto`.
- `review.mode: auto` requires `review.subagent`.
- `review.subagent.fail_closed` must be true for V1.
- `response.include_reasoning_summary` and `response.include_review_results` default to false.

- [ ] **Step 6: Register workflow template**

Update `proof_agent/control/workflow/templates.py`:

```python
"react_enterprise_qa": WorkflowTemplate(
    name="react_enterprise_qa",
    description="Controlled ReAct enterprise question answering.",
),
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_config_loader.py tests/test_composition.py -v
```

Expected: PASS after `examples/react_enterprise_qa/agent.yaml` exists in Task 3. If this task is executed before Task 3, keep only tmp_path based tests in this task and add example-file test in Task 3.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/contracts/manifest.py proof_agent/bootstrap proof_agent/control/workflow/templates.py tests/test_config_loader.py tests/test_composition.py
git commit -m "Extend agent contract for controlled ReAct"
```

---

## Task 3: Add Deterministic React Enterprise QA Example

**Files:**
- Create: `examples/react_enterprise_qa/README.md`
- Create: `examples/react_enterprise_qa/agent.yaml`
- Create: `examples/react_enterprise_qa/questions.yaml`
- Copy: `examples/react_enterprise_qa/knowledge/`
- Copy: `examples/react_enterprise_qa/policy.yaml`
- Copy: `examples/react_enterprise_qa/tools.yaml`
- Modify: `proof_agent/delivery/published_agents.py`
- Test: `tests/test_config_loader.py`
- Test: `tests/test_run_execution_api.py`

- [ ] **Step 1: Create example Agent package**

Copy the existing `examples/enterprise_qa/knowledge`, `policy.yaml`, and `tools.yaml` content.

Create `examples/react_enterprise_qa/agent.yaml`:

```yaml
name: react_enterprise_qa
purpose: "Answer enterprise knowledge questions through a governed ReAct workflow."

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
    provider: deterministic
    name: react-planner-demo

review:
  mode: auto
  subagent:
    provider: deterministic
    name: harness-review-demo
    timeout_seconds: 5
    max_output_tokens: 500
    fail_closed: true

response:
  include_reasoning_summary: false
  include_review_results: false

model:
  provider: deterministic
  name: demo

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

Create `questions.yaml` with these entries:

```yaml
questions:
  - name: supported
    text: "What is the reimbursement rule for travel meals?"
    expected_outcome: ANSWERED_WITH_CITATIONS
  - name: unsupported
    text: "What discount should we give this customer next year?"
    expected_outcome: REFUSED_NO_EVIDENCE
  - name: clarify
    text: "Can this customer claim it?"
    expected_outcome: WAITING_FOR_USER_CLARIFICATION
  - name: tool_required
    text: "Look up customer policy status before answering."
    expected_outcome: WAITING_FOR_APPROVAL
```

- [ ] **Step 2: Add Published Agent**

Update `proof_agent/delivery/published_agents.py`:

```python
"react_enterprise_qa": Path("examples/react_enterprise_qa/agent.yaml"),
```

- [ ] **Step 3: Add API registry test**

In `tests/test_run_execution_api.py`:

```python
def test_react_enterprise_qa_is_available_as_published_agent(tmp_path: Path) -> None:
    app = create_app(history_dir=tmp_path / "history", runs_dir=tmp_path / "latest")
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_config_loader.py tests/test_run_execution_api.py -v
```

Expected: this may still fail on runtime until Task 7 routes `react_enterprise_qa`. Keep the registry test marked to expect runtime success only after Task 7, or place the runtime assertion in Task 7.

- [ ] **Step 5: Commit**

```bash
git add examples/react_enterprise_qa proof_agent/delivery/published_agents.py tests/test_config_loader.py tests/test_run_execution_api.py
git commit -m "Add deterministic ReAct enterprise QA package"
```

---

## Task 4: Implement ReAct Planner Capability

**Files:**
- Create: `proof_agent/capabilities/react/__init__.py`
- Create: `proof_agent/capabilities/react/planner.py`
- Test: `tests/test_react_planner.py`

- [ ] **Step 1: Write planner tests**

Create `tests/test_react_planner.py`:

```python
from proof_agent.capabilities.react import resolve_react_planner
from proof_agent.contracts import ReActActionType
from proof_agent.contracts.manifest import ReActPlannerConfig


def test_deterministic_planner_plans_retrieval_for_supported_question() -> None:
    planner = resolve_react_planner(
        ReActPlannerConfig(provider="deterministic", name="react-planner-demo")
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Answer using only accepted evidence.",
        context_summary="",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meals reimbursement rule"
    assert proposal.reasoning_summary.selected_action == ReActActionType.PLAN_RETRIEVAL


def test_deterministic_planner_requests_clarification_for_underspecified_question() -> None:
    planner = resolve_react_planner(
        ReActPlannerConfig(provider="deterministic", name="react-planner-demo")
    )

    proposal = planner.plan(
        question="Can this customer claim it?",
        system_prompt="Answer using only accepted evidence.",
        context_summary="",
    )

    assert proposal.action_type == ReActActionType.ASK_CLARIFICATION
    assert "missing_fields" in proposal.parameters
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_react_planner.py -v
```

Expected: FAIL because the planner capability does not exist.

- [ ] **Step 3: Implement planner protocol and deterministic planner**

Create `proof_agent/capabilities/react/planner.py`:

```python
from __future__ import annotations

from typing import Protocol

from proof_agent.contracts import (
    ReasoningSummary,
    ReActActionProposal,
    ReActActionType,
)
from proof_agent.contracts.manifest import ReActPlannerConfig
from proof_agent.errors import ProofAgentError


class ReActPlanner(Protocol):
    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
    ) -> ReActActionProposal: ...


class DeterministicReActPlanner:
    def __init__(self, name: str) -> None:
        self.name = name

    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
    ) -> ReActActionProposal:
        normalized = question.lower()
        if "can this customer" in normalized or "claim it" in normalized:
            action = ReActActionType.ASK_CLARIFICATION
            summary = ReasoningSummary(
                goal="Resolve missing customer and claim details before execution.",
                observations=("The question lacks customer, policy, or claim identifiers.",),
                candidate_actions=(action,),
                selected_action=action,
                rationale_summary="The request is underspecified for governed QA.",
                risk_flags=("missing_required_context",),
                required_evidence=("customer identifier", "claim topic"),
            )
            return ReActActionProposal(
                action_id="act_clarify_1",
                action_type=action,
                reasoning_summary=summary,
                parameters={"missing_fields": ("customer_id_or_policy_id", "claim_topic")},
                risk_level="low",
            )

        if "look up customer policy status" in normalized:
            action = ReActActionType.PROPOSE_TOOL_CALL
            summary = ReasoningSummary(
                goal="Check customer policy status through a governed tool.",
                observations=("The question explicitly asks for customer policy status lookup.",),
                candidate_actions=(action,),
                selected_action=action,
                rationale_summary="A configured tool is needed before answering.",
                risk_flags=("tool_use",),
                required_evidence=("customer policy status",),
            )
            return ReActActionProposal(
                action_id="act_tool_1",
                action_type=action,
                reasoning_summary=summary,
                parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
                target_tool_name="customer_lookup",
                risk_level="medium",
            )

        action = ReActActionType.PLAN_RETRIEVAL
        summary = ReasoningSummary(
            goal="Find accepted evidence before answering.",
            observations=("The question can be checked against enterprise knowledge.",),
            candidate_actions=(action,),
            selected_action=action,
            rationale_summary="Enterprise QA requires retrieval before answer.",
            risk_flags=(),
            required_evidence=("enterprise policy evidence",),
        )
        return ReActActionProposal(
            action_id="act_retrieval_1",
            action_type=action,
            reasoning_summary=summary,
            parameters={"query": _deterministic_query(question)},
            risk_level="low",
        )
```

Add resolver:

```python
def resolve_react_planner(config: ReActPlannerConfig) -> ReActPlanner:
    if config.provider == "deterministic":
        return DeterministicReActPlanner(config.name)
    raise ProofAgentError(
        "PA_REACT_001",
        f"unsupported ReAct planner provider: {config.provider}",
        "Use react.planner.provider: deterministic for the V1 no-key path.",
    )
```

Implement `_deterministic_query` so the supported travel meal question returns `"travel meals reimbursement rule"` and other questions return the original question.

- [ ] **Step 4: Export capability**

Create `proof_agent/capabilities/react/__init__.py`:

```python
from proof_agent.capabilities.react.planner import (
    DeterministicReActPlanner,
    ReActPlanner,
    resolve_react_planner,
)

__all__ = ["DeterministicReActPlanner", "ReActPlanner", "resolve_react_planner"]
```

- [ ] **Step 5: Run tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_react_planner.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/react tests/test_react_planner.py
git commit -m "Add deterministic ReAct planner"
```

---

## Task 5: Implement Harness Review Subagent And Policy Validation

**Files:**
- Create: `proof_agent/capabilities/review/__init__.py`
- Create: `proof_agent/capabilities/review/subagent.py`
- Create: `proof_agent/control/policy/review.py`
- Modify: `proof_agent/control/policy/engine.py`
- Test: `tests/test_review_subagent.py`
- Test: `tests/test_policy_engine.py`

- [ ] **Step 1: Write review subagent tests**

Create `tests/test_review_subagent.py`:

```python
from proof_agent.capabilities.review import resolve_review_subagent
from proof_agent.contracts import (
    EnforcementPoint,
    PolicyDecisionType,
    ReActActionType,
)
from proof_agent.contracts.manifest import ReviewSubagentConfig


def test_deterministic_review_allows_safe_retrieval_plan(sample_action_proposal) -> None:
    reviewer = resolve_review_subagent(
        ReviewSubagentConfig(
            provider="deterministic",
            name="harness-review-demo",
            fail_closed=True,
        )
    )

    decision = reviewer.review(
        enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        action=sample_action_proposal(ReActActionType.PLAN_RETRIEVAL),
        context={"accepted_evidence_count": 0},
    )

    assert decision.suggested_decision == PolicyDecisionType.ALLOW


def test_deterministic_review_requires_approval_for_medium_tool(sample_action_proposal) -> None:
    reviewer = resolve_review_subagent(
        ReviewSubagentConfig(
            provider="deterministic",
            name="harness-review-demo",
            fail_closed=True,
        )
    )

    action = sample_action_proposal(
        ReActActionType.PROPOSE_TOOL_CALL,
        target_tool_name="customer_lookup",
        risk_level="medium",
    )
    decision = reviewer.review(
        enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
        action=action,
        context={"tool_name": "customer_lookup", "risk_level": "medium"},
    )

    assert decision.suggested_decision == PolicyDecisionType.REQUIRE_APPROVAL
```

Add a pytest fixture `sample_action_proposal` in this file using `ReasoningSummary` and `ReActActionProposal`.

- [ ] **Step 2: Write PolicyEngine review validation tests**

Add to `tests/test_policy_engine.py`:

```python
def test_policy_engine_overrides_review_allow_when_rule_requires_approval(sample_review_decision) -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    review = sample_review_decision(
        EnforcementPoint.BEFORE_TOOL_CALL,
        PolicyDecisionType.ALLOW,
    )

    decision, review_event = engine.evaluate_with_review(
        EnforcementPoint.BEFORE_TOOL_CALL,
        {"tool_name": "customer_lookup", "risk_level": "medium"},
        review_decision=review,
    )

    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert review_event["overridden"] is True


def test_policy_engine_fails_closed_on_invalid_model_call_review(sample_review_decision) -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    review = sample_review_decision(
        EnforcementPoint.BEFORE_MODEL_CALL,
        PolicyDecisionType.REQUIRE_APPROVAL,
    )

    decision, review_event = engine.evaluate_with_review(
        EnforcementPoint.BEFORE_MODEL_CALL,
        {"provider": "deterministic", "model": "demo", "estimated_tokens": None},
        review_decision=review,
    )

    assert decision.decision == PolicyDecisionType.DENY
    assert review_event["error_code"] == "invalid_review_decision"
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_review_subagent.py tests/test_policy_engine.py -v
```

Expected: FAIL because review capability and `evaluate_with_review` do not exist.

- [ ] **Step 4: Implement review subagent**

Create `proof_agent/capabilities/review/subagent.py` with protocol:

```python
class HarnessReviewSubagent(Protocol):
    def review(
        self,
        *,
        enforcement_point: EnforcementPoint,
        action: ReActActionProposal,
        context: Mapping[str, Any],
    ) -> ReviewDecision: ...
```

Implement deterministic behavior:

- `BEFORE_RETRIEVAL_PLAN` and `PLAN_RETRIEVAL`: `allow`.
- `BEFORE_RETRIEVAL_STEP` and `RUN_RETRIEVAL_STEP`: `allow`.
- `BEFORE_TOOL_CALL` with `risk_level: medium`: `require_approval`.
- `BEFORE_MODEL_CALL` with accepted evidence count greater than zero: `allow`.
- Unknown action or mismatched enforcement point: `deny`.

- [ ] **Step 5: Implement PolicyEngine review validation**

Add `evaluate_with_review` returning a tuple:

```python
def evaluate_with_review(
    self,
    enforcement_point: EnforcementPoint | str,
    context: Mapping[str, Any],
    *,
    review_decision: ReviewDecision | None,
    trace_event_id: str = "",
) -> tuple[PolicyDecision, dict[str, Any]]:
```

Validation rules:

- Run deterministic `evaluate` first.
- If no review decision, return deterministic decision and `{"used_review": False}`.
- If review enforcement point differs, fail closed.
- Allowed review decisions by enforcement point:
  - `before_retrieval_plan`: `allow`, `deny`, `escalate`
  - `before_retrieval_step`: `allow`, `deny`, `escalate`
  - `before_tool_call`: `allow`, `deny`, `require_approval`, `escalate`
  - `before_model_call`: `allow`, `deny`, `escalate`
- If deterministic decision is stricter than review, keep deterministic and mark overridden.
- If review is stricter than default allow, emit final decision from review with policy rule id `auto_review.<enforcement_point>`.
- If review output is invalid, fail closed:
  - tool call: `require_approval`
  - model call: `deny`
  - retrieval plan/step: `deny` unless explicit fallback is present in context

- [ ] **Step 6: Run tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_review_subagent.py tests/test_policy_engine.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/capabilities/review proof_agent/control/policy tests/test_review_subagent.py tests/test_policy_engine.py
git commit -m "Add auto review subagent validation"
```

---

## Task 6: Compose ReAct Planner And Review Subagent

**Files:**
- Modify: `proof_agent/bootstrap/composition.py`
- Test: `tests/test_composition.py`

- [ ] **Step 1: Write composition tests**

Add:

```python
def test_composes_react_planner_and_review_subagent() -> None:
    invocation = compose_harness_invocation("examples/react_enterprise_qa/agent.yaml")

    assert invocation.template.name == "react_enterprise_qa"
    assert invocation.react_planner is not None
    assert invocation.review_subagent is not None
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_composition.py -v
```

Expected: FAIL because `HarnessInvocation` lacks these fields.

- [ ] **Step 3: Update HarnessInvocation**

Add fields:

```python
react_planner: ReActPlanner | None = None
review_subagent: HarnessReviewSubagent | None = None
```

In `compose_harness_invocation`, resolve only when config is present:

```python
react_planner = (
    resolve_react_planner(resolved_manifest.react.planner)
    if resolved_manifest.react is not None
    else None
)
review_subagent = (
    resolve_review_subagent(resolved_manifest.review.subagent)
    if resolved_manifest.review is not None and resolved_manifest.review.subagent is not None
    else None
)
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_composition.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/bootstrap/composition.py tests/test_composition.py
git commit -m "Compose ReAct planner and review subagent"
```

---

## Task 7: Build React Enterprise QA LangGraph Runtime

**Files:**
- Create: `proof_agent/control/workflow/react_enterprise_qa.py`
- Create: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/runtime/langgraph_runner.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`

- [ ] **Step 1: Write runtime acceptance tests**

Create `tests/test_workflow_react_enterprise_qa.py`:

```python
from pathlib import Path
import json

from proof_agent.runtime.langgraph_runner import run_with_langgraph


AGENT = Path("examples/react_enterprise_qa/agent.yaml")


def _events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_react_supported_question_answers_with_citations(tmp_path: Path) -> None:
    result = run_with_langgraph(
        AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert "Travel meals are reimbursed" in result.final_output
    event_types = [event["event_type"] for event in _events(result.trace_path)]
    assert "reasoning_summary" in event_types
    assert "action_proposal" in event_types
    assert "review_requested" in event_types
    assert "review_decision" in event_types
    assert "policy_decision" in event_types
    assert event_types.index("review_decision") < event_types.index("policy_decision")


def test_react_unsupported_question_refuses_without_evidence(tmp_path: Path) -> None:
    result = run_with_langgraph(
        AGENT,
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"


def test_react_underspecified_question_requests_clarification(tmp_path: Path) -> None:
    result = run_with_langgraph(
        AGENT,
        question="Can this customer claim it?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "WAITING_FOR_USER_CLARIFICATION"
    assert "provide" in result.final_output.lower()
    event_types = [event["event_type"] for event in _events(result.trace_path)]
    assert "clarification_requested" in event_types


def test_react_tool_question_waits_for_approval(tmp_path: Path) -> None:
    result = run_with_langgraph(
        AGENT,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )

    assert result.outcome == "WAITING_FOR_APPROVAL"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_workflow_react_enterprise_qa.py -v
```

Expected: FAIL because runtime graph does not exist.

- [ ] **Step 3: Implement control helpers**

Create `proof_agent/control/workflow/react_enterprise_qa.py` with pure functions:

- `emit_reasoning_summary(trace, proposal)`
- `emit_action_proposal(trace, proposal)`
- `review_action(...) -> tuple[PolicyDecision, dict[str, Any]]`
- `clarification_message(proposal) -> str`
- `should_stop_for_step_budget(step_count, max_steps) -> bool`

These helpers must not import LangGraph.

- [ ] **Step 4: Implement `build_react_enterprise_qa_graph`**

In `proof_agent/runtime/react_graph.py`, use the same dependency style as `runtime/graph.py`.

Graph outline:

```text
START
  -> plan
  -> route_after_plan
      ASK_CLARIFICATION -> clarify -> END
      PROPOSE_TOOL_CALL -> review_tool -> tool -> END
      PLAN_RETRIEVAL -> review_retrieval_plan -> retrieval -> model -> END
      ESCALATE/STOP -> END
```

State fields:

- `run_id`
- `question`
- `messages`
- `step_count`
- `tool_call_count`
- `action`
- `reasoning_summary`
- `review_results`
- `evidence`
- `governance_refusal`
- `governance_message`
- `final_output`

Execution rules:

- `plan` uses `invocation.react_planner`.
- Emit `reasoning_summary` and `action_proposal` before review.
- If action type is outside `ReActActionType`, deny.
- For retrieval plan and retrieval step, call Harness Review Subagent only when `manifest.review.mode == "auto"`.
- After review, call `PolicyEngine.evaluate_with_review`.
- Emit `review_requested`, `review_decision`, `review_error`, or `review_overridden`.
- Retrieval uses existing `_run_retrieval` and evidence validators.
- Final model call reuses `_build_model_request`, `_validate_model_output`, `_model_response_payload`, and `_emit_model_error`.
- `before_answer` remains deterministic after evidence evaluation.
- Tool path reuses ToolGateway and approval trace semantics from existing graph.

- [ ] **Step 5: Route in `run_with_langgraph`**

Modify `proof_agent/runtime/langgraph_runner.py`:

```python
if manifest.workflow.template == "react_enterprise_qa":
    builder = build_react_enterprise_qa_graph(...)
else:
    builder = build_enterprise_qa_graph(...)
```

Keep finalization shared.

- [ ] **Step 6: Run runtime tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_workflow_enterprise_qa.py -v
```

Expected: PASS. Existing `enterprise_qa` tests must remain unchanged.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/control/workflow/react_enterprise_qa.py proof_agent/runtime/react_graph.py proof_agent/runtime/langgraph_runner.py tests/test_workflow_react_enterprise_qa.py
git commit -m "Add controlled ReAct enterprise QA runtime"
```

---

## Task 8: Extend Trace, Receipt, RunStore, And Dashboard Contracts

**Files:**
- Modify: `proof_agent/observability/audit/receipt.py`
- Modify: `proof_agent/observability/audit/templates/governance_receipt.md.j2`
- Modify: `proof_agent/observability/storage/run_store.py`
- Modify: `proof_agent/observability/api/serializers.py`
- Modify: `proof_agent/contracts/dashboard.py`
- Test: `tests/test_receipt_generator.py`
- Test: `tests/test_run_store.py`
- Test: `tests/test_dashboard_contracts.py`

- [ ] **Step 1: Write observability tests**

Add receipt assertion:

```python
def test_receipt_renders_react_review_sections(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("examples/react_enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")
    assert "## ReAct Reasoning Summary" in receipt
    assert "## Auto Review" in receipt
    assert "raw chain-of-thought" not in receipt.lower()
```

Add RunStore assertion:

```python
def test_run_store_extracts_governance_details_for_react_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    result = run_with_langgraph(
        Path("examples/react_enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "latest",
        run_id="run_react_test",
        store=store,
    )

    detail = store.get_run_detail("run_react_test")
    assert detail is not None
    assert detail.governance_details["reasoning_summary"]
    assert detail.governance_details["review_results"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_receipt_generator.py tests/test_run_store.py tests/test_dashboard_contracts.py -v
```

Expected: FAIL because extracted details and receipt sections are missing.

- [ ] **Step 3: Add RunDetail fields**

In `proof_agent/contracts/dashboard.py`:

```python
governance_details: dict[str, Any] = Field(default_factory=dict)
```

Keep it optional and default-empty for existing runs.

- [ ] **Step 4: Extract governance details in RunStore**

Add methods:

- `_extract_reasoning_summary(events)`
- `_extract_review_results(events)`
- `_extract_clarification_request(events)`
- `_extract_governance_details(events)`

Return only audit-safe payloads from existing trace events.

- [ ] **Step 5: Render receipt sections**

In `receipt.py`, collect:

- `reasoning_summary_events`
- `action_proposal_events`
- `review_events`
- `clarification_events`

In the template, render:

```markdown
## ReAct Reasoning Summary

## Auto Review

## Clarification
```

Only render sections when relevant events exist.

- [ ] **Step 6: Serialize details**

Add `governance_details` to `serialize_run_detail`.

- [ ] **Step 7: Run tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_receipt_generator.py tests/test_run_store.py tests/test_dashboard_contracts.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/contracts/dashboard.py proof_agent/observability tests/test_receipt_generator.py tests/test_run_store.py tests/test_dashboard_contracts.py
git commit -m "Expose ReAct governance details in observability"
```

---

## Task 9: Add Response Detail Policy To Chat API

**Files:**
- Modify: `proof_agent/delivery/api.py`
- Modify: `proof_agent/contracts/conversation.py`
- Test: `tests/test_run_execution_api.py`
- Test: `tests/test_conversation_api.py`

- [ ] **Step 1: Write API projection tests**

Add:

```python
def test_chat_run_omits_governance_details_by_default(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={"react_enterprise_qa": Path("examples/react_enterprise_qa/agent.yaml")},
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    assert "governance_details" not in response.json()


def test_chat_run_returns_governance_details_when_agent_policy_allows(tmp_path: Path) -> None:
    # copy examples/react_enterprise_qa to tmp_path and set:
    # response.include_reasoning_summary: true
    # response.include_review_results: true
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={"react_enterprise_qa": manifest_path},
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
            "include_governance_details": True,
        },
    )

    assert response.status_code == 200
    details = response.json()["governance_details"]
    assert details["reasoning_summary"]
    assert details["review_results"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_run_execution_api.py tests/test_conversation_api.py -v
```

Expected: FAIL because request fields and response projection are missing.

- [ ] **Step 3: Add request fields**

Update `ChatRunRequest` and `ConversationRunRequest`:

```python
include_governance_details: bool = False
```

- [ ] **Step 4: Cap projection by Agent Contract**

Pass `manifest` or response policy into `_run_response`. Projection logic:

```python
def _governance_projection(detail: Any, manifest: AgentManifest, requested: bool) -> dict[str, Any] | None:
    if not requested or manifest.response is None:
        return None
    allowed: dict[str, Any] = {}
    details = detail.governance_details or {}
    if manifest.response.include_reasoning_summary:
        allowed["reasoning_summary"] = details.get("reasoning_summary")
    if manifest.response.include_review_results:
        allowed["review_results"] = details.get("review_results", [])
    return allowed or None
```

- [ ] **Step 5: Persist conversation turn details**

Add optional `governance_details` to `ConversationTurn` and `conversation_record_payload` so a conversation timeline can retain details when response policy allows it.

- [ ] **Step 6: Run tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_run_execution_api.py tests/test_conversation_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/delivery/api.py proof_agent/contracts/conversation.py tests/test_run_execution_api.py tests/test_conversation_api.py
git commit -m "Add governed response detail projection"
```

---

## Task 10: Update Chat And Dashboard UI Types

**Files:**
- Modify: `chat/src/api/types.ts`
- Modify: `chat/src/api/client.ts`
- Modify: `chat/src/components/OutcomeBadge.tsx`
- Modify: `chat/src/pages/ChatPage.tsx`
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/pages/RunDetailPage.tsx`
- Optional Modify: `dashboard/src/pages/tabs/TimelineTab.tsx`

- [ ] **Step 1: Update TypeScript outcome and detail types**

Add outcome:

```ts
| 'WAITING_FOR_USER_CLARIFICATION'
```

Add governance details:

```ts
export interface GovernanceDetails {
  reasoning_summary?: Record<string, unknown> | null
  review_results?: Record<string, unknown>[]
}
```

Add `governance_details?: GovernanceDetails` to `ChatRunResponse`, `ConversationTurn`, and `RunDetail`.

- [ ] **Step 2: Add API request flag**

Update `createConversationRun`:

```ts
export function createConversationRun(
  conversationId: string,
  question: string,
  approved?: boolean,
  includeGovernanceDetails = false
): Promise<ChatRunResponse> {
  return fetchJson<ChatRunResponse>(`${BASE}/chat/conversations/${conversationId}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      approved,
      include_governance_details: includeGovernanceDetails,
    })
  })
}
```

- [ ] **Step 3: Update outcome badge**

Add style:

```ts
WAITING_FOR_USER_CLARIFICATION: {
  border: 'border-[var(--border)]',
  bg: 'bg-[var(--bg-surface)]',
  text: 'text-[var(--text-primary)]',
  label: 'Clarify',
  dot: 'bg-[var(--neutral-badge)]'
}
```

- [ ] **Step 4: Add Chat UI governance detail toggle**

In `ChatPage.tsx`, add state:

```ts
const [includeGovernanceDetails, setIncludeGovernanceDetails] = useState(false)
```

Add a checkbox near the input:

```tsx
<label className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
  <input
    type="checkbox"
    checked={includeGovernanceDetails}
    onChange={(e) => setIncludeGovernanceDetails(e.target.checked)}
  />
  Show governance details
</label>
```

Pass the flag to `createConversationRun`.

Render details only when present:

```tsx
{turn.governance_details && (
  <details className="pt-3 border-t border-[var(--border)]">
    <summary className="text-[11px] font-bold uppercase text-[var(--accent)] cursor-pointer">
      Governance Details
    </summary>
    <pre className="mt-2 text-[11px] overflow-auto bg-[var(--bg-surface)] p-3 rounded-md">
      {JSON.stringify(turn.governance_details, null, 2)}
    </pre>
  </details>
)}
```

- [ ] **Step 5: Update Dashboard run detail**

Dashboard can show `governance_details` in the existing Timeline tab or a new section in `RunDetailPage`. Use existing components and avoid raw chain-of-thought language.

- [ ] **Step 6: Run frontend validation**

Run:

```bash
cd chat && npm run build
cd dashboard && npm run build
```

Expected: both builds pass.

- [ ] **Step 7: Commit**

```bash
git add chat/src dashboard/src
git commit -m "Show governed ReAct details in UI"
```

---

## Task 11: CLI Demo And Deterministic Scenarios

**Files:**
- Modify: `proof_agent/delivery/cli.py`
- Modify: `proof_agent/evaluation/demo/scenarios.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_cli_demo.py` if present in branch history; otherwise create `tests/test_cli_react_demo.py`

- [ ] **Step 1: Add CLI scenario tests**

Create or extend CLI tests:

```python
def test_react_demo_command_runs_no_key_scenarios(cli_runner) -> None:
    result = cli_runner.invoke(app, ["react-demo"])

    assert result.exit_code == 0
    assert "supported: ANSWERED_WITH_CITATIONS" in result.output
    assert "clarify: WAITING_FOR_USER_CLARIFICATION" in result.output
    assert "tool_required: WAITING_FOR_APPROVAL" in result.output
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_cli.py -v
```

Expected: FAIL because command is missing.

- [ ] **Step 3: Implement `react-demo` command**

Add a Typer command:

```python
@app.command("react-demo")
def react_demo() -> None:
    """Run deterministic Controlled ReAct Enterprise QA scenarios."""
    scenarios = (
        ("supported", "What is the reimbursement rule for travel meals?"),
        ("unsupported", "What discount should we give this customer next year?"),
        ("clarify", "Can this customer claim it?"),
        ("tool_required", "Look up customer policy status before answering."),
    )
    store = RunStore(Path("runs/history"))
    for name, question in scenarios:
        result = run_with_langgraph(
            Path("examples/react_enterprise_qa/agent.yaml"),
            question=question,
            runs_dir=Path("runs/latest"),
            store=store,
        )
        typer.echo(f"{name}: {result.outcome.value}")
```

- [ ] **Step 4: Run CLI tests and smoke command**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_cli.py -v
uv run --extra dev --extra dashboard proof-agent react-demo
```

Expected: tests pass and command prints deterministic outcomes.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/delivery/cli.py proof_agent/evaluation/demo tests/test_cli.py
git commit -m "Add deterministic ReAct demo command"
```

---

## Task 12: Documentation Update

**Files:**
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`
- Modify: `docs/concepts/agent-contract.md`
- Modify: `docs/concepts/control-envelope.md`
- Modify: `docs/concepts/policy-engine.md`
- Modify: `docs/concepts/trace-event-contract.md`
- Modify: `docs/concepts/governance-receipt-contract.md`
- Modify: `docs/concepts/trust-boundaries.md`
- Modify: `docs/examples/enterprise-qa.md`
- Create: `docs/examples/react-enterprise-qa.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Update source-of-truth docs**

Document:

- `react_enterprise_qa` template
- `react`, `review`, and `response` Agent Contract sections
- fixed ReAct Action Set
- Auto Review Scope
- Harness Review Subagent advisory boundary
- Review Failure Policy
- `WAITING_FOR_USER_CLARIFICATION`
- ReAct trace events
- no raw chain-of-thought storage
- deterministic ReAct demo command

- [ ] **Step 2: Add example doc**

Create `docs/examples/react-enterprise-qa.md` with:

- purpose
- Quick Start command
- expected outcomes
- trace/receipt behavior
- governance detail response toggle behavior

- [ ] **Step 3: Run doc checks**

Run:

```bash
git diff --check
rg -n "raw chain-of-thought" docs proof_agent tests
rg -n "react_enterprise_qa" docs examples proof_agent tests
```

Expected:

- `git diff --check` passes.
- `raw chain-of-thought` appears only in warnings/rules that say it must not be recorded.
- `react_enterprise_qa` appears in docs, example, code, and tests.

- [ ] **Step 4: Commit**

```bash
git add docs examples
git commit -m "Document controlled ReAct workflow"
```

---

## Task 13: Full Verification

**Files:**
- No source edits unless verification finds a bug.

- [ ] **Step 1: Run Python tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
```

Expected: no Ruff errors.

- [ ] **Step 3: Run type check**

Run:

```bash
uv run --extra dev mypy proof_agent
```

Expected: no mypy errors.

- [ ] **Step 4: Run deterministic demos**

Run:

```bash
uv run --extra dev --extra dashboard proof-agent demo
uv run --extra dev --extra dashboard proof-agent react-demo
uv run --extra dev --extra dashboard proof-agent run examples/enterprise_qa/agent.yaml
uv run --extra dev --extra dashboard proof-agent run examples/react_enterprise_qa/agent.yaml --question "What is the reimbursement rule for travel meals?"
```

Expected:

- existing demo still reports `ANSWERED_WITH_CITATIONS`, `REFUSED_NO_EVIDENCE`, `WAITING_FOR_APPROVAL`
- ReAct demo reports supported, unsupported, clarify, and tool-required outcomes
- both run commands produce trace and receipt artifacts

- [ ] **Step 5: Run frontend builds**

Run:

```bash
cd chat && npm run build
cd dashboard && npm run build
```

Expected: both builds pass.

- [ ] **Step 6: Final commit if fixes were needed**

```bash
git add .
git commit -m "Verify controlled ReAct workflow"
```

Only run this commit step if verification required fixes after the prior task commits.

---

## Implementation Notes

- Keep `enterprise_qa` tests passing throughout.
- Do not add raw prompt or raw model response bodies to trace payloads.
- Do not add raw reasoning to receipt, RunStore, Dashboard API, or Chat API.
- Use `TraceWriter.emit` for all new trace events so redaction rules remain centralized.
- Keep SDK-specific model behavior inside capabilities; contracts and policy must stay provider-neutral.
- Treat deterministic ReAct planner/reviewer as the required V1 acceptance path, not as a test-only shortcut.
- The first ReAct implementation should prefer clear rule enforcement over clever planner behavior.

## Self-Review

- Spec coverage: The plan covers ReAct planning, Harness Review Subagent, Auto Review Mode, fixed action enum, clarification outcome, response projection, deterministic demo, docs, API, and UI.
- Placeholder scan: No unfinished marker text or open-ended implementation placeholders are intentionally left in tasks.
- Type consistency: The plan uses `ReasoningSummary`, `ReActActionProposal`, `ReviewDecision`, `GovernanceDetails`, `ResponseConfig`, `ReActConfig`, and `ReviewConfig` consistently across contracts, runtime, API, and UI tasks.
