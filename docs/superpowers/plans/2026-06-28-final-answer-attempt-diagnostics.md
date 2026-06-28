# Final Answer Attempt Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:test-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Controlled ReAct V3 final-answer failure mode that turns model-answer validation failures into opaque `REFUSED_NO_EVIDENCE` results by introducing a deeper Final Answer Attempt module and by promoting final-answer validation diagnostics into ordinary trace-safe workflow facts.

**Architecture:** Add a Controlled ReAct-local `FinalAnswerAttemptRunner` that owns the final-answer attempt lifecycle: prepare, generate, normalize, validate/diagnose, reserve repair status, and admit/map the attempt. Keep `ReceiptOutcome` as the terminal governed run outcome, and carry attempt-owned diagnostics through `AnswerSynthesisResult.stage_failure_diagnostics` into `WorkflowTemplateExecutionResult`, trace, validation capture, and Dashboard projections.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, Controlled ReAct V3, `AnswerSynthesisPort`, `AnswerEvidenceContext`, `PolicyEngine`, JSONL trace, validation capture v2, pytest, Ruff, mypy.

---

## Problems This Plan Solves

### Problem 1: Shallow Final-Answer Adapter

The current V3 `_ModelAnswerSynthesisAdapter.synthesize()` mixes evidence extraction, model request construction, policy evaluation, model invocation, validation, LLM interaction capture, and terminal outcome mapping in one method.

**Plain-language explanation:** This is like one person receiving evidence, calling the model, checking the answer, deciding whether to reject it, and writing the incident report all in one breath. When something fails, the system knows only that "answering failed," not which part failed.

This plan introduces a deeper module:

```text
Final Answer Attempt
prepare -> generate -> normalize -> validate/diagnose -> repair reserved -> admit/map
```

The first implementation reserves the repair step as typed status only. It does not make an automatic second model call.

### Problem 2: Missing Trace-Safe Validation Diagnostics

`validate_model_output()` already distinguishes schema, safety, citation, and adequacy failures, but V3 final-answer failures currently collapse into the generic message `I cannot answer because the model output failed validation.`

**Plain-language explanation:** The validator already knows which gate failed. The system is throwing away the inspection sheet before the operator can read it.

This plan carries validator failures as ordinary trace-safe facts:

- `AnswerSynthesisResult.stage_failure_diagnostics`
- `WorkflowTemplateExecutionResult.stage_failure_diagnostics`
- `final_answer_validation_failed` trace event
- `validation_capture.v2.failure_diagnostics`

---

## Decisions Already Recorded

- Domain term added: `Final Answer Attempt` in `docs/domain/workflow-control/CONTEXT.md`.
- Domain term added: `Final Answer Validation Failed Event` in `docs/domain/observability/CONTEXT.md`.
- ADR added: `docs/adr/0096-final-answer-attempt-boundary.md`.
- ADR added: `docs/adr/0097-final-answer-validation-failed-trace-event.md`.
- First implementation is Controlled ReAct V3-local: `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`.
- First implementation records repair eligibility and repair-not-attempted status but does not perform automatic repair retry.
- Diagnostics expose stable codes, counts, stage identity, role, contract name, validator names, violation codes, and content length only.
- Diagnostics must not expose raw model output, rejected field values, raw evidence, raw provider responses, secrets, stack traces, or chain-of-thought.

---

## Non-Goals

- Do not implement automatic repair retry in this slice.
- Do not change retrieval, evidence admission, or citation source authority.
- Do not make final-answer diagnostics a Delivery-layer trace reconstruction feature.
- Do not introduce raw prompt, raw context, raw evidence, or raw model output into ordinary trace.
- Do not broaden this module to all Workflow Templates before V3 behavior is stable.
- Do not modify `docs/zh/`.

---

## Target Behavior

When a V3 final-answer model response fails Harness validation:

1. The run still fails closed.
2. The customer-facing final output remains safe and generic.
3. Trace includes a `final_answer_validation_failed` event with stable diagnostic metadata.
4. `WorkflowTemplateExecutionResult.stage_failure_diagnostics` includes a `model_answer` diagnostic.
5. Full validation capture includes the same diagnostic in `failure_diagnostics`.
6. The failure can be distinguished as schema, safety, citation binding, adequacy, or generic final-answer validation failure.

**Plain-language explanation:** The user still does not see internal debug detail, but the operator can finally see which safety gate blocked the answer.

---

## Diagnostic Mapping

Primary `error_code` priority:

1. `schema_failed`
2. `safety_failed`
3. `citation_binding_failed`
4. `final_answer_adequacy_failed`
5. `final_answer_validation_failed`

Always preserve the complete validator and violation metadata:

- `validator_names`
- `violation_codes`
- `field_paths`
- `violation_count`

**Plain-language explanation:** If the answer is not valid JSON, say that first because later checks may be noisy. If the structure is valid but unsafe, say safety first. If safety is fine but citations do not bind, say citation binding. If citations bind but the answer is not good enough, say adequacy.

