# Shared Model Connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Dashboard-managed Shared Model Connections under Configuration > Models, with live Agent and Knowledge Source references, custom fallback configuration, secret-safe credential references, runtime resolution audit, and Reviewer model parameter cleanup.

**Architecture:** Introduce Shared Model Connection contracts and a live resolver that converts shared or custom model-source configuration into the existing provider-neutral `ModelConfig` shape at call time. Store Shared Model Connections in the Local Agent Configuration Store with Active/Archived lifecycle, reference impact review, validation, manual smoke testing, and configuration audit. Keep usage parameters on Agent roles and Knowledge Sources, with only connection-level default `timeout_seconds` allowed on the shared connection.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, file-backed `LocalAgentConfigurationStore`, FastAPI configuration API, LangGraph runner integration, pytest, React 19, Vite, TypeScript, Tailwind CSS v4, Vitest.

**ADR:** `docs/adr/0020-live-shared-model-connections.md`

---

## Scope Check

V1 includes:

- `/models` Dashboard workspace and `/models/:connectionId` detail workspace.
- `/api/config/model-connections` CRUD, validation, manual smoke test, archive/restore, references, and deletion eligibility.
- Agent Model module selector for Shared Model Connection or Custom Model Configuration per Answer, Planner, and Reviewer role.
- Knowledge Source ingestion/routing model selector for Shared Model Connection or Custom Model Configuration.
- Runtime resolution from shared/custom configuration into existing `ModelConfig`.
- Model Connection Resolution Records in trace/audit-safe projections.
- Reviewer YAML cleanup: model usage settings move under `review.subagent.params`.

V1 does not include:

- Dashboard-stored raw API keys or a secret vault.
- Shared Model Connection import/export.
- Published Agent Version pinning of model connection versions.
- Provider inventory lookup from remote vendors.
- Making `azure_openai` or `anthropic` production-ready unless their adapters are implemented separately.
- Migrating deterministic examples to require Shared Model Connections.

## Decisions Already Recorded

- Shared Model Connections are live references, not pinned published versions.
- Agents and Knowledge Sources may choose Shared Model Connection or Custom Model Configuration.
- Raw provider API keys are not stored; V1 supports environment credential references only.
- Shared Model Connection stores connection parameters: provider, model identifier, base URL, credential reference, optional account-scope env refs, and optional default `timeout_seconds`.
- Temperature, maximum output tokens, retrieval `top_k`, reviewer controls, ingestion tuning, and routing tuning stay on Agent or Knowledge Source usage configuration.
- Agent or Knowledge Source `params.timeout_seconds` overrides the Shared Model Connection default timeout.
- Archived connections cannot be newly selected or used for new production publication, but existing runtime references can continue resolving with warnings.
- Agent Validation Run may execute against archived connections but records a publish-blocking warning.
- Reviewer model usage settings migrate directly to `review.subagent.params`; old top-level reviewer usage fields are rejected rather than dual-read.

---

## File Structure

### Contracts And Bootstrap

- Modify `proof_agent/contracts/manifest.py` — add model-source discriminated model role configs, custom/shared reference shape, and Reviewer params cleanup.
- Modify `proof_agent/contracts/agent_configuration.py` — add Shared Model Connection, credential reference, lifecycle, reference summary, validation, smoke-test, and deletion eligibility contracts.
- Modify `proof_agent/contracts/trace.py` or `proof_agent/contracts/model.py` — add trace-safe Model Connection Resolution Record payload if the existing trace payload remains untyped, keep DTO provider-neutral.
- Modify `proof_agent/contracts/__init__.py` — export new contracts.
- Modify `proof_agent/bootstrap/manifest.py` — parse `model_source: shared|custom`, legacy inline provider/name, custom credential refs, and reviewer params.
- Modify `proof_agent/bootstrap/validation.py` — validate model-source shapes, reject old reviewer top-level usage fields, preserve standalone inline provider/name support, and reject raw secrets.
- Create `proof_agent/bootstrap/model_resolution.py` — resolve shared/custom/legacy model role config into `ModelConfig` plus resolution metadata.

### Configuration Store And API

- Modify `proof_agent/configuration/local_store.py` — persist model connections, lifecycle operations, reference summaries, deletion eligibility, validation records, and smoke-test records.
- Modify `proof_agent/delivery/configuration_api.py` — add `/api/config/model-connections` routes and Agent/Knowledge model reference helpers.
- Modify `proof_agent/observability/api/app.py` — no new store object expected; ensure existing configuration store covers model connections.

### Runtime And Capabilities

