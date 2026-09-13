# Adaptive Workflow implementation and verification

## Contract and status

[KNOWN | HIGH] Updated 2026-09-12. The user authorized implementation of
[the proposal](workflow-optimization-2026-09-12.md) with `按建议实施`, followed by `继续`.
The delivered increment is the proposal's first-stage Task-level cross-Run continuation,
with production persistence and the same V3 execution path. This is **PARTIAL_VERIFICATION
of the full proposal**, not a claim that every AC01–AC15 or all release Gates is closed.
No external-model replay, production deployment, publication, commit or push occurred.

Source baseline is HEAD `0d3009bd8d59bac2769e2b9d9212a480977c76ff` plus the user's existing
dirty Workflow UI/navigation/planner changes. Those changes are preserved. Authoritative
contract: [ADR-0255](../../adr/0255-compile-goal-driven-workflow-policies.md).
[Configuration and API guide](adaptive-workflow-configuration.md) describes actual behavior.

| Slice | Locally verified delivery | Remaining boundary |
|---|---|---|
| S1 Goal and acceptance | Strict Goal/Task contracts, owner/version/CAS, explicit criteria, verified proof binding, pause/cancel, cumulative budget | Goal revision conservatively invalidates all assessments; no selective reuse or 100-turn live-model proof |
| S2 Interaction | One policy at goal/plan/evidence/tool_input/finalization; typed fields, required-context protection, dedupe, bounded rounds, durable cross-Run answers | No nonblocking branch scheduler or same-Run local recomputation |
| S3 Assurance | Source identity/content dedupe, source metadata/date requirements, explicit applicability/conflict checks, fact validation, strict unassessed rejection | No calibrated correctness percentage, arbitrary semantic verifier or general rewrite/provenance independence detector |
| S4 Compiled paths | Same server compiler for preview/runtime; lite deterministic planner and optional memory bypass; bounded escalation; deep disables optional review fast path | Preview cannot predict unknown intent-dependent branches before execution |
| S5 Effort and budgets | OpenAI/DeepSeek wire payloads, capability rejection, all-role shared budgets, no hidden SDK retry, unknown-usage accounting | No real-model quality/cost/latency benchmark |
| S6 Durable HIL and UI | PostgreSQL Task/outbox/queue atomicity and fencing, retention/recovery, Task APIs, Chat and Dashboard | Cross-actor background outbox sweeper and same-Run HIL checkpoints are not implemented; `/resume` retries durable intents |

## Implementation and authority

- `contracts/workflow_policy.py`, `workflow_task.py`, `workflow_task_update.py` define strict
  policies, Goal revision, Task storage CAS, typed answers and internal executor updates.
  Model proposals and user answers never supply permission or Accepted Evidence.
- `control/workflow/execution_compiler.py`, `interaction.py`, `assurance.py`, `goal_control.py`
  and the existing `controlled_react/` implement the policies in V3. Required Task context
  is checked before any model/retrieval; required Goal queries cannot be removed by Planner.
  Tool input questions accept only the exact schema-bound USER_SUPPLIED fields.
- `execution_budget.py` wraps fresh per-invocation provider roles with one ledger. Model
  retries/repair, each physical retrieval binding and actual tool calls consume the same
  limit. Remaining active time is checked before work, before memory commit and at the
  final return. Task continuation restores cumulative usage once; unknown lost consumption
  blocks fresh retries. Waiting for human input does not consume active time.
- `capabilities/models/reasoning.py` and `openai_compatible.py` resolve requested/effective
  effort before transport. DeepSeek thinking uses supported automatic tool choice but still
  requires exactly the requested function. Default omitted effort retains legacy payloads.
  MockTransport validates real SDK serialization without sending external requests.
- `control/workflow/task_service.py`, `delivery/task_execution_service.py`,
  `delivery/workflow_task_api.py` and migration `0025_workflow_tasks` bind owner, exact Agent
  version, frozen snapshot digest, Run, goal revision, cumulative budget and resume intent.
  Production answer/outbox commit and Run publication are atomic. Result visibility and
  Task update share the fenced PostgreSQL transaction. Failure/reaper marks unknown debt.
  Production authority unavailable returns 503; SQLite is development-only.
- `observability/audit/task_redaction.py` projects private Task data across the actual
  TraceWriter and direct orchestration paths. Closed control reason codes remain visible;
  arbitrary model reasons, objective, user fields and typed answers are restricted.
  Five new event types are registered in the actual Trace enum. Real package execution tests
  verify the new events and absence of synthetic private markers from Trace/Receipt.
- Dashboard policy + stage edits save in a single revision-checked update. Read-only preview
  shares the compiler and preserves all ten nodes. Chat supports explicit Task creation,
  typed HIL, retries with the same idempotency key, pause/resume/cancel, goal revision and
  frozen-version task links. Expired questions renew through the guarded backend endpoint.

## RED/GREEN evidence

[KNOWN | HIGH] Behavior tests were added before their corresponding implementation.
Initial policy contract tests failed on missing/rejected fields, then passed after wiring
strict policies through manifest loading. Compiler, interaction, Goal, provider effort,
budget, Task persistence/API and UI tests were developed as bounded vertical slices.

Adversarial integration exposed and corrected the following regressions:

1. Lite could bypass an Intent ask; required missing context now precedes compiled retrieval.
2. Verified tool reports did not satisfy corresponding Goal criteria; acceptance now binds
   the already-verified tool proof, while explicit external-source requirements still block.
