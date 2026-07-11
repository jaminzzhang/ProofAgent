# Proof Agent S4 Run Queue and Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Replace synchronous API-owned execution with a bounded PostgreSQL queue and same-image Run Executor process role that delivers fast admission, fair execution, safe cancellation, fenced ownership, and reconnectable coarse progress.

**Architecture:** [FRAME | HIGH] The API validates and atomically persists `QUEUED`, then returns `202`. An active-slot Executor claims with PostgreSQL row locks, leases, claim tokens, Attempt number, and fencing epoch; it freezes the execution snapshot and performs governed execution/finalization. Durable state stays in PostgreSQL; trace-safe fine detail uses best-effort PostgreSQL notification and is not replayed.

**Tech Stack:** [FRAME | HIGH] FastAPI, Server-Sent Events, PostgreSQL `FOR UPDATE SKIP LOCKED` and `LISTEN/NOTIFY`, psycopg/SQLAlchemy adapters, Typer, React 19, pytest concurrency tests.

---

## Prerequisites and Exit Contract

- [ ] [FRAME | HIGH] Begin only after S1, S2, and S3 are merged and green.
- [ ] [KNOWN | HIGH] Read the workflow-control, observability, app-surface, and identity/security contexts routed by `CONTEXT-MAP.md`.
- [ ] [FRAME | HIGH] Use one Run Executor process role inside Proof Agent and the same product image as API; do not add Redis, RabbitMQ, Celery, or a separately deployed Run Worker service.
- [ ] [FRAME | HIGH] Exit only when all 5/50/idempotency/fairness/cancel/lease/fencing/result-visibility/reconnect invariants pass under real PostgreSQL concurrency.

## Task 1: Define Run Lifecycle and Execution-Snapshot Contracts

**Files:**

- Create: `proof_agent/contracts/run_execution.py`
- Modify: `proof_agent/contracts/run.py`
- Modify: `proof_agent/contracts/dashboard.py`
- Modify: `proof_agent/contracts/conversation.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_run_execution_contracts.py`

- [ ] [FRAME | HIGH] Write red tests for the exact durable state enum and every allowed/forbidden transition.
- [ ] [FRAME | HIGH] Implement states `QUEUED`, `RUNNING`, `FINALIZING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCEL_REQUESTED`, and `CANCELLED` with this transition authority:

```text
QUEUED -> RUNNING | CANCELLED
RUNNING -> FINALIZING | CANCEL_REQUESTED | FAILED | TIMED_OUT
FINALIZING -> SUCCEEDED | CANCEL_REQUESTED | FAILED | TIMED_OUT
CANCEL_REQUESTED -> CANCELLED | FAILED | TIMED_OUT
terminal -> no transition
```

- [ ] [FRAME | HIGH] Define `RunRequest`, `RunAttempt`, `RunExecutionSnapshot`, `RunClaim`, `RoleActivation`, `RunProgress`, `RunResultAvailability`, and stable failure-code DTOs with contract version `proofagent.run-execution.v1`.
- [ ] [FRAME | HIGH] Freeze release/image/contract/Agent/Knowledge/model/egress/Secret Handle/tool/permission configuration digests into the Attempt snapshot; later config edits cannot affect it.
- [ ] [FRAME | HIGH] Keep governed outcome separate from transport state. A terminal infrastructure failure may have `result_available=false`; any audience result requires the S3 manifest binding.
- [ ] [FRAME | HIGH] Commit with message `Define production run lifecycle contracts`.

## Task 2: Add Queue, Attempt, Lease, and Activation Schema

**Files:**

- Create: `proof_agent/capabilities/persistence/postgres/migrations/versions/0004_run_queue.py`
- Create: `proof_agent/contracts/ports/run_queue.py`
- Create: `proof_agent/capabilities/persistence/postgres/run_queue_repository.py`
- Create: `tests/test_postgres_run_queue.py`

