# Agent Contract YAML Stage Capability Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace public Agent Contract YAML workflow node terminology with `workflow.stages[]`, introduce top-level `capabilities` for optional tool and memory stage groups, publish frozen effective Workflow Stage configuration snapshots, and add validation-only full capture artifacts while preserving summary-only production traces.

**Architecture:** Treat Workflow Template Stage as the stable Agent Contract unit and keep Runtime Plane graph node terminology internal. The Agent Contract YAML stores stage overrides only; descriptors own defaults and allowed Prompt/context fields; Published Agent Versions freeze an effective stage configuration snapshot. Capability domains are explicit top-level switches. Validation runs may opt into sensitive full capture artifacts, while production/customer-facing runs remain summary-only.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, YAML Agent Contract loading, FastAPI Agent Configuration API, local file-backed Agent Configuration Store, LangGraph runtime adapter, JSONL trace, pytest, React 19, TypeScript, Vite, Vitest.

**Specs:** `CONTEXT.md`, `docs/adr/0027-workflow-template-stage-terminology-cutover.md`, `docs/adr/0028-agent-contract-stage-capability-and-trace-capture-contract.md`

---

## Implementation Invariants

- Direct cutover only. Do not dual-read `workflow.nodes[]`, `node_id`, `stage_id`, top-level `tools`, or top-level `memory`.
- Public/domain Workflow Template terminology is `stage`; Runtime Plane graph nodes may still use node terms.
- `ReActWorkflowNodes` remains named as-is in Slice 1; only its Agent Contract consumption changes from `workflow.nodes` to `workflow.stages`.
- Retrieval/local-index document `node_id` and unrelated tree/document node terms are out of scope.
- Prompt override fields remain limited to `business_context`, `task_instructions[]`, and `output_preferences[]`.
- Reject `system_prompt`, `developer_prompt`, `raw_prompt`, and `role_guidance` in Agent-owner stage Prompt config.
- `knowledge_bindings[]` remains separate from `capabilities`.
- Production and customer-facing runs must never persist full Prompt/context/intermediate-result capture.

## Small-Step Verification Cadence

Each behavior step must follow this loop before moving on:

1. Add or update the smallest targeted test for the behavior.
2. Run only that targeted test and confirm RED when feasible.
3. Implement the smallest code change.
4. Re-run the same targeted test and confirm GREEN.
5. Run the local file-level or slice-level test set before the next task.

Do not wait until the full refactor is complete to run tests.

