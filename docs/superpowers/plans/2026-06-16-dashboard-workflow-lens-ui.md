# Dashboard Workflow Lens UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use frontend tests and backend contract tests before each slice implementation. Do not collapse the three slices into one broad UI rewrite.

**Goal:** Upgrade the Dashboard Workflow experience so Agent owners can understand, validate, release, and observe governed Workflow Template Stage behavior after the Workflow refactor.

**Architecture:** Keep Dashboard information architecture separated by user task instead of creating a mixed top-level Workflow workspace.

- **Design:** `Agents > Workflow` explains the selected Workflow Template and edits bounded Workflow Template Stage configuration.
- **Verify:** `Agents > Validate & Test` becomes a Validation Workspace for draft readiness, validation runs, validation history, and validation capture safe sections.
- **Observe:** `Runs > Run Detail > Workflow` uses a backend-owned Dashboard Workflow Run Projection to explain one run by Workflow Template Stage.

**Specs:** `CONTEXT.md`, `docs/frontend-design-principles.md`, `docs/technical-design.md`, `docs/developer-guide.md`, `docs/adr/0009-dashboard-hosted-agent-configuration-workspace.md`, `docs/adr/0010-dashboard-sidebar-navigation-separation.md`, `docs/adr/0011-agent-configuration-module-structure.md`, `docs/adr/0027-workflow-template-stage-terminology-cutover.md`, `docs/adr/0028-agent-contract-stage-capability-and-trace-capture-contract.md`.

---

## Non-Goals

- Do not add a standalone top-level Workflow workspace.
- Do not build a drag-and-drop workflow editor.
- Do not let Dashboard edit runtime graph topology, stage ordering, or branch edges.
- Do not make the Dashboard API an execution or orchestration path.
- Do not let the frontend parse JSONL trace into governed Workflow semantics.
- Do not expose raw prompt, raw context, raw evidence, raw tool payload, provider response, Workflow Stage Continuation State, runtime state, LangGraph state, or chain-of-thought.
- Do not keep public UI labels that use `node` for Workflow Template Stage concepts.

---

## UX Information Architecture

Agent Detail navigation should use task-oriented groups:

- **Overview**
  - Overview
- **Design**
  - Workflow
  - Knowledge
  - Tools
  - Policy
  - Model
  - Memory
  - Response
- **Verify**
  - Validate & Test
  - Contract View
- **Release**
  - Versions
- **Observe**
  - Monitor

Workflow appears through Dashboard Workflow Lens in three places:

- `Agents > Workflow`: design-time stage configuration.
- `Agents > Validate & Test`: draft validation and validation capture.
- `Runs > Run Detail > Workflow`: run-time stage facts and drilldown.

---

## Task 0: Baseline And Guardrails

- [x] **Step 0.1: Capture current git status**

Run:

```bash
git status --short --branch
```

Expected: only intentional planning/context files are modified before implementation starts.

