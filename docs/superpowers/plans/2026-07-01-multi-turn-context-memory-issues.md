# Multi-Turn Context And Memory Issue Plan

> For agentic workers: REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` to implement each issue. Each issue is independently implementable, but the recommended migration order is Issue 1, Issue 3, then Issue 2.

**Goal:** Turn the first multi-turn Chat context slice into a complete Context Assembler and Memory Recall architecture that supports user supplements, follow-up questions, conversation recall, cache-stable ordering, configurable budget convergence, dynamic overflow recovery, and controlled memory use.

**Architecture:** Keep context ownership in the Control Plane. Runtime adapters, LangGraph state, model providers, memory adapters, and frontend chat surfaces may carry context references or trace-safe summaries, but they do not assemble complete Working Context or decide memory admission. The Context Assembler is the run-start boundary for both LangGraph workflows and the custom Controlled ReAct V3 runtime.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, Control Plane context contracts, Conversation Store, RunStore, JSONL trace, LangGraph runtime adapter, Controlled ReAct V3 Orchestrator, local and external memory adapters, pytest, Ruff, mypy.

**Relevant Decisions:** ADR-0003, ADR-0007, ADR-0008, ADR-0096, ADR-0098, and `docs/domain/tools-models-memory/decisions.md`.

---

## Decisions Already Locked

- Use Context Assembler as the single run-start context boundary.
- Preserve current public behavior and trace/API compatibility during Issue 1.
- Cover both runtime families: LangGraph workflows and the custom `react_enterprise_qa_v3` Controlled ReAct runtime.
- Run Context Assembler before runtime selection. LangGraph state may carry only a context summary projection or reference, not complete Working Context.
- Resume must reuse the run-start context summary or reference instead of reassembling from a changed conversation or memory state.
- Store context configuration in top-level Agent Contract `context:`.
- Use Control Plane `Context Budget Profile` as the authority when configured; provider token estimates remain final model-call guards.
- If no explicit budget is configured, use dynamic provider/model overflow handling: deep compress, update the default budget calibration, and do not mutate Agent Contract YAML.
- Use a `Context Convergence Ladder` with first convergence around 50 percent, second convergence around 80 percent, and deep compression at the hard budget limit or provider context-limit failure.
- Use cache-stable context ordering: stable Harness, Agent, policy, tool, and stage sections first; frequently changing evidence, memory, recent turns, and compaction summaries later.
- Introduce first-class Memory Recall Admission. Memory ids must not masquerade as `ContextAdmission.included_turn_ids`.
- Ordinary trace records memory recall summaries only. Working Context may include bounded policy-admitted memory fact values after relevance, budget, and convergence checks.
- Memory Recall may help intent, planning, retrieval review, and retrieval query construction with reference resolution and task continuity. Final answer may use it only for preferences and continuity. Business claims still require Knowledge or Tool evidence.
- Tool execution cannot use memory recall as parameter input unless Tool Contract and Agent Context Configuration explicitly allow it.

---

## Current Code Anchors

- `proof_agent/contracts/context.py`
  - Already contains `ControlledRunContext`, `ContextSourceRef`, `WorkingContextSection`, `ContextAssemblyBudget`, and `TraceSafeContextAssemblySummary`.
- `proof_agent/control/context_assembler.py`
  - Already assembles an initial conversation-timeline context slice, but it does not yet own all run-start context behavior.
- `proof_agent/runtime/langgraph_runner.py`
  - Still contains `_controlled_run_context_from_admission()` and `_workflow_template_execution_input()` summary logic inside the runtime adapter.
- `proof_agent/delivery/agent_package_execution.py`
  - Selects LangGraph for non-`react_enterprise_qa_v3` workflows and the custom Controlled ReAct V3 path for `react_enterprise_qa_v3`.
- `proof_agent/control/workflow/controlled_react/orchestrator.py`
  - Carries `conversation_context` in run state, but does not yet receive a full Controlled Run Context summary/reference as the shared run-start package.
- `proof_agent/delivery/api.py`
  - Chat conversation runs still use `admit_conversation_context(conversation)` and pass a `ContextAdmission` into the run.
- `proof_agent/delivery/customer_api.py`
  - Customer memory recall is now projected as `MemoryRecallAdmission` with optional bounded `MemoryRecallWorkingPayload`, instead of masquerading memory ids as conversation turn ids.

## Implementation Status

- Run-start Memory Recall Admission now carries trace-safe summaries plus bounded model-facing `MemoryRecallWorkingPayload`.
- V3 Controlled ReAct and LangGraph runtime paths pass admitted memory recall payloads to intent resolution, planning, and final-answer synthesis without treating memory as evidence.
- `ContextBudgetProfile`, `ContextConvergenceLadder`, and top-level Agent Contract `context:` are loaded from manifest YAML.
- `proof_agent/control/context_budget.py` resolves explicit, calibrated, and built-in default context budgets and records dynamic overflow calibration facts.
- `ContextAssemblyBudget` trace summaries now include `convergence_level`, `budget_source`, and `calibration_update_refs`.
- Context Assembler applies Level 1, Level 2, and deep compression decisions while keeping cache-stable section ordering.
- V3 final-answer synthesis has a bounded provider context-limit recovery hook for unconfigured dynamic budgets: emit model error, deep-compress continuity context, retry once, and record a calibration update.
- Remaining follow-up slices: durable calibration storage beyond the in-memory runtime store, LangGraph final-answer overflow recovery parity, approval-resume reuse tests for changed post-pause context, and Dashboard/API read projections for convergence and calibration fields.

---

## Issue 1: Use Context Assembler As The Run-Start Boundary

**Goal:** Make Context Assembler the single Control Plane entrypoint that packages run-start context for both LangGraph and Controlled ReAct V3, while preserving current behavior.

**Non-Goals:**

- Do not implement token-budget convergence in this issue.
- Do not introduce the final Memory Recall contract in this issue.
- Do not change final-answer evidence rules.
- Do not put complete Working Context into LangGraph checkpoint state.
- Do not change frontend Chat API behavior except for additive trace-safe fields.

**Contracts:**

- Add or extend a run-start context package that can carry:
  - `controlled_run_context: ControlledRunContext`
  - `trace_safe_summary: TraceSafeContextAssemblySummary`
  - compatibility `conversation_context: ContextAdmission | None`
  - optional `context_summary_ref` for future sensitive/full capture storage
- Keep `WorkflowTemplateExecutionInput.conversation_context_summary` compatible until callers and Dashboard projections are migrated.
- Prefer additive fields such as `controlled_run_context_summary` or `context_assembly_summary_ref` over replacing existing payloads in one step.

### Task 1.1: Add A Shared Run-Start Context Assembly Result

**Files:**

- Modify `proof_agent/contracts/context.py`
- Modify `proof_agent/control/context_assembler.py`
- Add or modify `tests/test_context_contracts.py`
- Add or modify `tests/test_context_assembler.py`

- [ ] Add a contract such as `RunStartContextAssembly` or equivalent if the existing contracts cannot express the boundary cleanly.
- [ ] Include the trace-safe summary and compatibility `ContextAdmission` projection.
- [ ] Keep forbidden-key validation for trace-safe summaries.
- [ ] Add a failing contract test proving complete raw context cannot enter the trace-safe summary.
- [ ] Add a test proving cache-stable Working Context section ordering remains deterministic.

### Task 1.2: Assemble Context Before Runtime Dispatch

**Files:**

- Modify `proof_agent/delivery/api.py`
- Modify `proof_agent/delivery/run_execution_service.py`
- Modify `proof_agent/delivery/agent_package_execution.py`
- Modify `tests/test_conversation_api.py`
- Modify `tests/test_agent_package_execution.py`

- [ ] Replace per-runtime context conversion with a Delivery or Control Plane call to Context Assembler before runtime selection.
- [ ] Preserve `ContextAdmission` output in Chat response payloads.
- [ ] Emit exactly one ordinary `context_assembly_summary` per run-start path.
- [ ] Pass the same context summary/reference to both runtime families.
- [ ] Add a failing test proving non-V3 LangGraph runs receive the shared run-start context package.
- [ ] Add a failing test proving V3 Controlled ReAct runs receive the same context summary/reference.

### Task 1.3: Move Runtime-Local Context Conversion Out Of LangGraph

**Files:**

- Modify `proof_agent/runtime/langgraph_runner.py`
- Modify `proof_agent/runtime/react_graph.py` only if the builder needs a typed context package
- Modify `tests/test_context_assembler.py`
- Modify `tests/test_conversation_api.py`

- [ ] Remove or deprecate `_controlled_run_context_from_admission()` in the LangGraph runtime adapter.
- [ ] Keep LangGraph graph state limited to a trace-safe summary or reference.
- [ ] Ensure graph closures may read the admitted compatibility context only as non-evidence input.
- [ ] Add a failing test proving LangGraph checkpoint state does not include complete Working Context payloads.

### Task 1.4: Preserve Resume Semantics

**Files:**

- Modify `proof_agent/runtime/approval_resume.py`
- Modify V3 snapshot or resume contracts only if needed
- Add or modify `tests/test_run_execution_api.py`
- Add or modify `tests/test_agent_package_execution.py`

- [ ] Persist only the context summary/ref needed to resume.
- [ ] On approval resume, reuse the original run-start context summary/ref.
- [ ] Do not re-read Conversation Store or memory providers during resume.
- [ ] Add a failing test where conversation or memory changes after approval pause do not change resumed context.

### Issue 1 Verification

```bash
uv run --extra dev python -m pytest tests/test_context_contracts.py tests/test_context_assembler.py tests/test_conversation_api.py tests/test_agent_package_execution.py tests/test_run_execution_api.py -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

