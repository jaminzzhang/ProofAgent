# Final Answer Repair Retry And Follow-up Context Injection Plan

> For agentic workers: REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement bounded final-answer repair retry and typed follow-up context injection for Controlled ReAct V3 without weakening evidence, policy, trace, or validation boundaries.

**Architecture:** Carry admitted conversation context as typed non-evidence run state into intent resolution, planning, and final-answer generation. Keep `AnswerEvidenceContext` as the evidence truth boundary. Extend `FinalAnswerAttemptRunner` into a small state machine with typed attempt status, deterministic repair eligibility, one default repair retry, and full policy/trace/validation handling for every model call.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, Controlled ReAct V3, `ContextAdmission`, `AnswerEvidenceContext`, `FinalAnswerAttemptRunner`, `PolicyEngine`, JSONL trace, validation capture v2, pytest, Ruff, mypy.

---

## Decisions Already Locked

- Follow-up context enters `ControlledReActRunState`, not `AnswerEvidenceContext`.
- Follow-up context is injected into `intent_resolution`, `plan`, and `model_answer` through typed `conversation_context`, not by stuffing text into `context_summary`.
- Repair retry lives inside `FinalAnswerAttemptRunner`; it is not a new Orchestrator action and not a Delivery retry.
- Repair retry is default-on for eligible validation failures, capped at one retry, with no new manifest option in the first implementation.
- Every repair retry is a new governed model call and must pass `BEFORE_MODEL_CALL` policy.
- Repair eligibility is conservative:
  - Repairable: `schema_failed`, `citation_binding_failed` when allowed citation refs exist, `final_answer_adequacy_failed` when safety passed.
  - Non-repairable: `safety_failed`, `policy_denied`, no accepted evidence, citation binding without allowed refs, exhausted retry budget.
- A repaired first failure is trace history plus LLM interaction capture, not `stage_failure_diagnostics`.
- Only the final unrepaired stop becomes a `WorkflowStageFailureDiagnostic`.
- Repair payloads carry stable, bounded repair facts only and never carry safety-failed previous content.

---

## Current Code Anchors

- `proof_agent/contracts/controlled_react.py`
  - `ControlledReActRunState` is the right home for run-scoped typed context.
  - `AnswerEvidenceContext` must remain evidence-only.
- `proof_agent/control/workflow/controlled_react/orchestrator.py`
  - `ControlledReActStartRequest` currently lacks `conversation_context`.
  - `start()` currently constructs state from request fields.
- `proof_agent/control/workflow/controlled_react/composition.py`
  - `_InvocationIntentResolutionAdapter` and `_InvocationPlannerAdapter` call model-bearing capabilities without conversation context.
  - `_ModelAnswerSynthesisAdapter` delegates final-answer model work to `FinalAnswerAttemptRunner`.
- `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
  - Existing lifecycle: `prepare -> generate -> normalize -> repair -> admit`.
  - `repair()` is currently no-op.
- `proof_agent/control/workflow/harness_helpers.py`
  - `build_model_request()` already accepts `conversation_context`.
  - `validate_model_output()` is the validation source of truth.
- `proof_agent/capabilities/react/intent.py`
  - Existing intent repair pattern is the closest implementation precedent.
- `proof_agent/capabilities/react/planner.py`
  - Planner already accepts `workflow_stage_context`; add typed conversation context alongside it.

---

## Non-Goals

- Do not put prior conversation summary into `AnswerEvidenceContext`.
- Do not treat follow-up context as evidence or citation support.
- Do not add a manifest or Agent Contract field for repair retry in this slice.
- Do not retry safety failures.
- Do not add retrieval during final-answer repair.
- Do not move repair logic into Delivery, RunStore, Dashboard, or validation capture.
- Do not expose raw model output, rejected values, provider envelopes, stack traces, secrets, or chain-of-thought in ordinary trace.
- Do not modify `docs/zh/`.

---

## Task 1: Carry Conversation Context Into V3 Run State

**Files:**

- Modify `proof_agent/contracts/controlled_react.py`
- Modify `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Modify `proof_agent/delivery/agent_package_execution.py`
- Tests in `tests/test_controlled_react_orchestrator.py` and `tests/test_agent_package_execution.py`

