# React Enterprise QA Workflow Execution Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the Slice 2 Workflow Template Execution boundary for React Enterprise QA by adding typed Workflow Execution contracts, making React Enterprise QA stage handlers return `WorkflowStageResult` envelopes, adapting those results back into LangGraph scheduling state, and preserving current React Enterprise QA behavior.

**Architecture:** Treat `ReActEnterpriseQAWorkflowExecution` as the concrete Control Plane execution object for `react_enterprise_qa` and `react_enterprise_qa_v2`. Stage handlers produce governed `WorkflowStageResult` facts. LangGraph remains a Runtime Plane scheduler and receives state deltas through a thin `WorkflowStageResultRuntimeAdapter`. `WorkflowTemplateExecutionResult` contains governed execution facts only; Delivery and Observability still own trace files, Governance Receipt rendering, RunStore persistence, and Dashboard projections.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, LangGraph runtime adapter, JSONL trace, pytest, Ruff.

**Specs:** `CONTEXT.md`, `docs/adr/0027-workflow-template-stage-terminology-cutover.md`, `docs/adr/0028-agent-contract-stage-capability-and-trace-capture-contract.md`

---

## Implementation Invariants

- Preserve current `react_enterprise_qa` and `react_enterprise_qa_v2` behavior.
- Do not make Published Effective Workflow Stage Configuration Snapshot the runtime source of truth in Slice 2; only prepare an optional input/reference boundary for a later slice.
- Do not rewrite the deterministic `enterprise_qa` baseline in Slice 2.
- Do not expose LangGraph state dictionaries, Runtime Plane final state, raw prompts, raw selected context, raw evidence content, raw tool payloads, complete provider responses, raw chain-of-thought, secrets, or secret-looking values through Workflow Execution contracts.
- `WorkflowStageResult.summary` is trace-safe. `WorkflowStageResult.continuation` is internal state for runtime adapters and must not become ordinary trace, receipt, Dashboard, or API projection content.
- Stage handlers return `WorkflowStageResult` envelopes. Runtime adapters convert stage results into LangGraph state deltas.
- `ApprovalPause` and `ClarificationNeed` are separate first-class execution facts.
- Use `ReActEnterpriseQAWorkflowExecution` for the concrete class name. Reserve generic `ReActWorkflowExecution` naming for future shared abstractions.
- Keep stage-specific result union design as a TODO; Slice 2 uses the envelope first.

## Small-Step Verification Cadence

Each behavior step must follow this loop before moving on:

1. Add or update the smallest targeted test for the behavior.
2. Run only that targeted test and confirm RED when feasible.
3. Implement the smallest code change.
4. Re-run the same targeted test and confirm GREEN.
5. Run the local file-level or slice-level test set before the next task.

Do not wait until the full refactor is complete to run tests.

---

## Task 0: Baseline And Guardrails

**Files:**
- Read-only: `CONTEXT.md`
- Read-only: `proof_agent/control/workflow/react_nodes.py`
- Read-only: `proof_agent/runtime/react_graph.py`

- [x] **Step 0.1: Capture current status**

Run:

```bash
git status --short
```

Expected: see only intentional Slice 2 planning/context work before code changes.

- [x] **Step 0.2: Run current React workflow baseline**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py -q
```

Expected: pass before execution-boundary refactor, or record existing failures before changing runtime code.

---

## Task 1: Workflow Execution Contracts

**Files:**
- Add: `proof_agent/contracts/workflow_execution.py`
- Modify: `proof_agent/contracts/__init__.py`
- Test: `tests/test_workflow_execution_contracts.py`

- [x] **Step 1.1: Add contract tests**

Add tests for:

- `WorkflowStageResult` freezes `summary` and `continuation`.
- `WorkflowStageResult.summary` rejects forbidden raw/debug keys such as `raw_prompt`, `raw_context`, `raw_tool_payload`, `provider_response`, `langgraph_state`, `chain_of_thought`, and `secret`.
- `ApprovalPause` carries approval id, action id, tool name, policy decision, checkpoint ref, and trace-safe summary.
- `ClarificationNeed` carries missing fields and message separately from approval state.
- `WorkflowTemplateExecutionResult` carries outcome, final output, approval pause, clarification need, stage results, evidence, governance details, model usage summary, and trace-safe refs without artifact paths.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_execution_contracts.py -q
```

Expected RED until the contract module is implemented.

- [x] **Step 1.2: Implement workflow execution contracts**

Add:

```python
WorkflowStageStatus
WorkflowTemplateExecutionInput
ApprovalPause
ClarificationNeed
WorkflowStageResult
WorkflowTemplateExecutionResult
```

