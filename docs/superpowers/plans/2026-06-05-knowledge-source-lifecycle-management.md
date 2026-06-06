# Knowledge Source Lifecycle Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add governed Knowledge Source archive, restore, deletion eligibility, and narrow physical deletion to Knowledge Hub.

**Architecture:** Add an explicit `lifecycle_state` to reusable Knowledge Sources and enforce lifecycle guards in the Local Configuration Store and Configuration API. Use one reference-summary projection for Archive impact and Physical Deletion blockers, and keep Physical Deletion audit outside the Source directory so it survives removal. Dashboard gets minimal lifecycle controls without adding a full Audit tab or artifact cleanup.

**Tech Stack:** Python 3.12, Pydantic v2, file-backed `LocalAgentConfigurationStore`, FastAPI configuration API, pytest, React 19, Vite, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-06-05-knowledge-source-lifecycle-management-design.md`

---

## File Structure

Modify:

- `proof_agent/contracts/agent_configuration.py` — add lifecycle state, reference summary, deletion eligibility, and lifecycle audit operation values.
- `proof_agent/contracts/__init__.py` — export new lifecycle contracts.
- `proof_agent/configuration/local_store.py` — add lifecycle state creation, reference summary, archive, restore, deletion eligibility, physical deletion, global configuration audit, and active-source guards.
- `proof_agent/delivery/configuration_api.py` — add lifecycle routes and route-level archived guards.
- `proof_agent/bootstrap/knowledge_resolution.py` — reject archived shared Sources during Configuration Store resolution.
- `proof_agent/delivery/published_agents.py` — no behavior change expected; tests verify pinned versions still run.
- `dashboard/src/api/types.ts` — add lifecycle and deletion eligibility types.
- `dashboard/src/api/client.ts` — add archive, restore, deletion eligibility, and physical delete calls.
- `dashboard/src/pages/KnowledgePage.tsx` — show lifecycle state and filter archived Sources from ordinary bindability expectations.
- `dashboard/src/pages/KnowledgeDetailPage.tsx` — add lifecycle controls and danger-zone blockers.
- `dashboard/src/pages/__tests__/KnowledgePage.test.tsx` — cover lifecycle state display.
- `dashboard/src/pages/__tests__/KnowledgeDetailPage.test.tsx` — cover archive/restore/delete controls.
- `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx` — cover archived Sources not selectable for new bindings.
- `docs/technical-design.md`, `docs/developer-guide.md`, `docs/development-progress.md` — document lifecycle behavior after implementation.

Create:

- `docs/adr/0019-knowledge-source-lifecycle-management.md` — record why Delete maps to Archive by default and Physical Deletion is narrow.

Tests:

- `tests/test_agent_configuration_contracts.py`
- `tests/test_agent_configuration_store.py`
- `tests/test_agent_configuration_api.py`
- `tests/test_knowledge_binding_resolver.py`
- `tests/test_published_agent_versions.py`

---

## Task 1: Add Lifecycle Contracts

**Files:**
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `tests/test_agent_configuration_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Add tests:

```python
def test_knowledge_source_requires_lifecycle_state() -> None:
    payload = {
        "source_id": "ks_policy",
        "name": "Policies",
        "provider": "local_index",
        "params": {},
        "created_at": "2026-06-05T00:00:00Z",
        "updated_at": "2026-06-05T00:00:00Z",
    }

    with pytest.raises(ValidationError):
        KnowledgeSource.model_validate(payload)


def test_knowledge_source_reference_summary_is_json_serializable() -> None:
    summary = KnowledgeSourceReferenceSummary(
        source_id="ks_policy",
        draft_agent_binding_count=1,
        published_agent_version_count=0,
        publication_count=0,
        snapshot_count=0,
        document_count=0,
        quarantined_upload_count=0,
        ingestion_job_count=0,
        audit_retention_blocked=False,
    )

    assert summary.model_dump(mode="json")["draft_agent_binding_count"] == 1
```