- [ ] [FRAME | HIGH] Add schema for request idempotency/digest, queue timestamps, Attempt state/version, claim token, lease/heartbeat, deadline, snapshot JSON+digest, result availability, terminal code, and role activation slot/epoch.
- [ ] [FRAME | HIGH] Use a unique `(operator_subject, idempotency_key)` constraint. Same key + same canonical request digest returns the existing Run; same key + different digest returns conflict without mutation.
- [ ] [FRAME | HIGH] Enforce no more than five claimed nonterminal Attempts across `RUNNING`, `FINALIZING`, and `CANCEL_REQUESTED`; `CANCEL_REQUESTED` retains its slot until terminal.
- [ ] [FRAME | HIGH] Enforce at most 50 `QUEUED` requests in the admission transaction. Request 51 returns overload with no partial Run.
- [ ] [FRAME | HIGH] Implement per-operator fair claim as one transaction: choose only each operator's oldest eligible head, order operators by least-recent successful claim then head enqueue time, lock one row with `SKIP LOCKED`, and update fairness/Attempt state atomically.
- [ ] [FRAME | HIGH] Write real concurrent transaction tests for capacity, double claim, fairness, activation epoch, and conditional terminal commit.
- [ ] [FRAME | HIGH] Commit with message `Add bounded fair PostgreSQL run queue`.

## Task 3: Make Submission Fast, Idempotent, and Permission-Bound

**Files:**

- Create: `proof_agent/delivery/run_submission_service.py`
- Modify: `proof_agent/delivery/api.py`
- Modify: `proof_agent/observability/api/dependencies.py`
- Create: `tests/test_run_submission_service.py`
- Rewrite: `tests/test_run_execution_api.py`

- [ ] [FRAME | HIGH] Fix API contracts:

```text
POST /api/runs                     -> 202 {run_id,state:"QUEUED",progress_url}
GET  /api/runs/{run_id}            -> durable projection
GET  /api/runs/{run_id}/progress   -> SSE
POST /api/runs/{run_id}/cancel     -> 202 or current terminal projection
```

- [ ] [FRAME | HIGH] Write red tests for `run.submit`, sole-Agent/version validation, CSRF, idempotent repeat, conflicting repeat, 50-queue overload `429` + `Retry-After`, and no row on rejection.
- [ ] [FRAME | HIGH] Canonicalize and digest the request, validate only the Published sole Agent boundary, atomically admit, and return without loading Knowledge/model or executing the Agent.
- [ ] [FRAME | HIGH] Record accept latency and overload metrics. Candidate Gate target is P95 at most 500 ms for 20 online operators.
- [ ] [FRAME | HIGH] Remove synchronous execution from API request handling; delete or reduce `proof_agent/delivery/run_execution_service.py` to a compatibility-free migration shim, then remove it once callers are gone.
- [ ] [FRAME | HIGH] Commit with message `Admit queued Runs asynchronously`.

## Task 4: Implement Role Activation, Claims, and Frozen Snapshots

**Files:**

- Create: `proof_agent/delivery/run_executor.py`
- Create: `proof_agent/control/run_execution.py`
- Create: `tests/test_run_executor.py`
- Create: `tests/test_run_lease_fencing.py`
- Modify: `proof_agent/delivery/agent_package_execution.py`

- [ ] [FRAME | HIGH] Write red tests for `STANDBY`, `ACTIVE`, and `DRAINING`; only the active slot/current epoch may claim. A higher epoch permanently fences lower-epoch terminal writes.
- [ ] [FRAME | HIGH] On claim, create a random claim token and increment Attempt number, then freeze/validate the complete execution snapshot before any model/Knowledge/tool call.
- [ ] [FRAME | HIGH] Use default 5-second heartbeat and 15-second lease expiry, both candidate-config-bound. A reaper marks the uncertain Attempt `FAILED/PA_EXECUTOR_LOST` after expiry; it never replays that Attempt.
- [ ] [FRAME | HIGH] A lost/failed snapshot freeze releases the slot through one conditional terminal transaction; a stale claim/token/attempt/epoch cannot change any later state.
- [ ] [FRAME | HIGH] Preserve the existing governed V3 execution core but inject materialized Knowledge, Secret resolver, guarded transport, Case Memory port, cancellation/deadline callback, and S3 finalizer.
- [ ] [FRAME | HIGH] Commit with message `Claim Runs with fenced execution snapshots`.