- [ ] Add `conversation_context: ContextAdmission | None = None` to `ControlledReActRunState`.
- [ ] Add `conversation_context: ContextAdmission | None = None` to `ControlledReActStartRequest`.
- [ ] In `ControlledReActOrchestrator.start()`, copy request conversation context into initial state.
- [ ] In `_execute_controlled_react_v3_agent_package_run()`, pass `request.conversation_context` into `ControlledReActStartRequest`.
- [ ] Add a failing test proving a v3 package run hands `conversation_context` to the controlled orchestrator start request.
- [ ] Add a focused state contract test proving `ControlledReActRunState.conversation_context` freezes and round-trips as a typed `ContextAdmission`.

**Plain-language explanation:** The v3 Control Plane currently drops the follow-up context before the Orchestrator starts. This task makes the context part of run state so all governed stages can read the same admitted, non-evidence fact.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_controlled_react_orchestrator.py tests/test_agent_package_execution.py -k "conversation_context or follow_up" -v
```

---

## Task 2: Inject Follow-up Context Into Intent Resolution

**Files:**

- Modify `proof_agent/capabilities/react/intent.py`
- Modify `proof_agent/control/workflow/controlled_react/composition.py`
- Tests in `tests/test_react_intent_resolution.py`

- [ ] Add optional `conversation_context: ContextAdmission | None = None` to intent resolver interfaces and implementations.
- [ ] Add admitted context to the LLM intent payload under a typed key such as `conversation_context`.
- [ ] Mark the payload text or object as non-evidence and follow-up-resolution-only.
- [ ] Do not include unadmitted context summaries.
- [ ] Preserve the existing intent repair request behavior and carry the same conversation context into the intent repair request when present.
- [ ] Update `_InvocationIntentResolutionAdapter.resolve()` to pass `state.conversation_context`.
- [ ] Add a failing test proving `LLMIntentResolver` includes admitted conversation context in the first request.
- [ ] Add a failing test proving the intent repair request preserves the admitted conversation context.
- [ ] Add a test proving unadmitted context is omitted.

**Plain-language explanation:** Intent resolution happens before retrieval. If the current question says "these pros and cons", the retrieval query can only be correct if intent resolution sees what "these" points to.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_react_intent_resolution.py -k "conversation_context or repair" -v
```

---

## Task 3: Inject Follow-up Context Into Planning

**Files:**

- Modify `proof_agent/capabilities/react/planner.py`
- Modify `proof_agent/control/workflow/controlled_react/composition.py`
- Tests in `tests/test_react_planner.py` and `tests/test_agent_package_execution.py`

- [ ] Add optional `conversation_context: ContextAdmission | None = None` to planner implementations.
- [ ] Add admitted context to the LLM planner payload under a typed key such as `conversation_context`.
- [ ] Keep `context_summary` focused on control-state facts such as observation count and accepted evidence count.
- [ ] Do not include unadmitted context.
- [ ] Update `_InvocationPlannerAdapter.plan()` and `_DeterministicPlannerAdapter.plan()` call sites to pass `state.conversation_context`.
- [ ] Add a failing test proving `LLMReActPlanner` receives admitted conversation context as a typed payload field.
- [ ] Add a failing test proving `context_summary` does not contain the conversation summary text.
- [ ] Add or update an integration test proving v3 package execution can pass follow-up context through to planner model requests.

**Plain-language explanation:** Planning chooses whether to retrieve, clarify, call a tool, or answer. Follow-up context belongs beside the question as non-evidence interpretation context, not hidden in a control summary string.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_react_planner.py tests/test_agent_package_execution.py -k "conversation_context or follow_up" -v
```

---

## Task 4: Inject Follow-up Context Into Final Answer Preparation

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Tests in `tests/test_agent_package_execution.py` or a new `tests/test_final_answer_attempt.py`

- [ ] In `FinalAnswerAttemptRunner.prepare()`, pass `state.conversation_context` into `build_model_request()`.
- [ ] Stop discarding `answer_context` only if no longer needed; keep it evidence-only if retained for future precheck use.
- [ ] Add a failing test proving final-answer model request metadata has `conversation_context_admitted=True` when context is admitted.
- [ ] Add a failing test proving final-answer user prompt includes the existing non-evidence instruction from `build_model_request()`.
- [ ] Add a failing test proving admitted context does not alter `EvidenceChunk` values or citation refs.

**Plain-language explanation:** The final answer model may use admitted conversation context to resolve references, but it must still answer only from accepted evidence.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_package_execution.py -k "model_answer and conversation_context" -v
```

---

## Task 5: Introduce Typed Final Answer Attempt Status

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Tests in `tests/test_final_answer_attempt.py` or `tests/test_agent_package_execution.py`

- [ ] Add a local enum or literal alias for `FinalAnswerAttemptStatus`:
  - `admitted`
  - `policy_denied`
  - `schema_failed`
  - `safety_failed`
  - `citation_binding_failed`
  - `final_answer_adequacy_failed`
  - `validation_failed`
  - `model_error`
