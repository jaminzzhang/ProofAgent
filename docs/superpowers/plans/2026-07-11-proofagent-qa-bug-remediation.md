# ProofAgent QA Bug Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development, with the user-mandated override that implementers must not commit. Each issue is committed only after independent spec and code/runtime validators approve the same staged-diff hash.

**Goal:** Fix all ten 2026-07-11 integration QA issues in severity order, with one TDD-backed and independently validated atomic commit per issue.

**Architecture:** Keep each fix at the boundary where its bad state originates: customer identity restoration in Customer Chat, asset namespace and verification process composition in delivery, compatibility-link publication in storage, PATCH/append semantics in ConversationStore, evidence normalization at adapters/projections, and responsive behavior in the shared Chat layout. Overlapping files are allowed only in separate sequential commits with issue-specific staged hunks.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest, Typer, React 19, TypeScript, Vite 6, Vitest, Testing Library, Radix Dialog, Tailwind CSS 4, gstack browser.

---

## Execution Protocol For Every Issue

- [ ] Dispatch a fresh implementer sub-agent with the complete task text; it must use TDD and must not commit.
- [ ] Capture the test-only RED command and expected failure before production changes.
- [ ] Run the targeted and adjacent GREEN commands after implementation.
- [ ] Stage only the task allowlist and inspect every staged hunk.
- [ ] Compute `git diff --cached --binary | shasum -a 256`.
- [ ] Dispatch a fresh spec-compliance reviewer for that hash; reject any missing or extra behavior.
- [ ] After spec approval, dispatch a fresh code/runtime validator for the same hash; it must run all task commands and browser checks and return `APPROVED` or `REJECTED`.
- [ ] If any file changes after approval, restage, rehash, and repeat both reviews.
- [ ] Root agent runs the decisive checks again, verifies the staged hash, then creates the one issue commit.

## Task 0: Commit Approved Design And Plan

**Files:**
- Create: `docs/superpowers/specs/2026-07-11-proofagent-qa-bug-remediation-design.md`
- Create: `docs/superpowers/plans/2026-07-11-proofagent-qa-bug-remediation.md`

- [ ] **Step 0: Import ignored QA baseline artifacts into the isolated worktree**

Run:

```bash
mkdir -p .gstack/qa-reports
cp /Users/jamin/.codex/worktrees/ef0e23d0-c159-488f-8451-ec24666d0c68/ProofAgent/.gstack/qa-reports/qa-report-proofagent-local-2026-07-11.md .gstack/qa-reports/
cp /Users/jamin/.codex/worktrees/ef0e23d0-c159-488f-8451-ec24666d0c68/ProofAgent/.gstack/qa-reports/baseline.json .gstack/qa-reports/
```

Expected: both ignored artifacts exist locally and remain absent from `git status`.

- [ ] **Step 1: Run documentation checks**

Run: `git diff --check`

Expected: exit 0.

- [ ] **Step 2: Commit only the two planning documents**

Run:

```bash
git add docs/superpowers/specs/2026-07-11-proofagent-qa-bug-remediation-design.md docs/superpowers/plans/2026-07-11-proofagent-qa-bug-remediation.md
git commit -m "docs: plan ProofAgent QA bug remediation"
```

Expected: one documentation-only commit before issue work.

## Task 1: ISSUE-009 — Restore And Enforce Customer Identity

**Files:**
- Modify: `chat/src/modes/customer/CustomerChatPage.tsx:47-156`
- Create: `chat/src/modes/customer/CustomerChatPage.regression-1.test.tsx`

- [ ] **Step 1: Write the failing component tests**

Create real adapter-mocked `MemoryRouter` tests that:

```tsx
test.each([
  [null, 'Guest', 'Anonymous'],
  ['CUST-001', 'Demo 1', 'CUST-001'],
  ['CUST-002', 'Demo 2', 'CUST-002'],
])('restores customer mode from a deep-linked server record', async (customerId, modeLabel, customerLabel) => {
  // fetchCustomerConversation returns the requested identity.
  // Assert the matching mode button and Customer label, not Guest by default.
})

test('fails closed for an unsupported deep-linked customer identity', async () => {
  // Return CUST-999 and assert the existing load-conversation error state.
})

test('does not run when active UI mode and conversation identity diverge', async () => {
  // Create/fetch a mismatched record, submit, and assert createCustomerRun is not called.
})

test('does not reuse a previous conversation after the deep-link route changes', async () => {
  // Keep the page mounted, navigate valid → missing/different, resolve fetches out of order,
  // and assert old turns disappear and createCustomerRun is never called.
})

test.each(['/customer', '/customer/new', '/customer/agents/agent-1'])(
  'clears server conversation state when navigating to %s',
  async (target) => {
    // Navigate from a loaded conversation without remounting. Assert its turns and
    // server-derived mode disappear, Guest/new-route state is active, and it cannot run.
  },
)

test('preserves the first submission through a controlled new-conversation binding', async () => {
  // From a non-conversation route, create a matching record, run, refresh, then navigate.
  // Assert the run uses only that new ID and the answer appears on its committed route.
})

test.each(['create', 'run', 'refresh'])(
  'ignores obsolete %s completion after navigation',
  async (stage) => {
    // Hold the named adapter promise, navigate while it is pending, then resolve it.
    // Assert no stale conversation/turn/mode/error/sending write and no later request starts.
  },
)
```

Include the ISSUE-009 attribution comment and exact QA report path.

- [ ] **Step 2: Verify RED**

Run: `npm test -w proof-agent-chat -- CustomerChatPage.regression-1.test.tsx --run`

Expected: fail because deep links still render Guest, mismatches can run, non-conversation navigation retains old state, and obsolete async completions can continue or repopulate the pipeline.

- [ ] **Step 3: Implement the identity mapping and invariant**

In `CustomerChatPage.tsx`, add a focused resolver:

```ts
function customerModeFor(customerId: string | null): CustomerMode | null {
  if (customerId === null) return 'anonymous'
  return CUSTOMER_MODES.some((item) => item.id === customerId)
    ? customerId as CustomerMode
    : null
}
```

Treat the mounted page as one route-scoped state machine. Maintain a monotonic request-generation ref and invalidate it synchronously for every location transition and explicit mode change. The transition handler clears `conversation`, `turns`, `sending`, and obsolete error state. Leaving a conversation route also clears its server-derived mode back to Guest unless the UI deliberately selected a new mode for the destination. Deep-link load, agent load, create, run, and refresh handlers may write state or launch their next request only while their captured generation is current.

Resolve and set mode before accepting a fetched deep-link record. Accept it only if its `conversation_id` equals the current route and the generation is still current; unsupported identities enter the existing load-error path. For an existing conversation, require the current generation, `activeMode.customerId === conversation.customer_id`, and `conversation.conversation_id === routeConversationId` immediately before the run API.

