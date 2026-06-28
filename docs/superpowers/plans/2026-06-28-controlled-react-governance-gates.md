# Controlled ReAct Governance Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each behavior slice and superpowers:verification-before-completion before claiming completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Controlled ReAct V3 governance so retrieval, final-answer model calls, final answer admission, approval-denial replanning, and trace ordering are controlled at execution time instead of being reconstructed by Delivery after the run.

**Architecture:** Controlled ReAct V3 remains the Control Plane execution authority. Delivery wires persistence adapters and final RunStore/receipt persistence only. The Orchestrator and its effect ports evaluate policy before guarded actions, emit trace facts through a narrow run-scoped `TracePort`, reuse `KnowledgeRetrievalService` for retrieval governance, and map terminal policy blocks to explicit outcomes.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, pytest, existing Controlled ReAct Orchestrator and Knowledge Retrieval Service.

**Relevant Decisions:** ADR-0088, ADR-0089, ADR-0090, ADR-0091, ADR-0092, ADR-0093, ADR-0094, ADR-0095.

**Phase 1 status:** Core governance fixes landed in commit `5fe9bbc`. Phase 2 starts with two closeout items from the Phase 1 review: direct `POLICY_DENIED` projection coverage through RunStore/API serialization, and an explicit memory-write TracePort scope decision. Delivery may keep stage/result projection as a temporary migration shim; it must not recreate core V3 governance decisions after execution.

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

### Phase 2: Memory Governance Completion And Closeout

### Task 7: Close Phase 1 Projection Coverage

**Files:**
- Modify: `tests/test_agent_package_execution.py` or `tests/test_dashboard_api.py`
- Modify: `tests/test_run_store.py` if a lower-level projection fixture is clearer
- Modify: Dashboard/Chat/API outcome mappings only if focused coverage exposes drift

- [x] Add a focused backend test proving a V3 `POLICY_DENIED` terminal result survives persistence and Dashboard/API serialization without becoming an unknown/default outcome.
- [x] Add a focused receipt or run-detail projection assertion when the existing test surface does not already cover the same public behavior.
- [x] Keep this as a closeout test slice; do not broaden Phase 2 into unrelated Dashboard UI refactors.

### Task 8: Split Memory Write Into Candidate And Commit

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/ports.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Modify: `tests/test_controlled_react_orchestrator.py`

- [x] Add a trace-safe `MemoryWriteCandidate` value carrying the prepared write `values` for policy evaluation plus derived safe metadata such as field names and field count.
- [x] Change the V3 memory port from a one-step `write(state, answer)` call into a two-step boundary: `prepare_write(state, answer)` followed by `commit_write(candidate)`.
- [x] Keep `_InvocationMemoryAdapter` responsible for constructing the same session-summary fields used today: `question`, `outcome`, and `final_output_length`.
- [x] Make the deterministic/default memory adapter follow the same two-step contract or return `None` when no memory write is configured.

### Task 9: Add Orchestrator-Owned `before_memory_write`

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/ports.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Modify: `tests/test_controlled_react_orchestrator.py`

- [x] Add a policy-port method for memory admission, such as `evaluate_memory_write(state, candidate)`, rather than overloading the existing tool-action `evaluate(state, action)` method.
- [x] Evaluate `before_memory_write` after `prepare_write()` and before `commit_write()`.
- [x] On deny, do not call `commit_write()`.
- [x] Return a blocked `ValidationResult` so the memory Workflow Stage Result is `BLOCKED` while the terminal user-facing answer remains unchanged.
- [x] Reserve terminal `POLICY_DENIED` for future explicit terminal memory policies; ordinary memory-write denial is a blocked side effect, not a failed answer.

### Task 10: Emit Memory Governance Trace Facts

**Files:**
- Modify: `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `proof_agent/observability/storage/run_store.py` only if existing projection fails to attribute events
- Modify: `tests/test_agent_package_execution.py`

- [x] Emit `memory_write_requested` before policy evaluation with safe metadata only: field names, field count, and write source.
- [x] Emit a normal `policy_decision` for `before_memory_write` using the existing policy trace payload shape.
- [x] Emit `memory_write_decision` after policy/validator resolution with `status=ok` on allow and `status=blocked` on deny.
- [x] Do not include raw memory values or final answer text in memory trace payloads.
- [x] Confirm RunStore already attributes `memory_write_requested` and `memory_write_decision` to the memory stage; update only if the focused V3 trace test proves a gap.

### Task 11: Align V3 And Legacy Memory Semantics

**Files:**
- Modify: `tests/test_agent_package_execution.py`
- Modify: `tests/test_customer_run_api.py` only for missing regression assertions
- Modify: `docs/technical-design.md` only if implementation reveals a contract wording mismatch

- [x] Add a V3 deny test: final answer/outcome remains governed answer/refusal, memory stage is blocked, trace has `policy_decision` and blocked `memory_write_decision`, and session memory is unchanged.
- [x] Add a V3 allow test: final answer/outcome remains unchanged, memory stage completes, trace has allow decisions, and session memory receives the prepared fields.
- [x] Keep the legacy Customer API memory path behavior unchanged; add only regression coverage or references needed to prove semantic alignment.
- [x] Verify the denied-tool replanning behavior from Phase 1 is unaffected by the new memory side-effect gate.

---

### Verification

- [x] Run focused tests after each task.
- [ ] Run `uv run --extra dev python -m pytest tests/test_controlled_react_orchestrator.py tests/test_agent_package_execution.py tests/test_run_execution_api.py tests/test_trace_model_events.py -q`.
- [ ] Run `uv run --extra dev python -m pytest tests/ -q`.
- [ ] Run `npm test`.
- [ ] Run `uv run --extra dev proof-agent demo`.
- [ ] Run a V3 fixture command and inspect trace order: `run_started` first, policy decisions before guarded actions, no Delivery-created core policy decision after terminal result.
- [ ] Run `python3 scripts/check-domain-contexts.py`.
- [ ] Run `git diff --check`.
