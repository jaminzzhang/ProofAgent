# Workflow Refactor Closure Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. This is a closure program plan; do not collapse the slices into one broad PR.

**Goal:** Close the remaining Workflow refactor debt after the Agent Contract stage/capability work by separating code-boundary cleanup, result-typing closure, and legacy contract/baseline convergence.

**Architecture:** The closure program has three small slices.

- **Slice A: ReAct Stage Behavior Consolidation** removes the `ReActWorkflowNodes` ambiguity and makes `ReActEnterpriseQAWorkflowExecution` the only public governed stage execution surface.
- **Slice B: Workflow Stage Result Union Decision** closes the per-stage union TODO by keeping `WorkflowStageResult` as the trace-safe envelope and adding stage-specific projections only for named consumers.
- **Slice C: Workflow Legacy Contract Convergence** retires the old `WorkflowState` contract and decides whether to preserve, reset, or rebuild the old deterministic `enterprise_qa` baseline around the new Deterministic ReAct Baseline.

**Specs:** `CONTEXT.md`, `docs/adr/0027-workflow-template-stage-terminology-cutover.md`, `docs/adr/0028-agent-contract-stage-capability-and-trace-capture-contract.md`, `docs/adr/0029-deterministic-react-baseline.md`, `docs/superpowers/plans/2026-06-16-react-stage-behavior-consolidation.md`.

---

## Non-Goals

- Do not introduce descriptor-derived dynamic Runtime Adapter topology.
- Do not add a second runtime.
- Do not build a historical executable descriptor registry.
- Do not change `validation_capture.v2` schema.
- Do not expose Workflow Stage Continuation State through trace, receipt, Dashboard, API, or validation capture projections.
- Do not preserve old Workflow terminology by adding new aliases such as `current_stage`.

---

## Task 0: Baseline And Program Guardrails

- [x] **Step 0.1: Capture current status**

Run:

```bash
git status --short
```

Expected: only intentional planning/context/ADR files are modified before implementation starts.

- [x] **Step 0.2: Run the current focused Workflow suite**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_workflow_enterprise_qa.py tests/test_workflow_stage_runtime_adapter.py tests/test_workflow_execution_contracts.py tests/test_run_execution_api.py tests/test_validation_capture_contracts.py -q
```

Expected: GREEN before implementation. Record existing failures before making runtime changes.

- [x] **Step 0.3: Capture residual terminology**

Run:

```bash
rg "ReActWorkflowNodes|react_nodes|WorkflowState|current_node|Enterprise QA Template.*baseline|deterministic regression baseline" proof_agent tests CONTEXT.md docs -g '*.py' -g '*.md'
```

Expected: produce the working list for the three closure slices.

---

## Task 1: Complete ReAct Stage Behavior Consolidation

Follow the dedicated plan:

```text
docs/superpowers/plans/2026-06-16-react-stage-behavior-consolidation.md
```

- [x] **Step 1.1: Execute the dedicated plan through Task 8**

Expected final state:

- `ReActEnterpriseQAWorkflowExecution` is the only public stage execution surface.
- `ReActEnterpriseQAStageBehavior` owns internal ReAct stage work.
- `ReActWorkflowNodes` is removed from production and tests.
- `react_nodes.py` is not a long-term compatibility module.
- `WorkflowStageResult` and approval behavior remain unchanged from the caller's perspective.

- [x] **Step 1.2: Run the dedicated plan's final checks**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_workflow_stage_runtime_adapter.py tests/test_workflow_execution_contracts.py tests/test_run_execution_api.py tests/test_validation_capture_contracts.py -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
rg "ReActWorkflowNodes|react_nodes" proof_agent tests -g '*.py'
```

Expected: tests, Ruff, and mypy pass; the search returns no production or test hits.

---

## Task 2: Close Workflow Stage Result Union Decision

This is a documentation and contract-safety slice, not a new result-union implementation.

- [x] **Step 2.1: Keep WorkflowStageResult as the contract**

Verify that `WorkflowStageResult` remains the only Workflow Template Execution stage-result contract and that no broad `PlanStageResult | RetrievalStageResult | ToolStageResult` union was introduced during Task 1.

Run:

```bash
rg "PlanStageResult|RetrievalStageResult|ToolStageResult|ModelAnswerStageResult|StageResultUnion" proof_agent tests -g '*.py'
```

Expected: no output unless a future explicit consumer has been approved and documented.