- [ ] Add status to the normalized/candidate attempt value.
- [ ] Replace direct validator-name-to-outcome logic in `admit()` with status-to-result mapping.
- [ ] Keep existing diagnostic error code priority for validation diagnostics.
- [ ] Add focused tests for validator result tuples mapping to attempt status.
- [ ] Add tests proving `policy_denied` maps to `ReceiptOutcome.POLICY_DENIED`.
- [ ] Add tests proving validation statuses map to safe fail-closed output with diagnostics.

**Plain-language explanation:** The module should first say what happened to the candidate, then map that status to the public run outcome. That avoids blending validation, policy, and output wording into one conditional.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_final_answer_attempt.py -v
```

---

## Task 6: Build Deterministic Repair Eligibility

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Tests in `tests/test_final_answer_attempt.py`

- [ ] Add a helper such as `_repair_eligibility(candidate, allowed_citation_refs, attempts_used)`.
- [ ] Return eligible for `schema_failed`.
- [ ] Return eligible for `citation_binding_failed` only when allowed citation refs exist.
- [ ] Return eligible for `final_answer_adequacy_failed` only when safety did not fail.
- [ ] Return ineligible for `safety_failed`.
- [ ] Return ineligible for `policy_denied`.
- [ ] Return ineligible when no accepted evidence exists.
- [ ] Return ineligible when retry budget is exhausted.
- [ ] Add table-driven tests for every eligibility case.

**Plain-language explanation:** Repair should fix model-output drift, not governance failures. This helper is the hard line that prevents "retry" from becoming "try to bypass the harness".

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_final_answer_attempt.py -k repair_eligibility -v
```

---

## Task 7: Create The Final Answer Repair Request

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Reuse `proof_agent/control/workflow/harness_helpers.py` helpers when useful
- Tests in `tests/test_final_answer_attempt.py`

- [ ] Build a repair request with the same provider/model and final-answer function schema.
- [ ] Include the original question.
- [ ] Include the same accepted evidence text and allowed citation refs.
- [ ] Include admitted conversation context summary only when admitted, labeled non-evidence.
- [ ] Include stable validation error code, violation codes, field paths, and violation count.
- [ ] Include `previous_response_json` only when prior content parses.
- [ ] Include `previous_response_parse_error_code` when prior content does not parse.
- [ ] Exclude free-form validator reason.
- [ ] Exclude provider envelope and stack traces.
- [ ] Exclude previous content from safety-failed candidates by making safety failures ineligible before request construction.
- [ ] Add tests that inspect the repair request JSON payload.
- [ ] Add tests proving forbidden fields are absent.

**Plain-language explanation:** The repair request tells the model exactly what shape to fix and which citations are allowed. It does not hand the model unsafe debug detail or permission to invent missing facts.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_final_answer_attempt.py -k repair_request -v
```

---

## Task 8: Execute One Repair Retry On Eligible Failure

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Tests in `tests/test_agent_package_execution.py` or `tests/test_final_answer_attempt.py`

- [ ] Replace the no-op `repair()` with one bounded retry when eligibility allows it.
- [ ] Ensure repair generation calls the same `BEFORE_MODEL_CALL` policy gate.
- [ ] Emit a separate policy decision for repair.
- [ ] Emit separate `model_request` and `model_response` events for repair with metadata such as `repair_attempt=1`.
- [ ] Capture both LLM interactions in `stage_llm_interactions`.
- [ ] Re-run `validate_model_output()` on the repair response.
- [ ] If repair succeeds, return `ANSWERED_WITH_CITATIONS` and no `stage_failure_diagnostics`.
- [ ] Keep the initial `final_answer_validation_failed` trace event for audit history.
- [ ] Add a test where first model response is schema-invalid and repair response is valid.
- [ ] Assert two model calls, two LLM interactions, final answered outcome, and empty diagnostics.
- [ ] Assert trace contains the first validation failure event.

**Plain-language explanation:** This is the happy repair path. The operator can later see that the first candidate failed, but the governed run result is successful because the stage repaired itself before final admission.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_package_execution.py -k "repair and answered" -v
```

---

## Task 9: Preserve Fail-Closed Behavior For Non-Repairable Failures

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Tests in `tests/test_agent_package_execution.py` or `tests/test_final_answer_attempt.py`