When a targeted pytest command includes FastAPI/Dashboard configuration API tests,
run it with Dashboard and Local Index extras because that test module also covers
knowledge ingestion endpoints:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest ...
```

## Allowed Residual Node Terms

Leave these alone unless a later slice explicitly targets them:

- `proof_agent/control/workflow/react_nodes.py::ReActWorkflowNodes` class name.
- LangGraph/runtime graph node variables and comments that describe runtime execution nodes.
- Retrieval, local-index, document-tree, or LlamaIndex `node_id` fields.
- Historical ADRs/plans that intentionally document the old terminology.

## File Structure

Modify:

- `proof_agent/contracts/manifest.py` — rename Workflow Node config contracts to Workflow Stage config contracts and add `CapabilitiesConfig`.
- `proof_agent/contracts/__init__.py` — export new contract names and remove old public Workflow Node exports.
- `proof_agent/bootstrap/manifest.py` — load `workflow.stages[]`, `id`, and `capabilities`; reject old shapes.
- `proof_agent/bootstrap/validation.py` — validate stages, capability readiness, disabled active config, descriptor allowlists, and context capability dependencies.
- `proof_agent/control/workflow/templates.py` — rename descriptor surface from nodes to stages.
- `proof_agent/control/workflow/node_context.py` -> `proof_agent/control/workflow/stage_context.py` — stage Prompt/context preview and trace-safe summary.
- `proof_agent/control/workflow/react_nodes.py` — keep class name, consume stage configs, emit stage trace summaries.
- `proof_agent/control/workflow/harness_helpers.py` — rename payload keys from workflow node context to workflow stage context.
- `proof_agent/capabilities/react/planner.py` — accept stage context payloads.
- `proof_agent/capabilities/react/intent.py` — accept stage context payloads.
- `proof_agent/capabilities/review/subagent.py` — accept stage context payloads.
- `proof_agent/contracts/trace.py` — replace `WORKFLOW_NODE_CONTEXT_APPLIED` with `WORKFLOW_STAGE_CONTEXT_APPLIED`.
- `proof_agent/contracts/agent_configuration.py` — add effective workflow stage snapshot and validation capture metadata contracts.
- `proof_agent/configuration/local_store.py` — freeze effective stage snapshots at publish time and store sensitive validation capture artifacts.
- `proof_agent/delivery/configuration_api.py` — expose `workflow-stages` APIs and validation full-capture switch.
- `proof_agent/observability/storage/run_store.py` — project summary-only stage traces and validation capture artifact references.
- `proof_agent/observability/api/routers/runs.py` — gate sensitive validation capture reads behind operator permissions.
- `dashboard/src/api/types.ts` — rename workflow node API types to stage types.
- `dashboard/src/api/client.ts` — rename workflow node API calls and route paths.
- `dashboard/src/pages/AgentDetailPage.tsx` — wire stage editor callbacks.
- `dashboard/src/components/agent/WorkflowModuleEditor.tsx` — rename public UI copy and data model to stages.
- `dashboard/src/utils/agentYaml.ts` — parse/render `workflow.stages[]` with `id`.
- Source-controlled examples/fixtures/docs using old Agent Contract YAML shape.

Tests:

- `tests/test_config_loader.py`
- `tests/test_workflow_templates.py`
- `tests/test_workflow_stage_context.py` (rename from `tests/test_workflow_node_context.py`)
- `tests/test_workflow_react_enterprise_qa.py`
- `tests/test_trace_model_events.py`
- `tests/test_agent_configuration_api.py`
- `tests/test_agent_configuration_contracts.py`
- `tests/test_agent_configuration_store.py`
- `tests/test_published_agent_versions.py`
- `tests/test_run_store_metadata.py`
- `tests/test_run_execution_api.py`
- `dashboard/src/utils/agentYaml.test.ts`
- `dashboard/src/api/client.test.ts`
- `dashboard/src/components/__tests__/agent/WorkflowModuleEditor.test.tsx`
- `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`

---

## Task 0: Baseline And Guardrails

**Files:**
- Read-only: `CONTEXT.md`
- Read-only: `docs/adr/0027-workflow-template-stage-terminology-cutover.md`
- Read-only: `docs/adr/0028-agent-contract-stage-capability-and-trace-capture-contract.md`

- [x] **Step 0.1: Capture current status**

Run:

```bash
git status --short
```

Expected: see only intentional ADR/context/plan work before code changes. Do not revert unrelated user changes.

- [x] **Step 0.2: Run current focused baseline**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py tests/test_workflow_templates.py tests/test_workflow_node_context.py tests/test_agent_configuration_api.py -q
```

Expected: pass before refactor, or record existing failures before making code changes.

- [x] **Step 0.3: Classify residual node references**

Run:

```bash
rg "WorkflowNode|workflow_node|workflow-nodes|workflow\\.nodes|node_id|nodes\\[\\]" proof_agent dashboard/src tests -g '*.py' -g '*.ts' -g '*.tsx'
```

Expected: produce a working list. Mark retrieval/local-index/document-node hits as out of scope.

---

## Task 1: Agent Contract YAML Schema Cutover

**Files:**
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Test: `tests/test_config_loader.py`

- [x] **Step 1.1: Add stage loader acceptance test**

In `tests/test_config_loader.py`, replace the old successful workflow-node fixture with a stage fixture:

```yaml
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  template_descriptor_version: react_enterprise_qa.v1
  stages:
    - id: plan
      prompt:
        business_context: "Insurance claim servicing context."
        task_instructions:
          - "Prefer retrieval before final answers."
      context:
        include_agent_purpose: true
capabilities:
  tools:
    enabled: false
  memory:
    enabled: false
```

Assert:

```python
assert manifest.workflow.stages[0].id == "plan"
assert manifest.capabilities.tools.enabled is False
assert manifest.capabilities.memory.enabled is False
```

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py::test_loads_workflow_stage_prompt_config -q
```

Expected RED: missing `stages`/`capabilities` contract fields.

- [x] **Step 1.2: Implement minimal stage and capability contracts**

In `proof_agent/contracts/manifest.py`, introduce:

```python
class WorkflowStagePromptConfig(FrozenModel): ...
class WorkflowStageContextConfig(FrozenModel): ...
class WorkflowStageConfig(FrozenModel):
    id: str
    prompt: WorkflowStagePromptConfig = Field(default_factory=WorkflowStagePromptConfig)
    context: WorkflowStageContextConfig = Field(default_factory=WorkflowStageContextConfig)

class ToolCapabilityConfig(FrozenModel):
    enabled: bool
    file: Path | None = None

class MemoryCapabilityConfig(FrozenModel):
    enabled: bool
    provider: str | None = None
    scopes: Mapping[str, bool] = Field(default_factory=FrozenDict)

class CapabilitiesConfig(FrozenModel):
    tools: ToolCapabilityConfig
    memory: MemoryCapabilityConfig
```

Update `WorkflowConfig.stages` and `AgentManifest.capabilities`. Remove public `WorkflowNode*`, top-level `tools`, and top-level `memory` fields.

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py::test_loads_workflow_stage_prompt_config -q
```

Expected: still RED until loader mapping is updated.

- [x] **Step 1.3: Implement loader mapping for `workflow.stages[]` and `capabilities`**

In `proof_agent/bootstrap/manifest.py`:

- Read `workflow.get("stages", ())`.
- Require each stage item to be a mapping with `id`.
- Reject `node_id` and `stage_id` keys.
- Read required top-level `capabilities`.
- Read `capabilities.tools.enabled` and `capabilities.memory.enabled` explicitly.
- Normalize prompt/context using new stage contract classes.

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py::test_loads_workflow_stage_prompt_config -q
```

Expected GREEN.

- [x] **Step 1.4: Add legacy rejection tests**

Add targeted tests:

- `workflow.nodes[]` is rejected.
- stage item `node_id` is rejected.
- stage item `stage_id` is rejected.
- top-level `tools` is rejected.
- top-level `memory` is rejected.
- missing `capabilities.tools.enabled` or `capabilities.memory.enabled` is rejected for React templates.

Run each test after adding it, for example:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py::test_rejects_legacy_workflow_nodes -q
uv run --extra dev python -m pytest tests/test_config_loader.py::test_rejects_workflow_stage_node_id -q
uv run --extra dev python -m pytest tests/test_config_loader.py::test_rejects_workflow_stage_stage_id -q
uv run --extra dev python -m pytest tests/test_config_loader.py::test_rejects_legacy_top_level_tools -q
uv run --extra dev python -m pytest tests/test_config_loader.py::test_rejects_legacy_top_level_memory -q
uv run --extra dev python -m pytest tests/test_config_loader.py::test_react_template_requires_explicit_capability_enabled_flags -q
```

Expected RED one by one before implementation, GREEN after each narrow loader/validation update.

- [x] **Step 1.5: Add capability semantic validation tests**

Add tests:

- `capabilities.tools.enabled: false` with active `file` config is rejected.
- `capabilities.tools.enabled: true` without at least one valid Tool Contract is rejected.
- `capabilities.memory.enabled: false` with active provider/scopes config is rejected.
- `capabilities.memory.enabled: true` without provider is rejected.
- scoped memory provider with all scopes false is rejected.

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py -q
```

Expected: full config loader suite passes.

- [x] **Step 1.6: Commit Slice 1 backend schema cutover**

Run:

```bash
git status --short
git add proof_agent/contracts/manifest.py proof_agent/contracts/__init__.py proof_agent/bootstrap/manifest.py proof_agent/bootstrap/validation.py tests/test_config_loader.py
git commit -m "Cut agent contract schema to workflow stages"
```

---

## Task 2: Workflow Template Descriptor Stage Surface

**Files:**
- Modify: `proof_agent/control/workflow/templates.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Test: `tests/test_workflow_templates.py`
- Test: `tests/test_trace_model_events.py`

- [x] **Step 2.1: Add descriptor stage tests**

Update `tests/test_workflow_templates.py` to assert:

```python
assert [stage.id for stage in descriptor.stages] == [
    "plan",
    "clarification",
    "retrieval_review",
    "retrieval",
    "model_answer",
    "tool_review",
    "tool",
    "memory",
    "response",
]
assert descriptor.stage("plan").label == "Plan"
```

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_templates.py -q
```

Expected RED until descriptor contracts are renamed.

- [x] **Step 2.2: Rename descriptor dataclasses and methods**

In `proof_agent/control/workflow/templates.py`:

- `WorkflowNodeDescriptor` -> `WorkflowStageDescriptor`.
- `WorkflowTemplate.nodes` -> `WorkflowTemplate.stages`.
- `WorkflowTemplate.node(node_id)` -> `WorkflowTemplate.stage(stage_id)`.
- Internal helper `_react_enterprise_qa_v2_nodes()` -> `_react_enterprise_qa_v2_stages()`.
- Error messages say `unsupported workflow stage id`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_templates.py -q
```

Expected GREEN for descriptor tests.

- [x] **Step 2.3: Update validation to descriptor stages**

In `proof_agent/bootstrap/validation.py`:

- Rename exported validator to `validate_workflow_stage_prompt_config`.
- Iterate `manifest.workflow.stages`.
- Validate duplicate `stage id`.
- Validate descriptor stage lookup with `descriptor.stage(stage_config.id)`.
- Keep editable Prompt field allowlist unchanged.
- Keep forbidden Prompt fields rejected.

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py tests/test_workflow_templates.py -q
```

Expected GREEN.

- [x] **Step 2.4: Rename trace event enum**

In `proof_agent/contracts/trace.py`, replace:

```python
WORKFLOW_NODE_CONTEXT_APPLIED = "workflow_node_context_applied"
```

with:

```python
WORKFLOW_STAGE_CONTEXT_APPLIED = "workflow_stage_context_applied"
```

Update `tests/test_trace_model_events.py`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_trace_model_events.py -q
```

Expected GREEN.

- [x] **Step 2.5: Commit descriptor stage surface**

Run:

```bash
git status --short
git add proof_agent/control/workflow/templates.py proof_agent/bootstrap/validation.py proof_agent/contracts/trace.py tests/test_workflow_templates.py tests/test_trace_model_events.py
git commit -m "Rename workflow template descriptors to stages"
```

---

## Task 3: Runtime Stage Configuration Consumption

**Files:**
- Rename: `proof_agent/control/workflow/node_context.py` -> `proof_agent/control/workflow/stage_context.py`
- Rename: `tests/test_workflow_node_context.py` -> `tests/test_workflow_stage_context.py`
- Modify: `proof_agent/control/workflow/react_nodes.py`
- Modify: `proof_agent/control/workflow/harness_helpers.py`
- Modify: `proof_agent/capabilities/react/planner.py`
- Modify: `proof_agent/capabilities/react/intent.py`
- Modify: `proof_agent/capabilities/review/subagent.py`
- Test: `tests/test_workflow_stage_context.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`

- [x] **Step 3.1: Rename stage context tests first**

Move the test file and update public assertions:

- `build_workflow_stage_context_preview`
- `workflow_stage_context_summary`
- payload key `stage_id`
- context key `workflow_stage_context`
- trace event `workflow_stage_context_applied`

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_stage_context.py -q
```

Expected RED until implementation is renamed.

- [x] **Step 3.2: Rename context module API**

Move module contents to `stage_context.py` and update function names and payload keys:

```python
def build_workflow_stage_context_preview(..., stage_id: str, ...) -> dict[str, Any]: ...
def workflow_stage_context_summary(preview: Mapping[str, Any]) -> dict[str, Any]: ...
```

Preview and summary payloads must include `stage_id`, never `node_id`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_stage_context.py -q
```

Expected GREEN.

- [x] **Step 3.3: Update ReAct runtime consumption**

In `proof_agent/control/workflow/react_nodes.py`:

- Keep `ReActWorkflowNodes` class name.
- Build `self.workflow_stage_configs = {stage.id: stage for stage in self.manifest.workflow.stages}`.
- Rename local method parameters from `node_id` to `stage_id` where they refer to Workflow Template Stage.
- Emit `workflow_stage_context_applied`.
- Payload includes `stage_id`.
- Runtime context keys use `workflow_stage_context` and `workflow_stage_context_summary`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_workflow_stage_context_extends_model_prompt_without_replacing_system_prompt -q
```

Expected GREEN after updating the test name/body.

- [x] **Step 3.4: Update model/review payload plumbing**

In helper/capability modules, rename accepted payload keys:

- `workflow_node_context` -> `workflow_stage_context`
- `workflow_node_context_summary` -> `workflow_stage_context_summary`

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py -q
```