Add a contract test for `KnowledgeSourceDeletionEligibility` that serializes blockers.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_contracts.py -q
```

Expected: fail because lifecycle contracts do not exist.

- [ ] **Step 3: Implement contracts**

In `ConfigurationOperation`, add:

```python
ARCHIVED = "archived"
RESTORED = "restored"
PHYSICAL_DELETED = "physical_deleted"
```

Add:

```python
class KnowledgeSourceLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
```

Add required field to `KnowledgeSource`:

```python
lifecycle_state: KnowledgeSourceLifecycleState
```

Add:

```python
class KnowledgeSourceReferenceSummary(FrozenModel):
    source_id: str
    draft_agent_binding_count: int
    published_agent_version_count: int
    publication_count: int
    snapshot_count: int
    document_count: int
    quarantined_upload_count: int
    ingestion_job_count: int
    audit_retention_blocked: bool = False


class KnowledgeSourceDeletionEligibility(FrozenModel):
    source_id: str
    eligible: bool
    lifecycle_state: KnowledgeSourceLifecycleState
    reference_summary: KnowledgeSourceReferenceSummary
    blockers: tuple[str, ...] = Field(default_factory=tuple)
```

Export new contracts.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_contracts.py -q
```

Expected: pass.

---

## Task 2: Store Lifecycle State, Reference Summary, And Global Audit

**Files:**
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `tests/test_agent_configuration_store.py`

- [ ] **Step 1: Write failing store tests**

Add tests:

```python
def test_create_knowledge_source_sets_active_lifecycle_state(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    source = store.create_knowledge_source(
        source_id="ks_policy",
        name="Policies",
        provider="local_markdown",
        params={"path": "./knowledge"},
        actor="operator",
    )

    assert source.lifecycle_state == KnowledgeSourceLifecycleState.ACTIVE


def test_reading_legacy_source_without_lifecycle_state_fails(tmp_path: Path) -> None:
    source_dir = tmp_path / "knowledge_sources" / "ks_legacy"
    source_dir.mkdir(parents=True)
    (source_dir / "source.json").write_text(
        json.dumps({
            "source_id": "ks_legacy",
            "name": "Legacy",
            "provider": "local_markdown",
            "params": {},
            "created_at": "2026-06-05T00:00:00Z",
            "updated_at": "2026-06-05T00:00:00Z",
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        store.get_knowledge_source("ks_legacy")
```

Add a reference summary test with a Draft Agent YAML binding and a Published Agent Version resolved binding pointing to the Source.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_store.py -q
```

Expected: fail because lifecycle state and summary methods do not exist.

- [ ] **Step 3: Implement source creation and strict read**

Set `lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE` in `create_knowledge_source()`.

Do not add fallback for missing lifecycle fields. Let Pydantic validation fail so stale generated
local-store data is reset instead of dual-read.

- [ ] **Step 4: Implement reference summary**

Add:

```python
def get_knowledge_source_reference_summary(self, source_id: str) -> KnowledgeSourceReferenceSummary:
    ...
```

Count:

- Draft Agent bindings by parsing each Draft Agent `contract_bundle.agent_yaml` and counting `knowledge_bindings[].source_ref.scope == "shared"` plus matching `source_id`.
- Published Agent Version references from `version.resolved_knowledge_bindings.bindings[].source_id`.
- publications via `list_knowledge_source_publications(source_id)`.
- snapshots via `list_knowledge_source_snapshots(source_id)`.
- documents, quarantined uploads, and ingestion jobs via existing list methods.
- `audit_retention_blocked=False` for V1.

- [ ] **Step 5: Implement global configuration audit helper**

Add root-level paths:

```python
def _configuration_audit_root(self) -> Path: ...
def _configuration_audit_path(self, operation_id: str) -> Path: ...
```

Add:

```python
def record_configuration_operation(self, audit: ConfigurationOperationAudit) -> None:
    ...
