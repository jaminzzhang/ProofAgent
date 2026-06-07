# Workflow Node Prompt Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add governed `workflow.nodes[]` Prompt and context configuration for the `react_enterprise_qa` Workflow Template, with backend-owned descriptors, validation, redacted preview, Dashboard rendering, and runtime Business Context Addendum injection.

**Architecture:** Keep workflow topology and Harness-owned control prompts in Proof Agent code and template descriptors. Store only structured Agent-owner business context and allowed context options in the Agent Contract under `workflow.nodes[]`, validate it through the existing manifest loader and Agent Configuration API path, render Dashboard from backend descriptors, and append sanitized Business Context Addendum only after Harness control prompts at model-bearing nodes.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, FastAPI Agent Configuration API, YAML Agent Contract loading, LangGraph runtime adapter, JSONL trace, pytest, React 19, TypeScript, Vite, Vitest.

**Spec:** `docs/adr/0022-workflow-node-prompt-configuration.md`

---

## File Structure

Create:

- `proof_agent/control/workflow/node_context.py` — validate node Prompt config against template descriptors, assemble redacted context previews, and produce trace-safe applied-context summaries.
- `dashboard/src/components/agent/WorkflowModuleEditor.tsx` — render Workflow Relationship Map, node selector, Node Panel, YAML toggle, and redacted context preview.
- `dashboard/src/components/__tests__/agent/WorkflowModuleEditor.test.tsx` — cover descriptor-driven map and prompt editing behavior.

Modify:

- `proof_agent/contracts/manifest.py` — add `WorkflowNodePromptConfig`, `WorkflowNodeContextConfig`, `WorkflowNodeConfig`, and extend `WorkflowConfig` with `template_descriptor_version` and `nodes`.
- `proof_agent/contracts/__init__.py` — export new workflow node config contracts.
- `proof_agent/bootstrap/manifest.py` — load `workflow.template_descriptor_version` and `workflow.nodes[]` from `agent.yaml`.
- `proof_agent/bootstrap/validation.py` — validate node ids, editable Prompt fields, context options, length limits, forbidden phrases, and template scope.
- `proof_agent/control/workflow/templates.py` — replace minimal template metadata with backend-owned Workflow Template Descriptors for `enterprise_qa` and `react_enterprise_qa`.
- `proof_agent/capabilities/react/planner.py` — accept node context summary as Business Context Addendum in the planner user payload.
- `proof_agent/capabilities/review/subagent.py` — accept node context summary in reviewer context payloads without changing review control prompt.
- `proof_agent/control/workflow/harness_helpers.py` — accept answer-node context summary in final-answer model request user payload.
- `proof_agent/runtime/react_graph.py` — assemble/apply node context summaries for model-bearing nodes and emit trace-safe `workflow_node_context_applied` events.
- `proof_agent/delivery/configuration_api.py` — expose workflow template descriptor endpoints, workflow node save endpoint, and redacted node context preview endpoint.
- `dashboard/src/api/types.ts` — add descriptor, workflow node config, preview, and save response types.
- `dashboard/src/api/client.ts` — add workflow template list/detail, workflow node save, and preview calls.
- `dashboard/src/api/client.test.ts` — cover new API client calls.
- `dashboard/src/pages/AgentDetailPage.tsx` — replace generic Workflow `ModuleEditor` with `WorkflowModuleEditor`.
- `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx` — cover Workflow tab integration.
- `dashboard/src/utils/agentYaml.ts` — add helpers for replacing `workflow.nodes[]` arrays while preserving the existing YAML editing style.
- `dashboard/src/utils/agentYaml.test.ts` — cover workflow node YAML replacement.
- `tests/test_config_loader.py` — cover loading and rejecting `workflow.nodes[]`.
- `tests/test_workflow_templates.py` — cover descriptor shape and public node ids.
- `tests/test_workflow_node_context.py` — cover preview assembly, redaction, forbidden prompts, and summary payloads.
- `tests/test_agent_configuration_api.py` — cover descriptor endpoints, workflow node update, preview, and validation/publish blockers.
- `tests/test_workflow_react_enterprise_qa.py` — cover runtime trace summary and model-bearing node context injection without replacing system prompts.
- `docs/technical-design.md`, `docs/developer-guide.md`, `docs/development-progress.md` — document the implemented contract and Dashboard behavior after code lands.

