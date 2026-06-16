# React Stage Behavior Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate React Enterprise QA Workflow internals so `ReActEnterpriseQAWorkflowExecution` is the only public stage execution surface, while reusable stage work lives in `ReActEnterpriseQAStageBehavior` and LangGraph remains only a Runtime Adapter.

**Architecture:** Keep three clear layers.

- `ReActEnterpriseQAWorkflowExecution` owns governed Workflow Stage execution methods and `WorkflowStageResult` envelope construction.
- `ReActEnterpriseQAStageBehavior` owns template-specific work such as planner calls, retrieval, review, model calls, stage context application, Tool Gateway calls, and approval decision handling. It returns scheduler-neutral state deltas.
- `Workflow Runtime Adapter` and `runtime/react_graph.py` own concrete LangGraph scheduling, branch routing, checkpoint, interrupt, and resume mechanics.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, LangGraph runtime adapter, JSONL trace, pytest, Ruff, mypy.

**Specs:** `CONTEXT.md`, `docs/adr/0027-workflow-template-stage-terminology-cutover.md`, `docs/adr/0028-agent-contract-stage-capability-and-trace-capture-contract.md`, `docs/adr/0026-approval-checkpoint-resume.md`, `docs/adr/0025-react-enterprise-qa-v2-intent-resolution.md`.

---

## Non-Goals

- Do not introduce complete stage-specific result union contracts.
- Do not derive dynamic Runtime Adapter topology from the Workflow Template Descriptor.
- Do not rename every LangGraph runtime graph node.
- Do not build a historical executable descriptor registry.
- Do not add a second runtime implementation.
- Do not change the deterministic `enterprise_qa` baseline.
- Do not rename or remove old `WorkflowState.current_node`.
- Do not change the `validation_capture.v2` schema.

---

## Implementation Invariants

- Preserve current `react_enterprise_qa` and `react_enterprise_qa_v2` behavior.
- `ReActEnterpriseQAWorkflowExecution` is the only object whose public methods represent governed Workflow Template Stage execution.
- `ReActEnterpriseQAStageBehavior` must not return `WorkflowStageResult` and must not expose a parallel Workflow Template Stage API.
- `WorkflowStageResult.summary` remains trace-safe.
- `WorkflowStageResult.continuation` remains internal adapter input and must not leak into ordinary trace, receipt, Dashboard, API, or validation capture projections.
- `ApprovalPause` is a governed Workflow Template Execution fact.
- LangGraph `interrupt(...)` payloads are Runtime Adapter mechanics derived from continuation state, not approval authority.
- The final code state removes the `ReActWorkflowNodes` class and avoids keeping `react_nodes.py` as a long-term compatibility module.
- Runtime graph node names may remain as runtime implementation details when they describe actual LangGraph mechanics.

---

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
- Read-only: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Read-only: `proof_agent/control/workflow/react_nodes.py`
- Read-only: `proof_agent/runtime/react_graph.py`
- Read-only: `tests/test_workflow_react_enterprise_qa.py`
- Read-only: `tests/test_run_execution_api.py`
- Read-only: `tests/test_workflow_stage_runtime_adapter.py`
- Read-only: `tests/test_workflow_execution_contracts.py`

- [x] **Step 0.1: Capture status**

Run:

```bash
git status --short
```

Expected: only intentional planning/context files are modified before implementation starts.

