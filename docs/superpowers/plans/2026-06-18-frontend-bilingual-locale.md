# Frontend Bilingual Locale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dashboard and Unified Chat support English/Simplified Chinese static UI switching with a shared language preference.

**Architecture:** Add small local i18n providers to each SPA instead of introducing a dependency. Default locale is inferred from browser/system language (`zh-*` -> `zh-CN`, everything else -> `en-US`), while a manual top-nav toggle persists `proof-agent-locale` across Dashboard and Chat. Translate static UI text, keep backend content, IDs, YAML/JSON, trace/receipt payloads, and core contract/audit terms unchanged.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, React Testing Library, Tailwind CSS v4.

---

### Task 1: Locale Provider And Toggle

**Files:**
- Create: `dashboard/src/i18n/locale.tsx`
- Create: `chat/src/i18n/locale.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `chat/src/App.tsx`
- Modify: `dashboard/src/components/TopNav.tsx`
- Modify: `chat/src/components/TopNav.tsx`
- Test: `dashboard/src/i18n/locale.test.tsx`
- Test: `chat/src/i18n/locale.test.tsx`

- [ ] **Step 1: Write failing tests**

Cover browser-language defaulting, persisted manual override, and top-nav language toggle rendering.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd dashboard && npm test -- locale
cd chat && npm test -- locale
```

Expected: fail because locale modules do not exist.

- [ ] **Step 3: Implement provider and toggle**

Add `LocaleProvider`, `useLocale`, `LanguageToggleButton`, localized date/number helpers, and document `lang` updates.

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd dashboard && npm test -- locale
cd chat && npm test -- locale
```

Expected: pass.

### Task 2: Chat Static UI Localization

**Files:**
- Modify: `chat/src/chat-core/ChatShell.tsx`
- Modify: `chat/src/components/AgentSelectionPanel.tsx`
- Modify: `chat/src/components/HistorySidebar.tsx`
- Modify: `chat/src/components/TopNav.tsx`
- Modify: `chat/src/modes/customer/*.tsx`
- Modify: `chat/src/modes/operator/*.tsx`
- Modify: `chat/src/pages/ModeSelectionPage.tsx`
- Test: `chat/src/App.test.tsx`
- Test: `chat/src/chat-core/ChatShell.test.tsx`

- [ ] **Step 1: Write failing tests**

Assert Simplified Chinese mode renders representative root, operator, customer, empty, loading, and toggle labels without exposing operator-only customer content.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd chat && npm test
```

Expected: fail until translations are wired.

- [ ] **Step 3: Replace static Chat strings**

Use translation keys for visible UI and aria labels. Leave API response content, user/assistant messages, sources, IDs, and status codes unchanged.

- [ ] **Step 4: Run Chat tests and build**

Run:

```bash
cd chat && npm test
cd chat && npm run build
```

Expected: pass.

### Task 3: Dashboard Static UI Localization

**Files:**
- Modify: `dashboard/src/components/**/*.tsx`
- Modify: `dashboard/src/pages/**/*.tsx`
- Modify: `dashboard/src/pages/tabs/*.tsx`
- Test: existing Dashboard tests plus focused locale assertions

- [ ] **Step 1: Write failing tests**

Assert Simplified Chinese mode renders representative navigation, Overview, Runs, Agents, Run Detail tabs, and locale-formatted dates while keeping IDs/outcomes/code-like values unchanged.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd dashboard && npm test
```

Expected: fail until translations are wired.

- [ ] **Step 3: Replace static Dashboard strings**

Use translation keys for page headings, nav, buttons, filters, table headers, empty/error/loading copy, labels, and aria labels. Keep Agent/Workflow/Governance/Trace/YAML/JSON/Run ID terminology as agreed.

- [ ] **Step 4: Run Dashboard tests and build**

Run:

```bash
cd dashboard && npm test
cd dashboard && npm run build
```

Expected: pass.

### Task 4: Final Verification

**Files:**
- Review: `git diff`

- [ ] **Step 1: Run both frontend verification suites**

Run:

```bash
cd dashboard && npm test && npm run build
cd chat && npm test && npm run build
git diff --check
```

Expected: pass.

- [ ] **Step 2: Summarize scope and any residual untranslated technical values**

Report that static UI is localized and dynamic backend content remains unchanged by design.