---

## Task 1: Add Workflow Node Contract Loading

**Files:**
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `tests/test_config_loader.py`

- [x] **Step 1: Write failing loader tests**

Add tests for loading `workflow.template_descriptor_version` and `workflow.nodes[]` in `tests/test_config_loader.py`:

```python
def test_loads_workflow_node_prompt_config(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(
        tmp_path,
        workflow_extra="""
  template_descriptor_version: react_enterprise_qa.v1
  nodes:
    - node_id: plan
      prompt:
        business_context: "Insurance claim servicing context."
        task_instructions:
          - "Prefer retrieval before final answers."
        output_preferences:
          - "Keep summaries concise."
      context:
        include_agent_purpose: true
        include_bound_tools: true
""",
    )

    manifest = load_agent_manifest(agent_yaml)

    assert manifest.workflow.template_descriptor_version == "react_enterprise_qa.v1"
    assert manifest.workflow.nodes[0].node_id == "plan"
    assert manifest.workflow.nodes[0].prompt.business_context == "Insurance claim servicing context."
    assert manifest.workflow.nodes[0].context.options["include_bound_tools"] is True
```

If `_write_react_manifest()` does not yet accept `workflow_extra`, extend the helper in the test file.

- [x] **Step 2: Run test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py::test_loads_workflow_node_prompt_config -q
```

Expected: fail because `WorkflowConfig` has no `nodes` or `template_descriptor_version`.

- [x] **Step 3: Implement manifest contracts**

In `proof_agent/contracts/manifest.py`, add frozen models:

```python
class WorkflowNodePromptConfig(FrozenModel):
    business_context: str = ""
    task_instructions: tuple[str, ...] = Field(default_factory=tuple)
    output_preferences: tuple[str, ...] = Field(default_factory=tuple)


class WorkflowNodeContextConfig(FrozenModel):
    options: Mapping[str, bool] = Field(default_factory=FrozenDict)

    @field_validator("options", mode="after")
    @classmethod
    def freeze_options(cls, value: Any) -> Any:
        return freeze_value(value)


class WorkflowNodeConfig(FrozenModel):
    node_id: str
    prompt: WorkflowNodePromptConfig = Field(default_factory=WorkflowNodePromptConfig)
    context: WorkflowNodeContextConfig = Field(default_factory=WorkflowNodeContextConfig)
```

Extend `WorkflowConfig`:

```python
class WorkflowConfig(FrozenModel):
    runtime: str
    template: str
    checkpointer: CheckpointerConfig | None = None
    template_descriptor_version: str | None = None
    nodes: tuple[WorkflowNodeConfig, ...] = Field(default_factory=tuple)
```

Export new contracts in `proof_agent/contracts/__init__.py`.

- [x] **Step 4: Implement manifest mapping**

In `proof_agent/bootstrap/manifest.py`, parse:

```python
template_descriptor_version=workflow.get("template_descriptor_version"),
nodes=tuple(_workflow_node_config_from_mapping(item) for item in workflow.get("nodes", ())),
```

Add helper functions that reject non-mapping `workflow.nodes[]` entries and normalize `context` mapping values to booleans.

- [x] **Step 5: Run loader test and existing config tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py -q
```

Expected: pass.

---

## Task 2: Add Workflow Template Descriptors

**Files:**
- Modify: `proof_agent/control/workflow/templates.py`
- Create/Modify: `tests/test_workflow_templates.py`

- [x] **Step 1: Write failing descriptor tests**

Create `tests/test_workflow_templates.py` with:

```python
from proof_agent.control.workflow.templates import list_workflow_templates, resolve_workflow_template


def test_react_template_descriptor_exposes_public_nodes() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa")

    assert descriptor.descriptor_version == "react_enterprise_qa.v1"
    assert [node.node_id for node in descriptor.nodes] == [
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
    plan = descriptor.node("plan")
    assert "business_context" in plan.editable_prompt_fields
    assert "include_bound_tools" in plan.context_options
    assert "retrieval_review" in plan.successors


def test_enterprise_qa_descriptor_is_read_only_for_prompt_nodes() -> None:
    descriptor = resolve_workflow_template("enterprise_qa")

    assert descriptor.descriptor_version == "enterprise_qa.v1"
    assert all(not node.editable_prompt_fields for node in descriptor.nodes)
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_templates.py -q
```