- [x] **Step 0.2: Run focused workflow baseline**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_workflow_stage_runtime_adapter.py tests/test_workflow_execution_contracts.py tests/test_run_execution_api.py -q
```

Expected: GREEN before refactoring. If there are existing failures, record them before changing code.

- [x] **Step 0.3: Capture current residual naming**

Run:

```bash
rg "ReActWorkflowNodes|react_nodes|current_node|WorkflowStageResult|approval_interrupt" proof_agent tests CONTEXT.md docs -g '*.py' -g '*.md'
```

Expected: `ReActWorkflowNodes` and `react_nodes` appear only in the known implementation targets; `current_node` remains the known out-of-scope TODO.

---

## Task 1: Lock Current Stage Behavior

**Files:**
- Modify: `tests/test_workflow_react_enterprise_qa.py`
- Modify if needed: `tests/test_workflow_stage_runtime_adapter.py`
- Modify if needed: `tests/test_workflow_execution_contracts.py`

- [x] **Step 1.1: Lock direct WorkflowStageResult behavior**

Ensure direct execution tests cover:

- `plan` returns `WorkflowStageResult(stage_id="plan", status=completed)`.
- `clarification` returns `WorkflowStageResult(status=waiting)` plus `clarification_need` continuation.
- stage summaries contain ids, counts, enums, and lengths only.
- continuation remains internal state and is not copied into the serialized `stage_results` projection.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_execution_plan_returns_workflow_stage_result tests/test_workflow_react_enterprise_qa.py::test_react_execution_clarification_returns_workflow_stage_result tests/test_workflow_stage_runtime_adapter.py -q
```

Expected: GREEN before and after the refactor.

- [x] **Step 1.2: Lock tool approval waiting behavior**

Ensure tests prove:

- tool questions stop with `WAITING_FOR_APPROVAL`.
- `approval_requested` and `pending_approval_created` trace events are emitted once.
- `PendingApproval` payload includes run id, thread id, action id, tool name, redacted-safe parameters, policy decision, and checkpoint id.
- `WorkflowStageResult` for `tool` has `status=waiting`, `outcome=WAITING_FOR_APPROVAL`, and `produced_fact_refs=("approval_pause",)`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_tool_question_waits_for_approval tests/test_workflow_stage_runtime_adapter.py::test_adapter_maps_approval_pause_without_leaking_continuation -q
```

Expected: GREEN before and after the refactor.

- [x] **Step 1.3: Lock approval resume behavior**

Ensure tests prove:

- approved resume continues the original checkpoint.
- `approval_granted` is emitted once.
- `pending_approval_created` is not duplicated.
- final answer remains the approved tool result path.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_tool_question_resumes_approved_react_tool_from_checkpoint tests/test_run_execution_api.py::test_chat_run_approval_endpoint_resumes_waiting_tool_run -q
```

Expected: GREEN before and after the refactor.

- [x] **Step 1.4: Lock stage context and validation capture handoff behavior**

Ensure tests prove:

- configured Workflow Stage Context still reaches planner/model/tool-related stage paths as before.
- `WorkflowTemplateExecutionResult.stage_context_applications` remains populated.
- `validation_capture.v2` still records projections from execution input and execution result without schema changes.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_workflow_stage_context_extends_model_prompt_without_replacing_system_prompt tests/test_agent_configuration_api.py::test_validation_run_full_capture_records_gated_v2_artifact -q
```

Expected: GREEN before and after the refactor. If the exact validation capture test name changes, use the nearest full-capture v2 API regression in `tests/test_agent_configuration_api.py`.

---

## Task 2: Add ReAct Enterprise QA Stage Behavior

**Files:**
- Add: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Temporarily retain: `proof_agent/control/workflow/react_nodes.py`

- [x] **Step 2.1: Introduce Stage Behavior class**

Create `ReActEnterpriseQAStageBehavior` with the same constructor dependencies currently used by `ReActWorkflowNodes`:

- `HarnessInvocation`
- `TraceWriter`
- `WorkflowTemplateExecutionInput`
- optional `ContextAdmission`
- `allow_untrusted_web_supplement`

Move or copy non-public helpers needed by the behavior into the new module. Do not change behavior yet.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_execution_plan_returns_workflow_stage_result -q
uv run --extra dev ruff check proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py proof_agent/control/workflow/react_enterprise_qa_execution.py
```

Expected: GREEN.

- [x] **Step 2.2: Make Workflow Execution use Stage Behavior**