---

## Issue 2: Add Agent Context Configuration And Context Convergence Ladder

**Goal:** Add configurable context budgets and multi-layer convergence so normal multi-turn Chat stays rich below budget, becomes progressively smaller before overflow, and can recover from provider context-limit failures.

**Non-Goals:**

- Do not rely on provider tokenizers as the sole Context Assembler authority.
- Do not rewrite Agent Contract YAML when dynamic calibration changes.
- Do not use convergence to drop required governance facts, current user input, active clarification state, or required evidence/citation constraints.
- Do not treat memory or prior turns as business evidence.
- Do not add a provider-native memory path.

**Contracts:**

- Add top-level Agent Contract `context:` configuration.
- Add `AgentContextConfiguration` with optional:
  - `budget_profile`
  - `convergence`
  - `dynamic_calibration`
  - source policies for conversation, compaction, memory recall, evidence, and tools
- Add `ContextBudgetProfile` with configured or calibrated token budget, reserved output tokens, estimation strategy, and profile version.
- Add `ContextConvergenceLadder` with level 1, level 2, and deep compression thresholds.
- Add `ContextBudgetCalibrationStore` keyed by provider, model or Shared Model Connection, model-call role, and context profile version.
- Extend trace-safe summaries with convergence level, budget source, dropped or compacted refs, fallback reasons, and calibration update refs.