Keep first submission as an explicit separate path rather than applying the existing-route invariant to an ID the router has not committed. On a non-conversation route, capture the generation, requested mode, and selected agent; create the record; validate its ID and identity; recheck the generation; run and refresh that exact local ID, checking the generation after every await and before every subsequent request/state write; only then navigate to `/customer/c/{id}`. An obsolete operation may have an already accepted backend request, but it must not update the new route or launch a later pipeline stage. In every `catch`/`finally`, mutate error/input/sending only if the captured generation is still current.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
npm test -w proof-agent-chat -- CustomerChatPage.regression-1.test.tsx CustomerChatPage.test.tsx customerAdapter.test.ts --run
npm run build -w proof-agent-chat
```

Expected: all pass.

- [ ] **Step 5: Browser/API validation**

Start the full local stack. Create anonymous, CUST-001, CUST-002, and unknown customer records. Open fresh deep links, verify the correct identity, complete a first submission, and confirm unknown/stale state fails closed. While throttling adapter/API responses, navigate from a loaded conversation to missing/different conversation IDs and to `/customer`, `/customer/new`, and `/customer/agents/{id}`; verify old turns and identity disappear and late load/create/run/refresh completion cannot repopulate them. Check console and API identity throughout.

- [ ] **Step 6: Validate and commit**

Allowlist only the two files above. After both validators approve the staged hash and root rechecks, commit:

`fix(qa): ISSUE-009 — restore customer identity on deep links`

## Task 2: ISSUE-002 — Namespace Chat Assets Through The Verification Gateway

**Files:**
- Modify: `proof_agent/delivery/remote_verify_gateway.py:26-155`
- Modify: `proof_agent/delivery/cli.py:47-64,793-880`
- Create: `tests/test_remote_verify_gateway_regression_1.py`
- Create: `tests/test_cli_regression_1.py`

- [ ] **Step 1: Write failing gateway and command-construction tests**

Use real threaded fake upstreams. Parameterize `/operator` and `/customer`; the Chat upstream must receive `/<chat-base>/operator` or `/<chat-base>/customer`, its HTML must emit base-prefixed Vite client/module paths, and all emitted paths must route back to Chat. Add a sentinel that Upgrade still returns 426 in this commit. Add a CLI test asserting the Chat dev argv contains the same `--base` used by the gateway.

- [ ] **Step 2: Verify RED**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_remote_verify_gateway_regression_1.py tests/test_cli_regression_1.py -v
```

Expected: fail because entry paths are not rewritten and root assets go to Dashboard.

- [ ] **Step 3: Implement one shared Chat base contract**

Define a verification-only base such as `/__proofagent_chat__/`. Normalize it in `GatewayConfig`; route the base prefix to Chat; rewrite public Chat entry paths under the prefix without changing the browser URL; preserve query strings and `/api`. Pass the identical base to Chat Vite with `--base`. Do not change dev/HMR or Upgrade rejection.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_remote_verify_gateway_regression_1.py tests/test_cli_regression_1.py tests/test_remote_verify_gateway.py -v
uv run --extra dev --extra dashboard python -m pytest tests/test_cli.py -k verify_remote -v
uv run --extra dev ruff check proof_agent/delivery/remote_verify_gateway.py proof_agent/delivery/cli.py tests/test_remote_verify_gateway_regression_1.py tests/test_cli_regression_1.py
uv run --extra dev --extra openai mypy proof_agent
```

- [ ] **Step 5: Browser validation**

Through port 18080, require `Operator Chat` and `Customer Chat`, Chat-prefixed assets, zero Router/asset errors, and only the known HMR 426.

- [ ] **Step 6: Validate and commit**

Commit after hash-bound approvals:

`fix(qa): ISSUE-002 — namespace verification Chat assets`

## Task 3: ISSUE-006 — Publish A Correct Atomic `runs/latest` Symlink

**Files:**
- Modify: `proof_agent/observability/storage/compat.py:14-37`
- Create: `tests/test_storage_compat_regression_1.py`
- Create: `tests/test_cli_regression_2.py`

- [ ] **Step 1: Write failing storage and lifecycle tests**

Cover a repository-style relative `runs/history/run_id`, repair of an already broken `runs/latest`, same-directory temporary link cleanup when `os.replace` fails, and preservation of a real `runs/latest` directory. Add a same-cwd lifecycle test that persists a real Chat/API run and then invokes `demo`, `react-demo`, and deterministic `run`.

- [ ] **Step 2: Verify RED**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_storage_compat_regression_1.py tests/test_cli_regression_2.py -v
```

Expected: relative link resolves through `runs/runs`, and CLI flows fail after the stored run.

- [ ] **Step 3: Implement atomic relative publication**