---

## File Map

### Contracts

- Modify `proof_agent/contracts/trace.py`
  - Add `TraceEventType.FINAL_ANSWER_VALIDATION_FAILED`.
- Modify `proof_agent/control/workflow/controlled_react/ports.py`
  - Add `stage_failure_diagnostics` to `AnswerSynthesisResult`.

### Controlled ReAct

- Create `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
  - Add `FinalAnswerAttemptRunner`.
  - Add helper functions for diagnostic mapping.
  - Add trace payload creation for `final_answer_validation_failed`.
- Modify `proof_agent/control/workflow/controlled_react/composition.py`
  - Make `_ModelAnswerSynthesisAdapter` delegate final-answer model work to `FinalAnswerAttemptRunner`.
- Modify `proof_agent/control/workflow/controlled_react/orchestrator.py`
  - Preserve answer-owned `stage_failure_diagnostics` when mapping to `WorkflowTemplateExecutionResult`.
  - Preserve diagnostics when `before_answer` denies an otherwise valid answer if applicable.

### Validation And Observability

- Reuse `proof_agent/control/workflow/harness_helpers.py`
  - Keep `validate_model_output()` as the validator source of truth.
  - Add helper extraction only if needed; avoid duplicating validator rules.
- Reuse `proof_agent/contracts/workflow_execution.py`
  - Keep `WorkflowStageFailureDiagnostic` as the diagnostic contract.
- Reuse `proof_agent/delivery/configuration_api.py`
  - Validation capture already projects `stage_failure_diagnostics`.

### Tests

- Modify `tests/test_agent_package_execution.py`
  - Assert V3 raw-evidence or inadequate final answer emits diagnostics and trace-safe failure event.
- Modify `tests/test_workflow_react_enterprise_qa.py` or add a V3-focused test
  - Assert `WorkflowTemplateExecutionResult.stage_failure_diagnostics` carries `model_answer`.
- Modify `tests/test_trace_model_events.py`
  - Assert `TraceEventType.FINAL_ANSWER_VALIDATION_FAILED` exists and trace payload is safe.
- Modify `tests/test_agent_configuration_api.py`
  - Assert full validation capture includes final-answer failure diagnostics.
- Modify `tests/test_model_output_validators.py` only if diagnostic helper tests need focused validator mapping coverage.

---

## Task 1: Add The Trace Event Contract

**Files:**

- Modify `proof_agent/contracts/trace.py`
- Test `tests/test_trace_model_events.py` or `tests/test_model_contracts.py`

- [ ] Add `FINAL_ANSWER_VALIDATION_FAILED = "final_answer_validation_failed"` to `TraceEventType`.
- [ ] Add a small contract test asserting the stable string value.

**Plain-language explanation:** First add the official event name to the trace vocabulary. This prevents later code from emitting an ad hoc string that the trace contract does not recognize.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_trace_model_events.py tests/test_model_contracts.py -v
```

---

## Task 2: Let AnswerSynthesisResult Carry Diagnostics

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/ports.py`
- Modify `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Test `tests/test_controlled_react_orchestrator.py`

- [ ] Import `WorkflowStageFailureDiagnostic` into `controlled_react/ports.py`.
- [ ] Add `stage_failure_diagnostics: tuple[WorkflowStageFailureDiagnostic, ...] = field(default_factory=tuple)` to `AnswerSynthesisResult`.
- [ ] Update `_workflow_result_from_answer()` to include `answer.stage_failure_diagnostics`.
- [ ] Update `_admit_final_answer()` to preserve diagnostics when policy blocks an answer.
- [ ] Add or update tests proving diagnostics survive answer-to-workflow-result mapping.

**Plain-language explanation:** The answer attempt should carry its own inspection sheet. The Orchestrator should pass that sheet forward, not recreate it later.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_controlled_react_orchestrator.py -v
```

---

## Task 3: Create FinalAnswerAttemptRunner

**Files:**

- Create `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Modify `proof_agent/control/workflow/controlled_react/composition.py`
- Test `tests/test_agent_package_execution.py`

- [ ] Move final-answer model request construction into `FinalAnswerAttemptRunner.prepare()`.
- [ ] Move `before_model_call` evaluation into the runner's generate path.
- [ ] Move model invocation and LLM interaction capture into the runner.
- [ ] Keep `_ModelAnswerSynthesisAdapter` as a thin adapter around the runner.
- [ ] Preserve current successful final-answer behavior exactly.
- [ ] Preserve no-evidence and tool-answer behavior outside the runner unless the code becomes cleaner by placing no-evidence attempt status inside it.