- Modify `proof_agent/bootstrap/composition.py` — accept a model connection resolver or precomputed resolution context when composing Harness invocation.
- Modify `proof_agent/runtime/langgraph_runner.py` — resolve live model connections for configured runs and pass resolution metadata into trace.
- Modify `proof_agent/capabilities/models/openai_compatible.py` — accept resolved connection params cleanly, including base URL and timeout default.
- Modify `proof_agent/capabilities/models/registry.py` — expose provider readiness metadata for Models Workspace provider options.
- Modify `proof_agent/observability/audit/trace.py` — emit model connection resolution records without raw secrets.
- Modify `proof_agent/observability/audit/receipt.py` and template if model usage summary should show connection id.

### Knowledge Source Integration

- Modify `proof_agent/contracts/agent_configuration.py` — if Knowledge Source params remain generic, add typed helpers or validation records without moving all provider params into new contracts.
- Modify `proof_agent/configuration/local_store.py` — update local index source creation/update validation for ingestion/routing model source configs.
- Modify `proof_agent/delivery/configuration_api.py` — accept shared/custom ingestion and routing model config in Knowledge Source create/update payloads.
- Modify `proof_agent/capabilities/knowledge/ingestion/configuration.py` and `proof_agent/capabilities/knowledge/ingestion/worker.py` — resolve ingestion model connection before artifact builds.
- Modify `proof_agent/capabilities/knowledge/local_index_routing.py` — resolve routing model connection before routing calls.

### Dashboard Frontend

- Modify `dashboard/src/components/Sidebar.tsx` — add `Models` under Configuration.
- Modify `dashboard/src/router.tsx` — add `/models` and `/models/:connectionId`.
- Create `dashboard/src/pages/ModelsPage.tsx` — operational inventory list and create action.
- Create `dashboard/src/pages/ModelConnectionDetailPage.tsx` — Overview, References, Test, Audit tabs.
- Modify `dashboard/src/api/types.ts` — add model connection DTOs, reference summary, validation, smoke-test, and lifecycle types.
- Modify `dashboard/src/api/client.ts` — add model connection API functions.
- Modify `dashboard/src/components/agent/ModelModuleEditor.tsx` — shared/custom selector per role and Reviewer params cleanup.
- Modify `dashboard/src/components/agent/KnowledgeModuleEditor.tsx` or Knowledge Source pages — add model source selectors for ingestion/routing where Source-owned provider config is edited.
- Modify `dashboard/src/pages/KnowledgePage.tsx` and `dashboard/src/pages/KnowledgeDetailPage.tsx` — wire local index ingestion/routing model selectors to model connections.

### Tests And Docs

- Create `tests/test_model_connection_contracts.py`
- Create `tests/test_model_connection_store.py`
- Create `tests/test_model_connection_api.py`
- Create `tests/test_model_connection_resolution.py`
- Modify `tests/test_model_config_validation.py`
- Modify `tests/test_config_loader.py`
- Modify `tests/test_review_subagent.py`
- Modify `tests/test_knowledge_ingestion_store.py`
- Modify `tests/test_knowledge_ingestion_worker.py`
- Modify `tests/test_knowledge_source_publication.py`
- Modify `tests/test_trace_model_events.py`
- Modify `dashboard/src/api/client.test.ts`
- Create `dashboard/src/pages/__tests__/ModelsPage.test.tsx`
- Create `dashboard/src/pages/__tests__/ModelConnectionDetailPage.test.tsx`
- Modify `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`
- Modify `dashboard/src/pages/__tests__/KnowledgePage.test.tsx`
- Modify `dashboard/src/pages/__tests__/KnowledgeDetailPage.test.tsx`
- Update `docs/technical-design.md`, `docs/developer-guide.md`, and `docs/development-progress.md` after implementation.
- Do not update `docs/zh/` during development.

---

## Task 1: Add Shared Model Connection Contracts

**Files:**
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_model_connection_contracts.py`

- [x] **Step 1: Write failing contract tests**

Add tests for:

```python
def test_shared_model_connection_is_secret_safe_and_json_serializable() -> None:
    connection = SharedModelConnection(
        connection_id="model_deepseek_default",
        display_name="DeepSeek Default",
        description="Default DeepSeek connection",
        tags=("prod", "deepseek"),
        provider="deepseek",
        model_identifier="deepseek-chat",
        base_url="https://api.deepseek.com",
        credential_ref=EnvironmentModelCredentialReference(
            name="DEEPSEEK_API_KEY",
        ),
        timeout_seconds=20,
        lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
        created_at="2026-06-06T00:00:00Z",
        updated_at="2026-06-06T00:00:00Z",
    )

    payload = connection.model_dump(mode="json")

    assert payload["connection_id"] == "model_deepseek_default"
    assert payload["credential_ref"] == {"type": "env", "name": "DEEPSEEK_API_KEY"}
    assert "api_key" not in payload
