# Controlled ReAct Governance Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each behavior slice and superpowers:verification-before-completion before claiming completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Controlled ReAct V3 governance so retrieval, final-answer model calls, final answer admission, approval-denial replanning, and trace ordering are controlled at execution time instead of being reconstructed by Delivery after the run.

**Architecture:** Controlled ReAct V3 remains the Control Plane execution authority. Delivery wires persistence adapters and final RunStore/receipt persistence only. The Orchestrator and its effect ports evaluate policy before guarded actions, emit trace facts through a narrow run-scoped `TracePort`, reuse `KnowledgeRetrievalService` for retrieval governance, and map terminal policy blocks to explicit outcomes.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, pytest, existing Controlled ReAct Orchestrator and Knowledge Retrieval Service.

**Relevant Decisions:** ADR-0088, ADR-0089, ADR-0090, ADR-0091, ADR-0092, ADR-0093, ADR-0094.

---

### Phase 1: Core Governance Gates And Approval Semantics

### Task 1: Add `POLICY_DENIED` Outcome Surface

**Files:**
- Modify: `proof_agent/contracts/receipt.py`
- Modify: Dashboard/API outcome badge mappings as needed
- Modify: evaluation gate mappings as needed
- Modify: receipt rendering tests and API serialization tests as needed

- [ ] Add `ReceiptOutcome.POLICY_DENIED`.
- [ ] Update receipt, Dashboard, API, and evaluation projections so the new outcome is displayed and does not fall into unknown/default buckets.
- [ ] Add focused tests proving `POLICY_DENIED` serializes through contracts, receipt, RunStore, and Dashboard API types.

### Task 2: Introduce Controlled ReAct `TracePort`

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/ports.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `proof_agent/delivery/agent_package_execution.py`
- Modify: `proof_agent/observability/api/routers/runs.py`
- Add focused tests in `tests/test_controlled_react_orchestrator.py` and `tests/test_agent_package_execution.py`

- [ ] Define a narrow `TracePort` protocol for policy decisions, retrieval/evidence summaries, model request/response/error summaries, approval events, stage results, and terminal output.
- [ ] Add a no-op trace adapter for pure unit tests.
- [ ] Add a `TraceWriter` adapter at the composition/delivery boundary.
- [ ] Move V3 `run_started` and core governance event emission to the execution start/order where the event actually happens.
- [ ] Remove Delivery's responsibility for creating core V3 policy decisions after `orchestrator.start()` returns.

### Task 3: Route V3 Retrieval Through `KnowledgeRetrievalService`

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `proof_agent/control/knowledge/retrieval_service.py` only if a trace adapter seam is missing
- Modify: `tests/test_controlled_react_orchestrator.py`
- Modify: `tests/test_agent_package_execution.py`

- [ ] Replace `_InvocationKnowledgeObservationAdapter` direct `knowledge_provider.retrieve()` calls with a `KnowledgeRetrievalService` invocation.
- [ ] Preserve Observation Record commit semantics: retrieval service admits evidence; Orchestrator commits accepted evidence into `RetrievalObservationTruth`.
- [ ] Add tests proving V3 emits `before_retrieval` / `before_retrieval_step` policy decisions before retrieval result events.
- [ ] Add tests proving policy-denied retrieval produces no provider call and leads to a governed terminal result or replan path.

### Task 4: Add Policy-Gated Final Answer Model Boundary

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `proof_agent/control/workflow/controlled_react/ports.py` if the boundary deserves its own protocol
- Modify: `tests/test_controlled_react_orchestrator.py`
- Modify: `tests/test_agent_package_execution.py`
- Modify: `tests/test_trace_model_events.py`

- [ ] Wrap final-answer model calls in a model-call guard that estimates tokens, evaluates `before_model_call`, emits policy decision and model request summaries, then calls the provider only if allowed.
- [ ] Emit `model_response` on success and `model_error` on provider failure.
- [ ] Add tests proving `before_model_call` denial does not call the provider.
- [ ] Map required final-answer model-call denial to `POLICY_DENIED`.

### Task 5: Move `before_answer` To Final Answer Admission

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `proof_agent/delivery/agent_package_execution.py`
- Modify: `tests/test_controlled_react_orchestrator.py`
- Modify: `tests/test_agent_package_execution.py`

- [ ] Evaluate `before_answer` after candidate answer synthesis and before terminal result commit.
- [ ] Include accepted evidence count, citation presence, citation binding, authorized tool-result support, and validation status in the policy context.
- [ ] If final answer admission is denied and no alternate path remains, return `POLICY_DENIED`.
- [ ] Delete or neutralize Delivery's post-run `_emit_controlled_react_answer_policy_decision` path.
- [ ] Add tests proving `before_answer` denial prevents `final_output` from being emitted as an answered outcome.

### Task 6: Align Approval Denial Replanning

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `tests/test_controlled_react_orchestrator.py`
- Modify: `tests/test_run_execution_api.py`

- [ ] Keep approval denial as an `Approval Denial Observation` and replan from remaining admitted context.
- [ ] Ensure answer synthesis does not treat a denied tool observation as an authorized successful tool result.
- [ ] When the planner determines the denied tool is necessary and no alternate path remains, return `TOOL_APPROVAL_DENIED`.
- [ ] Add tests for both branches: denial followed by alternate evidence-backed answer, and denial followed by necessary-tool terminal `TOOL_APPROVAL_DENIED`.

---

### Phase 2: Memory Governance Completion

### Task 7: Add Policy-Gated Memory Write

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `tests/test_controlled_react_orchestrator.py`
- Modify: `tests/test_memory_boundary.py` or a new focused V3 test

- [ ] Evaluate `before_memory_write` before writing V3 session memory.
- [ ] Emit `memory_write_decision` through `TracePort`.
- [ ] Preserve current safe session-summary write fields.
- [ ] If memory write is denied, do not change the terminal user-facing answer unless policy explicitly requires terminal denial.

---

### Verification

- [ ] Run focused tests after each task.
- [ ] Run `uv run --extra dev python -m pytest tests/test_controlled_react_orchestrator.py tests/test_agent_package_execution.py tests/test_run_execution_api.py tests/test_trace_model_events.py -q`.
- [ ] Run `uv run --extra dev python -m pytest tests/ -q`.
- [ ] Run `npm test`.
- [ ] Run `uv run --extra dev proof-agent demo`.
- [ ] Run a V3 fixture command and inspect trace order: `run_started` first, policy decisions before guarded actions, no Delivery-created core policy decision after terminal result.
- [ ] Run `python3 scripts/check-domain-contexts.py`.
- [ ] Run `git diff --check`.
