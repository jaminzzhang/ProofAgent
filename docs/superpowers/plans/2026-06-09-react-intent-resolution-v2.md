# React Intent Resolution V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add React Enterprise QA Template V2 with a governed Intent Resolution step before ReAct planning.

**Architecture:** Introduce an audit-safe `IntentResolution` contract and resolver capability that reuses `ReActPlannerConfig` while emitting a distinct model-call role and trace event. Register `react_enterprise_qa_v2` as a versioned workflow template and insert an `intent_resolution` node before the existing ReAct plan node only for that template. Project intent summaries through internal governance details while keeping customer-safe responses unchanged.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, LangGraph StateGraph, pytest, existing Proof Agent model provider normalization and trace infrastructure.

---

### Task 1: Add Intent Resolution Contract

**Files:**
- Modify: `proof_agent/contracts/react_workflow.py`
- Modify: `proof_agent/contracts/model.py`
- Modify: `proof_agent/contracts/trace.py`
- Modify: `proof_agent/contracts/__init__.py`
- Test: `tests/test_react_contracts.py`
- Test: `tests/test_trace_model_events.py`

- [x] **Step 1: Write failing tests** for frozen `IntentResolution`, export availability, `ModelCallRole.INTENT_RESOLUTION`, and `TraceEventType.INTENT_RESOLUTION`.
- [x] **Step 2: Run targeted tests** with `uv run --extra dev python -m pytest tests/test_react_contracts.py tests/test_trace_model_events.py -v` and confirm they fail for missing symbols.
- [x] **Step 3: Implement minimal contracts** with fields `resolution_id`, `user_goal`, `domain_intent`, `known_facts`, `missing_fields`, `ambiguities`, `risk_flags`, `confidence`, and `recommended_next_action`.
- [x] **Step 4: Re-run targeted tests** and confirm pass.

### Task 2: Add Intent Resolver Capability

**Files:**
- Create: `proof_agent/capabilities/react/intent.py`
- Modify: `proof_agent/capabilities/react/__init__.py`
- Test: `tests/test_react_intent_resolution.py`

- [x] **Step 1: Write failing tests** for deterministic intent resolution, compact LLM JSON parsing, semantic validation, and planner-config reuse.
- [x] **Step 2: Run targeted tests** and confirm missing capability failures.
- [x] **Step 3: Implement resolver protocol, deterministic resolver, LLM resolver, validation, and `resolve_intent_resolver(config)`.**
- [x] **Step 4: Re-run targeted tests** and confirm pass.

### Task 3: Register V2 Workflow Template

**Files:**
- Modify: `proof_agent/control/workflow/templates.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Test: `tests/test_workflow_templates.py` or existing workflow validation tests

- [x] **Step 1: Write failing tests** that `react_enterprise_qa_v2` resolves with descriptor `react_enterprise_qa.v2` and includes `intent_resolution -> plan`.
- [x] **Step 2: Run targeted tests** and confirm failure.
- [x] **Step 3: Register v2 template** by extending the existing ReAct descriptor with a leading intent node.
- [x] **Step 4: Re-run targeted tests** and confirm pass.

### Task 4: Wire Intent Resolution Into Harness Invocation And Runtime

**Files:**
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`

- [x] **Step 1: Write failing tests** that v2 emits `intent_resolution`, then `reasoning_summary`, and still answers/refuses/clarifies through existing governed paths.
- [x] **Step 2: Run targeted tests** and confirm missing runtime behavior.
- [x] **Step 3: Add intent resolver to invocation** and execute intent node only when template descriptor version is v2.
- [x] **Step 4: Re-run targeted tests** and confirm pass.

### Task 5: Project Governance Details

**Files:**
- Modify: `proof_agent/contracts/react_workflow.py`
- Modify: `proof_agent/observability/storage/run_store.py`
- Modify: `proof_agent/observability/audit/receipt.py`
- Modify: `proof_agent/observability/audit/templates/governance_receipt.md.j2`
- Test: `tests/test_run_store.py`

- [x] **Step 1: Write failing tests** that RunStore governance details include `intent_resolution` for v2 internal/operator views.
- [x] **Step 2: Run targeted tests** and confirm failure.
- [x] **Step 3: Extract and render intent summaries from trace without changing customer-safe projections.**
- [x] **Step 4: Re-run targeted tests** and confirm pass.

### Task 6: Add Fixture And Full Verification

**Files:**
- Create: `proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2/`
- Test: relevant CLI/workflow/API tests

- [x] **Step 1: Add v2 fixture** copied from ReAct fixture with `workflow.template: react_enterprise_qa_v2`.
- [x] **Step 2: Run focused tests** for contracts, resolver, workflow, run store, and API projection.
- [x] **Step 3: Run formatting/lint check** with `uv run --extra dev ruff check proof_agent tests`.
- [x] **Step 4: Run `git diff --check`.