```

Also test:

- `SharedModelConnectionLifecycleState.ACTIVE` and `ARCHIVED`.
- `SharedModelConnectionReferenceSummary` has draft, published version, and Knowledge Source counts.
- `SharedModelConnectionDeletionEligibility` serializes blockers.
- `ModelConnectionValidationRecord` and `ModelConnectionSmokeTestRecord` do not contain raw response text or raw credentials.

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_connection_contracts.py -q
```

Expected: fail because contracts do not exist.

- [x] **Step 3: Implement contracts**

Add:

```python
class SharedModelConnectionLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EnvironmentModelCredentialReference(FrozenModel):
    type: Literal["env"] = "env"
    name: str


class SharedModelConnection(FrozenModel):
    connection_id: str
    display_name: str
    description: str = ""
    tags: tuple[str, ...] = Field(default_factory=tuple)
    provider: str
    model_identifier: str
    base_url: str | None = None
    credential_ref: EnvironmentModelCredentialReference
    organization_env: str | None = None
    project_env: str | None = None
    timeout_seconds: float | None = None
    lifecycle_state: SharedModelConnectionLifecycleState
    created_at: str
    updated_at: str
```

Add reference summary, deletion eligibility, validation, and smoke-test records. Export them from `proof_agent/contracts/__init__.py`.

- [x] **Step 4: Run tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_connection_contracts.py -q
```

Expected: pass.

- [x] **Step 5: Commit**

```bash
git add proof_agent/contracts/agent_configuration.py proof_agent/contracts/__init__.py tests/test_model_connection_contracts.py
git commit -m "feat: add shared model connection contracts"
```

---

## Task 2: Add Model Source Contract Shapes And Reviewer Params Cleanup

**Files:**
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `tests/test_model_config_validation.py`
- Modify: `tests/test_config_loader.py`
- Modify: `tests/test_review_subagent.py`
- Modify: `examples/insurance_customer_service/agent.yaml`
- Modify: `proof_agent/evaluation/demo/fixtures/**/agent*.yaml`

- [x] **Step 1: Write failing loader tests for shared model source**

Add a manifest fixture with:

```yaml
model:
  model_source: shared
  connection_id: model_deepseek_default
  params:
    temperature: 0
    max_output_tokens: 800
    timeout_seconds: 20
```

Assert:

```python
assert manifest.model.model_source == "shared"
assert manifest.model.connection_id == "model_deepseek_default"
assert manifest.model.params["max_output_tokens"] == 800
```

- [x] **Step 2: Write failing loader tests for custom model source**

Add:

```yaml
model:
  model_source: custom
  provider: deepseek
  name: deepseek-chat
  base_url: https://api.deepseek.com
  credential_ref:
    type: env
    name: DEEPSEEK_API_KEY
  params:
    temperature: 0
```

Assert provider/name/base URL/credential reference are parsed and frozen.

- [x] **Step 3: Write failing reviewer cleanup tests**

Add a valid reviewer shape:

```yaml
review:
  mode: auto
  subagent:
    model_source: shared
    connection_id: model_deepseek_default
    fail_closed: true
    params:
      timeout_seconds: 5
      max_output_tokens: 500
      temperature: 0
```

Assert:

```python
assert manifest.review.subagent.params["timeout_seconds"] == 5
assert manifest.review.subagent.fail_closed is True
```

Add a rejection test for old top-level reviewer usage fields:

```yaml
review:
  subagent:
    provider: deepseek
    name: deepseek-chat
    timeout_seconds: 5
    max_output_tokens: 500
```

Expected: `ProofAgentError` with a fix mentioning `review.subagent.params.timeout_seconds` and `review.subagent.params.max_output_tokens`.

- [x] **Step 4: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_config_validation.py tests/test_config_loader.py tests/test_review_subagent.py -q
```

Expected: fail on new shapes.

- [x] **Step 5: Implement model-source contracts**

Keep legacy standalone inline shape supported:

```yaml
model:
  provider: deterministic
  name: demo
```

Add discriminated support for:

- `model_source: shared` + `connection_id`
- `model_source: custom` + provider/name/base_url/credential_ref

Do not require all demo fixtures to use shared connections.

- [x] **Step 6: Implement reviewer cleanup**