Expected: fail because descriptors do not expose nodes.

- [x] **Step 3: Implement descriptor models**

In `proof_agent/control/workflow/templates.py`, add dataclasses:

```python
@dataclass(frozen=True)
class WorkflowNodeDescriptor:
    node_id: str
    label: str
    description: str
    predecessors: tuple[str, ...] = ()
    successors: tuple[str, ...] = ()
    branch_conditions: Mapping[str, str] = field(default_factory=dict)
    governed_handoff_points: tuple[str, ...] = ()
    editable_prompt_fields: tuple[str, ...] = ()
    context_options: tuple[str, ...] = ()
    input_summary: str = ""
    output_summary: str = ""
    model_bearing: bool = False
    required: bool = True


@dataclass(frozen=True)
class WorkflowTemplate:
    name: str
    description: str
    descriptor_version: str
    nodes: tuple[WorkflowNodeDescriptor, ...] = ()

    def node(self, node_id: str) -> WorkflowNodeDescriptor:
        ...
```

Keep `resolve_workflow_template()` compatible for existing callers.

- [x] **Step 4: Define `react_enterprise_qa.v1` descriptor**

Add public nodes:

```text
plan -> clarification | retrieval_review | tool_review | response
retrieval_review -> retrieval | response
retrieval -> model_answer | response
model_answer -> response
tool_review -> tool | response
tool -> response
memory -> response
```

Mark `plan`, `retrieval_review`, `tool_review`, and `model_answer` as model-bearing. Keep `retrieval`, `tool`, `memory`, `response`, and `clarification` as non-model governed nodes. Declare per-node `editable_prompt_fields` and `context_options` from ADR-0022.

- [x] **Step 5: Run descriptor tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_templates.py -q
```

Expected: pass.

---

## Task 3: Validate Workflow Node Prompt Config

**Files:**
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `tests/test_config_loader.py`

- [x] **Step 1: Write failing validation tests**

Add tests:

```python
def test_enterprise_template_rejects_workflow_nodes(tmp_path: Path) -> None:
    agent_yaml = _write_enterprise_manifest_with_workflow_nodes(tmp_path)

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert exc.value.code == "PA_CONFIG_002"
    assert "workflow.nodes is only supported for react_enterprise_qa" in exc.value.message


def test_unknown_workflow_node_is_rejected(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(tmp_path, workflow_extra="...")

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert "unsupported workflow node_id" in exc.value.message


def test_workflow_node_prompt_rejects_policy_bypass(tmp_path: Path) -> None:
    agent_yaml = _write_react_manifest(tmp_path, workflow_extra="...")

    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)

    assert "workflow node prompt contains forbidden governance override language" in exc.value.message
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py -q
```

Expected: fail on missing validation.

- [x] **Step 3: Implement validation constants**

In `proof_agent/bootstrap/validation.py`, add:

```python
MAX_WORKFLOW_NODE_BUSINESS_CONTEXT_CHARS = 2000
MAX_WORKFLOW_NODE_INSTRUCTION_COUNT = 10
MAX_WORKFLOW_NODE_INSTRUCTION_CHARS = 500
MAX_WORKFLOW_NODE_OUTPUT_PREFERENCE_COUNT = 10
MAX_WORKFLOW_NODE_OUTPUT_PREFERENCE_CHARS = 300
MAX_WORKFLOW_NODE_TOTAL_PROMPT_CHARS = 12000
FORBIDDEN_WORKFLOW_NODE_PROMPT_PHRASES = (
    "system_prompt",
    "developer_prompt",
    "ignore policy",
    "bypass approval",
    "reveal chain-of-thought",
    "ignore evidence",
    "call tool directly",
    "override validator",
)
```

- [x] **Step 4: Implement `_validate_workflow_node_config()`**

Rules:

- `workflow.nodes[]` only allowed when `manifest.workflow.template == "react_enterprise_qa"`.
- `template_descriptor_version`, when set, must match the resolved descriptor version.
- Every `node_id` must exist in descriptor and be unique.
- Configured prompt fields must be in descriptor `editable_prompt_fields`.
- Context option keys must be in descriptor `context_options`.
- Text length and item count limits must pass.
- Forbidden phrases are checked case-insensitively across all prompt text.
- Prompt text still goes through existing secret-looking model param checks indirectly; add explicit token checks for `api_key`, `bearer`, `password`, `secret`, `access_token`.

- [x] **Step 5: Run config loader tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py tests/test_workflow_templates.py -q
```

