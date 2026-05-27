# Agent Configuration Workspace MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Dashboard-hosted Agent Configuration Workspace loop: import an Agent Package, edit a Draft Agent, validate it, publish an immutable version, monitor runs, and roll back the active version.

**Architecture:** Add a new configuration domain boundary under `proof_agent/configuration/` with contracts in `proof_agent/contracts/`, a local file-backed store, and a separate Agent Configuration API router. Keep existing Dashboard API read-only and keep production execution on Published Agent Versions resolved by the Run Execution API and Customer Run API.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, FastAPI, local JSON/YAML file storage, pytest, Vite/React/TypeScript/Tailwind CSS v4, Vitest.

---

## Scope Check

This MVP intentionally proves the vertical loop before deep configuration UX. It includes import, draft persistence, basic edit, Contract View, validation run, publication, active version resolution, rollback, and Agent-centric Dashboard pages.

Do not implement full RBAC, tenant management, full Tool Source administration, advanced Policy condition builder, multi-source parallel retrieval, memory lifecycle UI, or drag-and-drop workflow canvas in this plan.

## Decisions Already Recorded

- Domain language updated in `CONTEXT.md`.
- ADR added at `docs/adr/0009-dashboard-hosted-agent-configuration-workspace.md`.
- Agent configuration lives in the shared Dashboard Shell, but API boundaries remain separate.
- Draft Agent saves are not publication.
- Agent Publication requires a successful Agent Validation Run.
- Published Agent Versions are immutable; rollback changes the Active Agent Version pointer.
- Workflow editing is Workflow Template Node Configuration, first represented by a Workflow Node Panel.
- Knowledge and Tools use Source plus Binding concepts; Memory remains Agent-specific configuration in the MVP.
- Contract View is an advanced view over the same Draft Agent state, not a second source of truth.

## File Map

### Configuration Domain

- Create `proof_agent/contracts/agent_configuration.py`
  - Pydantic contracts for Draft Agent, Contract Bundle, Knowledge Source, Tool Source, Published Agent Version, Active Agent pointer, validation records, and operation audit metadata.
- Modify `proof_agent/contracts/__init__.py`
  - Export the new contracts.
- Create `proof_agent/configuration/__init__.py`
  - Public configuration package exports.
- Create `proof_agent/configuration/local_store.py`
  - Local Agent Configuration Store using directories and JSON/YAML files.
- Create `proof_agent/configuration/importer.py`
  - Convert reviewable Agent Packages into Draft Agents.
- Create `proof_agent/configuration/compiler.py`
  - Compile Draft Agent records into an on-disk Agent Package snapshot for validation and publication.
- Create `proof_agent/configuration/validation.py`
  - Coordinate contract validation and Agent Validation Runs.

### Execution And Run Metadata

- Modify `proof_agent/contracts/dashboard.py`
  - Add `RunPurpose`, `agent_id`, `agent_version_id`, `draft_id`, and `run_purpose` to run summaries/details/index metadata.
- Modify `proof_agent/observability/storage/run_store.py`
  - Persist and filter run purpose and Agent version metadata.
- Modify `proof_agent/runtime/langgraph_runner.py`
  - Accept optional run metadata and emit trace-safe run metadata.
- Modify `proof_agent/delivery/api.py`
  - Resolve active Published Agent Versions through the registry/store and pass metadata into runs.
- Modify `proof_agent/delivery/customer_api.py`
  - Same version-aware resolution for customer runs.
- Modify `proof_agent/delivery/published_agents.py`
  - Resolve default examples plus config-store-backed Published Agent Versions.

### Agent Configuration API

- Create `proof_agent/delivery/configuration_api.py`
  - Routes under `/api/config/...`.
- Modify `proof_agent/observability/api/app.py`
  - Initialize Local Agent Configuration Store and include the configuration router.

### Dashboard Frontend

- Modify `dashboard/src/api/types.ts`
  - Agent configuration DTOs and run purpose fields.
- Modify `dashboard/src/api/client.ts`
  - Agent Configuration API client functions.
- Create `dashboard/src/hooks/useAgents.ts`
- Create `dashboard/src/hooks/useAgentDetail.ts`
- Create `dashboard/src/pages/AgentsListPage.tsx`
- Create `dashboard/src/pages/AgentDetailPage.tsx`
- Create `dashboard/src/pages/agent/AgentMonitorTab.tsx`
- Create `dashboard/src/pages/agent/AgentConfigureTab.tsx`
- Create `dashboard/src/pages/agent/WorkflowNodePanel.tsx`
- Create `dashboard/src/pages/agent/ContractViewTab.tsx`
- Create `dashboard/src/pages/agent/ValidateTestTab.tsx`
- Create `dashboard/src/pages/agent/VersionsTab.tsx`
- Modify `dashboard/src/router.tsx`
- Modify `dashboard/src/components/Sidebar.tsx`
- Modify `dashboard/src/hooks/useRuns.ts`
- Modify `dashboard/src/pages/RunsListPage.tsx`
- Modify `dashboard/src/pages/OverviewPage.tsx`