Move `ReviewSubagentConfig.timeout_seconds` and `max_output_tokens` into `params`.

Keep `fail_closed` top-level.

Update runtime code that reads reviewer timeout/max output tokens to use params.

- [x] **Step 7: Update YAML fixtures**

For every existing `review.subagent.timeout_seconds` and `review.subagent.max_output_tokens`, move values under:

```yaml
review:
  subagent:
    params:
      timeout_seconds: 5
      max_output_tokens: 500
```

Do not change deterministic provider/name unless required by tests.

- [x] **Step 8: Run tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_config_validation.py tests/test_config_loader.py tests/test_review_subagent.py -q
```

Expected: pass.

- [x] **Step 9: Commit**

```bash
git add proof_agent/contracts/manifest.py proof_agent/bootstrap/manifest.py proof_agent/bootstrap/validation.py tests/test_model_config_validation.py tests/test_config_loader.py tests/test_review_subagent.py examples proof_agent/evaluation/demo/fixtures
git commit -m "feat: add model source config shapes"
```

---

## Task 3: Implement Model Connection Store

**Files:**
- Modify: `proof_agent/configuration/local_store.py`
- Create: `tests/test_model_connection_store.py`

- [x] **Step 1: Write failing store tests for create/list/get**

Test that `create_model_connection()`:

- Generates or accepts a stable `connection_id`.
- Sets lifecycle to `ACTIVE`.
- Rejects duplicate ids.
- Rejects unsafe identifier characters.
- Persists and reads back JSON.

- [x] **Step 2: Write failing lifecycle tests**

Test:

- `archive_model_connection()` changes lifecycle to `ARCHIVED`.
- `restore_model_connection()` changes lifecycle to `ACTIVE`.
- Archived connections remain readable.
- Physical deletion requires archived lifecycle and zero references.
- Deletion writes root-level configuration audit before removing storage.

- [x] **Step 3: Write failing reference summary tests**

Create Draft Agent, Published Agent Version, and Knowledge Source fixture records that reference `model_deepseek_default`.

Assert:

```python
summary = store.get_model_connection_reference_summary("model_deepseek_default")
assert summary.draft_agent_reference_count == 1
assert summary.published_agent_version_reference_count == 1
assert summary.knowledge_source_reference_count == 1
```

Reference summary scans configuration references only, not run history.

- [x] **Step 4: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_connection_store.py -q
```

Expected: fail because store methods do not exist.

- [x] **Step 5: Implement storage layout**

Use a focused directory:

```text
runs/config/model_connections/{connection_id}/connection.json
runs/config/model_connections/{connection_id}/validation_records/{validation_id}.json
runs/config/model_connections/{connection_id}/smoke_tests/{smoke_test_id}.json
```

Keep writes deterministic and secret-safe.

- [x] **Step 6: Implement lifecycle and deletion eligibility**

Add:

- `create_model_connection`
- `get_model_connection`
- `list_model_connections`
- `update_model_connection`
- `archive_model_connection`
- `restore_model_connection`
- `get_model_connection_reference_summary`
- `get_model_connection_deletion_eligibility`
- `physically_delete_model_connection`

High-impact update metadata should identify changed high-impact fields for later API/UI impact review.

- [x] **Step 7: Run tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_connection_store.py -q
```

Expected: pass.

- [x] **Step 8: Commit**

```bash
git add proof_agent/configuration/local_store.py tests/test_model_connection_store.py
git commit -m "feat: persist shared model connections"
```

---

## Task 4: Add Model Connection Configuration API

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Create: `tests/test_model_connection_api.py`

- [x] **Step 1: Write failing API tests for collection routes**

Cover:

- `GET /api/config/model-connections`
- `POST /api/config/model-connections`
- provider validation against production-ready provider options for creation: `openai`, `openai_compatible`, `deepseek`

Expected create payload:

```json
{
  "connection_id": "model_deepseek_default",
  "display_name": "DeepSeek Default",
  "provider": "deepseek",
  "model_identifier": "deepseek-chat",
  "base_url": "https://api.deepseek.com",
  "credential_ref": {"type": "env", "name": "DEEPSEEK_API_KEY"},
  "timeout_seconds": 20,
  "actor": "dashboard"
}
```

- [x] **Step 2: Write failing API tests for detail and update**

Cover:

- `GET /api/config/model-connections/{connection_id}`
- `PATCH /api/config/model-connections/{connection_id}`
- high-impact update response includes `requires_impact_review` or impact summary before save if implemented as preview-then-save.

If using one-step update, require request field:

```json
{"confirm_impact": true}
```

for high-impact changes with existing references.

- [x] **Step 3: Write failing lifecycle and deletion tests**

Cover:

- archive
- restore
- deletion eligibility
- physical delete blocked while active
- physical delete blocked with references

- [x] **Step 4: Write failing validation and smoke-test tests**

Cover:

- `POST /api/config/model-connections/{connection_id}/validate`
- Missing env var returns validation failed without raw secret.
- `POST /api/config/model-connections/{connection_id}/smoke-test`
- Missing env var does not call remote provider.

Use monkeypatch/mocks; do not require real network.

- [x] **Step 5: Run tests and verify RED**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_model_connection_api.py -q
```