- [x] **Step 2.2: Verify stage-specific projections stay purpose-bound**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_execution_contracts.py tests/test_workflow_stage_runtime_adapter.py tests/test_validation_capture_contracts.py -q
```

Expected: GREEN. `ApprovalPause`, `ClarificationNeed`, and `WorkflowStageResultVerificationProjection` remain purpose-bound projections, not a complete per-stage union.

---

## Task 3: Retire Legacy WorkflowState

**Files likely affected:**

- `proof_agent/contracts/run.py`
- `proof_agent/contracts/__init__.py`
- `proof_agent/control/workflow/state.py`
- `tests/test_contracts.py`

- [x] **Step 3.1: Confirm no runtime consumer remains**

Run:

```bash
rg "WorkflowState|current_node" proof_agent tests -g '*.py'
```

Expected: only the legacy contract, export, shim, and tests appear before deletion.

- [x] **Step 3.2: Remove the legacy contract**

Remove `WorkflowState` from `contracts/run.py`, remove its export from `contracts/__init__.py`, remove `proof_agent/control/workflow/state.py` if it only re-exports `WorkflowState`, and delete or update tests that only prove the old snapshot behavior.

Run:

```bash
uv run --extra dev python -m pytest tests/test_contracts.py tests/test_workflow_execution_contracts.py -q
uv run --extra dev ruff check proof_agent/contracts proof_agent/control/workflow tests/test_contracts.py tests/test_workflow_execution_contracts.py
```

Expected: GREEN.

- [x] **Step 3.3: Verify the old terminology is gone from code**

Run:

```bash
rg "WorkflowState|current_node" proof_agent tests -g '*.py'
```

Expected: no output.

---

## Task 4: Assess Enterprise QA Baseline Reset

This task decides whether old `enterprise_qa` remains a compatibility path or is deleted and rebuilt around the Deterministic ReAct Baseline.

- [x] **Step 4.1: Inventory `enterprise_qa` consumers**

Run:

```bash
rg "enterprise_qa" proof_agent tests examples docs -g '*.py' -g '*.md' -g '*.yaml'
```

Classify each hit as:

- default demo or CI baseline
- compatibility package
- documentation/history
- runtime routing
- test fixture

Expected: a short migration list before touching code.

Decision recorded during execution:

- default demo and compare harness default move to `react_enterprise_qa`
- old `enterprise_qa` remains a read-only compatibility path
- legacy `enterprise_qa` tests remain only to prove supported compatibility behavior

- [x] **Step 4.2: Move deterministic baseline expectations to React**

Prefer `react_enterprise_qa` deterministic fixtures for default governed Workflow Template regression. Update tests and docs that treat old linear `enterprise_qa` as the primary baseline, while preserving compatibility tests only when they prove an explicit supported path.

Run the affected focused tests after each small change.

Expected: the primary deterministic regression path runs through React Enterprise QA.

- [x] **Step 4.3: Decide old `enterprise_qa` fate**

Choose one of two explicit outcomes:

- Keep `enterprise_qa` as a compatibility path with read-only docs and minimal tests.
- Delete and rebuild the old baseline through **Enterprise QA Baseline Reset** if keeping it blocks Workflow Template Execution boundaries.

Do not leave old `enterprise_qa` half-primary and half-compatibility.

- [x] **Step 4.4: Verify baseline behavior**

Run:

```bash
uv run --extra dev proof-agent demo
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py tests/test_run_execution_api.py tests/test_conversation_api.py -q
```

Expected: deterministic supported, unsupported, and approval-wait scenarios still pass through the selected primary baseline path.

---

## Task 5: Documentation Cleanup

- [x] **Step 5.1: Update current architecture docs**

Update English docs only. Likely targets:

- `docs/technical-design.md`
- `docs/developer-guide.md`
- `docs/development-progress.md`
- relevant concept docs under `docs/concepts/`

Expected: current docs describe Deterministic ReAct Baseline and do not present old `enterprise_qa` as the long-term primary regression baseline.

- [x] **Step 5.2: Preserve historical docs as historical**

Do not rewrite old completed implementation plans unless they present themselves as current truth. Historical mentions may remain if clearly historical or superseded.

Run:

```bash
rg "enterprise_qa.*baseline|deterministic regression baseline|WorkflowState|current_node|ReActWorkflowNodes|react_nodes" docs CONTEXT.md -g '*.md'
```

Expected: remaining hits are either current accepted terms, ADR history with superseded notes, or old completed plans.

---

## Task 6: Final Verification

- [x] **Step 6.1: Full backend suite**

Run:

```bash
uv run --extra dev python -m pytest
```

Expected: GREEN.

- [x] **Step 6.2: Lint and type check**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
```

Expected: GREEN.

- [x] **Step 6.3: Final residual search**

Run:

```bash
rg "ReActWorkflowNodes|react_nodes|WorkflowState|current_node|complete stage-specific result union|enterprise_qa.*deterministic regression baseline" proof_agent tests CONTEXT.md docs -g '*.py' -g '*.md'
```

Expected: no production/test hits for retired code terms; remaining documentation hits are intentional historical or superseded references.