### Task 2.1: Add Agent Contract Context Configuration

**Files:**

- Modify Agent Manifest contract files under `proof_agent/contracts/`
- Modify bootstrap validation under `proof_agent/bootstrap/`
- Modify example agent YAML only if a focused example is needed
- Add or modify `tests/test_contracts.py`
- Add or modify `tests/test_bootstrap.py`

- [ ] Add top-level `context:` to Agent Manifest.
- [ ] Validate thresholds are monotonic and within allowed ranges.
- [ ] Reject secret-looking strings and raw prompt fields in context config.
- [ ] Reject configuration that tries to make memory or prior turns evidence.
- [ ] Preserve manifest loading when `context:` is absent.
- [ ] Add positive and negative YAML fixture tests.

### Task 2.2: Implement Context Budget Profile Resolution

**Files:**

- Modify `proof_agent/control/context_assembler.py`
- Add `proof_agent/control/context_budget.py` or equivalent if a focused module is cleaner
- Add or modify `tests/test_context_assembler.py`
- Add `tests/test_context_budget.py` if needed

- [ ] Resolve explicit Agent Context Configuration first.
- [x] Resolve explicit Agent Context Configuration first.
- [x] If no explicit config exists, resolve a dynamic/default profile from calibration store.
- [x] Fall back to a conservative built-in default when no calibration exists.
- [x] Keep provider estimate as a model-call guard, not the source of the assembly budget.
- [x] Add tests for explicit config, calibrated default, and built-in default.

### Task 2.3: Add Level 1 And Level 2 Convergence

**Files:**