Resolve semantic paths, derive the target with `os.path.relpath(run_dir.resolve(), latest.parent.resolve())`, create a unique sibling temporary symlink, and publish with `os.replace`. Clean the temporary link in `finally`; preserve real directories; repair broken links. Do not alter `harness_helpers.py`.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_storage_compat_regression_1.py tests/test_cli_regression_2.py tests/test_storage_compat.py tests/test_cli.py -v
uv run --extra dev ruff check proof_agent/observability/storage/compat.py tests/test_storage_compat_regression_1.py tests/test_cli_regression_2.py
uv run --extra dev --extra openai mypy proof_agent
```

- [ ] **Step 5: Runtime validation**

In one clean cwd, persist a real API/Chat run, assert `latest.resolve()` equals the history run, then run:

```bash
uv run --extra dev proof-agent demo
uv run --extra dev proof-agent react-demo
uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml --question "What documents are required for inpatient claim reimbursement?"
```

- [ ] **Step 6: Validate and commit**

`fix(qa): ISSUE-006 — publish valid latest run symlink`

## Task 4: ISSUE-008 — Preserve Omitted Conversation PATCH Fields

**Files:**
- Modify: `proof_agent/delivery/api.py:65-71,154-170`
- Modify: `proof_agent/observability/storage/conversation_store.py:74-99`
- Create: `tests/test_conversation_api_regression_1.py`

- [ ] **Step 1: Write failing PATCH semantics tests**

Create API tests for title → pin/unpin preserving title; pin → rename/null/empty title preserving pin; explicit `pinned:null` returning 422; and `{}` preserving representation, `updated_at`, and list order.

- [ ] **Step 2: Verify RED**

Run: `uv run --extra dev --extra dashboard python -m pytest tests/test_conversation_api_regression_1.py -v`

Expected: sibling values reset and empty PATCH changes metadata.

- [ ] **Step 3: Implement field-presence semantics**

Make omitted `pinned` distinguishable while rejecting explicit null. Build keyword arguments from `request.model_fields_set`. If neither supported field is present, return the existing record without Store write. Also make the Store's all-`_UNCHANGED` path a no-op defense.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_conversation_api_regression_1.py tests/test_conversation_api.py -v
uv run --extra dev ruff check proof_agent/delivery/api.py proof_agent/observability/storage/conversation_store.py tests/test_conversation_api_regression_1.py
uv run --extra dev --extra openai mypy proof_agent
```

- [ ] **Step 5: API/browser lifecycle validation**

Replay rename → pin/unpin → GET/list and pin → rename/clear → GET/list; verify title, pinned, timestamps, and ordering.

- [ ] **Step 6: Validate and commit**

`fix(qa): ISSUE-008 — preserve partial conversation updates`

## Task 5: ISSUE-010 — Preserve Conversation Metadata When Appending Turns

**Files:**
- Modify: `proof_agent/observability/storage/conversation_store.py:58-72`
- Create: `tests/test_conversation_api_regression_2.py`

- [ ] **Step 1: Write the failing public lifecycle test**

Through the API: create → append → PATCH title/pinned → append → GET → list. Assert title, pin, prior turns, new turn, and pinned-first ordering survive.

- [ ] **Step 2: Verify RED**

Run: `uv run --extra dev --extra dashboard python -m pytest tests/test_conversation_api_regression_2.py -v`

Expected: title becomes null and pinned becomes false after the second append.

- [ ] **Step 3: Implement immutable model copy**

Replace manual reconstruction with:

```python
updated = record.model_copy(
    update={"updated_at": _now(), "turns": (*record.turns, turn)}
)
```

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_conversation_api_regression_2.py tests/test_conversation_api.py -v
uv run --extra dev ruff check proof_agent/observability/storage/conversation_store.py tests/test_conversation_api_regression_2.py
uv run --extra dev --extra openai mypy proof_agent
```

- [ ] **Step 5: Browser/API validation and commit**

Rename and pin in Operator Chat, append a question, reload, verify title/pin, obtain validator approvals, then commit:

`fix(qa): ISSUE-010 — preserve metadata when appending turns`

## Task 6: ISSUE-003 — Normalize Operator Evidence In Both Data Paths

**Files:**
- Modify: `chat/src/api/types.ts:132-182`
- Modify: `chat/src/modes/operator/operatorAdapter.ts:1-43`
- Modify: `chat/src/modes/operator/OperatorChatPage.tsx:67-175,388-423`
- Create: `chat/src/modes/operator/operatorAdapter.regression-1.test.ts`
- Create: `chat/src/modes/operator/OperatorChatPage.regression-1.test.tsx`

- [ ] **Step 1: Write failing adapter and page tests**

Feed real `{source, citation, status, scores}` evidence through both fetched conversation GET and new run POST. Assert identical typed views and visible source/citation immediately after append and after reload.

- [ ] **Step 2: Verify RED**

```bash
npm test -w proof-agent-chat -- operatorAdapter.regression-1.test.ts OperatorChatPage.regression-1.test.tsx --run
```

Expected: source/citation labels are blank.

- [ ] **Step 3: Implement one evidence normalizer**

Replace `any[]` with raw `unknown[]` at the transport type, define a typed `OperatorEvidenceView`, normalize `source`/`citation` with deterministic `Source N` fallback, and wrap both `fetchOperatorConversation` and `createOperatorConversationRun`. Render citation separately when it differs from the label.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
npm test -w proof-agent-chat -- operatorAdapter.regression-1.test.ts OperatorChatPage.regression-1.test.tsx operatorAdapter.test.ts OperatorChatPage.test.tsx --run
npm run build -w proof-agent-chat
```

- [ ] **Step 5: Browser validation and commit**

Ask an evidence-backed question; assert source/citation before and after reload and clean console. After approvals commit:

`fix(qa): ISSUE-003 — normalize operator evidence labels`

## Task 7: ISSUE-004 — Add An Accessible Mobile Operator History Drawer

**Files:**
- Modify: `chat/src/App.tsx:90-108`
- Modify: `chat/src/components/TopNav.tsx:1-23`
- Modify: `chat/src/components/HistorySidebar.tsx:6-22,87-156`
- Modify: `chat/src/i18n/messages.ts`
- Create: `chat/src/App.regression-1.test.tsx`
- Create: `chat/src/components/HistorySidebar.regression-1.test.tsx`

- [ ] **Step 1: Write failing interaction tests**

Test trigger accessible name, Dialog open/focus, focus trap, Escape close and focus return, New Chat/conversation selection close, and desktop sidebar preservation. Directly test `onNavigate` callbacks in HistorySidebar.

- [ ] **Step 2: Verify RED**

```bash
npm test -w proof-agent-chat -- App.regression-1.test.tsx HistorySidebar.regression-1.test.tsx --run
```

Expected: no mobile trigger or drawer exists.

- [ ] **Step 3: Implement with shared Radix Dialog**