Expected: fail because routes do not exist.

- [x] **Step 6: Implement routes under `/api/config/model-connections`**

Add request models with `extra="forbid"`.

Routes:

- `GET /config/model-connections`
- `POST /config/model-connections`
- `GET /config/model-connections/{connection_id}`
- `PATCH /config/model-connections/{connection_id}`
- `POST /config/model-connections/{connection_id}/archive`
- `POST /config/model-connections/{connection_id}/restore`
- `GET /config/model-connections/{connection_id}/references`
- `GET /config/model-connections/{connection_id}/deletion-eligibility`
- `DELETE /config/model-connections/{connection_id}`
- `POST /config/model-connections/{connection_id}/validate`
- `POST /config/model-connections/{connection_id}/smoke-test`

- [x] **Step 7: Run tests and verify GREEN**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_model_connection_api.py -q
```

Expected: pass.

- [x] **Step 8: Commit**

```bash
git add proof_agent/delivery/configuration_api.py tests/test_model_connection_api.py
git commit -m "feat: add model connection configuration api"
```

---

## Task 5: Add Model Connection Resolver And Runtime Audit

**Files:**
- Create: `proof_agent/bootstrap/model_resolution.py`
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `proof_agent/runtime/langgraph_runner.py`
- Modify: `proof_agent/observability/audit/trace.py`
- Modify: `proof_agent/observability/audit/receipt.py`
- Create: `tests/test_model_connection_resolution.py`
- Modify: `tests/test_trace_model_events.py`
- Modify: `tests/test_receipt_model_usage.py`

- [x] **Step 1: Write failing resolver tests**

Test:

- Shared reference resolves connection provider/model/base URL/credential env into `ModelConfig`.
- Custom reference resolves without store lookup.
- Legacy inline provider/name still returns `ModelConfig`.
- Agent or Knowledge `params.timeout_seconds` overrides Shared Model Connection `timeout_seconds`.
- Missing shared connection raises `ProofAgentError` with stable model connection resolution error code.
- Archived connection resolves with warning metadata, not silent success.
- Missing env var fails validation/smoke/run resolution where runtime credential presence is required.

- [x] **Step 2: Write failing trace tests**

Assert a model call emits a trace-safe resolution payload:

```json
{
  "connection_id": "model_deepseek_default",
  "provider": "deepseek",
  "model_identifier": "deepseek-chat",
  "base_url_host": "api.deepseek.com",
  "credential_ref": {"type": "env", "name": "DEEPSEEK_API_KEY"},
  "usage_params": {"temperature": 0, "max_output_tokens": 800}
}
```

No raw credential value appears.

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_connection_resolution.py tests/test_trace_model_events.py tests/test_receipt_model_usage.py -q
```

Expected: fail.

- [x] **Step 4: Implement resolver**

Create functions:

```python
def resolve_model_role_config(
    role_config: ModelRoleConfig,
    *,
    configuration_store: LocalAgentConfigurationStore | None,
    require_runtime_credentials: bool,
) -> ResolvedModelConnection:
    ...
```

Return both:

- Existing `ModelConfig` for provider adapters.
- `ModelConnectionResolutionRecord` for trace/audit.
- warnings such as archived connection.

- [ ] **Step 5: Wire runtime paths**

Update model provider creation paths so final answer, ReAct planner, reviewer, retrieval planner/evaluator, ingestion, and routing use resolved model configs.

Keep deterministic demo working without configuration store.

- [x] **Step 6: Emit trace-safe resolution record**

Emit before or alongside `model_request` events. Keep payload free of raw credentials and raw provider responses.