```

Use it for Source lifecycle operations, especially physical deletion.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_store.py -q
```

Expected: pass.

---

## Task 3: Store Archive, Restore, Eligibility, And Physical Deletion

**Files:**
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `tests/test_agent_configuration_store.py`

- [ ] **Step 1: Write failing lifecycle operation tests**

Add tests:

```python
def test_archive_source_requires_reason_and_does_not_change_draft_version(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)

    with pytest.raises(ProofAgentError):
        store.archive_knowledge_source(source_id=source.source_id, actor="operator", reason="")

    archived = store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    assert archived.lifecycle_state == KnowledgeSourceLifecycleState.ARCHIVED
    assert archived.source_draft_version_id == source.source_draft_version_id


def test_restore_source_keeps_draft_version(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    source = _create_source(store)
    archived = store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )

    restored = store.restore_knowledge_source(source_id=source.source_id, actor="operator")

    assert restored.lifecycle_state == KnowledgeSourceLifecycleState.ACTIVE
    assert restored.source_draft_version_id == archived.source_draft_version_id
```

Add tests:

- physical deletion rejects active Source;
- physical deletion rejects archived Source with any blocker;
- physical deletion removes an empty archived Source and keeps global audit.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_store.py -q
```

Expected: fail because lifecycle methods do not exist.

- [ ] **Step 3: Implement archive and restore**

Add:

```python
def archive_knowledge_source(self, *, source_id: str, actor: str, reason: str) -> KnowledgeSource: ...
def restore_knowledge_source(self, *, source_id: str, actor: str, reason: str | None = None) -> KnowledgeSource: ...
```

Archive:

- requires non-empty reason;
- requires Source exists;
- is idempotent only if already archived and reason is still recorded as an audit event, or reject with a stable `PA_CONFIG_002`. Prefer reject to keep the API simple.
- updates lifecycle state and `updated_at`;
- does not change `source_draft_version_id`;
- records `ConfigurationOperation.ARCHIVED`.

Restore:

- requires Source exists and is archived;
- updates lifecycle state and `updated_at`;
- does not change `source_draft_version_id`;
- records `ConfigurationOperation.RESTORED`.

- [ ] **Step 4: Implement deletion eligibility**

Add:

```python
def get_knowledge_source_deletion_eligibility(self, source_id: str) -> KnowledgeSourceDeletionEligibility: ...
```

Blockers:

- `source_not_archived`
- `draft_agent_bindings`
- `published_agent_versions`
- `publications`
- `snapshots`
- `documents`
- `quarantined_uploads`
- `ingestion_jobs`
- `audit_retention`

- [ ] **Step 5: Implement physical deletion**

Add:

```python
def physically_delete_knowledge_source(self, *, source_id: str, actor: str, reason: str) -> KnowledgeSourceDeletionEligibility: ...
```

Behavior:

- requires non-empty reason;
- computes eligibility under lock;
- rejects if not eligible with `PA_CONFIG_002`;
- writes global `ConfigurationOperation.PHYSICAL_DELETED` audit with summary and reference counts;
- removes `knowledge_sources/{source_id}` directory;
- returns the eligibility record used for deletion.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_agent_configuration_store.py -q
```

Expected: pass.

---

## Task 4: Add API Routes And Archived Guards

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/bootstrap/knowledge_resolution.py`
- Modify: `tests/test_agent_configuration_api.py`
- Modify: `tests/test_knowledge_binding_resolver.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

- `POST /archive` returns archived Source and requires reason.
- `POST /restore` returns active Source.
- `GET /deletion-eligibility` returns blockers.
- `DELETE /knowledge-sources/{source_id}` physically deletes only an eligible archived empty Source.
- upload, routing metadata update, snapshot freeze, publication validation, and publication reject archived Sources.
- binding an archived Source to a Draft Agent is rejected.

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_agent_configuration_api.py tests/test_knowledge_binding_resolver.py -q
```

Expected: fail because routes and guards do not exist.

- [ ] **Step 3: Add request models and routes**

Add request models:

```python
class KnowledgeSourceArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)
    actor: str = "local-user"


class KnowledgeSourceRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = None
    actor: str = "local-user"


class KnowledgeSourcePhysicalDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)
    actor: str = "local-user"
```

Add routes:

```python
@router.post("/config/knowledge-sources/{source_id}/archive")
@router.post("/config/knowledge-sources/{source_id}/restore")
@router.get("/config/knowledge-sources/{source_id}/deletion-eligibility")
@router.delete("/config/knowledge-sources/{source_id}")
```

- [ ] **Step 4: Add archived guards**

Add helper:

```python
def _require_active_knowledge_source(store: LocalAgentConfigurationStore, source_id: str) -> KnowledgeSource:
    source = _require_knowledge_source(store, source_id)
    if source.lifecycle_state != KnowledgeSourceLifecycleState.ACTIVE:
        raise HTTPException(status_code=400, detail="Knowledge Source is archived.")
    return source
```

Use it for routes that mutate or publish Source state:

- document upload;
- batch upload;
- routing metadata edit;
- candidate snapshot;
- foundation validation;
- freeze;
- publication validate;
- publication publish;
- remote validation/preview where present;
- Agent binding attach.

Do not use it for reads, unbind, restore, archive, deletion eligibility, or physical delete.

- [ ] **Step 5: Reject archived Sources in resolver**

In `ConfigurationStoreKnowledgeBindingResolver.resolve()`, reject archived Sources with `PA_CONFIG_002`.

This makes Draft validation and Agent publication fail when a Draft still binds an archived Source.

- [ ] **Step 6: Run API tests and verify GREEN**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_agent_configuration_api.py tests/test_knowledge_binding_resolver.py -q
```

Expected: pass.

---

## Task 5: Dashboard API Client And Types

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/api/client.test.ts`

- [ ] **Step 1: Write failing frontend client tests**

Add tests that assert calls to:

- `/archive`;
- `/restore`;
- `/deletion-eligibility`;
- `DELETE /api/config/knowledge-sources/{source_id}`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd dashboard && npm test -- client
```

Expected: fail because client calls do not exist.

- [ ] **Step 3: Add types**

Add:

```ts
export type KnowledgeSourceLifecycleState = 'ACTIVE' | 'ARCHIVED'

export interface KnowledgeSourceReferenceSummary {
  source_id: string
  draft_agent_binding_count: number
  published_agent_version_count: number
  publication_count: number
  snapshot_count: number
  document_count: number
  quarantined_upload_count: number
  ingestion_job_count: number
  audit_retention_blocked: boolean
}

export interface KnowledgeSourceDeletionEligibility {
  source_id: string
  eligible: boolean
  lifecycle_state: KnowledgeSourceLifecycleState
  reference_summary: KnowledgeSourceReferenceSummary
  blockers: string[]
}
```

Extend `KnowledgeSource` with required `lifecycle_state`.

- [ ] **Step 4: Add client methods**

Add:

```ts
archiveKnowledgeSource(sourceId, payload)
restoreKnowledgeSource(sourceId, payload)
fetchKnowledgeSourceDeletionEligibility(sourceId)
permanentlyDeleteKnowledgeSource(sourceId, payload)
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
cd dashboard && npm test -- client
```

Expected: pass.

---

## Task 6: Dashboard Lifecycle Controls

**Files:**
- Modify: `dashboard/src/pages/KnowledgePage.tsx`
- Modify: `dashboard/src/pages/KnowledgeDetailPage.tsx`
- Modify: `dashboard/src/components/agent/KnowledgeModuleEditor.tsx`
- Modify: `dashboard/src/pages/__tests__/KnowledgePage.test.tsx`
- Modify: `dashboard/src/pages/__tests__/KnowledgeDetailPage.test.tsx`
- Modify: `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`