- [x] **Step 0.2: Run current Dashboard and backend focused tests**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest tests/test_dashboard_contracts.py tests/test_run_store.py tests/test_run_execution_api.py tests/test_agent_configuration_api.py tests/test_validation_capture_contracts.py -q
cd dashboard && npm test -- --run
```

Expected: GREEN before implementation. Record existing failures before changing UI or API contracts.

- [x] **Step 0.3: Capture terminology debt**

Run:

```bash
rg "Workflow node|workflow node|Node Panel|node editor|ReAct Governance|JSONL Trace" dashboard/src docs CONTEXT.md -g '*.tsx' -g '*.ts' -g '*.md'
```

Expected: produce the working list of UI labels and docs that need stage/workflow-lens treatment.

---

## Task 1: Update Agent Detail Navigation Groups

**Goal:** Make the Agent detail shell match the user's mental model: design, verify, release, observe.

**Files likely affected:**

- `dashboard/src/components/agent/AgentDetailShell.tsx`
- `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`

- [x] **Step 1.1: Add a failing navigation grouping test**

Assert that Agent detail navigation renders the groups:

- `Overview`
- `Design`
- `Verify`
- `Release`
- `Observe`

Assert that `Workflow` appears under `Design`, `Validate & Test` and `Contract View` appear under `Verify`, `Versions` appears under `Release`, and `Monitor` appears under `Observe`.

- [x] **Step 1.2: Implement grouping change**

Update `AgentDetailShell` group construction only. Do not change routes, tab ids, or API calls in this step.

- [x] **Step 1.3: Verify**

Run:

```bash
cd dashboard && npm test -- --run src/pages/__tests__/AgentDetailPage.test.tsx
```

Expected: GREEN.

---

## Task 2: Redesign Agents > Workflow Around Template Summary, Map, And Inspector

**Goal:** Convert the Workflow module from "form plus stage list" into a governed Workflow design view.

**Current state:** `WorkflowModuleEditor` already loads a backend descriptor, reads and writes `workflow.stages[]`, renders a grouped stage list, and provides context preview. It needs stronger information architecture, clearer capability boundaries, and less YAML-first framing.

**Files likely affected:**

- `dashboard/src/components/agent/WorkflowModuleEditor.tsx`
- `dashboard/src/components/agent/WorkflowTemplateSummary.tsx` or local subcomponent
- `dashboard/src/components/agent/WorkflowRelationshipMap.tsx` or local subcomponent
- `dashboard/src/components/agent/WorkflowStageInspector.tsx` or local subcomponent
- `dashboard/src/components/agent/module-configs/workflow.ts`
- `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`
- `dashboard/src/utils/agentYaml.test.ts`

- [x] **Step 2.1: Add failing tests for primary Workflow layout**

Test that `Agents > Workflow` renders:

- template name
- descriptor version
- total stage count
- read-only relationship map label
- selected stage inspector
- advanced YAML toggle

Test that `Show YAML` is not the primary page content.

- [x] **Step 2.2: Add failing tests for stage terminology**

Test that the primary Workflow UI uses `stage` language and does not render public labels such as `Node Panel`, `node editor`, or `workflow node`.

- [x] **Step 2.3: Implement Workflow Template Summary**

Summary should show:

- `workflow.template`
- `workflow.runtime`
- `workflow.checkpointer.provider`
- descriptor version
- stage count
- model-bearing stage count
- editable stage count

Keep this dense and operational. Do not use a hero layout.

- [x] **Step 2.4: Implement Workflow Relationship Map**

Render a read-only map/list from `WorkflowTemplateDescriptor.stages`.

Show:

- stage label and id
- predecessor/successor relationship
- branch condition summary when available
- governed handoff points when available
- model-bearing badge
- required badge

The map must not expose drag handles, edge editors, or topology actions.

- [x] **Step 2.5: Implement Stage Inspector**

When a stage is selected, show:

- label, id, description
- input summary
- output summary
- model-bearing/governed status
- editable prompt fields
- context option selection
- context preview
- Harness-owned prompt authority notice

Group editing fields as:

- Business Context
- Task Instructions
- Output Preferences
- Context Options
- Preview

- [x] **Step 2.6: Move YAML to Advanced**

Keep generated YAML visible through an advanced toggle. The primary path should be descriptor summary, map, and inspector.

- [x] **Step 2.7: Verify**

Run:

```bash
cd dashboard && npm test -- --run src/pages/__tests__/AgentDetailPage.test.tsx src/utils/agentYaml.test.ts
cd dashboard && npm run build
```

Expected: tests and build pass.

---

## Task 3: Build Validation Workspace

**Goal:** Replace the "Quick Test" mental model with a draft validation workspace that explains readiness, latest result, history, and safe validation capture.

**Current state:** `ValidateWorkspace` can run a validation question and list validation records. The backend already exposes `/api/runs/{run_id}/validation-capture` for validation runs with `agent.validate` permission, but the frontend does not consume it.

**Files likely affected:**

- `dashboard/src/components/agent/ValidateWorkspace.tsx`
- `dashboard/src/components/agent/ValidationCapturePanel.tsx`
- `dashboard/src/api/types.ts`
- `dashboard/src/api/client.ts`
- `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`
- `dashboard/src/pages/__tests__/RunDetailPage.test.tsx`

- [x] **Step 3.1: Add frontend API types for validation capture**

Add TypeScript types matching `validation_capture.v2` sections:

- `source`
- `stage_prompt_values`
- `context_configuration`
- `context_applications`
- `stage_results`
- `result_summary`
- `exclusions`

Do not add raw content fields.

- [x] **Step 3.2: Add `fetchValidationCapture(runId)` client call**

Call:

```text
GET /api/runs/{run_id}/validation-capture
```

Return metadata and payload.

- [x] **Step 3.3: Add failing Validation Workspace tests**

Assert that the page renders:

- `Draft Readiness`
- `Run Validation`
- `Latest Validation Result`
- `Validation History`

Assert that the old label `Quick Test` is gone.

- [x] **Step 3.4: Implement Draft Readiness**

Use data already available to `AgentDetailPage` and `ValidateWorkspace` first:

- draft id
- latest validation status
- last validation run id
- validation error count
- publish eligibility signal when available

If deeper readiness requires new backend fields, add a TODO in the UI plan rather than inventing frontend-only truth.

- [x] **Step 3.5: Implement Latest Validation Result and History**

Show:

- latest outcome/status
- run id link to Run Detail
- created time
- summary
- top errors
- validation capture availability when `validation_capture_id` or link is present

- [x] **Step 3.6: Implement Validation Capture safe sections panel**

For validation runs only, reveal the safe sections returned by the backend endpoint.

Display semantic sections, not raw JSON first:

- Source
- Stage Prompt Values
- Context Configuration
- Context Applications
- Stage Results
- Result Summary
- Exclusions

JSON views may exist as drilldown inside each safe section.

- [x] **Step 3.7: Verify**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest tests/test_run_execution_api.py tests/test_agent_configuration_api.py tests/test_validation_capture_contracts.py -q
cd dashboard && npm test -- --run src/pages/__tests__/AgentDetailPage.test.tsx src/pages/__tests__/RunDetailPage.test.tsx
cd dashboard && npm run build
```