- Modify `proof_agent/control/context_assembler.py`
- Add focused helpers if convergence rules become dense
- Add or modify `tests/test_context_assembler.py`

- [x] Level 1, around 50 percent, reduces redundancy while preserving most semantics.
- [x] Level 1 may deduplicate repeated summaries, collapse repeated references, and trim clearly irrelevant older low-priority sections.
- [x] Level 2, around 80 percent, performs structured trade-offs: compact older turns and narrow low-relevance memory recall.
- [x] Keep current user input, active clarification/task state, governance facts, and evidence constraints.
- [x] Add tests proving level 1 keeps rich recent conversation details.
- [x] Add tests proving level 2 compacts older turns and narrows low-relevance memory without mutating Conversation Timeline.

### Task 2.4: Add Deep Compression And Provider Overflow Recovery

**Files:**

- Modify Context Assembler and model-call guard integration points
- Modify provider adapter error handling only where context-limit errors are normalized
- Add or modify `tests/test_context_assembler.py`
- Add or modify `tests/test_model_providers.py`
- Add or modify `tests/test_agent_package_execution.py`

- [x] Deep compression keeps a task-continuity skeleton only.
- [x] Preserve current user input, active clarification/task state, required governance facts, necessary memory recall, and provenance or omission-risk refs.
- [x] On provider context-limit failure with no explicit config, deep compress and retry only if the call site already permits bounded repair/retry behavior.
- [x] Update Context Budget Calibration Store after overflow recovery.
- [x] Do not update calibration when explicit Agent Context Configuration is present.
- [x] Add tests proving calibration updates are persisted as runtime facts and do not mutate YAML.
- [x] Add tests proving provider overflow fallback emits trace-safe convergence and calibration summaries.

### Task 2.5: Keep Prompt Caching Stable

**Files:**

- Modify Context Assembler ordering helpers
- Add or modify `tests/test_context_assembler.py`

- [ ] Keep stable Harness, Agent, policy, tool, and stage sections before volatile sections.
- [ ] Place current evidence, memory recall, recent turns, and compaction summaries later.
- [ ] Keep priority sorting deterministic across equivalent runs.
- [ ] Add a snapshot-style test for section order.

### Issue 2 Verification