### Tests And Docs

- Create `tests/test_agent_configuration_contracts.py`
- Create `tests/test_agent_configuration_store.py`
- Create `tests/test_agent_package_import.py`
- Create `tests/test_agent_configuration_api.py`
- Create `tests/test_published_agent_versions.py`
- Create `tests/test_run_store_metadata.py`
- Create `dashboard/src/pages/agent/WorkflowNodePanel.test.tsx`
- Create `dashboard/src/pages/AgentsListPage.test.tsx`
- Create `dashboard/src/pages/AgentDetailPage.test.tsx`
- Update `docs/technical-design.md`
- Update `docs/developer-guide.md`
- Update `docs/development-progress.md`

---

### Task 1: Add Agent Configuration Contracts

**Files:**
- Create: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/contracts/__init__.py`
- Test: `tests/test_agent_configuration_contracts.py`

- [ ] Write failing tests for Draft Agent, Contract Bundle, Published Agent Version, Active Agent Version, Knowledge Source, Tool Source, and operation audit payloads.
- [ ] Assert contracts are frozen and JSON-serializable.
- [ ] Assert Draft Agent and Published Agent Version keep separate identifiers.
- [ ] Assert Published Agent Version requires a validation run id.
- [ ] Run `uv run --extra dev python -m pytest tests/test_agent_configuration_contracts.py -v`.
- [ ] Implement the Pydantic contracts with explicit field names that match `CONTEXT.md`.
- [ ] Export the contracts from `proof_agent/contracts/__init__.py`.
- [ ] Re-run the targeted test and verify it passes.

### Task 2: Build The Local Agent Configuration Store

**Files:**
- Create: `proof_agent/configuration/__init__.py`
- Create: `proof_agent/configuration/local_store.py`
- Test: `tests/test_agent_configuration_store.py`

- [ ] Write failing tests for creating a Draft Agent, reading it back, updating it, listing drafts, and preserving operation audit metadata.
- [ ] Write failing tests for publishing an immutable version snapshot and updating `active_version.json`.
- [ ] Write failing tests proving rollback changes the active pointer without changing old version files.
- [ ] Use a temporary directory in tests; do not write into real `runs/config`.
- [ ] Run `uv run --extra dev python -m pytest tests/test_agent_configuration_store.py -v` and verify failure.
- [ ] Implement the local store layout under a configurable root:

```text
config/
  agents/{agent_id}/drafts/{draft_id}/
  agents/{agent_id}/versions/{version_id}/
  agents/{agent_id}/active_version.json
  knowledge_sources/{source_id}.json
  tool_sources/{source_id}.json