Expected GREEN.

- [x] **Step 3.5: Commit runtime stage consumption**

Run:

```bash
git status --short
git add proof_agent/control/workflow/stage_context.py proof_agent/control/workflow/react_nodes.py proof_agent/control/workflow/harness_helpers.py proof_agent/capabilities/react/planner.py proof_agent/capabilities/react/intent.py proof_agent/capabilities/review/subagent.py tests/test_workflow_stage_context.py tests/test_workflow_react_enterprise_qa.py
git add -u proof_agent/control/workflow/node_context.py tests/test_workflow_node_context.py
git commit -m "Consume workflow stage config in ReAct runtime"
```

---

## Task 4: Agent Configuration API Stage Surface

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `tests/test_agent_configuration_api.py`

- [x] **Step 4.1: Update API tests to stage routes and payloads**

In `tests/test_agent_configuration_api.py`, replace expectations:

- `body["nodes"]` -> `body["stages"]`
- `node_id` -> `id` for Workflow Template Stage payloads.
- `PATCH /workflow-nodes` -> `PATCH /workflow-stages`
- `POST /workflow-nodes/{node_id}/preview` -> `POST /workflow-stages/{stage_id}/preview`
- preview response `node_id` -> `stage_id`

Run one updated test at a time:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py::test_workflow_template_descriptor_lists_stages -q
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py::test_update_workflow_stages_persists_valid_stage_config -q
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py::test_preview_workflow_stage_context -q
```

Expected RED until API is updated.

- [x] **Step 4.2: Rename request models and routes**

In `proof_agent/delivery/configuration_api.py`:

- `WorkflowNodePromptRequest` -> `WorkflowStagePromptRequest`.
- `WorkflowNodeUpdateItemRequest` -> `WorkflowStageUpdateItemRequest` with `id`.
- `WorkflowNodesUpdateRequest` -> `WorkflowStagesUpdateRequest` with `stages`.
- `WorkflowNodePreviewRequest` -> `WorkflowStagePreviewRequest`.
- Route path `/workflow-stages`.
- Route function `update_config_draft_workflow_stages`.
- Preview path `/workflow-stages/{stage_id}/preview`.
- Docstrings say Agent Contract `workflow.stages[]`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py::test_update_workflow_stages_persists_valid_stage_config -q
```

Expected GREEN for update route.

- [x] **Step 4.3: Update descriptor and preview payload builders**

Update helper payloads:

- `_workflow_template_payload` emits `stages`.
- `_workflow_stage_request_payload` emits `id`.
- preview uses `descriptor.stage(stage_id)`.
- preview imports `WorkflowStagePromptConfig` and `build_workflow_stage_context_preview`.
- `_workflow_stage_sample_context` reads `manifest.capabilities.tools`, not top-level `manifest.tools`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py -q
```

Expected GREEN.

- [x] **Step 4.4: Commit API stage surface**

Run:

```bash
git status --short
git add proof_agent/delivery/configuration_api.py tests/test_agent_configuration_api.py
git commit -m "Expose workflow stages in configuration API"
```

---

## Task 5: Dashboard Stage Surface

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`
- Modify: `dashboard/src/components/agent/WorkflowModuleEditor.tsx`
- Modify: `dashboard/src/utils/agentYaml.ts`
- Test: `dashboard/src/api/client.test.ts`
- Test: `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`
- Test: `dashboard/src/components/__tests__/agent/WorkflowModuleEditor.test.tsx`
- Test: `dashboard/src/utils/agentYaml.test.ts`

Run every `npm` command in this task from `/Users/jamin/Dev/mz-projects/ProofAgent/dashboard`.

- [x] **Step 5.1: Update YAML utility tests**

In `dashboard/src/utils/agentYaml.test.ts`, change fixtures to:

```yaml
workflow:
  template_descriptor_version: react_enterprise_qa.v1
  stages:
    - id: plan
```

Rename helpers:

- `readWorkflowNodeConfigs` -> `readWorkflowStageConfigs`
- `replaceWorkflowNodes` -> `replaceWorkflowStages`