Expected: pass.

---

## Task 4: Add Context Preview And Summary Assembly

**Files:**
- Create: `proof_agent/control/workflow/node_context.py`
- Create: `tests/test_workflow_node_context.py`

- [x] **Step 1: Write failing context tests**

Create tests:

```python
from proof_agent.control.workflow.node_context import build_workflow_node_context_preview
from proof_agent.control.workflow.templates import resolve_workflow_template


def test_preview_redacts_secret_like_prompt_text() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa")
    preview = build_workflow_node_context_preview(
        descriptor=descriptor,
        node_id="plan",
        prompt={
            "business_context": "Use account secret token SECRET-123.",
            "task_instructions": ["Prefer retrieval."],
            "output_preferences": [],
        },
        context_options={"include_agent_purpose": True},
        sample_context={"agent_purpose": "Answer claims questions."},
    )

    assert preview["node_id"] == "plan"
    assert "SECRET-123" not in preview["business_context_addendum"]
    assert preview["summary"]["redaction_applied"] is True


def test_preview_rejects_unknown_context_option() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa")

    with pytest.raises(ProofAgentError):
        build_workflow_node_context_preview(
            descriptor=descriptor,
            node_id="plan",
            prompt={},
            context_options={"include_raw_trace": True},
            sample_context={},
        )
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_node_context.py -q
```

Expected: fail because module does not exist.

- [x] **Step 3: Implement context service**

Expose:

```python
def build_business_context_addendum(
    *,
    descriptor: WorkflowTemplate,
    node_id: str,
    prompt: WorkflowNodePromptConfig,
    context_options: Mapping[str, bool],
    sample_context: Mapping[str, Any],
) -> WorkflowNodeContextRender
```

Use a small frozen dataclass or `dict` projection with:

```text
node_id
harness_control_prompt_summary
structured_control_context
business_context_addendum
summary
```

Redact secret-looking strings with existing redaction helpers if available; otherwise add a narrow local redaction helper and keep it trace-safe.

- [x] **Step 4: Implement trace-safe summary helper**

Add:

```python
def workflow_node_context_summary(render: WorkflowNodeContextRender) -> dict[str, Any]:
    return {
        "node_id": ...,
        "prompt_fields": ...,
        "context_options": ...,
        "business_context_length": ...,
        "task_instruction_count": ...,
        "output_preference_count": ...,
        "redaction_applied": ...,
    }
```

- [x] **Step 5: Run context tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_node_context.py -q
```

Expected: pass.

---

## Task 5: Add Agent Configuration API Endpoints

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `tests/test_agent_configuration_api.py`

- [x] **Step 1: Write failing API tests**

Add tests:

```python
def test_workflow_template_descriptor_api_lists_react_nodes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/config/workflow-templates/react_enterprise_qa")

    assert response.status_code == 200
    body = response.json()
    assert body["descriptor_version"] == "react_enterprise_qa.v1"
    assert body["nodes"][0]["node_id"] == "plan"


def test_update_workflow_nodes_persists_valid_nodes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_agent(client)

    response = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-nodes",
        json={
            "actor": "workflow-editor",
            "template_descriptor_version": "react_enterprise_qa.v1",
            "nodes": [
                {
                    "node_id": "plan",
                    "prompt": {"business_context": "Insurance servicing context."},
                    "context": {"include_agent_purpose": True},
                }
            ],
        },
    )

    assert response.status_code == 200
    assert "nodes:" in response.json()["agent_yaml"]


def test_workflow_node_preview_does_not_create_run(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_react_agent(client)

    response = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/workflow-nodes/plan/preview",
        json={
            "prompt": {"business_context": "Insurance context."},
            "context": {"include_agent_purpose": True},
            "actor": "workflow-editor",
        },
    )

    assert response.status_code == 200
    assert response.json()["node_id"] == "plan"
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py -q
```

Expected: fail on missing routes.

- [x] **Step 3: Add request models**

In `proof_agent/delivery/configuration_api.py`, add:

```python
class WorkflowNodePromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_context: str | None = None
    task_instructions: list[str] = Field(default_factory=list)
    output_preferences: list[str] = Field(default_factory=list)


class WorkflowNodeUpdateItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1)
    prompt: WorkflowNodePromptRequest = Field(default_factory=WorkflowNodePromptRequest)
    context: dict[str, bool] = Field(default_factory=dict)


class WorkflowNodesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_descriptor_version: str | None = None
    nodes: list[WorkflowNodeUpdateItemRequest]
    actor: str = "local-user"
```

- [x] **Step 4: Add descriptor endpoints**

Expose:

```text
GET /api/config/workflow-templates
GET /api/config/workflow-templates/{template_id}
```

Return `model_dump`-compatible dicts from descriptor dataclasses. Include `descriptor_version`, `nodes`, `editable_prompt_fields`, `context_options`, `predecessors`, `successors`, and `branch_conditions`.

- [x] **Step 5: Add workflow node update endpoint**

Patch `agent_yaml` by parsing YAML with `yaml.safe_load`, writing:

```python
raw["workflow"]["template_descriptor_version"] = request.template_descriptor_version
raw["workflow"]["nodes"] = [...]
```

Dump with `yaml.safe_dump(sort_keys=False)`, compile draft, call `load_agent_manifest()`, resolve draft knowledge bindings, then persist via `store.update_draft()`.

- [x] **Step 6: Add preview endpoint**

Expose:

```text
POST /api/config/agents/{agent_id}/drafts/{draft_id}/workflow-nodes/{node_id}/preview
```

Compile/load the draft, resolve descriptor, build a sample context from manifest purpose, bound knowledge source ids, bound tool file path, and selected context options. Return the redacted preview payload. Do not call `run_with_langgraph()`.

- [x] **Step 7: Run API tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_api.py -q
```

Expected: pass.

---

## Task 6: Add Dashboard API Types And Client Calls

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/api/client.test.ts`

- [x] **Step 1: Write failing client tests**

In `dashboard/src/api/client.test.ts`, add tests that assert:

- `fetchWorkflowTemplate("react_enterprise_qa")` calls `/api/config/workflow-templates/react_enterprise_qa`.
- `updateWorkflowNodes(agentId, draftId, payload)` PATCHes `/workflow-nodes`.
- `previewWorkflowNodeContext(agentId, draftId, nodeId, payload)` POSTs `/workflow-nodes/:nodeId/preview`.

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
cd dashboard && npm test -- --run src/api/client.test.ts
```

Expected: fail on missing functions.

- [x] **Step 3: Add TypeScript types**

Add:

```typescript
export interface WorkflowNodeDescriptor { ... }
export interface WorkflowTemplateDescriptor { ... }
export interface WorkflowNodePromptConfig { ... }
export interface WorkflowNodeConfig { ... }
export interface WorkflowNodeContextPreview { ... }
```

- [x] **Step 4: Add client functions**

Add:

```typescript
export function fetchWorkflowTemplates(): Promise<WorkflowTemplatesResponse>
export function fetchWorkflowTemplate(templateId: string): Promise<WorkflowTemplateDescriptor>
export function updateWorkflowNodes(...)
export function previewWorkflowNodeContext(...)
```

- [x] **Step 5: Run client tests**

Run:

```bash
cd dashboard && npm test -- --run src/api/client.test.ts
```

Expected: pass.

---

## Task 7: Add Dashboard Workflow Module

