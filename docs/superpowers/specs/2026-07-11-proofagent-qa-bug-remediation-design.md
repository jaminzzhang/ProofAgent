# ProofAgent QA Bug Remediation Design

## Goal

[KNOWN] Resolve all ten issues recorded by the 2026-07-11 ProofAgent integration QA run, in severity order, without mixing unrelated changes. Each issue must have a regression test that fails before the fix, an independent validator sub-agent review, fresh verification, and one atomic commit containing only that issue's test and fix.

## Delivery Invariants

- [KNOWN] Work occurs on `codex/fix-proofagent-qa-bugs` in an isolated worktree created from `1bd0fbf`.
- [KNOWN] The original dirty worktree is outside the remediation workspace and must remain untouched.
- [KNOWN] Commit messages use `fix(qa): ISSUE-NNN — description`.
- [KNOWN] Exactly one implementation commit is created per issue. The regression test and production fix live in the same commit.
- [KNOWN] This cross-issue design and its implementation plan are committed in one separate pre-implementation documentation commit; neither document is folded into an issue commit.
- [KNOWN] No issue is committed until the root agent has captured the test-only RED failure, staged an explicit issue file allowlist, hashed the staged binary diff with SHA-256, and a validator sub-agent has reviewed that exact hash and run the applicable targeted, adjacent, type, build, and browser checks.
- [KNOWN] Any edit after validator approval changes or invalidates the staged-diff hash and requires a fresh validator pass before commit.
- [KNOWN] The root agent independently re-runs the decisive checks after validator approval and before commit.
- [KNOWN] A validator failure returns the issue to implementation; approval is not inferred from partial or stale output.

## Priority Order

[COMPUTED] Severity and user impact produce this execution order:

1. `ISSUE-009` High: customer identity shown as Guest while the server retains an authenticated customer context.
2. `ISSUE-002` High: the single verification gateway routes Chat entry documents to Chat but routes their root assets to Dashboard.
3. `ISSUE-006` High: relative `runs/latest` symlink targets resolve through an extra `runs/` segment and break CLI flows.
4. `ISSUE-008` Medium: partial conversation PATCH requests clear omitted sibling fields.
5. `ISSUE-010` Medium: appending an operator turn drops title and pinned metadata.
6. `ISSUE-003` Medium: Operator Chat reads evidence fields that do not match the API payload.
7. `ISSUE-004` Medium: the fixed-width Operator history sidebar leaves the mobile chat unusable.
8. `ISSUE-005` Medium: the Customer side panel competes with the fixed-height message region on mobile.
9. `ISSUE-001` Low: the verification gateway rejects Vite HMR WebSocket upgrades and pollutes the console.
10. `ISSUE-007` Low: Dashboard evidence chunks lack the stable index required by the React list contract.

## Issue Designs

### ISSUE-009: Restore Customer Identity From the Server Record

[COMPUTED] `CustomerChatPage` initializes `mode` to anonymous and does not update it after `fetchCustomerConversation()` returns `customer_id`. Subsequent runs reuse the existing conversation, so the UI identity and authorization context diverge.

[KNOWN] Treat the mounted Customer page as a route-scoped state machine. Every location transition and explicit mode change invalidates the prior request generation before any new work can reuse it. Clear prior conversation, turns, sending/error state, and server-derived mode when leaving or beginning to load a conversation route; a non-conversation Customer route has no reusable server conversation and starts as Guest unless that navigation carries a deliberate new mode selection. Every asynchronous stage (`fetchCustomerConversation`, `createCustomerConversation`, `createCustomerRun`, and the post-run refresh) must check the same captured generation before launching its next request or writing state. A request already accepted by the backend cannot be undone, but completion from an obsolete generation must not mutate the new route.

[KNOWN] For a deep link, map `record.customer_id` to a supported `CustomerMode` and accept the record only while the generation remains current and `record.conversation_id` still equals the active route. Anonymous records map to Guest, `CUST-001` and `CUST-002` map to their named demo modes, and unsupported non-null identities fail closed with the existing load-error state. The server record is the identity source of truth. Before running an existing conversation, require the current generation plus both `activeMode.customerId === conversation.customer_id` and `conversation.conversation_id === routeConversationId`. The first submission from a non-conversation route uses a separate controlled new-conversation binding: capture the current generation, requested mode, and agent; validate the created record's identity against that request; recheck the generation before the run; keep the new record local until run and refresh complete; then navigate to its conversation route. This preserves the first submission without pretending that the pre-navigation route already owns the new ID. Fail closed before the run API whenever any applicable binding check diverges.