Export them from `proof_agent/contracts/__init__.py`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_execution_contracts.py -q
uv run --extra dev ruff check proof_agent/contracts tests/test_workflow_execution_contracts.py
```

Expected GREEN.

---

## Task 2: Workflow Stage Result Runtime Adapter

**Files:**
- Add: `proof_agent/runtime/workflow_stage_adapter.py`
- Test: `tests/test_workflow_stage_runtime_adapter.py`

- [x] **Step 2.1: Add adapter mapping tests**

Test that a `WorkflowStageResult` converts to LangGraph state deltas for:

- `plan` with action and reasoning continuation.
- `clarification` waiting outcome.
- `retrieval` evidence and review results.
- `tool` waiting approval state.
- accumulated `stage_results` without leaking raw summary-forbidden fields.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_stage_runtime_adapter.py -q
```

Expected RED.

- [x] **Step 2.2: Implement adapter**

Implement a thin adapter that:

- stores stage result summary facts under `stage_results`.
- maps `result.continuation` into existing LangGraph state update fields.
- does not write `summary` into `continuation`.
- preserves existing list-append semantics for `review_results`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_stage_runtime_adapter.py -q
```

Expected GREEN.

---

## Task 3: ReAct Enterprise QA Execution Skeleton

**Files:**
- Add: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/control/workflow/react_nodes.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`

- [x] **Step 3.1: Add skeleton tests for plan and clarification**

Add targeted assertions that:

- `ReActEnterpriseQAWorkflowExecution.plan()` returns `WorkflowStageResult`.
- plan result has `stage_id="plan"`, status `completed`, trace-safe summary, and continuation with action/reasoning values.
- clarification result has `stage_id="clarification"`, status `waiting`, `outcome=WAITING_FOR_USER_CLARIFICATION`, and `ClarificationNeed`-compatible continuation facts.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_execution_plan_returns_workflow_stage_result -q
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_execution_clarification_returns_workflow_stage_result -q
```

Expected RED.

- [x] **Step 3.2: Implement skeleton and wire LangGraph wrapper**

Create `ReActEnterpriseQAWorkflowExecution` and migrate `plan` plus `clarification` first. Keep `ReActWorkflowNodes` as a compatibility shim or wrapper during transition.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_underspecified_customer_claim_question_requests_clarification -q
```

Expected GREEN.

---

## Task 4: Migrate Retrieval, Review, And Model Stages

**Files:**
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/control/workflow/react_nodes.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`

- [x] **Step 4.1: Migrate retrieval review and retrieval**

Stage handlers return `WorkflowStageResult` for `retrieval_review` and `retrieval`. Continuation carries existing review/evidence state for routing.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_supported_travel_meal_question_answers_with_react_review_trace -q
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_agentic_retrieval_uses_shared_retrieval_service -q
```

Expected GREEN.

- [x] **Step 4.2: Migrate model answer**

Stage handler returns `WorkflowStageResult` for `model_answer`. Continuation carries final output/outcome for existing finalization.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_workflow_stage_context_extends_model_prompt_without_replacing_system_prompt -q
```

Expected GREEN.

---

## Task 5: Migrate Tool And Approval Stages

**Files:**
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/control/workflow/react_nodes.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`
- Test: `tests/test_run_execution_api.py`

- [x] **Step 5.1: Migrate tool review**

Stage handler returns `WorkflowStageResult` for `tool_review`. Continuation carries existing tool policy decision and review results.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_tool_question_waits_for_approval -q
```

Expected GREEN.

- [x] **Step 5.2: Migrate tool and approval pause**

Stage handler returns `WorkflowStageResult(status=waiting)` plus `ApprovalPause`-compatible continuation when approval is required. Runtime adapter creates the LangGraph interrupt payload.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_tool_question_waits_for_approval -q
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_tool_question_resumes_approved_react_tool_from_checkpoint -q
uv run --extra dev python -m pytest tests/test_run_execution_api.py::test_chat_run_approval_endpoint_resumes_waiting_tool_run -q
```

Expected GREEN.

---

## Task 6: Execution Result Aggregation

**Files:**
- Modify: `proof_agent/runtime/langgraph_runner.py`
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`
- Test: `tests/test_run_execution_api.py`

- [x] **Step 6.1: Aggregate workflow execution result**

Create `WorkflowTemplateExecutionResult` from accumulated stage results and final state facts. Keep `RunResult` unchanged as the CLI/runtime artifact result.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py -q
```

Expected GREEN.

- [x] **Step 6.2: Preserve Run Execution API behavior**

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_execution_api.py -q
```

Expected GREEN.

---

## Task 7: Final Verification

- [x] **Step 7.1: Focused backend suite**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_execution_contracts.py tests/test_workflow_stage_runtime_adapter.py tests/test_workflow_react_enterprise_qa.py tests/test_run_execution_api.py -q
```

Expected GREEN.

- [x] **Step 7.2: Lint**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
```

Expected GREEN.

- [x] **Step 7.3: Residual contract search**

Run:

```bash
rg "current_node|Runtime Plane state dict|WorkflowStageResult|WorkflowTemplateExecutionResult|ReActWorkflowNodes" proof_agent tests CONTEXT.md docs -g '*.py' -g '*.md'
```

Expected: `current_node` only remains as the known follow-up TODO, `ReActWorkflowNodes` only remains as a compatibility shim/deferred cleanup, and new execution contracts are used by Slice 2 code/tests.