- [ ] **Step 1: Write failing UI tests**

Add tests:

- Knowledge list shows `ACTIVE` / `ARCHIVED`.
- Detail page shows Archive Source for active Source.
- Detail page shows Restore Source for archived Source.
- Danger-zone permanent delete button is disabled with blockers.
- Published-but-archived Source is not selectable for a new Agent binding.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd dashboard && npm test -- KnowledgePage KnowledgeDetailPage AgentDetailPage
```

Expected: fail because lifecycle controls do not exist.

- [ ] **Step 3: Update list/detail display**

Render lifecycle state as a compact operational status near published/draft state.

Do not hide archived Sources from the Knowledge list by default; operators need to inspect and
restore them.

- [ ] **Step 4: Add detail actions**

In `KnowledgeDetailPage.tsx`:

- fetch deletion eligibility with detail data;
- show Archive Source button when active;
- show Restore Source button when archived;
- disable publish/upload/provider-changing actions when archived;
- add danger-zone panel for Permanently delete Source with blockers.

Keep controls compact and aligned with existing dashboard patterns; do not add nested cards.

- [ ] **Step 5: Filter binding selector**

In `KnowledgeModuleEditor.tsx`, filter bindable Sources to:

```ts
source.published_snapshot_id && source.lifecycle_state === 'ACTIVE'
```

Show archived count as unavailable with a concrete reason.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
cd dashboard && npm test -- KnowledgePage KnowledgeDetailPage AgentDetailPage
```

Expected: pass.

---

## Task 7: ADR And Docs

**Files:**
- Create: `docs/adr/0019-knowledge-source-lifecycle-management.md`
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`

- [ ] **Step 1: Write ADR**

Create ADR covering:

- default Delete maps to Archive Source;
- Physical Deletion is separate and narrow;
- `ACTIVE/ARCHIVED` only, no `DELETED` state;
- no local-store compatibility for old generated data;
- Physical Deletion audit survives Source directory removal.

- [ ] **Step 2: Update technical design**

Update Knowledge Hub section with lifecycle state, API routes, archived guards, reference summary,
and Physical Deletion guard.

- [ ] **Step 3: Update developer guide**

Add operator flow:

```text
Archive Source -> inspect blockers -> restore or permanently delete if eligible
```

Mention `config-reset` for stale generated local-store data after lifecycle contract changes.

- [ ] **Step 4: Update development progress**

Move Knowledge Source lifecycle management from gap to implemented once code lands.

- [ ] **Step 5: Run docs check**

Run:

```bash
git diff --check
```

Expected: pass.

---

## Task 8: Final Verification

**Files:**
- No new code edits unless verification exposes a bug.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree python -m pytest \
  tests/test_agent_configuration_contracts.py \
  tests/test_agent_configuration_store.py \
  tests/test_agent_configuration_api.py \
  tests/test_knowledge_binding_resolver.py \
  tests/test_published_agent_versions.py -q
```

Expected: pass.

- [ ] **Step 2: Run focused frontend tests**

Run:

```bash
cd dashboard && npm test -- client KnowledgePage KnowledgeDetailPage AgentDetailPage
```

Expected: pass.

- [ ] **Step 3: Run deterministic smoke**

Run:

```bash
uv run --extra dev proof-agent demo
```

Expected:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

- [ ] **Step 4: Run formatting/checks**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
git diff --check
```

Expected: pass.

---

## Execution Notes

- Use TDD for every code task: write the failing test, verify it fails, implement, verify it passes.
- Do not add a hidden compatibility path for generated Source JSON without `lifecycle_state`.
- Do not physically delete retained publications, snapshots, documents, uploads, ingestion jobs, or artifacts.
- Do not auto-remove Draft Agent bindings when archiving a Source.
- Do not mutate existing Published Agent Versions when archiving or restoring a Source.
- Keep provider public contract as `provider + params`; organize validation/UI/docs by provider instead of introducing a public provider-union rewrite.