[KNOWN] Add component and browser/API tests for CUST-001, CUST-002, anonymous, unknown identities, injected stale-state mismatch, the successful first-submission path, mounted navigation from a valid conversation to a missing/different conversation and to each non-conversation Customer route, and deferred completion after navigation at each create/run/refresh stage. Tests must prove obsolete completions cannot restore old conversation, turns, mode, error, or sending state and cannot launch a later pipeline request.

### ISSUE-002: Give Chat Assets an Unambiguous Gateway Namespace

[COMPUTED] Path-only routing cannot distinguish Dashboard `/src/main.tsx` from Chat `/src/main.tsx` after the entry HTML loads absolute root assets.

[KNOWN] Start the Chat Vite server in verification mode with a dedicated base prefix and route that prefix to the Chat upstream. The gateway must internally rewrite public `/operator` and `/customer` entry requests to `/<chat-base>/operator` and `/<chat-base>/customer` because Vite serves history fallback beneath its configured base; the browser-visible URL remains unchanged so React Router still sees `/operator` or `/customer`. Preserve `/api/*` as backend paths. Add gateway tests that request both rewritten entry documents, parse their emitted module/client paths, request those paths through the gateway, and prove every request reaches Chat rather than Dashboard. This issue deliberately preserves and tests the gateway's existing Upgrade rejection; its browser gate allows only the already-known HMR 426 while requiring zero Router mismatch or asset errors. `ISSUE-001` removes that final 426 later.

### ISSUE-006: Make `runs/latest` Resolve Correctly for Relative Run Directories

[COMPUTED] A symlink target is resolved relative to the link's parent, not the process working directory. Writing `runs/history/run_id` into `runs/latest` therefore resolves to `runs/runs/history/run_id`.

[KNOWN] Normalize the target against `latest.parent`, write a correct relative target such as `history/run_id`, create a temporary symlink in the same directory, and atomically publish it with `os.replace`. Repair stale or broken symlinks, clean temporary links after failures, and never replace a real directory. Add repository-style relative-path tests, failure-injection cleanup coverage, and an integration test that performs a real persisted API/Chat run in a working directory before executing `demo`, `react-demo`, and `run` in that same working directory.

### ISSUE-008: Preserve Omitted Fields in Conversation PATCH

[COMPUTED] Pydantic defaults omitted update fields to `None`, and the endpoint forwards both fields unconditionally, defeating the store's `_UNCHANGED` sentinel.

[KNOWN] Use request field-presence information to pass only fields explicitly supplied by the client. An omitted title is unchanged; explicit `title:null` or an empty title clears it. An omitted pinned field is unchanged; explicit `pinned:null` is rejected with 422 because pin state is boolean. An empty `{}` PATCH is a true no-op: it returns the existing representation without changing `updated_at` or list ordering. Add symmetric API tests proving pin/unpin preserves title, rename/clear-title preserves pinned state, null pin is rejected, and empty PATCH is timestamp/order stable.

### ISSUE-010: Preserve Metadata When Appending Turns

[COMPUTED] `ConversationStore.append_turn()` reconstructs `ConversationRecord` without copying `title` or `pinned`, so model defaults overwrite both values.

[KNOWN] Use `record.model_copy(update={"updated_at": ..., "turns": ...})` so all present and future metadata fields are preserved by default. Add a public API lifecycle regression covering create, append, PATCH rename/pin, append again, GET reload, and list ordering.

### ISSUE-003: Normalize Operator Evidence at the API Adapter Boundary

[COMPUTED] The API returns evidence fields such as `source` and `citation`, while `OperatorGovernanceDetails` reads `source_id`, `label`, and `excerpt` from `any[]`.