**Plain-language explanation:** This turns a long adapter method into a proper machine with named stages. The outside behavior should stay the same while the inside becomes easier to reason about.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_package_execution.py::test_execute_agent_package_run_projects_v3_complete_model_answer_chain -v
```

---

## Task 4: Map Validator Failures To Diagnostics

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Reuse `proof_agent/control/workflow/harness_helpers.py`
- Test `tests/test_agent_package_execution.py`

- [ ] Call `validate_model_output()` after model response capture.
- [ ] Collect failed `ValidationResult` values.
- [ ] Compute primary `error_code` using the agreed priority order.
- [ ] Build one `WorkflowStageFailureDiagnostic` for `stage_id="model_answer"`.
- [ ] Set `role="final_answer"`.
- [ ] Set `contract_name="FinalAnswerOutput"`.
- [ ] Set `raw_content_length=len(model_response.content)`.
- [ ] Populate bounded `violation_codes`, `field_paths`, and `violation_count` from validator metadata.
- [ ] Return blocked `AnswerSynthesisResult` with `stage_failure_diagnostics`.

**Plain-language explanation:** The validator's result becomes a stable diagnostic object. Operators get the reason code without getting unsafe payloads.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_package_execution.py::test_execute_agent_package_run_rejects_v3_raw_evidence_final_answer -v
```

---

## Task 5: Emit final_answer_validation_failed Trace Event

**Files:**

- Modify `proof_agent/control/workflow/controlled_react/final_answer_attempt.py`
- Test `tests/test_agent_package_execution.py`
- Test `tests/test_trace_model_events.py`

- [ ] Emit `TraceEventType.FINAL_ANSWER_VALIDATION_FAILED` when any final-answer validator fails.
- [ ] Use `status="blocked"`.
- [ ] Include only trace-safe payload keys:
  - `stage_id`
  - `role`
  - `error_code`
  - `validator_names`
  - `violation_codes`
  - `field_paths`
  - `violation_count`
  - `contract_name`
  - `raw_content_length`
- [ ] Attach the trace event id to the diagnostic's `related_event_id`.
- [ ] Assert raw model output and sentinel sensitive strings are absent from trace payloads.

**Plain-language explanation:** This is the ordinary run artifact that says where the final answer failed. It is useful enough for operators but still safe enough for normal trace retention.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_package_execution.py tests/test_trace_model_events.py -v
```

---

## Task 6: Ensure Validation Capture Shows The Same Diagnostics

**Files:**

- Likely no production code change in `proof_agent/delivery/configuration_api.py`
- Modify `tests/test_agent_configuration_api.py`

- [ ] Add or update a full-capture validation test using a provider response that fails final-answer validation.
- [ ] Assert `payload["failure_diagnostics"]` contains one `model_answer` diagnostic.
- [ ] Assert the diagnostic uses `event_type="final_answer_validation_failed"`.
- [ ] Assert the capture still includes `llm_interactions` only in the sensitive validation capture path.
- [ ] Assert ordinary run detail does not expose raw model output.

**Plain-language explanation:** Validation capture should show the same diagnosis as the workflow result. It should not invent a second version of the story.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py -k "validation_capture" -v
```

---

## Task 7: Preserve Current Outcome Semantics

**Files:**

- Modify tests where needed.

- [ ] Keep current customer-facing refusal message for failed validation in this slice.
- [ ] Keep `ReceiptOutcome.REFUSED_NO_EVIDENCE` for the terminal outcome unless a policy denial occurs.
- [ ] Record richer attempt diagnostics without changing customer-facing behavior.
- [ ] Do not add automatic repair retry.

**Plain-language explanation:** This slice improves diagnosis first. It should not surprise users by changing the final answer policy or adding extra model calls.

**Verification:**

```bash
uv run --extra dev python -m pytest tests/test_agent_package_execution.py tests/test_workflow_react_enterprise_qa.py -v
```

---

## Task 8: Final Quality Gates

Run the focused checks first, then the broader repo checks:

```bash
uv run --extra dev python -m pytest tests/test_agent_package_execution.py tests/test_controlled_react_orchestrator.py tests/test_agent_configuration_api.py tests/test_trace_model_events.py -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

**Plain-language explanation:** The first command checks the behavior we changed. Ruff and mypy catch style and type contract drift. The domain-context check protects the glossary changes. `git diff --check` catches whitespace problems before review.

---

## Expected Result For A run_2d2ffa2e-Like Failure

Before this plan:

```text
outcome: REFUSED_NO_EVIDENCE
final_output: I cannot answer because the model output failed validation.
diagnostic: not available in ordinary run artifacts
```

After this plan:

```text
outcome: REFUSED_NO_EVIDENCE
final_output: I cannot answer because the model output failed validation.
trace event: final_answer_validation_failed
stage_failure_diagnostics:
  stage_id: model_answer
  event_type: final_answer_validation_failed
  error_code: schema_failed | citation_binding_failed | final_answer_adequacy_failed | safety_failed
  role: final_answer
  contract_name: FinalAnswerOutput
  violation_codes: [...]
```

**Plain-language explanation:** The system still fails closed, but the operator can now see the actual blocked gate.