## Task 5: Run Up to Five Attempts and Commit Results Safely

**Files:**

- Modify: `proof_agent/delivery/run_executor.py`
- Modify: `proof_agent/control/artifacts/finalization.py`
- Create: `tests/test_run_executor_capacity.py`
- Create: `tests/test_run_terminal_commit.py`

- [ ] [FRAME | HIGH] Add a bounded concurrency supervisor with five slots, graceful signal handling, claim polling, heartbeat, deadline enforcement, and no unbounded task creation.
- [ ] [FRAME | HIGH] Write tests proving the sixth Attempt stays queued, a terminal Attempt frees exactly one slot, `CANCEL_REQUESTED` does not, and the next eligible request starts within one second in the reference environment.
- [ ] [FRAME | HIGH] At governed completion, transition `RUNNING -> FINALIZING`, finalize/verify S3 artifacts, then conditionally commit exactly one terminal state plus visibility. A cancellation/fencing race that wins prevents visibility.
- [ ] [FRAME | HIGH] Enforce a hard 120-second Attempt deadline across execution and finalization. Bounded model retries must fit the remaining budget.
- [ ] [FRAME | HIGH] Add `proof-agent run-executor --concurrency 5 --poll-interval 0.2 --heartbeat-interval 5 --lease-seconds 15`; reject production concurrency above five.
- [ ] [FRAME | HIGH] Commit with message `Execute bounded governed Runs from PostgreSQL`.

## Task 6: Implement Queue and Running Cancellation

**Files:**

- Create: `proof_agent/delivery/run_cancellation_service.py`
- Create: `tests/test_run_cancellation.py`
- Modify: `proof_agent/delivery/api.py`
- Modify: `proof_agent/delivery/run_executor.py`

- [ ] [FRAME | HIGH] Write race tests first: queued cancel versus claim, running cancel, finalizing cancel versus visibility, duplicate cancel, terminal cancel, Executor loss while cancel requested, and stale Executor completion.
- [ ] [FRAME | HIGH] Queued cancel atomically changes `QUEUED -> CANCELLED` and prevents claim. Running/finalizing cancel changes to `CANCEL_REQUESTED`, retaining capacity.
- [ ] [FRAME | HIGH] Executor checks cancellation at governed boundaries before/after model, retrieval, tool, memory, and artifact steps; it writes no partial final manifest and reaches `CANCELLED` within the hard deadline.
- [ ] [FRAME | HIGH] Exactly one conditional state transition wins; state, capacity, and artifact visibility cannot disagree.
- [ ] [FRAME | HIGH] Commit with message `Enforce queued and running cancellation`.

## Task 7: Add Durable Coarse SSE and Best-Effort Detail

**Files:**

- Create: `proof_agent/delivery/run_progress_service.py`
- Create: `proof_agent/observability/progress_notifications.py`
- Modify: `proof_agent/delivery/api.py`
- Create: `tests/test_run_progress_api.py`

- [ ] [FRAME | HIGH] Write red tests for authenticated `run.view`, immediate first coarse event, state changes, heartbeat comments, disconnect without cancellation, reconnect current-state snapshot, missed detail tolerance, trace-safe payload, and terminal close.
- [ ] [FRAME | HIGH] Persist every coarse transition in PostgreSQL. Publish bounded trace-safe fine details with `pg_notify` after commit; do not persist or replay them as an event log.
- [ ] [FRAME | HIGH] On each SSE connection, query and emit current durable state immediately, then subscribe for future notifications and periodically re-read coarse state. Ignore `Last-Event-ID` as a replay promise; label the first event `state_snapshot`.
- [ ] [FRAME | HIGH] Never stream raw model tokens, prompts, secrets, tool arguments, raw evidence, or sensitive trace fields.
- [ ] [FRAME | HIGH] Candidate targets are first SSE state P95 at most one second and browser disconnect never cancelling execution.
- [ ] [FRAME | HIGH] Commit with message `Stream reconnectable coarse Run progress`.