Run:

```bash
npm test -- src/utils/agentYaml.test.ts
```

Expected RED until utility is updated.

- [x] **Step 5.2: Update YAML utility implementation**

In `dashboard/src/utils/agentYaml.ts`:

- Rename interfaces to `AgentYamlWorkflowStage*`.
- Parse `- id:` under `workflow.stages`.
- Render `stages:` and `- id:`.
- Do not emit `nodes:` or `node_id:`.

Run:

```bash
npm test -- src/utils/agentYaml.test.ts
```

Expected GREEN.

- [x] **Step 5.3: Update API client tests and implementation**

Rename client calls:

- `updateWorkflowNodes` -> `updateWorkflowStages`
- `previewWorkflowNodeContext` -> `previewWorkflowStageContext`
- `/workflow-nodes` -> `/workflow-stages`
- payload `nodes` -> `stages`
- payload `node_id` -> `id`

Run:

```bash
npm test -- src/api/client.test.ts
```

Expected GREEN.

- [x] **Step 5.4: Update editor component tests and UI copy**

In `WorkflowModuleEditor` and its tests:

- Public labels: `Stage Panel`, `Stage`, `stage id`.
- Type names: `WorkflowStageDescriptor`, `WorkflowStageConfig`, `WorkflowStageContextPreview`.
- Internal grouping helpers use stage terminology.

Run:

```bash
npm test -- src/components/__tests__/agent/WorkflowModuleEditor.test.tsx
```

Expected GREEN.

- [x] **Step 5.5: Update Agent Detail integration**

Update `AgentDetailPage.tsx` and its test to use stage callbacks.

Run:

```bash
npm test -- src/pages/__tests__/AgentDetailPage.test.tsx
```

Expected GREEN.

- [x] **Step 5.6: Dashboard build verification**

Run:

```bash
npm run build
```

Expected GREEN.

- [x] **Step 5.7: Commit Dashboard stage surface**

Run from repository root:

```bash
git status --short
git add dashboard/src/api/types.ts dashboard/src/api/client.ts dashboard/src/pages/AgentDetailPage.tsx dashboard/src/components/agent/WorkflowModuleEditor.tsx dashboard/src/utils/agentYaml.ts dashboard/src/api/client.test.ts dashboard/src/pages/__tests__/AgentDetailPage.test.tsx dashboard/src/components/__tests__/agent/WorkflowModuleEditor.test.tsx dashboard/src/utils/agentYaml.test.ts
git commit -m "Rename dashboard workflow configuration to stages"
```

---

## Task 6: Published Effective Stage Configuration Snapshot

**Files:**
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `proof_agent/delivery/configuration_api.py`
- Test: `tests/test_agent_configuration_contracts.py`
- Test: `tests/test_agent_configuration_store.py`
- Test: `tests/test_published_agent_versions.py`

- [x] **Step 6.1: Add contract tests for effective snapshot**

Add a frozen contract shape such as:

```python
class PublishedWorkflowStageConfigurationSnapshot(FrozenModel):
    descriptor_version: str
    stages: tuple[Mapping[str, Any], ...]
    capabilities: Mapping[str, Any]
```

Add `PublishedAgentVersion.effective_workflow_stage_configuration`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_contracts.py::test_published_agent_version_includes_effective_workflow_stage_configuration -q
```

Expected RED.

- [x] **Step 6.2: Implement snapshot contract**

Update `proof_agent/contracts/agent_configuration.py` and exports.

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_contracts.py::test_published_agent_version_includes_effective_workflow_stage_configuration -q
```

Expected GREEN.

- [x] **Step 6.3: Build effective snapshot at publication**

In `proof_agent/configuration/local_store.py` publication path:

- Load the draft Agent Contract.
- Resolve workflow template descriptor.
- Merge descriptor defaults with `workflow.stages[]` overrides.
- Remove capability-dependent context keys when the capability is unavailable.
- Persist descriptor version, effective stages, capability summary, and source override references.

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_store.py::test_publish_version_freezes_effective_workflow_stage_configuration -q
```

Expected GREEN after implementation.

- [x] **Step 6.4: Expose snapshot in version API payload**

Update `_version_payload` in `proof_agent/delivery/configuration_api.py`.

Run:

```bash
uv run --extra dev python -m pytest tests/test_published_agent_versions.py -q
```

Expected GREEN.

- [x] **Step 6.5: Commit effective snapshot publication**

Run:

```bash
git status --short
git add proof_agent/contracts/agent_configuration.py proof_agent/configuration/local_store.py proof_agent/delivery/configuration_api.py tests/test_agent_configuration_contracts.py tests/test_agent_configuration_store.py tests/test_published_agent_versions.py
git commit -m "Freeze effective workflow stage configuration on publish"
```

---

## Task 7: Validation Full Capture Artifacts

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `proof_agent/observability/storage/run_store.py`
- Modify: `proof_agent/observability/api/routers/runs.py`
- Test: `tests/test_agent_configuration_api.py`
- Test: `tests/test_agent_configuration_store.py`
- Test: `tests/test_run_store_metadata.py`
- Test: `tests/test_run_execution_api.py`

- [x] **Step 7.1: Add validation request switch tests**

Extend `DraftValidationRequest` with:

```python
full_capture: bool = False
retain_for_audit: bool = False
```

Test default validation response includes only summary trace links and no capture artifact link.

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py::test_validation_run_defaults_to_summary_only_trace_capture -q
```

Expected RED until request/response is implemented.

- [x] **Step 7.2: Implement summary-only default**

Update validation endpoint so default behavior records:

- Workflow Stage Configuration Trace Summary.
- Published Agent Version or draft/effective snapshot reference.
- No full prompt text, raw context values, raw evidence content, raw tool payloads, provider full responses, or Runtime Plane state dicts.

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py::test_validation_run_defaults_to_summary_only_trace_capture -q
```

Expected GREEN.

- [x] **Step 7.3: Add sensitive artifact store tests**

Test `full_capture: true` creates a `SensitiveValidationCaptureArtifact` metadata record with:

- `capture_id`
- `run_id`
- `draft_id`
- `created_at`
- `expires_at` defaulting to 7 days
- `retention_class: sensitive_validation_capture`
- redaction/exclusion metadata

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_store.py::test_records_sensitive_validation_capture_artifact_with_default_ttl -q
```

Expected RED.

- [x] **Step 7.4: Implement artifact storage**

Store capture artifacts outside ordinary receipt/export paths, for example:

```text
<configuration_store>/validation_captures/<capture_id>/capture.json
```

Hard-exclude:

- raw chain-of-thought
- secrets
- raw evidence content
- raw tool payloads
- complete provider responses
- Runtime Plane state dicts

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_store.py::test_records_sensitive_validation_capture_artifact_with_default_ttl -q
```

Expected GREEN.

- [x] **Step 7.5: Add gated read endpoint tests**

Add an operator-only endpoint such as:

```text
GET /api/runs/{run_id}/validation-capture
```

Requirements:

- Requires `agent.validate`.
- Returns 404/403 for production runs.
- Returns 404 after expiry.
- Ordinary `/api/runs/{run_id}/trace`, receipt, and evaluation export do not include the full artifact.

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_execution_api.py::test_validation_capture_requires_agent_validate_permission -q
uv run --extra dev python -m pytest tests/test_run_execution_api.py::test_production_run_never_exposes_validation_capture -q
```

Expected RED before endpoint, GREEN after.

- [x] **Step 7.6: Implement gated read endpoint and projections**

Update `RunStore`/API projection to expose only a capture reference in validation run detail when authorized. Keep production/customer APIs summary-only.

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_store_metadata.py tests/test_run_execution_api.py tests/test_agent_configuration_api.py -q
```

Expected GREEN.

- [x] **Step 7.7: Commit validation capture artifacts**

Run:

```bash
git status --short
git add proof_agent/delivery/configuration_api.py proof_agent/contracts/agent_configuration.py proof_agent/configuration/local_store.py proof_agent/observability/storage/run_store.py proof_agent/observability/api/routers/runs.py tests/test_agent_configuration_api.py tests/test_agent_configuration_store.py tests/test_run_store_metadata.py tests/test_run_execution_api.py
git commit -m "Add validation-only workflow capture artifacts"
```

---

## Task 8: Source-Controlled Examples, Fixtures, And Docs

**Files:**
- Modify: `CONTEXT.md`
- Modify: `docs/adr/0022-workflow-node-prompt-configuration.md`
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`
- Modify: source-controlled Agent Contract YAML examples/fixtures found by search
- Test: `tests/test_institution_insurance_specialist_example.py`
- Test: `tests/test_model_config_validation.py`
- Test: `tests/test_knowledge_binding_resolver.py`