- [ ] **Step 7: Run tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_connection_resolution.py tests/test_trace_model_events.py tests/test_receipt_model_usage.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/bootstrap/model_resolution.py proof_agent/bootstrap/composition.py proof_agent/runtime/langgraph_runner.py proof_agent/observability/audit tests/test_model_connection_resolution.py tests/test_trace_model_events.py tests/test_receipt_model_usage.py
git commit -m "feat: resolve live model connections at runtime"
```

---

## Task 6: Enforce Publication And Lifecycle Guards

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `tests/test_agent_configuration_api.py`
- Modify: `tests/test_knowledge_source_publication.py`
- Modify: `tests/test_model_connection_store.py`

- [ ] **Step 1: Write failing Agent publication guard tests**

Create a Draft Agent referencing an archived Shared Model Connection.

Assert:

- Validation endpoint can run and returns publish-blocking warning metadata.
- Publication endpoint rejects with actionable error until connection is active or reference changes.

- [ ] **Step 2: Write failing Knowledge publication guard tests**

Create a Knowledge Source with ingestion/routing shared connection archived.

Assert new production-bound Source publication is blocked while existing source runtime config remains readable.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_agent_configuration_api.py tests/test_knowledge_source_publication.py tests/test_model_connection_store.py -q
```

Expected: fail.

- [ ] **Step 4: Implement guards**

At validation:

- Resolve archived connection.
- Record warning and publish blocker.

At Agent publication:

- Reject archived shared model references.

At Knowledge Source publication:

- Reject archived shared model references for production-bound publication.

Existing Published Agent execution should not be blocked solely because the live connection is archived.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_agent_configuration_api.py tests/test_knowledge_source_publication.py tests/test_model_connection_store.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/delivery/configuration_api.py proof_agent/configuration/local_store.py tests/test_agent_configuration_api.py tests/test_knowledge_source_publication.py tests/test_model_connection_store.py
git commit -m "feat: enforce model connection lifecycle guards"
```

---

## Task 7: Integrate Knowledge Source Model Selection

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/configuration.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/worker.py`
- Modify: `proof_agent/capabilities/knowledge/local_index_routing.py`
- Modify: `tests/test_knowledge_ingestion_store.py`
- Modify: `tests/test_knowledge_ingestion_worker.py`
- Modify: `tests/test_local_index_provider.py`

- [ ] **Step 1: Write failing Knowledge Source config tests**

For `local_index` create/update payloads, support:

```json
{
  "ingestion_model": {
    "model_source": "shared",
    "connection_id": "model_openai_ingestion",
    "params": {
      "timeout_seconds": 60
    }
  },
  "routing_model": {
    "model_source": "custom",
    "provider": "deepseek",
    "name": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "credential_ref": {"type": "env", "name": "DEEPSEEK_API_KEY"},
    "params": {
      "timeout_seconds": 10
    }
  }
}
```

Assert Knowledge Source stores source-owned model config and Agent Knowledge Bindings cannot override it.

- [ ] **Step 2: Write failing ingestion/routing resolver tests**

Assert ingestion and routing resolve the model connection before model calls and record connection resolution.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_ingestion_store.py tests/test_knowledge_ingestion_worker.py tests/test_local_index_provider.py -q
```

Expected: fail.

- [ ] **Step 4: Implement source-owned model config parsing**

Normalize existing local index params so old simple `ingestion_model.provider/name/params` fixtures migrate to `model_source: custom` or remain accepted only if they are standalone fixture-compatible. Avoid Agent Binding overrides.

- [ ] **Step 5: Wire ingestion and routing runtime**

Use `resolve_model_role_config()` or a source-level wrapper before constructing `ProofAgentLLM` for ingestion/routing.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_ingestion_store.py tests/test_knowledge_ingestion_worker.py tests/test_local_index_provider.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/delivery/configuration_api.py proof_agent/configuration/local_store.py proof_agent/capabilities/knowledge tests/test_knowledge_ingestion_store.py tests/test_knowledge_ingestion_worker.py tests/test_local_index_provider.py
git commit -m "feat: support source-owned model connections"
```

---