```

- [ ] Keep JSON writes deterministic with sorted keys and UTF-8.
- [ ] Re-run the targeted test and verify it passes.

### Task 3: Import Existing Agent Packages Into Draft Agents

**Files:**
- Create: `proof_agent/configuration/importer.py`
- Create: `proof_agent/configuration/compiler.py`
- Test: `tests/test_agent_package_import.py`

- [ ] Write failing tests that import `examples/enterprise_qa/agent.yaml` into a Draft Agent.
- [ ] Assert imported Draft Agent includes a Contract Bundle with `agent.yaml`, `policy.yaml`, and `tools.yaml` content.
- [ ] Assert relative paths are resolved for validation but Contract View preserves reviewable contract text.
- [ ] Assert import does not modify the source example files.
- [ ] Assert unsupported but valid fields are preserved in the Contract Bundle.
- [ ] Run `uv run --extra dev python -m pytest tests/test_agent_package_import.py -v` and verify failure.
- [ ] Implement `import_agent_package(manifest_path, store, imported_by)` using existing `load_agent_manifest` validation.
- [ ] Implement a compiler that writes a Draft Agent snapshot to a temporary Agent Package directory for validation/publication.
- [ ] Re-run the targeted test and verify it passes.

### Task 4: Add Run Purpose And Agent Version Metadata To RunStore

**Files:**
- Modify: `proof_agent/contracts/dashboard.py`
- Modify: `proof_agent/observability/storage/run_store.py`
- Modify: `proof_agent/runtime/langgraph_runner.py`
- Test: `tests/test_run_store_metadata.py`

- [ ] Write failing tests for persisted `run_meta.json` containing `run_purpose`, `agent_id`, `agent_version_id`, and `draft_id`.
- [ ] Write failing tests that `list_runs()` defaults to production runs but can include validation runs through an explicit filter.
- [ ] Write failing tests that RunDetail exposes the same metadata.
- [ ] Run `uv run --extra dev python -m pytest tests/test_run_store_metadata.py -v` and verify failure.
- [ ] Add a `RunPurpose` contract with `production`, `validation`, and `preview`.
- [ ] Extend `RunIndex`, `RunSummary`, and `RunDetail` with optional Agent metadata.
- [ ] Extend `RunStore.save_run_artifacts()` and filtering without breaking existing callers.
- [ ] Extend `run_with_langgraph()` to accept optional run metadata and pass it into finalization/storage.
- [ ] Re-run the targeted test and existing run store/API tests.

### Task 5: Resolve Published Agent Versions For Execution

**Files:**
- Modify: `proof_agent/delivery/published_agents.py`
- Modify: `proof_agent/delivery/api.py`
- Modify: `proof_agent/delivery/customer_api.py`
- Test: `tests/test_published_agent_versions.py`

- [ ] Write failing tests that the registry still resolves default example agents.
- [ ] Write failing tests that a config-store-backed Published Agent resolves to its Active Agent Version manifest.
- [ ] Write failing tests that production runs record the resolved `agent_version_id`.
- [ ] Write failing tests that arbitrary manifest paths are still rejected by execution APIs.
- [ ] Run `uv run --extra dashboard --extra dev python -m pytest tests/test_published_agent_versions.py -v` and verify failure.
- [ ] Update `PublishedAgentRegistry` to optionally accept an Agent Configuration Store.
- [ ] Return a resolved manifest path plus Agent version metadata from the registry.
- [ ] Update Run Execution API and Customer Run API helpers to use the resolved version metadata.
- [ ] Re-run targeted tests plus `tests/test_conversation_api.py` and `tests/test_customer_run_api.py`.

### Task 6: Add Agent Configuration API

**Files:**
- Create: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/observability/api/app.py`
- Test: `tests/test_agent_configuration_api.py`

- [ ] Write failing API tests for `GET /api/config/agents`.
- [ ] Write failing API tests for importing an existing Agent Package into a Draft Agent.
- [ ] Write failing API tests for reading/updating Draft Agent basic fields and Contract View.
- [ ] Write failing API tests for triggering an Agent Validation Run with `run_purpose: validation`.
- [ ] Write failing API tests for publishing a Draft Agent after validation.
- [ ] Write failing API tests for rollback.
- [ ] Run `uv run --extra dashboard --extra dev python -m pytest tests/test_agent_configuration_api.py -v` and verify failure.
- [ ] Implement a router under `/api/config`.
- [ ] Initialize `LocalAgentConfigurationStore` in `create_app()` with a default root such as `runs/config`.
- [ ] Keep validation endpoints separate from production execution endpoints.
- [ ] Return actionable error payloads for invalid contracts, missing drafts, and missing validation runs.
- [ ] Re-run targeted tests.

### Task 7: Add Dashboard Agent Configuration API Client And Types

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Create: `dashboard/src/hooks/useAgents.ts`
- Create: `dashboard/src/hooks/useAgentDetail.ts`

- [ ] Add TypeScript types for Agent summaries, Draft Agent, Published Agent Version, Contract Bundle, validation record, Knowledge Source, Tool Source, and Run Purpose.
- [ ] Add client functions for list/import/get/update/validate/publish/rollback.
- [ ] Add hook tests if the existing dashboard test pattern supports hooks; otherwise test through pages in later tasks.
- [ ] Run `cd dashboard && npm test` and verify current tests still pass.

### Task 8: Add Agents Navigation And List Page

**Files:**
- Create: `dashboard/src/pages/AgentsListPage.tsx`
- Create: `dashboard/src/pages/AgentsListPage.test.tsx`
- Modify: `dashboard/src/router.tsx`
- Modify: `dashboard/src/components/Sidebar.tsx`

- [ ] Write a failing test that `/agents` renders imported/default Agents with active version, draft status, last validation status, and recent run health.
- [ ] Write a failing test that the sidebar includes `Agents`.
- [ ] Implement the Agents list with dense operational styling consistent with the existing Dashboard.
- [ ] Add an import action that calls Agent Package Import for configured examples or a selected server-known package id.
- [ ] Avoid a marketing/landing page; this is an operational work surface.
- [ ] Run `cd dashboard && npm test`.

### Task 9: Build Agent Detail Shell With Monitor And Configure Tabs

**Files:**
- Create: `dashboard/src/pages/AgentDetailPage.tsx`
- Create: `dashboard/src/pages/AgentDetailPage.test.tsx`
- Create: `dashboard/src/pages/agent/AgentMonitorTab.tsx`
- Create: `dashboard/src/pages/agent/AgentConfigureTab.tsx`
- Modify: `dashboard/src/router.tsx`
- Modify: `dashboard/src/hooks/useRuns.ts`