Change `ReActEnterpriseQAWorkflowExecution` to construct `ReActEnterpriseQAStageBehavior` instead of `ReActWorkflowNodes`. Keep public execution method names unchanged.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_execution_plan_returns_workflow_stage_result tests/test_workflow_react_enterprise_qa.py::test_react_execution_clarification_returns_workflow_stage_result -q
```

Expected: GREEN.

---

## Task 3: Migrate Non-Tool Stage Behavior

**Files:**
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Modify if needed: `tests/test_workflow_react_enterprise_qa.py`

- [x] **Step 3.1: Migrate intent, plan, and clarification behavior**

Move the behavior for:

- `intent_resolution`
- `plan`
- `clarify`

`ReActEnterpriseQAWorkflowExecution` should call behavior methods and wrap returned deltas into `WorkflowStageResult`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_v2_resolves_intent_before_react_planning tests/test_workflow_react_enterprise_qa.py::test_react_execution_plan_returns_workflow_stage_result tests/test_workflow_react_enterprise_qa.py::test_react_execution_clarification_returns_workflow_stage_result -q
```

Expected: GREEN.

- [x] **Step 3.2: Migrate retrieval and model behavior**

Move the behavior for:

- `review_retrieval_plan`
- `retrieval`
- `model`

Preserve trace event ordering and policy decisions.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_supported_travel_meal_question_answers_with_react_review_trace tests/test_workflow_react_enterprise_qa.py::test_react_agentic_retrieval_uses_shared_retrieval_service -q
```

Expected: GREEN.

- [x] **Step 3.3: Migrate tool review behavior**

Move `review_tool` behavior and keep tool capability availability checks before policy review.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_disabled_tools_block_react_tool_action_before_review tests/test_workflow_react_enterprise_qa.py::test_tool_question_waits_for_approval -q
```

Expected: GREEN.

---

## Task 4: Consolidate Tool And Approval Behavior

**Files:**
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Modify: `tests/test_workflow_react_enterprise_qa.py`
- Modify: `tests/test_run_execution_api.py`

- [x] **Step 4.1: Define internal tool approval delta**

Use an internal delta shape, not a public contract, for the no-decision approval path. It should carry enough data for `ReActEnterpriseQAWorkflowExecution` to construct:

- `ApprovalPause`
- `approval_interrupt`
- waiting `WorkflowStageResult`

Recommended internal keys:

- `tool_approval_state`
- `tool_approval_parameters`
- `tool_approval_policy_decision`
- `tool_approval_checkpoint_ref`

Do not expose these keys through ordinary `stage_results` summary or validation capture projection.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_tool_question_waits_for_approval tests/test_workflow_stage_runtime_adapter.py::test_adapter_maps_approval_pause_without_leaking_continuation -q
```

Expected: GREEN.

- [x] **Step 4.2: Move Tool Gateway calls into Stage Behavior**

`ReActEnterpriseQAStageBehavior.tool(...)` owns:

- Tool Gateway request
- approval decision handling
- `approval_denied` trace event
- `approval_granted` trace event
- `tool_result` trace event
- final output disclosure for untrusted web supplement

`ReActEnterpriseQAWorkflowExecution.tool(...)` owns:

- converting approval-request delta into `ApprovalPause`
- converting approval-request delta into `approval_interrupt` continuation
- producing waiting, blocked, or completed `WorkflowStageResult`

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_tool_question_waits_for_approval tests/test_workflow_react_enterprise_qa.py::test_tool_question_resumes_approved_react_tool_from_checkpoint tests/test_run_execution_api.py::test_chat_run_approval_endpoint_resumes_waiting_tool_run -q
```

Expected: GREEN.

- [x] **Step 4.3: Verify denied and duplicate approval paths**

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_execution_api.py::test_chat_run_approval_endpoint_rejects_duplicate_resume tests/test_run_execution_api.py::test_chat_run_approval_endpoint_rejects_concurrent_resume_claim tests/test_run_execution_api.py::test_chat_run_approval_endpoint_resumes_after_app_restart -q
```

Expected: GREEN.

---

## Task 5: Move Runtime And Trace Helpers To Their Owners

**Files:**
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Temporarily retain: `proof_agent/control/workflow/react_nodes.py`

- [x] **Step 5.1: Localize routing proposal parsing**

Move `proposal_from_state` usage in `runtime/react_graph.py` to a private runtime helper such as `_proposal_from_state`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_supported_travel_meal_question_answers_with_react_review_trace -q
uv run --extra dev ruff check proof_agent/runtime/react_graph.py
```

Expected: GREEN, and `runtime/react_graph.py` no longer imports `proposal_from_state` from a Control Plane behavior module.