- [x] **Step 8.1: Find source-controlled old YAML shapes**

Run:

```bash
rg "workflow:\\n|workflow\\.nodes|nodes:|node_id:|^tools:|^memory:" . -g '*.yaml' -g '*.yml' -g '*.md' -g '*.py' -g '*.ts' -g '*.tsx'
```

Expected: classify hits. Do not edit historical docs unless they are active product documentation.

- [x] **Step 8.2: Update examples/fixtures to Agent Contract YAML**

For active manifests:

- `workflow.nodes:` -> `workflow.stages:`
- `node_id:` -> `id:`
- top-level `tools:` -> `capabilities.tools:`
- top-level `memory:` -> `capabilities.memory:`
- include explicit `enabled` for tools/memory.

Run targeted tests for each changed fixture. Examples:

```bash
uv run --extra dev python -m pytest tests/test_institution_insurance_specialist_example.py -q
uv run --extra dev python -m pytest tests/test_model_config_validation.py tests/test_knowledge_binding_resolver.py -q
```

Expected GREEN.

- [x] **Step 8.3: Update active docs**

Update active docs to use:

- Agent Contract YAML
- Workflow Template Stage
- `workflow.stages[]`
- `id`
- `capabilities.tools.enabled`
- `capabilities.memory.enabled`
- Published Effective Workflow Stage Configuration Snapshot
- Sensitive Validation Capture Artifact

Run:

```bash
rg "workflow\\.nodes|workflow-nodes|Workflow Node|workflow node|node_id|nodes\\[\\]" CONTEXT.md docs proof_agent dashboard/src tests -g '!docs/superpowers/plans/2026-06-07-workflow-node-prompt-configuration.md' -g '!docs/adr/0022-workflow-node-prompt-configuration.md'
```

Expected: only allowed residual node terms remain.

- [x] **Step 8.4: Commit examples and docs**

Run:

```bash
git status --short
git add CONTEXT.md docs proof_agent tests dashboard/src
git commit -m "Update Agent Contract docs and fixtures to stages"
```

---

## Task 9: Final Verification

**Files:** All modified files.

- [x] **Step 9.1: Backend focused suite**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py tests/test_workflow_templates.py tests/test_workflow_stage_context.py tests/test_workflow_react_enterprise_qa.py tests/test_agent_configuration_api.py tests/test_agent_configuration_store.py tests/test_published_agent_versions.py tests/test_run_store_metadata.py tests/test_run_execution_api.py -q
```

Expected GREEN.

- [x] **Step 9.2: Backend lint**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
```

Expected GREEN.

- [x] **Step 9.3: Dashboard tests and build**

Run from `dashboard/`:

```bash
npm test -- src/utils/agentYaml.test.ts src/api/client.test.ts src/components/__tests__/agent/WorkflowModuleEditor.test.tsx src/pages/__tests__/AgentDetailPage.test.tsx
npm run build
```

Expected GREEN.

- [x] **Step 9.4: Contract terminology search gate**

Run:

```bash
rg "workflow\\.nodes|workflow-nodes|Workflow Node|workflow node|workflow_node|WorkflowNode|node_id|nodes\\[\\]" proof_agent dashboard/src tests docs -g '!docs/superpowers/plans/2026-06-07-workflow-node-prompt-configuration.md' -g '!docs/adr/0022-workflow-node-prompt-configuration.md'
```

Expected: every remaining hit is either Runtime Plane graph node terminology, retrieval/document/local-index terminology, historical documentation, or `ReActWorkflowNodes` deferred by ADR-0028.

- [x] **Step 9.5: Diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intentional files changed.

- [x] **Step 9.6: Final commit**

Run:

```bash
git add docs/superpowers/plans/2026-06-14-agent-contract-yaml-stage-capability-cutover.md
git commit -m "Plan Agent Contract stage capability cutover"
```

If implementation commits were already created during tasks, this final commit may be unnecessary except for the plan file.