Expected: GREEN.

---

## Task 4: Add Backend Dashboard Workflow Run Projection

**Goal:** Add a backend-owned read projection that organizes trace-safe Workflow Template Execution facts by Workflow Template Stage for Run Detail.

**Current state:** `RunDetail` exposes trace events, receipt markdown, evidence chunks, model usage, approval state, pending approvals, and ReAct-specific `governance_details`. It does not expose a neutral stage-organized Workflow projection.

**Files likely affected:**

- `proof_agent/contracts/dashboard.py`
- `proof_agent/observability/storage/run_store.py`
- `proof_agent/observability/api/serializers.py`
- `tests/test_dashboard_contracts.py`
- `tests/test_run_store.py`
- `tests/test_run_execution_api.py`
- `dashboard/src/api/types.ts`

- [x] **Step 4.1: Add failing backend contract tests**

Add contract tests for a new Run Detail field, for example:

```text
workflow_projection
```

The projection should contain:

- template name when known
- descriptor version when known
- stage configuration source summary when known
- ordered stage projections

Each stage projection should contain:

- stage id
- label when known
- status
- outcome
- safe summary
- context application summary
- produced fact refs
- related event ids
- approval pause summary when applicable
- clarification need summary when applicable

- [x] **Step 4.2: Implement contract models**

Prefer typed Pydantic models in `proof_agent/contracts/dashboard.py` rather than loose dicts for the public Run Detail projection.

Do not include:

- continuation state
- raw runtime state
- raw prompt/context/evidence/tool payloads
- provider responses
- chain-of-thought

- [x] **Step 4.3: Extract projection in RunStore**

Build from existing persisted artifacts:

- `workflow_stage_configuration_trace_summary`
- `workflow_stage_context_applied`
- workflow stage result events if present
- approval events
- clarification events
- evidence/model/tool events as related event ids or counts

If a historical run lacks stage facts, return an empty or partial projection instead of fabricating stage semantics.