- [x] **Step 5.2: Move model-provider trace wrapping out of runtime graph**

Move `wrap_control_plane_model_providers(...)` into `ReActEnterpriseQAWorkflowExecution` or `ReActEnterpriseQAStageBehavior` initialization. Runtime graph should construct the execution object and should not prepare Control Plane model providers directly.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_supported_travel_meal_question_answers_with_react_review_trace tests/test_workflow_react_enterprise_qa.py::test_v2_resolves_intent_before_react_planning -q
```

Expected: GREEN, with the same `model_request` and `model_response` trace events as before.

---

## Task 6: Delete Old Node Naming

**Files:**
- Delete or empty through real replacement: `proof_agent/control/workflow/react_nodes.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Modify: `proof_agent/runtime/react_graph.py`
- Modify docs only if they describe current code rather than historical planning

- [x] **Step 6.1: Remove `ReActWorkflowNodes`**

Remove the `ReActWorkflowNodes` class and all imports of it.

Run:

```bash
rg "ReActWorkflowNodes" proof_agent tests -g '*.py'
```

Expected: no output.

- [x] **Step 6.2: Remove `react_nodes.py` imports**

Remove remaining production imports from `proof_agent.control.workflow.react_nodes`.

Run:

```bash
rg "react_nodes" proof_agent tests -g '*.py'
```

Expected: no output. Historical docs may still mention `react_nodes.py` only when describing completed past plans or old deferrals.

- [x] **Step 6.3: Run focused workflow suite**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_workflow_stage_runtime_adapter.py tests/test_workflow_execution_contracts.py tests/test_run_execution_api.py -q
```

Expected: GREEN.

---

## Task 7: Validation Capture And API Regression

**Files:**
- Read-only unless failures point to refactor leakage: `proof_agent/delivery/configuration_api.py`
- Read-only unless failures point to refactor leakage: `proof_agent/contracts/validation_capture.py`
- Test: `tests/test_agent_configuration_api.py`
- Test: `tests/test_validation_capture_contracts.py`

- [x] **Step 7.1: Verify full capture v2 still uses projections**

Run:

```bash
uv run --extra dev python -m pytest tests/test_validation_capture_contracts.py tests/test_agent_configuration_api.py::test_validation_run_defaults_to_summary_only_trace_capture tests/test_agent_configuration_api.py::test_validation_run_full_capture_records_gated_v2_artifact -q
```

Expected: GREEN. The refactor must not add raw prompt, raw context, raw evidence, raw tool payload, provider response, or continuation state to `validation_capture.v2`.

- [x] **Step 7.2: Verify Run Execution API approval surface**

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_execution_api.py::test_chat_run_execution_returns_approval_state_for_tool_question tests/test_run_execution_api.py::test_chat_run_approval_endpoint_resumes_waiting_tool_run -q
```

Expected: GREEN.

---

## Task 8: Final Verification

- [x] **Step 8.1: Focused backend suite**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_workflow_stage_runtime_adapter.py tests/test_workflow_execution_contracts.py tests/test_run_execution_api.py tests/test_validation_capture_contracts.py -q
```

Expected: GREEN.

- [x] **Step 8.2: Broader regression suite**

Run:

```bash
uv run --extra dev python -m pytest
```

Expected: GREEN.

- [x] **Step 8.3: Lint**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
```

Expected: GREEN.

- [x] **Step 8.4: Type check**

Run:

```bash
uv run --extra dev mypy proof_agent
```

Expected: GREEN.

- [x] **Step 8.5: Residual terminology search**

Run:

```bash
rg "ReActWorkflowNodes|react_nodes|Runtime Plane state dict|raw_prompt|raw_context|raw_tool_payload|provider_response|langgraph_state" proof_agent tests CONTEXT.md docs -g '*.py' -g '*.md'
```

Expected:

- `ReActWorkflowNodes` does not appear in production or tests.
- `react_nodes` does not appear in production or tests.
- raw forbidden keys appear only in contract validators, tests, or documentation that explicitly describes forbidden content.
- `current_node` remains only as the known out-of-scope `WorkflowState` convergence TODO if included in separate searches.