**Files:**
- Create: `dashboard/src/components/agent/WorkflowModuleEditor.tsx`
- Create: `dashboard/src/components/__tests__/agent/WorkflowModuleEditor.test.tsx`
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`
- Modify: `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`
- Modify: `dashboard/src/utils/agentYaml.ts`
- Modify: `dashboard/src/utils/agentYaml.test.ts`

- [x] **Step 1: Write failing utility tests**

Add helper tests for replacing `workflow.nodes[]` while preserving top-level `workflow.runtime`, `workflow.template`, and `workflow.checkpointer`.

- [x] **Step 2: Implement YAML node replacement helper**

Implement a helper that accepts node configs from the backend response and replaces the nested `workflow.nodes` block using simple YAML rendering. Keep it scoped to arrays of objects needed for this feature.

- [x] **Step 3: Write failing component tests**

Test that `WorkflowModuleEditor`:

- Shows descriptor node labels and successors.
- Opens a selected node panel.
- Shows locked Harness boundary copy.
- Edits `business_context`.
- Requests preview without running validation.
- Calls `onSaveNodes()` with structured nodes.

- [x] **Step 4: Implement WorkflowModuleEditor**

Use existing Dashboard styling. The layout is:

```text
Header: Workflow Configuration + Save + Show YAML
Map: compact vertical/branch list of descriptor nodes
Panel: selected node inputs and context option checkboxes
Preview: redacted context preview response
```

No drag-and-drop, no edge editing, no disable toggles.

- [x] **Step 5: Integrate AgentDetailPage**

Replace generic Workflow `ModuleEditor` with `WorkflowModuleEditor`. Fetch descriptor from `workflow.template` in `agentYaml`, falling back to `react_enterprise_qa`. Saving uses `updateWorkflowNodes()` and then updates local `agentYaml` from returned `ContractBundle`.

- [x] **Step 6: Run Dashboard tests**

Run:

```bash
cd dashboard && npm test -- --run src/components/__tests__/agent/WorkflowModuleEditor.test.tsx src/pages/__tests__/AgentDetailPage.test.tsx src/utils/agentYaml.test.ts
```

Expected: pass.

---

## Task 8: Inject Business Context Addendum At Runtime

**Files:**
- Modify: `proof_agent/capabilities/react/planner.py`
- Modify: `proof_agent/capabilities/review/subagent.py`
- Modify: `proof_agent/control/workflow/harness_helpers.py`
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `tests/test_react_planner.py`
- Modify: `tests/test_workflow_react_enterprise_qa.py`

- [x] **Step 1: Write failing planner/reviewer tests**

In `tests/test_react_planner.py`, add a fake provider assertion that node context appears in the planner user JSON as `business_context_addendum`, while the system prompt remains `_planner_control_prompt()`.

In reviewer tests or workflow tests, assert review context includes node context under a structured key and does not alter allowed decisions.

- [x] **Step 2: Extend planner protocol**

Add optional parameter:

```python
node_context_summary: Mapping[str, Any] | None = None
```

Include it in the LLM planner user JSON as `business_context_addendum`.

- [x] **Step 3: Extend reviewer context path**

Keep `LLMHarnessReviewSubagent.review()` signature unchanged if possible. Pass node context inside the existing `context` mapping under `business_context_addendum`, and ensure it serializes through the existing user JSON payload.

- [x] **Step 4: Extend final answer model request**

In `build_model_request()`, accept:

```python
node_context_summary: Mapping[str, Any] | None = None
```

Append it to the user message before `Question`, clearly labeled as business context and not evidence.

- [x] **Step 5: Wire runtime nodes**

In `runtime/react_graph.py`, for `plan`, `review_retrieval_plan`, `review_tool`, and `model`:

- Resolve configured public node id.
- Build Business Context Addendum through `node_context.py`.
- Emit `workflow_node_context_applied` with trace-safe summary.
- Pass context into planner, review context, or final answer model request.

- [x] **Step 6: Run workflow tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_react_planner.py tests/test_workflow_react_enterprise_qa.py tests/test_workflow_node_context.py -q
```

Expected: pass.

---

## Task 9: Documentation And Full Verification

**Files:**
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`

- [x] **Step 1: Update docs**

Document:

- `workflow.template_descriptor_version`
- `workflow.nodes[]`
- descriptor-driven Dashboard map
- Business Context Addendum runtime boundary
- trace-safe summary behavior
- validation/publish gate behavior

- [x] **Step 2: Run backend verification**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py tests/test_workflow_templates.py tests/test_workflow_node_context.py tests/test_agent_configuration_api.py tests/test_react_planner.py tests/test_workflow_react_enterprise_qa.py -q
uv run --extra dev ruff check proof_agent tests
```

Expected: pass.

- [x] **Step 3: Run frontend verification**

Run:

```bash
cd dashboard && npm test -- --run src/api/client.test.ts src/components/__tests__/agent/WorkflowModuleEditor.test.tsx src/pages/__tests__/AgentDetailPage.test.tsx src/utils/agentYaml.test.ts
cd dashboard && npm run build
```

Expected: pass.

- [x] **Step 4: Run Markdown check**

Run:

```bash
git diff --check
```

Expected: no output.