- [ ] Add a safety failure test proving only one model call occurs.
- [ ] Assert safety failure returns a final diagnostic with `safety_failed`.
- [ ] Add a citation failure test with no allowed citation refs proving no repair occurs.
- [ ] Add an exhausted retry test where first and repair responses both fail.
- [ ] Assert final diagnostics describe the final unrepaired stop.
- [ ] Assert both LLM interactions are captured when repair was attempted.
- [ ] Assert only the final unrepaired stop enters `stage_failure_diagnostics`.

**Plain-language explanation:** Repair is bounded and conservative. If the failure is safety-related or cannot be repaired from allowed evidence and citations, the system still fails closed.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_package_execution.py -k "repair and failed" -v
```

---

## Task 10: Handle Repair Policy Denial Correctly

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Tests in `tests/test_final_answer_attempt.py` or `tests/test_agent_package_execution.py`

- [ ] Add a test where the initial model call is allowed, validation fails, and the repair model call is denied by `BEFORE_MODEL_CALL`.
- [ ] Assert final outcome is `ReceiptOutcome.POLICY_DENIED`.
- [ ] Assert the denial is not reported as `final_answer_validation_failed`.
- [ ] Assert `stage_failure_diagnostics` is empty unless the existing policy-denial semantics elsewhere require a separate governed projection.
- [ ] Assert trace contains a repair policy decision with blocked status.

**Plain-language explanation:** Policy denial is a governed decision, not a model-output validation failure. The repair attempt does not get to bypass the same model-call policy used by the original attempt.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_final_answer_attempt.py -k policy_denied -v
```

---

## Task 11: Update Validation Capture And Trace Expectations

**Files:**

- Modify tests only unless implementation reveals a projection gap
- Tests in `tests/test_agent_configuration_api.py`, `tests/test_agent_package_execution.py`, `tests/test_trace_model_events.py`

- [ ] Add or update a full validation capture test for repair success:
  - `llm_interactions` includes both initial and repair interactions.
  - `failure_diagnostics` is empty.
- [ ] Add or update a full validation capture test for final unrepaired failure:
  - `failure_diagnostics` includes the final diagnostic.
  - `llm_interactions` includes all attempted model calls.
- [ ] Assert ordinary trace model events remain summary-only.
- [ ] Assert `final_answer_validation_failed` payload remains trace-safe.

**Plain-language explanation:** Sensitive validation capture can show model inputs and outputs for debugging, but ordinary trace must stay safe and bounded. A repaired success should look successful in failure diagnostics while still being explainable in interaction history.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py tests/test_agent_package_execution.py tests/test_trace_model_events.py -k "validation_capture or final_answer_validation_failed or repair" -v
```

---

## Task 12: Run The Focused Quality Gate

**Files:** no code edits expected

- [ ] Run focused tests:

```bash
uv run --extra dev python -m pytest \
  tests/test_react_intent_resolution.py \
  tests/test_react_planner.py \
  tests/test_controlled_react_orchestrator.py \
  tests/test_agent_package_execution.py \
  tests/test_agent_configuration_api.py \
  tests/test_trace_model_events.py \
  tests/test_model_contracts.py \
  -v
```

- [ ] Run Ruff:

```bash
uv run --extra dev ruff check proof_agent tests
```

- [ ] Run mypy at least on changed Python files:

```bash
uv run --extra dev --extra openai mypy \
  proof_agent/contracts/controlled_react.py \
  proof_agent/control/workflow/controlled_react/final_answer_attempt.py \
  proof_agent/control/workflow/controlled_react/orchestrator.py \
  proof_agent/control/workflow/controlled_react/composition.py \
  proof_agent/capabilities/react/intent.py \
  proof_agent/capabilities/react/planner.py
```

- [ ] Run domain docs checks:

```bash
python3 scripts/check-domain-contexts.py
git diff --check
```

---

## Expected End State

When a follow-up question reaches Controlled ReAct V3:

1. Delivery admits prior turns into `ContextAdmission`.
2. The start request carries that context into Orchestrator state.
3. Intent resolution and planning receive typed non-evidence context.
4. Retrieval and tool observations still produce accepted evidence through normal governed paths.
5. Final answer generation receives accepted evidence plus non-evidence follow-up context.
6. Final answer validation can trigger one bounded repair retry.
7. Repair retry is policy-gated, traced, validated, and captured like the original model call.
8. Successful repair returns an answered outcome without failure diagnostics.
9. Unrepairable or exhausted failures fail closed with stable diagnostics.

**Plain-language explanation:** The system can now understand follow-up wording earlier, answer from the right evidence, and repair common final-output contract drift without hiding governance facts or inventing evidence.