[KNOWN] Define a typed Operator evidence view and normalize the API payload in the operator adapter or a focused projection helper. Apply the same normalization to both fetched conversation turns and the newly returned run response so a just-appended turn and a reloaded turn render identically. Render a non-empty source label with citation fallback and remove the `any[]` trust gap. Add component/adapter tests using the real API evidence shape for both paths and assert visible file names and citations before and after reload.

### ISSUE-004: Replace the Mobile Operator Sidebar With a Drawer

[COMPUTED] `HistorySidebar` is always `w-64 shrink-0`, leaving only 119 px for the main area at a 375 px viewport.

[KNOWN] Keep the desktop sidebar unchanged at the existing breakpoint. On smaller viewports, hide the fixed sidebar behind an accessible menu button and modal drawer. At 375×812 and 768×812, the main region must occupy at least 90% of viewport width and the textarea must be at least 240 px wide. The drawer must trap focus, return focus to its trigger on close, close on Escape, and close after conversation selection. Add component behavior tests and browser verification at both widths.

### ISSUE-005: Give Mobile Customer Messages a Readable Height

[COMPUTED] The fixed-height `ChatShell` grid places the Customer side panel in a second mobile row and compresses the message region to 85 px before auto-scrolling to the bottom.

[KNOWN] Present side-panel content in a collapsed mobile disclosure/drawer while retaining the desktop side column. Keep the message region as the primary flexible row with a measured height of at least 320 px at 375×812. After auto-scroll, the beginning of the newest answer must be inside the message scroller's initial viewport rather than above it. Add `ChatShell` behavior/layout assertions, browser verification at 375×812, and an adjacent Operator Chat scrolling regression because both modes share `ChatShell`.

### ISSUE-001: Disable HMR for Verification Gateway Sessions

[COMPUTED] The gateway explicitly does not implement WebSocket tunneling, but the Vite clients still attempt HMR through port 18080 and receive 426.

[KNOWN] HMR is not part of a verification session's product behavior, and Vite 6.4.3 still injects a WebSocket-opening client when `server.hmr=false`. Therefore `verify-remote` must build and serve both SPAs through `vite preview` rather than their dev servers. Build Chat with the dedicated base introduced by ISSUE-002; keep normal `npm run dev` commands unchanged with HMR. Add command-construction tests and browser verification proving verification pages emit no HMR client connection or WebSocket request.

### ISSUE-007: Enforce Stable Evidence Chunk Identity

[COMPUTED] Dashboard declares `EvidenceChunk.index` as required, but the backend projection can return real evidence dictionaries without it, producing duplicate `undefined` React keys.

[KNOWN] Introduce a typed evidence read-projection/serializer contract instead of passing `dict[str, Any]` across the API boundary. Assign a stable index for every chunk, define uniqueness under missing provider identity, and preserve identity when chunks are reordered. Keep a defensive frontend composite fallback key for old artifacts. Add backend serialization/uniqueness/reordering coverage and a non-empty `EvidenceTab` component regression test that spies on console errors.

## Per-Issue Validation Contract

[KNOWN] Every issue follows this auditable sequence: write only the regression test, run it and capture the expected RED output; implement the fix; run target checks; stage only the issue allowlist; compute `git diff --cached --binary | shasum -a 256`; give that hash, RED output, intended behavior, changed-file list, and exact commands to a read-only validator. The validator approves or rejects that exact hash. The root agent re-runs decisive checks, verifies the staged hash is unchanged, and commits. Its report must include:

1. [COMPUTED] Diff scope and root-cause alignment.
2. [COMPUTED] Regression-test quality and proof that the test covers the original symptom.
3. [COMPUTED] Targeted tests plus adjacent subsystem tests.
4. [COMPUTED] Ruff/mypy for Python changes or test/build for frontend changes.
5. [COMPUTED] Browser reproduction for UI or gateway issues, including console inspection and mobile viewport checks where applicable.
6. [COMPUTED] Explicit `APPROVED` or `REJECTED` verdict with command outputs and remaining risks.

## Issue Reproduction And Verification Matrix

