# Intent failure capture and answer-repair diagnostics

Date: 2026-09-10. Design: [ADR-0254](../../adr/0254-preserve-model-contract-failure-diagnostics.md).

[KNOWN | HIGH] `LOCAL_VERIFIED` for deterministic local behavior. Initial local verification did not call DeepSeek; the explicitly authorized replay
below now verifies one real-model execution. No publication or commit.

## Evidence and root cause

- `runs/dify-verification/history/run_36c2900a/trace.jsonl`: nine events, two successful
  model responses of 1940 characters, then no terminal event. The API reported
  `Model output did not match IntentResolutionResult.` No capture was persisted.
- Resolver retries normalization once; the invocation adapter previously copied
  interactions only after successful return. The orchestrator did not catch intent
  contract failure, so execution never reached validation capture/finalization.
- `run_964c1d47`: required queries completed; nine statements failed subject-bound
  numeric matching, followed by `invalid_source_selection`. No captured model JSON
  exists to determine the exact invalid selection or whether facts were false
  positives. This change does not speculate or weaken the fact checker.

## RED → GREEN

1. API regression using a deterministic provider returning invalid nested intent
   twice: capture both disabled/enabled reproduced HTTP 400 with the user's exact
   error. Both now return a persisted `FAILED_WITH_TRACE` run, blocked intent stage,
   safe field diagnostics, and two opt-in capture interactions. No planner/retrieval
   starts and no model JSON enters ordinary trace.
2. Two relationship-error tests initially found generic `value_error`; now distinct
   duplicate/unknown-field codes and actionable repair guidance retain strict checks.
3. Five invalid source-selection cases initially reported generic failure/missing
   evidence; now each has a safe specific diagnostic and `FAILED_WITH_TRACE`.
4. Existing negative tests now assert the corrected failure outcome while retaining
   no-wrong-answer, bounded call count, policy denial, safety and conflict assertions.

## Verification

- `.venv/bin/python -m pytest tests/ -q` with local socket permission:
  **2769 passed, 92 skipped, 2 deselected**, 36.12 seconds. Existing Authlib and
  FrozenDict serializer warnings remain visible.
- Ruff and Mypy: passed (398 source files).
- API integration validates the real resolver, invocation adapter, orchestrator,
  local run persistence, trace endpoint and sensitive capture endpoint together.
- No frontend change: both surfaces already recognize `FAILED_WITH_TRACE`.

## Review and limits

Main-agent self-review: kept capture opt-in, avoided raw provider output in trace,
retained one repair and all evidence gates, guarded the catch by intent role, and
preserved unrelated worktree changes. No independent agent review.

The original 400's exact invalid field cannot be recovered from its length-only
trace. Future identical failures now retain diagnostics and optional interactions.
Prompt improvements are not a guarantee of model compliance. Provider endpoint and
strict-mode compatibility remain unchanged. See the subsequent authorized replay below.


## Authorized real-model replay — 2026-09-11

[KNOWN | HIGH] After explicit user authorization, validated the original question
`平安集团的2026 年业绩怎么样？` through the existing local validation API using
`agent_management_insurance_specialist` / `draft_a701d51c`, observed revision 32,
with `full_capture=true` and `retain_for_audit=false`.

- Run: `run_284f92e5`; outcome: `ANSWERED_WITH_CITATIONS`; error_code: null.
- Capture: `vcap_1e213a938c7b`; both the API response and capture retrieval succeeded.
- Intent resolved on its first model response, with no remaining missing fields.
- Initial answer failed fact validation on 12 statements (numeric/explicit assertion
  subject matches). Its opening sentence mixed reporting-period facts with evidence
  coverage commentary. This is not proof that all rejected numbers were incorrect.
- The single repair selected exactly 16 distinct known IDs (`s1`–`s16`). Server-rendered
  source statements passed final validation. No gate or contract was relaxed.
- The final text describes retrieved 2026 Q1 performance. This replay establishes
  execution and source-bound repair, not source authenticity, latest-period coverage,
  exhaustive metric coverage or a general model success rate. Selection is bounded
  and can deliver less detail than the initial proposed answer.
- Ordinary trace retains the initial validation failure even though the successful
  capture's terminal `failure_diagnostics` list is empty. Capture contains both answer
  interactions, allowing the repair to be audited.

Evidence: `runs/dify-verification/history/run_284f92e5/trace.jsonl`, `run_meta.json`,
and the existing authorized `/api/runs/run_284f92e5/validation-capture` endpoint.
Sensitive capture content is not copied into this report. No additional code change
was necessary during this replay; prior local test results remain applicable.

## Scoped commit verification — 2026-09-11

Exported the Git index into an isolated temporary checkout and confirmed Python
imports resolved to that checkout. Ran clarification, intent, answer-fact,
configuration API/workspace and orchestrator tests against the staged scope:
**350 passed, 2 skipped** (5.18 seconds). This excludes unrelated uncommitted
Workflow UI, navigation and planner-pending-context changes. Staged whitespace,
Ruff and domain-context checks also passed. Earlier full-worktree test results
above remain labeled as such; this check verifies the narrower commit boundary.
