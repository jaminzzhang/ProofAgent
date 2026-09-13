# Task-to-answer workflow implementation evidence

[KNOWN | HIGH] Plan v1 T1–T6 was explicitly confirmed by user “同意” on 2026-09-13.
Plan: `task-answer-workflow-plan-2026-09-13.md`; decision: ADR-0258.
Existing unrelated working-tree edits were preserved. No commit/push or production restart.

## Scope and status

**LOCAL_VERIFIED** for the implemented bounded workflow and its synthetic/local paths.
**PARTIAL_VERIFICATION** for real-model quality, general semantic reasoning and operational
readiness. This is an integrated V3 change, not a universal reasoning engine. The initial
domain profile supports explicit insurance-performance business comparisons; unsupported
semantics/constraints remain unassessed. No financial source authenticity/latestness claim.

| Task | Implementation and acceptance evidence |
|---|---|
| T1 | User-clause requirement contract, control-owned intent normalization, same clause IDs in planner and answer requests, preserved Task constraints during repair. Generic clauses retain literal user text and remain unassessed when no semantic verifier applies. |
| T2 | Business facts bind to explicit source subjects or unambiguous same-chunk paragraph/heading context. Rejected chunks, conflicting contexts and retrieval order cannot supply subjects. Query completion and analysis gaps are exposed separately; original evidence admission and provenance checks remain. |
| T3 | Source-bound renderer groups improvement/pressure/mixed assessments by business; available directions per represented business must survive selection. Exact reproduction gates derived prose; numeric facts still use ordinary checks. Raw metrics, decorative headings, altered values/periods and unsupported rankings fail. |
| T4 | Model may request known requirement IDs as evidence gaps. Answer port carries typed recovery IDs; orchestrator generates bounded queries through the existing governed retrieval path. Repeated gaps, round budgets and policy denial bound recovery. Expression/schema failures keep finite answer repair. Prior answer diagnostics and model interactions survive successful evidence recovery. |
| T5 | Stage descriptor and actual Dashboard flow expose retrieval/answer feedback. Stage result separately reports requirement verification. Supported Task creation/revision adds a required grounded-analysis criterion, reserved ID protection and fresh revision binding; arbitrary extra criteria cannot inherit a profile pass. UI explains the narrower meaning of source support. |
| T6 | 21 new task-answer regressions, updated prior table/comparison tests, descriptor/UI regressions, fixed 8-case evaluator, original evidence probe and historical-flat-answer rejection. Full backend/frontend checks and an actual rendered component inspection completed. |

## RED → GREEN and review findings

Initial RED: flat metrics passed adequacy; headings also passed; answer request had no
subquestion requirements (3 failed). Subsequent assertion failures covered unnecessary
answer retry for evidence gaps, absent orchestration recovery, year-report fragment,
unknown semantic Task accidentally passing, lost repair constraints, rejected-source
subject inheritance, conflicting heading/paragraph binding, missing compiled Task criterion
and a reserved criterion silently replacing user acceptance. Each was corrected and
regressed. A temporary wrong test import and preview CSS import were setup errors, not RED
behavior evidence; both corrected before their checks.

Self-review only; no independent agent or external model review claimed. The earlier
flat-table tests were updated to require grounded grouping for analytical questions,
while retaining numeric tampering assertions. No failing test was deleted or skipped.

## Final checks

| Command / evidence | Result |
|---|---|
| `.venv/bin/python -m pytest tests/ -q` with loopback permission | **3020 passed, 102 skipped, 2 deselected**, 39.32s; existing Authlib/FrozenDict warnings |
| Additional composed Agentset/intent/planner/answer path, normal and gap-once recovery | **2 passed** after the full suite; runtime unchanged; verifies 2→3 governed HTTP calls and 1→2 answer calls |
| `npm test` | Dashboard **269 passed**, Operator Chat **57 passed** |
| `npm run build` | All UI workspaces built, including TypeScript project checks; existing bundle-size warnings |
| `npm run typecheck` | Passed (root script checks workspaces defining this script; full UI type checks also ran in build) |
| `.venv/bin/python -m ruff check proof_agent tests scripts/evaluate-task-answer-contracts.py` | Passed |
| `.venv/bin/python -m mypy proof_agent` | Passed, **422 source files** |
| `python3 scripts/check-domain-contexts.py`, `git diff --check` | Passed |
| `PYTHONPATH=. .venv/bin/python scripts/evaluate-task-answer-contracts.py` | **8/8** fixed synthetic development cases match expectations; zero model calls |
| `.venv/bin/python docs/research/run-1fbcbc32-offline-probe.py` | ANSWERED_WITH_CITATIONS, 8 selected statements, 4 unique evidence chunks, one deterministic model-boundary call; request 10387 characters |
| `PYTHONPATH=. .venv/bin/python docs/research/run-28973387-adequacy-probe.py` | Historical raw metrics now fail adequacy; the red-capable assertion now passes |

All test counts include the current workspace, including pre-existing work, not only this
change. Evidence object hashes are in `task-answer-verification-fingerprints-2026-09-13.json`.
Fixed evaluator results: `task-answer-evaluation-2026-09-13.json`.
Example actual current answer: `task-answer-offline-example-2026-09-13.md`.

## Rendered verification

Used ego-browser to inspect the actual WorkflowConfigurationFlow/workflowPresentation
components in an isolated local Vite fixture on loopback 5179, including the complete
10-node inventory and visible evidence-gap/answer-repair feedback. Screenshot:
`workflow-answer-recovery-2026-09-13.png`. This was rendered-component verification,
not a signed-in production end-to-end run. Frontend tests cover editor behavior and
Task display/reconnect. Temporary preview files were removed and the owned Vite process
stopped; existing gateway/Agent services were not restarted.

## Remaining verification and limits

- Real DeepSeek selection/recovery stability and actual provider retrieval gains are
  unmeasured. Captured-evidence probes use deterministic selection, not a real model.
- The eight development cases are not an independent holdout. Independently curated
  business answers and unseen real tasks remain necessary before claiming general quality.
  No synthetic pass ratio is presented as an answer accuracy probability.
- Semantic analysis is currently a bounded insurance-performance profile with limited
  metric directions. General causal analysis, cross-business ranking, unknown metrics,
  arbitrary user constraints and proof of latest/comprehensive source coverage are not
  implemented as automatic pass criteria. Such Task requirements remain unassessed.
- Clause splitting preserves explicit clauses; it does not prove that all implicit intents
  have been understood. A whole-answer source-support pass retains its narrower meaning.
- Budget exhaustion still returns a truthful incomplete/failure outcome. This change does
  not introduce a new universally composable partial-answer public outcome.
- External-model diagnostic replay requires explicit authorization; none was invoked.
  Source-provider publication, production migration/release gates and deployment were not run.