| Issue | Automated gate | Runtime reproduction required before approval |
|---|---|---|
| ISSUE-009 | `npm test -w proof-agent-chat -- CustomerChatPage.regression-1.test.tsx CustomerChatPage.test.tsx customerAdapter.test.ts --run`; `npm run build -w proof-agent-chat` | Create CUST-001/CUST-002/anonymous conversations, open each fresh `/customer/c/{id}` page, assert matching session identity, complete a first submission, then navigate while deferred load/create/run/refresh requests are pending; verify missing/different and non-conversation routes clear old state, obsolete completions cannot write or advance the pipeline, and unknown/stale identities fail closed |
| ISSUE-002 | `uv run --extra dev --extra dashboard python -m pytest tests/test_remote_verify_gateway.py -v` | Start `verify-remote --local-only`; load `/operator` and `/customer`; inspect emitted Chat asset requests, headings, and Router console |
| ISSUE-006 | `uv run --extra dev --extra dashboard python -m pytest tests/test_storage_compat.py tests/test_cli.py -v` | In one cwd, persist a real API/Chat run, inspect `runs/latest`, then run `proof-agent demo`, `proof-agent react-demo`, and a deterministic `proof-agent run` |
| ISSUE-008 | `uv run --extra dev --extra dashboard python -m pytest tests/test_conversation_api.py -v` | Rename → pin/unpin → reload and pin → rename/clear → reload through API/browser; verify sibling metadata, timestamps, and order |
| ISSUE-010 | `uv run --extra dev --extra dashboard python -m pytest tests/test_conversation_api.py -v` | Create → append → rename/pin → append → GET/list/browser reload; verify title and pin survive |
| ISSUE-003 | `npm test -w proof-agent-chat -- OperatorChatPage.test.tsx operatorAdapter.test.ts --run`; `npm run build -w proof-agent-chat` | Submit an evidence-backed operator question and verify visible source/citation text immediately and after reload plus a clean console |
| ISSUE-004 | `npm test -w proof-agent-chat -- App.test.tsx HistorySidebar.test.tsx --run`; `npm run build -w proof-agent-chat` | At 375×812 and 768×812, exercise trigger/focus trap/Escape/focus return/selection close and measure main ≥90% plus textarea ≥240 px |
| ISSUE-005 | `npm test -w proof-agent-chat -- ChatShell.test.tsx OperatorChatPage.test.tsx --run`; `npm run build -w proof-agent-chat` | At 375×812, load a completed Customer answer, measure messages ≥320 px, confirm answer start is initially visible, open details, then verify Operator scrolling |
| ISSUE-001 | `uv run --extra dev --extra dashboard python -m pytest tests/test_cli.py tests/test_remote_verify_gateway.py -v`; `npm run build -w proof-agent-dashboard`; `npm run build -w proof-agent-chat` | Load Dashboard, Operator, and Customer through port 18080; verify no HMR client/WebSocket request/426 while direct `npm run dev` remains HMR-capable |
| ISSUE-007 | `uv run --extra dev --extra dashboard python -m pytest tests/test_run_store.py -v`; `npm test -w proof-agent-dashboard -- EvidenceTab.test.tsx --run`; `npm run build -w proof-agent-dashboard` | Open a multi-evidence run, reorder/refresh the typed evidence projection, and verify stable cards with no React key warning |

## Final Verification

[KNOWN] After all ten atomic commits, run exactly: `uv run --extra dev --extra dashboard --extra ingestion --extra tree --extra openai python -m pytest tests -q`; `uv run --extra dev ruff check proof_agent tests`; `uv run --extra dev --extra openai mypy proof_agent`; `npm test -w proof-agent-dashboard -- --run`; `npm test -w proof-agent-chat -- --run`; `npm run build -w proof-agent-dashboard`; `npm run build -w proof-agent-chat`; `uv run --extra dev proof-agent demo`; `uv run --extra dev proof-agent react-demo`; and `uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml --question "What documents are required for inpatient claim reimbursement?"`. Then start `uv run --extra dashboard --extra ingestion --extra tree proof-agent verify-remote --local-only` and replay every runtime row in the matrix, including the API-run-before-CLI sequence for ISSUE-006 and PATCH/append/reload flows for ISSUE-008/010. Recompute the QA baseline and confirm every original issue is fixed without a new regression before marking the goal complete.