- [ ] Write failing tests for `/agents/:agentId` rendering Monitor and Configure tabs.
- [ ] Write failing tests that Monitor filters runs by Agent id and defaults away from validation runs.
- [ ] Implement the tab shell with `Monitor`, `Configure`, `Validate & Test`, `Versions`, and `Contract View`.
- [ ] Reuse existing outcome badges, tables, and loading/error states.
- [ ] Add run purpose filter support in `useRuns`.
- [ ] Run `cd dashboard && npm test`.

### Task 10: Implement Workflow Node Panel And Basic Configuration Editing

**Files:**
- Create: `dashboard/src/pages/agent/WorkflowNodePanel.tsx`
- Create: `dashboard/src/pages/agent/WorkflowNodePanel.test.tsx`
- Modify: `dashboard/src/pages/agent/AgentConfigureTab.tsx`

- [ ] Write failing tests that `react_enterprise_qa` displays planner, retrieval, review, tool gate, answer gate, memory, and response nodes.
- [ ] Write failing tests that locked nodes cannot be deleted or reordered.
- [ ] Write failing tests that editing core fields updates the Draft Agent state through the API client.
- [ ] Implement an ordered, expandable Workflow Node Panel.
- [ ] Include configured/missing/advanced/locked states.
- [ ] Link each node to the relevant Contract View section.
- [ ] Do not implement drag/drop, zoom, or canvas layout.
- [ ] Run `cd dashboard && npm test`.

### Task 11: Add Contract View, Validate/Test, Versions, And Rollback UI

**Files:**
- Create: `dashboard/src/pages/agent/ContractViewTab.tsx`
- Create: `dashboard/src/pages/agent/ValidateTestTab.tsx`
- Create: `dashboard/src/pages/agent/VersionsTab.tsx`
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`

- [ ] Write failing tests that Contract View shows `agent.yaml`, `policy.yaml`, and `tools.yaml`.
- [ ] Write failing tests that unsupported advanced fields are displayed as preserved rather than dropped.
- [ ] Write failing tests that Validate & Test triggers an Agent Validation Run and shows trace/receipt links.
- [ ] Write failing tests that Versions lists immutable versions and exposes rollback for non-active versions.
- [ ] Implement read-only Contract View first; editable advanced Contract View can be added only if parser/validation is wired.
- [ ] Implement validation and publish buttons with disabled states until requirements are met.
- [ ] Implement rollback confirmation with clear active version result.
- [ ] Run `cd dashboard && npm test`.

### Task 12: Update Overview And Runs For Run Purpose

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/pages/RunsListPage.tsx`
- Modify: `dashboard/src/pages/OverviewPage.tsx`
- Modify: `dashboard/src/hooks/useRuns.ts`

- [ ] Add tests or page assertions that production metrics exclude validation runs by default.
- [ ] Add a Runs filter for `Production`, `Validation`, and `Preview`.
- [ ] Show run purpose in Runs rows when non-production.
- [ ] Keep Overview metrics production-focused by default.
- [ ] Run `cd dashboard && npm test`.

### Task 13: Documentation Update

**Files:**
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`

- [ ] Document the Agent Configuration API boundary separately from Dashboard API and execution APIs.
- [ ] Document the Local Agent Configuration Store layout as the first implementation, not a permanent production storage choice.
- [ ] Document Draft Agent, Agent Validation Run, Agent Publication, Published Agent Version, Active Agent Version, and rollback.
- [ ] Document the MVP scope and explicitly deferred items.
- [ ] Keep Chinese docs under `docs/zh/` unchanged.
- [ ] Run `git diff --check`.

### Task 14: Full Verification

**Files:**
- All touched files.

- [ ] Run Python contract/store/API tests:

```bash
uv run --extra dashboard --extra dev python -m pytest \
  tests/test_agent_configuration_contracts.py \
  tests/test_agent_configuration_store.py \
  tests/test_agent_package_import.py \
  tests/test_run_store_metadata.py \
  tests/test_published_agent_versions.py \
  tests/test_agent_configuration_api.py -v
```

- [ ] Run existing execution API and customer API tests:

```bash
uv run --extra dashboard --extra dev python -m pytest \
  tests/test_conversation_api.py \
  tests/test_customer_run_api.py \
  tests/test_customer_journeys.py -v
```

- [ ] Run Dashboard tests and build:

```bash
cd dashboard && npm test
cd dashboard && npm run build
```

- [ ] Run lint/type checks expected for runtime changes:

```bash
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
```

- [ ] Run `git diff --check`.
- [ ] Inspect the final diff for API boundary violations, accidental Dashboard API execution behavior, or lost Contract View fields.