Keep desktop sidebar in `hidden lg:block`; add a controlled mobile Dialog using `@proofagent/ui`, place the trigger in a new TopNav `leading` slot, and close through `onNavigate`. Add concise English/Chinese labels. Do not hand-roll focus behavior.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
npm test -w proof-agent-chat -- App.regression-1.test.tsx HistorySidebar.regression-1.test.tsx App.test.tsx --run
npm run build -w proof-agent-chat
```

- [ ] **Step 5: Browser validation**

At 375×812 and 768×812, measure main ≥90% of viewport and textarea ≥240 px; exercise pointer/keyboard open, focus trap, Escape, focus return, and selection close.

- [ ] **Step 6: Validate and commit**

`fix(qa): ISSUE-004 — add mobile operator history drawer`

## Task 8: ISSUE-005 — Preserve Mobile Customer Message Height And Answer Start

**Files:**
- Modify: `chat/src/chat-core/ChatShell.tsx:67-222`
- Modify: `chat/src/i18n/messages.ts`
- Create: `chat/src/chat-core/ChatShell.regression-1.test.tsx`
- Create: `chat/src/modes/operator/OperatorChatPage.regression-2.test.tsx`

- [ ] **Step 1: Write failing shared-shell tests**

Assert a collapsed mobile side-details disclosure, `minmax(0,1fr) auto` row contract, newest completed answer `scrollIntoView({block:'start'})`, sending-progress bottom behavior, and an adjacent Operator reload/scroll regression.

- [ ] **Step 2: Verify RED**

```bash
npm test -w proof-agent-chat -- ChatShell.regression-1.test.tsx OperatorChatPage.regression-2.test.tsx --run
```

Expected: no disclosure exists and the shell calls absolute bottom scrolling.

- [ ] **Step 3: Implement responsive grid and answer anchor**

Render one side-panel subtree through a mobile disclosure and desktop column; keep messages in the primary flex row. Attach a ref to the newest completed assistant article and scroll its start into view; retain bottom behavior only for active sending progress.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
npm test -w proof-agent-chat -- ChatShell.regression-1.test.tsx OperatorChatPage.regression-2.test.tsx ChatShell.test.tsx OperatorChatPage.test.tsx --run
npm run build -w proof-agent-chat
```

- [ ] **Step 5: Browser validation**

At 375×812 require message region ≥320 px, newest answer beginning visible initially, usable input, expandable details, and unchanged Operator scrolling.

- [ ] **Step 6: Validate and commit**

`fix(qa): ISSUE-005 — preserve mobile customer message space`

## Task 9: ISSUE-001 — Serve Built SPAs During Verification

**Files:**
- Modify: `proof_agent/delivery/cli.py:147-238,793-880`
- Create: `tests/test_cli_regression_3.py`

- [ ] **Step 1: Write failing build/preview orchestration tests**

Mock synchronous command execution and process launch. Assert Dashboard build and Chat base-aware build occur after cross-link env values are blank and before long-lived preview specs. Assert preview, not dev, is supervised and normal dev commands remain unchanged.

- [ ] **Step 2: Verify RED**

Run: `uv run --extra dev --extra dashboard python -m pytest tests/test_cli_regression_3.py -v`

Expected: no blocking build occurs and process specs use Vite dev.

- [ ] **Step 3: Implement verification-only build/preview**

Add a blocking frontend build helper called before `_run_dev_processes`; do not place finite build commands inside the supervisor. Build Dashboard normally, build Chat with the ISSUE-002 base, and serve both with existing `preview` scripts. Preserve direct `npm run dev` HMR.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_cli_regression_3.py tests/test_cli.py tests/test_remote_verify_gateway.py -v
npm run build -w proof-agent-dashboard
npm run build -w proof-agent-chat
uv run --extra dev ruff check proof_agent/delivery/cli.py tests/test_cli_regression_3.py
uv run --extra dev --extra openai mypy proof_agent
```

- [ ] **Step 5: Browser validation**

Through port 18080 load Dashboard, Operator, and Customer. Assert no `@vite/client`, no WebSocket request, no 426, and no console errors. Separately start direct dev and verify the HMR client remains present.

- [ ] **Step 6: Validate and commit**

`fix(qa): ISSUE-001 — serve built SPAs for verification`

## Task 10: ISSUE-007 — Type And Stabilize Evidence Projection Identity

**Files:**
- Modify: `proof_agent/contracts/dashboard.py:45-100`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `proof_agent/observability/storage/run_store.py:150-194,420-493`
- Modify: `proof_agent/observability/api/serializers.py:33-58`
- Modify: `proof_agent/delivery/api.py:215-319`
- Modify: `proof_agent/delivery/customer_api.py:1190-1235`
- Modify: `dashboard/src/pages/tabs/EvidenceTab.tsx:18-24`
- Modify: `tests/test_run_store.py:493-566`
- Modify: `tests/test_dashboard_contracts.py:60-75`
- Modify: `tests/test_customer_run_api.py:160-180`
- Create: `tests/test_run_store_regression_1.py`
- Create: `tests/test_dashboard_contracts_regression_1.py`
- Create: `dashboard/src/pages/tabs/EvidenceTab.regression-1.test.tsx`

- [ ] **Step 1: Write failing typed projection tests**

Test unique deterministic indexes for missing provider identity, identity stability across reordered chunks, explicit typed serialization, preserved Chat/customer payload fields, and a legacy Dashboard fallback with two index-less chunks that emits no React key warning.

- [ ] **Step 2: Verify RED**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_run_store_regression_1.py tests/test_dashboard_contracts_regression_1.py -v
npm test -w proof-agent-dashboard -- EvidenceTab.regression-1.test.tsx --run
```