## Task 8: Convert Operator Chat and Dashboard to Async Runs

**Files:**

- Modify: `chat/src/api/client.ts`
- Modify: `chat/src/api/types.ts`
- Modify: `chat/src/modes/operator/operatorAdapter.ts`
- Create: `chat/src/modes/operator/runProgress.ts`
- Modify: `chat/src/modes/operator/OperatorChatPage.tsx`
- Modify: related Chat tests/regression tests
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/pages/RunsListPage.tsx`
- Modify: `dashboard/src/pages/RunDetailPage.tsx`
- Modify: related Dashboard tests

- [ ] [FRAME | HIGH] Write frontend tests for `202`, immediate queued/running display, reconnect, cancel, overload with retry guidance, result-unavailable infrastructure failure, terminal result refresh, and navigation away without cancel.
- [ ] [FRAME | HIGH] Submit with a fresh idempotency key, render durable state and best-effort detail separately, and fetch the exact terminal projection only after a terminal SSE state.
- [ ] [FRAME | HIGH] Show visible queue time separately from execution time; do not imply every detail event is durable.
- [ ] [FRAME | HIGH] Hide cancel unless `run.cancel` is effective and state is cancellable; backend remains authoritative.
- [ ] [FRAME | HIGH] Commit with message `Make operator Runs asynchronous`.

## Task 9: Add N/N-1 Queue Contract Fixtures

**Files:**

- Create: `tests/fixtures/run_execution_contract/v1/old_api_requests.json`
- Create: `tests/fixtures/run_execution_contract/v1/candidate_api_requests.json`
- Create: `tests/test_run_execution_compatibility.py`

- [ ] [FRAME | HIGH] Freeze canonical V1 requests/snapshots/results for both admission directions.
- [ ] [FRAME | HIGH] Prove candidate Executor can consume old-API queued requests and old Executor can consume candidate-API queued requests without default reinterpretation. Unknown required fields/version must fail clearly.
- [ ] [FRAME | HIGH] Expose the compatibility result to S6 release choreography. If either direction cannot pass for a future release, S6 must pause admission for the switch/rollback window.
- [ ] [FRAME | HIGH] Commit with message `Freeze bidirectional Run execution contract fixtures`.

## Task 10: S4 Full Verification and Review

- [ ] [KNOWN | HIGH] Run:

```bash
PROOF_AGENT_TEST_POSTGRES_DSN=postgresql+psycopg://proofagent:proofagent@127.0.0.1:55432/proofagent_test \
  uv run --extra dev --extra postgres --extra s3 --extra security python -m pytest \
  tests/test_run_execution_contracts.py \
  tests/test_postgres_run_queue.py \
  tests/test_run_submission_service.py \
  tests/test_run_executor.py \
  tests/test_run_executor_capacity.py \
  tests/test_run_terminal_commit.py \
  tests/test_run_cancellation.py \
  tests/test_run_lease_fencing.py \
  tests/test_run_progress_api.py \
  tests/test_run_execution_compatibility.py -v
npm run test -w proof-agent-dashboard
npm run test -w proof-agent-chat
npm run build
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai --extra postgres --extra s3 --extra security mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

- [ ] [FRAME | HIGH] Independently review queue SQL under concurrency, capacity accounting, fairness/starvation, lease/activation fencing, no-replay semantics, cancellation/visibility races, deadlines, SSE redaction/reconnect, and frontend failure UX.
- [ ] [FRAME | HIGH] Resolve all P0/P1 findings, record the S4 commit in the master plan, and only then start S5.