## Task 8: Add Dashboard API Types And Client Functions

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/api/client.test.ts`

- [ ] **Step 1: Write failing client tests**

Add tests for:

- `fetchModelConnections`
- `createModelConnection`
- `fetchModelConnection`
- `updateModelConnection`
- `archiveModelConnection`
- `restoreModelConnection`
- `fetchModelConnectionReferences`
- `fetchModelConnectionDeletionEligibility`
- `deleteModelConnection`
- `validateModelConnection`
- `smokeTestModelConnection`

Assert URLs use `/api/config/model-connections`.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```bash
cd dashboard && npm test -- src/api/client.test.ts
```

Expected: fail because functions do not exist.

- [ ] **Step 3: Implement types and client calls**

Add TypeScript interfaces matching backend DTOs. Do not include raw credential value fields.

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run:

```bash
cd dashboard && npm test -- src/api/client.test.ts
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/api/types.ts dashboard/src/api/client.ts dashboard/src/api/client.test.ts
git commit -m "feat: add model connection api client"
```

---

## Task 9: Build Models Workspace List

**Files:**
- Modify: `dashboard/src/components/Sidebar.tsx`
- Modify: `dashboard/src/router.tsx`
- Create: `dashboard/src/pages/ModelsPage.tsx`
- Create: `dashboard/src/pages/__tests__/ModelsPage.test.tsx`

- [ ] **Step 1: Write failing page tests**

Test:

- Sidebar shows `Models` under Configuration and links to `/models`.
- `/models` lists display name, connection id, provider, model identifier, base URL host, credential ref, lifecycle, reference counts, last smoke-test status, and updated time.
- Filters exist for provider, lifecycle, referenced/unreferenced, smoke-test status, and text search.
- Create form supports OpenAI, OpenAI-compatible, and DeepSeek options only in V1.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```bash
cd dashboard && npm test -- src/pages/__tests__/ModelsPage.test.tsx
```

Expected: fail.

- [ ] **Step 3: Implement ModelsPage**

Keep it operational and dense. Do not create a marketing page.

Use cards only for the create panel if needed; the list should be a scan-friendly table or row list.

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run:

```bash
cd dashboard && npm test -- src/pages/__tests__/ModelsPage.test.tsx
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/Sidebar.tsx dashboard/src/router.tsx dashboard/src/pages/ModelsPage.tsx dashboard/src/pages/__tests__/ModelsPage.test.tsx
git commit -m "feat: add models workspace"
```

---

## Task 10: Build Model Connection Detail Workspace

**Files:**
- Create: `dashboard/src/pages/ModelConnectionDetailPage.tsx`
- Create: `dashboard/src/pages/__tests__/ModelConnectionDetailPage.test.tsx`
- Modify: `dashboard/src/router.tsx`

- [ ] **Step 1: Write failing detail tests**

Test tabs:

- Overview
- References
- Test
- Audit

Test Overview can edit metadata and connection fields.

Test high-impact changes require impact confirmation when references exist.

Test Archive/Restore and Delete eligibility controls.

Test Test tab can run local validation and manual smoke test.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```bash
cd dashboard && npm test -- src/pages/__tests__/ModelConnectionDetailPage.test.tsx
```

Expected: fail.

- [ ] **Step 3: Implement detail page**

Use four lightweight tabs:

- Overview: connection form
- References: Draft Agents, Published Agent Versions, Knowledge Sources
- Test: validation/smoke actions and recent records
- Audit: operation audit list

Never render raw API key fields.

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run:

```bash
cd dashboard && npm test -- src/pages/__tests__/ModelConnectionDetailPage.test.tsx
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/ModelConnectionDetailPage.tsx dashboard/src/pages/__tests__/ModelConnectionDetailPage.test.tsx dashboard/src/router.tsx
git commit -m "feat: add model connection detail workspace"
```

---

## Task 11: Update Agent Model Module

**Files:**
- Modify: `dashboard/src/components/agent/ModelModuleEditor.tsx`
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`
- Modify: `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`
- Modify: `dashboard/src/components/__tests__/agent/ModuleEditor.test.tsx` if affected

- [ ] **Step 1: Write failing Agent UI tests**

Test:

- Answer, Planner, Reviewer each show a dropdown with Shared Model Connections and `Custom`.
- Archived connections are hidden from new selection.
- Existing archived references render with warning.
- Selecting shared writes `model_source: shared` and `connection_id`.
- Selecting custom exposes provider/name/base_url/credential_ref.
- Reviewer usage fields write into `review.subagent.params`.
- Unified Setup applies selected shared connection or custom values to all three roles.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```bash
cd dashboard && npm test -- src/pages/__tests__/AgentDetailPage.test.tsx
```

Expected: fail.

- [ ] **Step 3: Load model connections in AgentDetailPage**

Fetch `/api/config/model-connections` alongside Knowledge Sources.

Pass connections into `ModelModuleEditor`.

- [ ] **Step 4: Implement shared/custom selector**

Keep role-specific usage parameters close to each role.

Do not store raw credential values.

- [ ] **Step 5: Implement save-as-shared entry point**

For custom role config, add a clear action that creates a Shared Model Connection from connection fields and then asks the user whether to switch the current role to it.

- [ ] **Step 6: Run frontend tests and verify GREEN**

Run:

```bash
cd dashboard && npm test -- src/pages/__tests__/AgentDetailPage.test.tsx
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/components/agent/ModelModuleEditor.tsx dashboard/src/pages/AgentDetailPage.tsx dashboard/src/pages/__tests__/AgentDetailPage.test.tsx
git commit -m "feat: select shared model connections in agents"
```

---

## Task 12: Update Knowledge Source Model UI

**Files:**
- Modify: `dashboard/src/pages/KnowledgePage.tsx`
- Modify: `dashboard/src/pages/KnowledgeDetailPage.tsx`
- Modify: `dashboard/src/pages/__tests__/KnowledgePage.test.tsx`
- Modify: `dashboard/src/pages/__tests__/KnowledgeDetailPage.test.tsx`

- [ ] **Step 1: Write failing Knowledge UI tests**

Test:

- Local Index creation supports ingestion model source: shared or custom.
- Routing model can inherit ingestion model or explicitly choose shared/custom.
- Agent Knowledge Binding UI does not expose model connection override.
- Archived connections are hidden for new Source configuration and warn for existing references.
- Custom source config can be saved as shared and optionally switched.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```bash
cd dashboard && npm test -- src/pages/__tests__/KnowledgePage.test.tsx src/pages/__tests__/KnowledgeDetailPage.test.tsx
```

Expected: fail.

- [ ] **Step 3: Implement source-owned selectors**

Fetch Shared Model Connections in Knowledge pages.

Keep ingestion/routing usage params in Knowledge Source provider config.

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run:

```bash
cd dashboard && npm test -- src/pages/__tests__/KnowledgePage.test.tsx src/pages/__tests__/KnowledgeDetailPage.test.tsx
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/KnowledgePage.tsx dashboard/src/pages/KnowledgeDetailPage.tsx dashboard/src/pages/__tests__/KnowledgePage.test.tsx dashboard/src/pages/__tests__/KnowledgeDetailPage.test.tsx
git commit -m "feat: select model connections for knowledge sources"
```

---

## Task 13: Update Documentation

**Files:**
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`
- Modify: `AGENTS-COMMON.md` only if commands or canonical status change

- [ ] **Step 1: Update technical design**

Document:

- Models Workspace
- Shared Model Connection live reference behavior
- Model Connection Configuration API
- Model Connection Resolution Record
- Agent/Knownledge shared/custom model source shapes
- Reviewer params cleanup
- Secret boundary

- [ ] **Step 2: Update developer guide**

Add examples:

```yaml
model:
  model_source: shared
  connection_id: model_deepseek_default
  params:
    temperature: 0
    max_output_tokens: 800
```

and:

```yaml
model:
  model_source: custom
  provider: deepseek
  name: deepseek-chat
  base_url: https://api.deepseek.com
  credential_ref:
    type: env
    name: DEEPSEEK_API_KEY
  params:
    temperature: 0
```

- [ ] **Step 3: Update progress doc**

Record what shipped and any known limitations:

- No secret vault.
- No import/export.
- Azure/Anthropic placeholders not ready in Models Workspace create flow.

- [ ] **Step 4: Run markdown check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add docs/technical-design.md docs/developer-guide.md docs/development-progress.md
git commit -m "docs: document shared model connections"
```

---

## Task 14: Full Verification

**Files:**
- No source changes expected unless failures expose bugs.

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_model_connection_contracts.py tests/test_model_connection_store.py tests/test_model_connection_api.py tests/test_model_connection_resolution.py tests/test_model_config_validation.py tests/test_trace_model_events.py -q
```

Expected: pass.

- [ ] **Step 2: Run broader backend tests touched by model config**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_agent_configuration_api.py tests/test_knowledge_source_publication.py tests/test_knowledge_ingestion_store.py tests/test_knowledge_ingestion_worker.py tests/test_review_subagent.py -q
```

Expected: pass.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
cd dashboard && npm test
```

Expected: pass.

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd dashboard && npm run build
```

Expected: pass.

- [ ] **Step 5: Run deterministic demo**

Run:

```bash
uv run --extra dev proof-agent demo
```

Expected deterministic outcomes remain:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

- [ ] **Step 6: Inspect changed UI**

Start backend and Dashboard:

```bash
uv run --extra dashboard proof-agent server --host 127.0.0.1 --port 8000
cd dashboard && npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/models`.

Verify:

- Models list is not blank.
- Create form does not expose raw API key input.
- Detail tabs render without overlap on desktop and mobile widths.
- Agent Model module shared/custom selector writes expected YAML.
- Knowledge Source model selector stays Source-owned.

- [ ] **Step 7: Final diff check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.