Expected: backend items remain dictionaries without index and frontend warns about duplicate undefined keys.

- [ ] **Step 3: Implement the typed stable projection**

Add a frozen Dashboard evidence projection contract. Normalize both trace evidence shapes into it. Derive deterministic JavaScript-safe identity from stable evidence/provider fields or canonical trace-safe JSON, with duplicate ordinals and collision handling; never use Python `hash()` or list position. Serialize explicitly at API boundaries. Keep Dashboard's typed index required and add a defensive legacy composite key.

Migrate existing RunStore assertions from dictionary subscription to typed attributes, and update Dashboard/customer fixtures to construct the typed projection with stable identity. These migrations are part of ISSUE-007 because the public contract changes in the same commit.

- [ ] **Step 4: Run GREEN and adjacent checks**

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_run_store_regression_1.py tests/test_dashboard_contracts_regression_1.py tests/test_run_store.py tests/test_dashboard_contracts.py tests/test_customer_run_api.py tests/test_conversation_api.py -v
npm test -w proof-agent-dashboard -- EvidenceTab.regression-1.test.tsx --run
npm run build -w proof-agent-dashboard
uv run --extra dev ruff check proof_agent tests/test_run_store_regression_1.py tests/test_dashboard_contracts_regression_1.py tests/test_run_store.py tests/test_dashboard_contracts.py tests/test_customer_run_api.py
uv run --extra dev --extra openai mypy proof_agent
```

- [ ] **Step 5: Browser validation and commit**

Open a run with multiple evidence chunks, reload/reorder the projection, verify stable cards and zero key warnings, obtain hash-bound approvals, then commit:

`fix(qa): ISSUE-007 — stabilize evidence projection identity`

## Task 11: Final Regression And Report Update

**Files:**
- Modify: `.gstack/qa-reports/qa-report-proofagent-local-2026-07-11.md` (ignored local artifact only)
- Modify: `.gstack/qa-reports/baseline.json` (ignored local artifact only)

- [ ] **Step 1: Run the complete backend gates**

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree --extra openai python -m pytest tests -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
```

- [ ] **Step 2: Run complete frontend gates**

```bash
npm test -w proof-agent-dashboard -- --run
npm test -w proof-agent-chat -- --run
npm run build -w proof-agent-dashboard
npm run build -w proof-agent-chat
```

- [ ] **Step 3: Run deterministic CLI gates**

```bash
uv run --extra dev proof-agent demo
uv run --extra dev proof-agent react-demo
uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml --question "What documents are required for inpatient claim reimbursement?"
```

- [ ] **Step 4: Run final browser QA**

Start `uv run --extra dashboard --extra ingestion --extra tree proof-agent verify-remote --local-only`. Replay all ten issue reproductions, inspect console after every flow, and test 375×812 plus 768×812 responsive states.

- [ ] **Step 5: Dispatch final whole-branch reviewer**

Require it to verify ten issue commits, ten validator approvals, severity order, clean diff scope, and all final gates.

- [ ] **Step 6: Update ignored QA artifacts**

Record each fix status, commit SHA, files changed, before/after evidence, final health score, and regression delta. Do not create an extra source commit for ignored artifacts.