- [x] **Step 4.4: Serialize through the Dashboard API**

Ensure `/api/runs/{run_id}` includes the projection and frontend types compile.

- [x] **Step 4.5: Verify**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest tests/test_dashboard_contracts.py tests/test_run_store.py tests/test_run_execution_api.py -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
```

Expected: GREEN.

---

## Task 5: Build Run Detail Workflow Tab

**Goal:** Make Run Detail default to a governed Workflow understanding path while preserving existing drilldown tabs.

**Files likely affected:**

- `dashboard/src/pages/RunDetailPage.tsx`
- `dashboard/src/pages/tabs/WorkflowTab.tsx`
- `dashboard/src/pages/tabs/TimelineTab.tsx`
- `dashboard/src/pages/__tests__/RunDetailPage.test.tsx`
- `dashboard/src/api/types.ts`

- [x] **Step 5.1: Add failing Run Detail tests**

Assert that Run Detail renders a `Workflow` tab when `workflow_projection` is present.

Assert that the Workflow tab shows:

- stage list
- stage status
- outcome where available
- context application summary
- produced fact refs
- approval or clarification state when present

- [x] **Step 5.2: Add Workflow tab before artifact drilldowns**

Recommended tab order:

- Workflow
- Governance Receipt
- Approval State when needed
- Evidence Base
- Model Usage
- JSONL Trace

Keep `JSONL Trace` as a drilldown/debug artifact, not the primary explanation.

- [x] **Step 5.3: Replace or demote `ReAct Governance`**

If `workflow_projection` provides equivalent stage facts, do not keep `ReAct Governance` as a primary tab. Either:

- hide it when Workflow projection exists, or
- move legacy ReAct details inside a secondary compatibility section.

Do not expose the template implementation name as the main user-facing run explanation.

- [x] **Step 5.4: Link stage facts to drilldowns**

For each stage, provide links or anchors to related:

- evidence entries
- model usage
- approval action
- trace events

Use references and counts where exact linking is not yet available.

- [x] **Step 5.5: Verify**

Run:

```bash
cd dashboard && npm test -- --run src/pages/__tests__/RunDetailPage.test.tsx
cd dashboard && npm run build
```

Expected: GREEN.

---

## Task 6: Documentation And Final Verification

- [x] **Step 6.1: Update Dashboard docs**

Update the relevant docs after implementation:

- `docs/developer-guide.md`
- `docs/technical-design.md`
- `docs/development-progress.md`
- `docs/frontend-design-principles.md` if the Workflow Lens pattern needs to be named there

Document:

- Dashboard Workflow Lens
- Validation Workspace
- Dashboard Workflow Run Projection
- frontend does not parse JSONL into governed semantics

- [x] **Step 6.2: Search for stale labels**

Run:

```bash
rg "Workflow node|workflow node|Node Panel|node editor|ReAct Governance|Quick Test" dashboard/src docs CONTEXT.md -g '*.tsx' -g '*.ts' -g '*.md'
```

Expected: no stale user-facing labels remain unless intentionally documented as historical.

Result: current source/docs are clean when excluding historical implementation plans; remaining hits are only in `docs/superpowers/plans/**` historical records.

- [x] **Step 6.3: Full verification**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai --extra ingestion mypy proof_agent
cd dashboard && npm test -- --run
cd dashboard && npm run build
```

Expected: all checks pass.

Result: all checks pass. Full backend suite: `1030 passed, 3 warnings`. Dashboard suite: `104 passed`. Dashboard production build succeeded.

---

## Open Design Notes

- Stage availability details may require descriptor/API enrichment if the current `WorkflowStageDescriptor` cannot explain disabled capability reasons clearly enough.
- Publish readiness should not be inferred only in frontend. If the existing draft/validation records do not expose enough data, add a backend readiness projection in a later slice.
- Run Detail Workflow tab should be useful for historical runs with partial stage facts, but it should not invent missing facts.
- The existing `governance_details` field is ReAct-specific and should not become the long-term Dashboard Workflow projection.