```bash
uv run --extra dev python -m pytest tests/test_contracts.py tests/test_bootstrap.py tests/test_context_contracts.py tests/test_context_assembler.py tests/test_model_providers.py tests/test_agent_package_execution.py -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

---

## Issue 3: Introduce First-Class Memory Recall Admission

**Goal:** Stop representing recalled memory as conversation turns and introduce a scoped, trace-safe, policy-admitted Memory Recall path that Context Assembler can budget, order, and expose to only the stages that may use it.

**Non-Goals:**

- Do not make memory a business evidence source.
- Do not include full memory facts in ordinary trace.
- Do not allow tool parameters to be filled from memory recall by default.
- Do not enable cross-user Persistent User Memory without consent and lifecycle controls.
- Do not change current memory write governance except where read/recall contracts require test fixtures.

**Contracts:**

- Add `MemoryRecallAdmission` with scope, subject reference, included memory refs, rejected memory refs, bounded summary, fact keys/counts, lifecycle refs, and policy decision refs.
- Add `MemoryRecallTraceSummary` for ordinary trace.
- Add `MemoryRecallWorkingPayload` for bounded model-facing fact values admitted after policy, relevance, budget, and convergence.
- Add `MemoryRecallStageVisibility` in Agent Context Configuration or a related policy object.
- Extend `ControlledRunContext` source refs to carry `memory_recall` refs without using `ContextAdmission.included_turn_ids`.

### Task 3.1: Add Memory Recall Contracts

**Files:**

- Modify `proof_agent/contracts/context.py`
- Modify memory-related contracts under `proof_agent/contracts/`
- Add or modify `tests/test_context_contracts.py`
- Add or modify `tests/test_memory_admission.py`

- [ ] Add `MemoryRecallAdmission`.
- [ ] Add `MemoryRecallTraceSummary`.
- [ ] Add `MemoryRecallWorkingPayload`.
- [ ] Preserve memory scope values such as `case` and `user`.
- [ ] Validate trace summaries reject raw memory values and secret-looking keys.
- [ ] Add contract tests for case and user scope provenance.

### Task 3.2: Replace Customer API Memory-As-Conversation Context

**Files:**

- Modify `proof_agent/delivery/customer_api.py`
- Modify tests in `tests/test_customer_run_api.py`
- Modify local memory tests if fixtures assume memory ids are turn ids

- [ ] Replace `_memory_context()` with a function that returns Memory Recall admissions.
- [ ] Do not put memory ids into `ContextAdmission.included_turn_ids`.
- [ ] Preserve existing customer-visible answer behavior.
- [ ] Add a failing test proving memory ids no longer appear in conversation turn admission.
- [ ] Add a failing test proving case and user memory recall scopes are preserved.

### Task 3.3: Teach Context Assembler Memory Recall Inputs

**Files:**

- Modify `proof_agent/control/context_assembler.py`
- Modify run request/context plumbing in Delivery as needed
- Add or modify `tests/test_context_assembler.py`
- Add or modify `tests/test_agent_package_execution.py`

- [ ] Accept Memory Recall admissions as explicit Context Assembler inputs.
- [ ] Emit `ContextSourceType.MEMORY_RECALL` refs from Memory Recall Admission.
- [ ] Default Working Context layout to one cache-stable `memory_recall` section.
- [ ] Split sections only when relevance policy requires separate sectioning.
- [ ] Budget memory recall after stable Harness/Agent/policy sections and before or near recent volatile context according to the cache-stable ordering decision.
- [ ] Add tests proving memory recall source refs and sections are deterministic.

### Task 3.4: Split Trace Summary From Working Payload

**Files:**

- Modify trace event builders
- Modify `proof_agent/observability/storage/run_store.py` only if projections need additive fields
- Add or modify `tests/test_agent_package_execution.py`
- Add or modify `tests/test_customer_run_api.py`

- [ ] Ordinary trace emits `MemoryRecallTraceSummary` only.
- [ ] Working Context can include `MemoryRecallWorkingPayload` with bounded admitted fact values.
- [ ] Trace summaries include scope, source refs, included/rejected ids, bounded summary, fact keys/counts, and lifecycle refs.
- [ ] Trace summaries exclude full memory fact values.
- [ ] Add tests proving trace does not contain raw memory facts.
- [ ] Add tests proving Working Context can carry bounded fact values when policy admits them.

### Task 3.5: Enforce Stage Visibility

**Files:**

- Modify intent, planner, retrieval review/query, final answer, and tool call integration points
- Modify `proof_agent/control/workflow/harness_helpers.py` if final-answer context metadata needs distinction
- Add or modify tests:
  - `tests/test_react_intent_resolution.py`
  - `tests/test_react_planner.py`
  - `tests/test_agent_package_execution.py`
  - `tests/test_tool_approval.py` or related tool gateway tests

- [ ] Allow intent resolution, planning, retrieval review, and retrieval query construction to use Memory Recall Working Payload for reference resolution and task continuity.
- [ ] Allow final answer to use memory recall only for preferences and continuity.
- [ ] Keep business claims tied to Knowledge Evidence or Authorized Tool Results.
- [ ] Prevent tool execution from using memory recall as parameter input unless Tool Contract and Agent Context Configuration explicitly allow it.
- [ ] Add tests proving final-answer citations cannot cite memory recall.
- [ ] Add tests proving tool call parameters cannot be filled from memory by default.

### Issue 3 Verification

```bash
uv run --extra dev python -m pytest tests/test_context_contracts.py tests/test_context_assembler.py tests/test_memory_admission.py tests/test_local_memory_store.py tests/test_mem0_memory_store.py tests/test_customer_run_api.py tests/test_agent_package_execution.py tests/test_react_intent_resolution.py tests/test_react_planner.py -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

---

## Current Implementation Status

**Implemented in the first TDD slice:**

- Issue 1 run-start context boundary:
  - `RunStartContextAssembly` contract.
  - Shared Context Assembler path before LangGraph versus Controlled ReAct V3 dispatch.
  - Additive `controlled_run_context_summary` on `WorkflowTemplateExecutionInput`.
  - V3 and LangGraph `context_assembly_summary` trace emission from the same run-start package.
  - Runtime-local LangGraph conversion from `ContextAdmission` to `ControlledRunContext` removed.