3. Tail/memory execution could exceed the active deadline; both paths now return incomplete.
4. Task trace content and new event types were not fully covered by mock emitters; a real
   package Run now proves redaction and TraceWriter enum acceptance.
5. Compiled plans were missing after tool checkpoint restoration; the plan is resolved on restore.
6. Assurance behavior drifted after serialization; policy requirements use values, not fields-set.
7. Pause/expired-question UI resumed by directly changing phase; two RED component tests now
   pass through the backend resume endpoint. Expired old answers remain rejected.
8. Blanket reason redaction hid budget/skip codes; a RED adversarial test now passes with a
   closed code allowlist, while free-text reasons remain restricted.
9. Different source IDs could count identical republished content twice; a RED source test
   now passes after conservative source/content component deduplication.

Late targeted verification: Task API + adversarial + actual package execution: **21 passed**;
assurance + adversarial after source deduplication: **19 passed**. These are included in the
final full backend suite below.

## Final local verification

[KNOWN | HIGH] Final source verification on 2026-09-12:

| Check | Result |
|---|---|
| Backend, isolated real PostgreSQL and loopback enabled | **3044 passed, 7 skipped, 2 deselected**, 99.19 seconds |
| Dashboard | **266 passed**, 40 files |
| Operator Chat | **57 passed**, 19 files |
| Frontend typecheck | Passed for all workspaces |
| Frontend production builds | Passed UI package, Dashboard and Chat |
| Ruff | All checks passed |
| Mypy | No issues in 415 source files |
| `uv lock --check --offline` | Resolved 114 packages, consistent lock |
| Domain context checker and `git diff --check` | Passed |
| Published example + documented policy YAML through real manifest loader | Loaded standard/adaptive/grounded successfully |

Reproduction commands (use an isolated PostgreSQL database; no external-model invocation):

```bash
PROOF_AGENT_TEST_POSTGRES_DSN=<isolated-postgres-dsn> \
PROOF_AGENT_REQUIRE_POSTGRES_TESTS=1 .venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check proof_agent tests
.venv/bin/mypy proof_agent
uv lock --check --offline
npm run typecheck
npm test
npm run build
python3 scripts/check-domain-contexts.py
git diff --check
```

The final PostgreSQL instance was a temporary `postgres:17-alpine` container bound only to
127.0.0.1:55439, separate from the running project services. Earlier sandbox-only loopback
failures were rerun with loopback access; they are not counted as product defects or passes.
The macOS sandbox caused `uv` system-configuration initialization to panic; the same offline
lock check passed outside that sandbox. Backend warnings are the existing Authlib deprecation
and FrozenDict `params` serializer warning. Builds retain the existing >500 kB chunk warning.

Final run logs were captured at `/tmp/proofagent-adaptive-final-backend-v2.log`,
`/tmp/proofagent-adaptive-final-chat.log`, `/tmp/proofagent-adaptive-final-types.log`,
`/tmp/proofagent-adaptive-final-build.log`. Counts above are recorded here for durable evidence.

## Rendered browser evidence

[KNOWN | HIGH] Dashboard was inspected against a local Draft at desktop and 390 px.
Lite + strict preview retained ten nodes and exposed deterministic planner/memory bypass;
preview did not mutate Draft revision 34. Unsaved test edits were discarded.

Operator Chat was inspected using the actual production build with a **synthetic local HTTP
fixture**, separate from backend integration tests. The rendered path covered explicit Task
creation, two acceptance items, missing text/boolean/integer input, pause/resume, injected
HTTP 503 on first answer, retained values, successful retry, completed acceptance, read-only
answered fields, and reopening the frozen-version Task URL. Server capture confirmed the
answers contained `false` as boolean and `35` as integer, and both retries used the same
idempotency key. No model or real business answer was used for this UI check.

At 390 px both document and Task panel had `clientWidth == scrollWidth == 390`; desktop and
mobile screenshots were visually reviewed. Evidence images are under `evidence/adaptive-workflow/`.
These fixtures prove rendered state and request behavior, not deployment or business correctness.
The temporary browser space, local fixture server and isolated PostgreSQL container were
closed after verification; existing project services were not stopped.

## Acceptance still open

[KNOWN | HIGH] Full proposal acceptance is not complete. Specifically:

- **AC02 partial:** durable Goal/source identity and revision checks are covered. Goal edits
  currently clear every assessment and require fresh proof; selective invalidation and the
  proposed 100-turn scenario have not been delivered/verified.
- **AC06 open:** there is no scheduler to keep independent branches running while a nonblocking
  question waits, or to resume only affected nodes within the same Run. The current implementation
  deliberately waits at Task level and starts a newly bound Run after input.
- **AC09 bounded:** strict single-source and identical-content dedupe are tested. General
  authority-category qualification, rewritten republication detection and independent-source
  provenance require additional admitted metadata and validators.
- **AC14 bounded:** compiler/configuration digest and frozen Agent version are implemented;
  preview is pre-intent and may resolve additional conditional stages or escalation at runtime.
  It does not claim a precomputed general dependency DAG.
- **S6 evaluation:** deterministic/mocked transport and real PostgreSQL behavior are verified.
  Paired quality, unnecessary-question rate, task completion, token/cost and p50/p95 comparisons
  across real-model profiles require a fixed business holdout and authorized external-model data.
- Same-Run checkpoints, generalized local recomputation and an automatic cross-actor resume
  sweeper remain future implementation, not properties inferred from the durable outbox.
- All existing external Knowledge, model, identity, artifact-store, deployment and release Gates
  remain independent. Local green results do not establish Production GO.
