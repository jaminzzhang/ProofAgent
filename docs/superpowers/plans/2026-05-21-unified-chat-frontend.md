# Unified Chat Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate operator and customer chat into one `chat/` SPA with explicit `/operator` and `/customer` modes.

**Architecture:** Build a shared `ChatShell` for layout, message rendering, composer, empty state, and side panels. Keep mode-specific API contracts in operator and customer adapters so the UI can share a normalized message model without merging backend trust boundaries.

**Tech Stack:** React 19, React Router, Vite, TypeScript, Tailwind CSS v4, Vitest, Testing Library.

---

### Task 1: Lock Frontend Routing And Adapter Boundaries

**Files:**
- Create: `chat/src/chat-core/types.ts`
- Create: `chat/src/pages/ModeSelectionPage.tsx`
- Create: `chat/src/modes/operator/operatorAdapter.ts`
- Create: `chat/src/modes/customer/customerAdapter.ts`
- Create: `chat/src/router.test.tsx`
- Create: `chat/src/modes/operator/operatorAdapter.test.ts`
- Create: `chat/src/modes/customer/customerAdapter.test.ts`
- Modify: `chat/src/router.tsx`
- Modify: `chat/src/api/client.ts`
- Modify: `chat/src/api/types.ts`

- [ ] Write failing tests for root mode selection and explicit namespaced routes.
- [ ] Write failing tests proving operator adapter calls `/api/chat/...`.
- [ ] Write failing tests proving customer adapter calls `/api/customer/...` and normalizes only customer-safe fields.
- [ ] Run targeted tests and verify they fail for missing routes/adapters.
- [ ] Implement minimal routing and adapters.
- [ ] Run targeted tests and verify they pass.

### Task 2: Build Shared Chat Shell And Migrate Operator Mode

**Files:**
- Create: `chat/src/chat-core/ChatShell.tsx`
- Create: `chat/src/modes/operator/OperatorChatPage.tsx`
- Modify: `chat/src/components/HistorySidebar.tsx`
- Modify: `chat/src/components/TopNav.tsx`
- Modify: `chat/src/App.tsx`
- Modify: `chat/src/pages/ChatPage.tsx`

- [ ] Add a failing test or extend route tests for operator-only audit affordances.
- [ ] Implement `ChatShell` with shared message list, composer, loading, error, and empty starter support.
- [ ] Move current `ChatPage` behavior into `OperatorChatPage` using `ChatShell`.
- [ ] Preserve operator conversation list, rename, pin, delete, governance checkbox, audit links, receipt links, approval review link.
- [ ] Run `cd chat && npm test`.

### Task 3: Migrate Customer Mode Into Shared Shell

**Files:**
- Create: `chat/src/modes/customer/CustomerChatPage.tsx`
- Create: `chat/src/modes/customer/CustomerSidebar.tsx`
- Create: `chat/src/modes/customer/FeedbackControl.tsx`
- Create: `chat/src/modes/customer/ProgressState.tsx`
- Create: `chat/src/modes/customer/SourceList.tsx`
- Modify: `chat/src/router.tsx`

- [ ] Add a failing test that customer rendering excludes audit links, governance details, approval state, raw run ids, receipt links, and internal handoff state.
- [ ] Migrate customer persona/session selector into customer mode.
- [ ] Clear customer conversation state when persona changes.
- [ ] Use `ChatShell` for customer message flow, progress state, safe sources, and feedback.
- [ ] Run `cd chat && npm test`.

### Task 4: Remove Independent Customer App And Update Docs

**Files:**
- Delete: `customer/`
- Modify: `AGENTS-COMMON.md`
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/examples/insurance-customer-service.md`
- Modify: `docs/development-progress.md`
- Modify: `docs/superpowers/specs/2026-05-20-v1-autonomous-customer-service-design.md`
- Modify: `proof_agent/delivery/cli.py`

- [ ] Delete migrated `customer/` app files.
- [ ] Replace customer frontend commands with `cd chat && npm run dev` and `/customer`.
- [ ] Remove statements that customer frontend is a separate app.
- [ ] Run `rg` to verify stale `cd customer`, `customer/` app, and port `5175` references are gone or historical.

### Task 5: Full Verification

**Files:**
- All touched files.

- [ ] Run `cd chat && npm run build`.
- [ ] Run `cd chat && npm test`.
- [ ] Run `uv run --extra dashboard --extra dev python -m pytest tests/test_conversation_api.py tests/test_customer_run_api.py tests/test_customer_journeys.py -v`.
- [ ] Run `git diff --check`.
- [ ] Inspect final diff for customer-safety and unrelated churn.