- Issue 3 first-class Memory Recall source foundation:
  - `MemoryRecallAdmission`, `MemoryRecallTraceSummary`, and `MemoryRecallWorkingPayload` contracts.
  - Memory recall source refs and default `memory_recall` Working Context section in Context Assembler.
  - Customer API replacement for memory-as-conversation context.
  - `memory_recall_summary` trace event.
  - Regression coverage proving memory ids no longer appear as conversation turn ids.
- Issue 2 configuration schema foundation:
  - Top-level Agent Contract `context:` field.
  - `ContextBudgetProfile`, `ContextConvergenceLadder`, and `AgentContextConfiguration` contracts.
  - Manifest loader support and source-policy forbidden-key validation.

**Remaining implementation slices:**

1. **Issue 3 stage visibility enforcement.**
   Wire `MemoryRecallWorkingPayload` into intent resolution, planning, retrieval review/query construction, and final answer preparation with explicit stage permissions. Add negative tests proving final-answer citations cannot cite memory recall and tool parameters cannot be filled from memory by default.

2. **Issue 2 budget profile resolution.**
   Add a Control Plane resolver for explicit Agent Context Configuration, calibrated default profile, and built-in fallback. Keep explicit config higher priority than dynamic calibration.

3. **Issue 2 Context Budget Calibration Store.**
   Persist trace-safe calibration records keyed by provider, model or Shared Model Connection, model-call role, and context profile version. Do not mutate Agent Contract YAML.

4. **Issue 2 Context Convergence Ladder.**
   Implement level 1, level 2, and deep compression in Context Assembler. Preserve current user input, active clarification/task state, governance facts, evidence constraints, and necessary memory recall.

5. **Issue 2 provider overflow recovery.**
   Normalize provider context-limit failures, deep-compress when no explicit config exists, update calibration, and retry only through bounded call-site retry rules.

6. **Sensitive Context Capture follow-up.**
   Add a separate authorization-gated capture path for full Working Context or detailed memory payload inspection. Ordinary trace must remain summary-only.

7. **Dashboard/API projection follow-up.**
   Add read projections for `controlled_run_context_summary`, `memory_recall_summary`, convergence level, budget source, and calibration refs without exposing full Working Context.

---

## Recommended Migration Order

1. **Issue 1 first:** establish one run-start context package before splitting memory and budget semantics. This prevents LangGraph and Controlled ReAct V3 from drifting.
2. **Issue 3 second:** clean memory recall into a first-class source type before budget convergence starts dropping, compacting, or reordering sections.
3. **Issue 2 third:** implement budget profiles and convergence on top of clean source categories, stable summaries, and scoped memory recall.

This order keeps each issue mergeable and testable without requiring a large-bang context rewrite.

---

## Cross-Issue Definition Of Done

- Every Chat turn remains a governed run with its own retrieval, evidence admission, policy checks, validation, trace, and receipt.
- Conversation Timeline remains the complete record and is never modified by Working Context convergence.
- Ordinary trace stores only trace-safe context summaries, source refs, budget decisions, convergence facts, and fallback reasons.
- Complete Working Context or detailed memory payload capture requires an explicit sensitive capture mode.
- LangGraph and Controlled ReAct V3 use the same run-start context summary/reference.
- Memory Recall is scoped, admitted, and visible only to allowed stages.
- Business answers still require Knowledge Evidence or Authorized Tool Results for claims.
- Cache-stable ordering is deterministic and keeps frequently changing context near the tail.
- Explicit Agent Context Configuration always wins over dynamic calibration.
- Dynamic budget calibration updates a store, not Agent Contract YAML.

---

## Full Verification Gate

Run the focused issue suites during implementation, then the broader backend gate before claiming completion:

```bash
uv run --extra dev python -m pytest tests/test_conversation_api.py tests/test_context_contracts.py tests/test_context_assembler.py tests/test_customer_run_api.py tests/test_agent_package_execution.py tests/test_run_execution_api.py tests/test_memory_admission.py tests/test_local_memory_store.py tests/test_mem0_memory_store.py tests/test_react_intent_resolution.py tests/test_react_planner.py tests/test_model_providers.py -q
uv run --extra dev python -m pytest tests/ -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
uv run --extra dev proof-agent demo
python3 scripts/check-domain-contexts.py
git diff --check
```
