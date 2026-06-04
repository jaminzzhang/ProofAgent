# Knowledge Hub Production Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one Dashboard-managed `local_index` Knowledge Source production-bindable end to end through Source publication, explicit knowledge binding resolution, and a minimal Knowledge Hub UI loop.

**Architecture:** Migrate the Agent Contract to explicit `package_knowledge_sources[]` plus `knowledge_bindings[].source_ref`, then introduce a `KnowledgeBindingResolver` that emits a `ResolvedKnowledgeBindingSet` for both standalone package execution and Configuration Store execution. Add Local Index Source publication validation and publication records before allowing Dashboard-managed Agents to bind shared Sources.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, Typer CLI, FastAPI configuration API, file-backed `LocalAgentConfigurationStore`, React 19, Vite, TypeScript, Tailwind CSS v4, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-06-04-knowledge-hub-production-loop-design.md`

---

## File Structure

Create:
- `proof_agent/contracts/knowledge_resolution.py` - resolved binding contracts used by runtime composition.
- `proof_agent/bootstrap/knowledge_resolution.py` - package-local and Configuration Store knowledge binding resolvers.
- `proof_agent/control/knowledge/source_publication.py` - Source-level Local Index smoke retrieval validation without final-answer generation.
- `dashboard/src/pages/KnowledgeDetailPage.tsx` - minimal Source detail workspace for Provider, Documents, Publication, and Overview sections.
- `tests/test_knowledge_binding_resolver.py` - resolver behavior and fail-closed cases.
- `tests/test_knowledge_source_publication.py` - store and smoke validation behavior.

Modify:
- `proof_agent/contracts/manifest.py` - rename package-local Source field, add `source_ref` to bindings.
- `proof_agent/contracts/agent_configuration.py` - add Source publication validation and publication record contracts; add resolved binding persistence fields to Published Agent Versions.
- `proof_agent/contracts/__init__.py` - export new contracts.
- `proof_agent/bootstrap/manifest.py` - parse `package_knowledge_sources[]` and `knowledge_bindings[].source_ref`.
- `proof_agent/bootstrap/validation.py` - reject legacy ambiguous `knowledge_sources[]`; validate `source_ref`.
- `proof_agent/bootstrap/composition.py` - accept a resolver or precomputed resolved set.
- `proof_agent/capabilities/knowledge/blended.py` - construct bound providers from `ResolvedKnowledgeBindingSet`.
- `proof_agent/configuration/importer.py` - preserve contract view and classify `package_knowledge_sources` as a basic field.
- `proof_agent/configuration/local_store.py` - persist publication validations, publication records, resolved sets, and reset support.
- `proof_agent/delivery/cli.py` - add explicit local Configuration Store reset command.
- `proof_agent/delivery/configuration_api.py` - add publication routes and shared-source binding behavior.
- `proof_agent/delivery/published_agents.py` - resolve configured Published Agent Versions with persisted resolved bindings.
- `proof_agent/runtime/langgraph_runner.py` - pass resolved binding data into composition for configured runs if needed by API path.
- `proof_agent/delivery/api.py`, `proof_agent/delivery/customer_api.py`, and `proof_agent/delivery/customer_adapters.py` - preserve production execution behavior when Published Agent Registry returns configured versions with resolved sets.
- `proof_agent/evaluation/demo/fixtures/**/agent*.yaml` and `examples/insurance_customer_service/agent.yaml` - migrate standalone packages to `package_knowledge_sources[]` and `source_ref(scope=package)`.
- `dashboard/src/api/types.ts` and `dashboard/src/api/client.ts` - add publication and detail API types/client calls.
- `dashboard/src/pages/KnowledgePage.tsx` - remove stale `index_path` creation and link to detail route.
- `dashboard/src/router.tsx` - add `/knowledge/:sourceId`.
- `dashboard/src/components/agent/KnowledgeModuleEditor.tsx` - list only published shared Sources and write `source_ref(scope=shared)` bindings.
- `docs/technical-design.md`, `docs/developer-guide.md`, `docs/development-progress.md` - update English docs after implementation.

Keep unchanged unless a test proves they need a focused update:
- `proof_agent/capabilities/knowledge/local_index.py` - already consumes `snapshot_path + artifact_root`.
- `proof_agent/capabilities/knowledge/local_index_snapshot.py` - already validates `local_index.snapshot.v2`.
- Chinese docs under `docs/zh/` - release-sync only.

---

## Task 0: Add Local Configuration Store Reset

**Files:**
- Modify: `proof_agent/delivery/cli.py`
- Modify: `tests/test_cli.py`
- Optional modify: `proof_agent/configuration/local_store.py` if reset helper belongs in the store

- [ ] **Step 1: Write failing CLI reset tests**

Add tests to `tests/test_cli.py`:

```python
def test_config_reset_local_store_deletes_only_config_dir(tmp_path: Path) -> None:
    config_dir = tmp_path / "runs" / "config"
    history_dir = tmp_path / "runs" / "history"
    latest_dir = tmp_path / "runs" / "latest"
    config_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)
    latest_dir.mkdir(parents=True)
    (config_dir / "source.json").write_text("{}", encoding="utf-8")
    (history_dir / "trace.jsonl").write_text("{}", encoding="utf-8")
    (latest_dir / "governance_receipt.md").write_text("# receipt", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "config-reset",
            "--scope",
            "local-store",
            "--config-dir",
            str(config_dir),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert not config_dir.exists()
    assert history_dir.exists()
    assert latest_dir.exists()
    assert "cleared local configuration store" in result.output


def test_config_reset_requires_explicit_scope(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config-reset", "--config-dir", str(tmp_path / "config")])

    assert result.exit_code != 0
    assert "local-store" in result.output
```

- [ ] **Step 2: Run reset tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_cli.py::test_config_reset_local_store_deletes_only_config_dir tests/test_cli.py::test_config_reset_requires_explicit_scope -q
```

Expected: fail because `config-reset` does not exist.

- [ ] **Step 3: Implement the command**

In `proof_agent/delivery/cli.py`, add:

```python
@app.command("config-reset")
def config_reset(
    scope: str = typer.Option(..., "--scope"),
    config_dir: str = typer.Option("runs/config", "--config-dir"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Clear generated local configuration state."""

    if scope != "local-store":
        typer.echo("Supported reset scope: local-store", err=True)
        raise typer.Exit(code=2)
    if not yes:
        typer.echo("Pass --yes to clear the local Configuration Store.", err=True)
        raise typer.Exit(code=2)
    path = Path(config_dir)
    if path.exists():
        import shutil

        shutil.rmtree(path)
    typer.echo(f"cleared local configuration store: {path}")
```

Keep the deletion limited to the supplied config dir. Do not touch `runs/history` or `runs/latest`.

- [ ] **Step 4: Run reset tests and verify pass**

Run:

```bash
uv run --extra dev python -m pytest tests/test_cli.py::test_config_reset_local_store_deletes_only_config_dir tests/test_cli.py::test_config_reset_requires_explicit_scope -q
```

Expected: pass.

- [ ] **Step 5: Execute reset against generated local state**

Run:

```bash
uv run --extra dev proof-agent config-reset --scope local-store --config-dir runs/config --yes
```

Expected: `runs/config` is removed or absent; `runs/history` and `runs/latest` remain untouched.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/delivery/cli.py tests/test_cli.py
git commit -m "feat: add local configuration store reset"
```

---

## Task 1: Migrate Agent Contract To Explicit Source References

**Files:**
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `proof_agent/configuration/importer.py`
- Modify: `tests/test_config_loader.py`
- Modify: `tests/test_agent_package_import.py`
- Modify: `tests/test_trust_boundaries.py`
- Modify: `tests/test_model_config_validation.py`
- Modify: `proof_agent/evaluation/demo/fixtures/**/agent*.yaml`
- Modify: `examples/insurance_customer_service/agent.yaml`

- [ ] **Step 1: Write failing contract parser tests**

In `tests/test_config_loader.py`, change the happy path fixture to:

```yaml
package_knowledge_sources:
  - source_id: ks_local
    name: Local Knowledge
    provider: local_markdown
    params:
      path: ./knowledge
knowledge_bindings:
  - binding_id: kb_local
    source_ref:
      scope: package
      source_id: ks_local
    alias: policy_docs
```

Assert:

```python
assert manifest.package_knowledge_sources[0].source_id == "ks_local"
assert manifest.knowledge_bindings[0].source_ref.scope == "package"
assert manifest.knowledge_bindings[0].source_ref.source_id == "ks_local"
```

Add a rejection test:

```python
def test_legacy_knowledge_sources_field_is_rejected(tmp_path: Path) -> None:
    # write agent.yaml with top-level knowledge_sources and old binding source_id
    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)
    assert exc.value.code == "PA_CONFIG_001"
    assert "package_knowledge_sources" in exc.value.fix
```

- [ ] **Step 2: Run loader tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py -q
```

Expected: fail because contracts still expect `knowledge_sources[]`.

- [ ] **Step 3: Update manifest contracts**

In `proof_agent/contracts/manifest.py`, add:

```python
class KnowledgeSourceReferenceConfig(FrozenModel):
    scope: Literal["package", "shared"]
    source_id: str


class PackageKnowledgeSourceConfig(FrozenModel):
    source_id: str
    name: str
    provider: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)
```

Update `KnowledgeBindingConfig`:

```python
class KnowledgeBindingConfig(FrozenModel):
    binding_id: str
    source_ref: KnowledgeSourceReferenceConfig
    alias: str | None = None
    failure_mode: str = "required"
    fusion_weight: float = 1.0
    top_k: int | None = None
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
```

Update `AgentManifest`:

```python
package_knowledge_sources: tuple[PackageKnowledgeSourceConfig, ...]
knowledge_bindings: tuple[KnowledgeBindingConfig, ...]
```

Export the new classes from `proof_agent/contracts/__init__.py`.

- [ ] **Step 4: Update manifest parsing**

In `proof_agent/bootstrap/manifest.py`:

- read `package_knowledge_sources = raw["package_knowledge_sources"]`;
- parse package entries with `_package_knowledge_source_config_from_mapping()`;
- parse binding `source_ref` as a required mapping;
- remove old top-level `knowledge_sources` parser.

Expected binding parser shape:

```python
source_ref = raw["source_ref"]
if not isinstance(source_ref, dict):
    raise TypeError("knowledge_bindings entries require source_ref mappings")
```

- [ ] **Step 5: Update validation**

In `proof_agent/bootstrap/validation.py`:

- replace required top-level `knowledge_sources` with `package_knowledge_sources`;
- reject top-level `knowledge_sources` with `PA_CONFIG_001`;
- validate package Source ids are unique;
- validate each package Source provider params with the existing provider validation logic;
- validate each binding has a `source_ref.scope` of `package` or `shared`;
- for `scope=package`, require `source_ref.source_id` exists in `package_knowledge_sources`;
- for `scope=shared`, do not require a package Source id because the Configuration Store resolver owns that check.

Error guidance should mention `package_knowledge_sources[]` and `knowledge_bindings[].source_ref`.

- [ ] **Step 6: Update importer UI field classification**

In `proof_agent/configuration/importer.py`, replace `"knowledge_sources"` in `BASIC_UI_TOP_LEVEL_FIELDS` with `"package_knowledge_sources"`.

- [ ] **Step 7: Migrate standalone fixtures**

Update every standalone package YAML under:

```text
proof_agent/evaluation/demo/fixtures/
examples/insurance_customer_service/
```

Pattern:

```yaml
package_knowledge_sources:
  - source_id: enterprise_qa_knowledge
    name: Enterprise QA Knowledge
    provider: local_markdown
    params:
      path: ./knowledge
knowledge_bindings:
  - binding_id: enterprise_qa_knowledge_binding
    source_ref:
      scope: package
      source_id: enterprise_qa_knowledge
```

Do not add shared Source refs to deterministic fixtures.

- [ ] **Step 8: Run loader and package tests**

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_config_loader.py \
  tests/test_agent_package_import.py \
  tests/test_trust_boundaries.py \
  tests/test_model_config_validation.py -q
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add proof_agent/contracts/manifest.py proof_agent/contracts/__init__.py \
  proof_agent/bootstrap/manifest.py proof_agent/bootstrap/validation.py \
  proof_agent/configuration/importer.py \
  proof_agent/evaluation/demo/fixtures examples/insurance_customer_service \
  tests/test_config_loader.py tests/test_agent_package_import.py \
  tests/test_trust_boundaries.py tests/test_model_config_validation.py
git commit -m "feat: make knowledge source references explicit"
```

---

## Task 2: Add Resolved Knowledge Binding Contracts And Package Resolver

**Files:**
- Create: `proof_agent/contracts/knowledge_resolution.py`
- Create: `proof_agent/bootstrap/knowledge_resolution.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_knowledge_binding_resolver.py`

- [ ] **Step 1: Write failing package resolver tests**

Create `tests/test_knowledge_binding_resolver.py` with tests:

```python
def test_package_resolver_resolves_package_source(tmp_path: Path) -> None:
    manifest = load_agent_manifest(agent_yaml)
    resolved = PackageKnowledgeBindingResolver().resolve(manifest)
    assert resolved.bindings[0].source_scope == "package"
    assert resolved.bindings[0].source_id == "ks_local"
    assert resolved.bindings[0].provider == "local_markdown"
    assert resolved.bindings[0].provider_params["path"] == tmp_path / "knowledge"


def test_package_resolver_rejects_shared_source_ref() -> None:
    with pytest.raises(ProofAgentError) as exc:
        PackageKnowledgeBindingResolver().resolve(manifest_with_shared_ref)
    assert exc.value.code == "PA_CONFIG_002"
```

- [ ] **Step 2: Run resolver tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_binding_resolver.py -q
```

Expected: fail because resolver module does not exist.

- [ ] **Step 3: Add resolved contracts**

Create `proof_agent/contracts/knowledge_resolution.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from pydantic import Field, field_serializer, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class ResolvedKnowledgeBinding(FrozenModel):
    binding_id: str
    source_scope: Literal["package", "shared"]
    source_id: str
    source_version_id: str
    provider: str
    provider_params: Mapping[str, Any] = Field(default_factory=FrozenDict)
    alias: str | None = None
    failure_mode: str = "required"
    fusion_weight: float = 1.0
    top_k: int | None = None
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("provider_params", "routing_metadata", mode="after")
    @classmethod
    def freeze_mapping(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("provider_params", "routing_metadata")
    def serialize_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], value)


class ResolvedKnowledgeBindingSet(FrozenModel):
    bindings: tuple[ResolvedKnowledgeBinding, ...]
```

Export both classes.

- [ ] **Step 4: Add package resolver**

Create `proof_agent/bootstrap/knowledge_resolution.py`:

```python
from __future__ import annotations

from typing import Protocol

from proof_agent.contracts import AgentManifest
from proof_agent.contracts.knowledge_resolution import (
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.errors import ProofAgentError


class KnowledgeBindingResolver(Protocol):
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet: ...


class PackageKnowledgeBindingResolver:
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        source_by_id = {
            source.source_id: source for source in manifest.package_knowledge_sources
        }
        resolved = []
        for binding in manifest.knowledge_bindings:
            ref = binding.source_ref
            if ref.scope != "package":
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    "Standalone package execution cannot resolve shared Knowledge Sources.",
                    "Use a Configuration Store resolver for source_ref.scope: shared.",
                )
            source = source_by_id[ref.source_id]
            resolved.append(
                ResolvedKnowledgeBinding(
                    binding_id=binding.binding_id,
                    source_scope="package",
                    source_id=source.source_id,
                    source_version_id="package",
                    provider=source.provider,
                    provider_params=source.params,
                    alias=binding.alias,
                    failure_mode=binding.failure_mode,
                    fusion_weight=binding.fusion_weight,
                    top_k=binding.top_k,
                    routing_metadata=binding.routing_metadata,
                )
            )
        return ResolvedKnowledgeBindingSet(bindings=tuple(resolved))
```

- [ ] **Step 5: Run resolver tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_binding_resolver.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/contracts/knowledge_resolution.py proof_agent/contracts/__init__.py \
  proof_agent/bootstrap/knowledge_resolution.py tests/test_knowledge_binding_resolver.py
git commit -m "feat: add knowledge binding resolver contracts"
```

---

## Task 3: Route Composition Through Resolved Bindings

**Files:**
- Modify: `proof_agent/capabilities/knowledge/blended.py`
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `tests/test_composition.py`
- Modify: `tests/test_knowledge_retrieval_service.py` if imports expect old `BoundKnowledgeProvider`

- [ ] **Step 1: Write failing composition tests**

Update `tests/test_composition.py` blended fixture to use `package_knowledge_sources[]` and `source_ref(scope=package)`.

Add:

```python
def test_compose_harness_invocation_accepts_precomputed_resolved_bindings(tmp_path: Path) -> None:
    resolved = ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeBinding(
                binding_id="kb_alpha",
                source_scope="package",
                source_id="ks_alpha",
                source_version_id="package",
                provider="local_markdown",
                provider_params={"path": source_one},
                failure_mode="required",
                fusion_weight=1.0,
            ),
        )
    )
    invocation = compose_harness_invocation(agent_yaml, resolved_knowledge_bindings=resolved)
    assert invocation.knowledge_provider.provider_name == "local_markdown"
```

- [ ] **Step 2: Run composition tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_composition.py -q
```

Expected: fail because composition still resolves from manifest sources.

- [ ] **Step 3: Change blended provider construction**

In `proof_agent/capabilities/knowledge/blended.py`:

- change `BoundKnowledgeProvider` to hold `resolved: ResolvedKnowledgeBinding` and `provider`;
- add `resolve_blended_knowledge_provider(resolved_set: ResolvedKnowledgeBindingSet)`;
- instantiate each provider with:

```python
provider = resolve_knowledge_provider(
    KnowledgeConfig(provider=resolved.provider, params=resolved.provider_params)
)
```

Update `_tag_chunk()` to use `bound.resolved.source_id`, `binding_id`, and `fusion_weight`.

- [ ] **Step 4: Change composition**

In `proof_agent/bootstrap/composition.py`:

```python
def compose_harness_invocation(
    agent_yaml: Path | str,
    *,
    manifest: AgentManifest | None = None,
    knowledge_binding_resolver: KnowledgeBindingResolver | None = None,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None,
) -> HarnessInvocation:
    ...
    resolved_bindings = resolved_knowledge_bindings
    if resolved_bindings is None:
        resolver = knowledge_binding_resolver or PackageKnowledgeBindingResolver()
        resolved_bindings = resolver.resolve(resolved_manifest)
```

Add `resolved_knowledge_bindings` to `HarnessInvocation` for trace/debug visibility.

- [ ] **Step 5: Update retrieval service tests if needed**

If tests directly construct `BoundKnowledgeProvider(source=..., binding=...)`, update helpers to construct `ResolvedKnowledgeBinding` first.

- [ ] **Step 6: Run composition and retrieval tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_composition.py tests/test_knowledge_retrieval_service.py -q
```

Expected: pass.

- [ ] **Step 7: Run deterministic demo smoke**

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

- [ ] **Step 8: Commit**

```bash
git add proof_agent/capabilities/knowledge/blended.py proof_agent/bootstrap/composition.py \
  tests/test_composition.py tests/test_knowledge_retrieval_service.py
git commit -m "feat: compose harness from resolved knowledge bindings"
```

---

## Task 4: Add Source Publication Contracts And Store Persistence

**Files:**
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `proof_agent/configuration/local_store.py`
- Create or modify: `tests/test_knowledge_source_publication.py`

- [ ] **Step 1: Write failing store publication tests**

In `tests/test_knowledge_source_publication.py`, add tests:

```python
def test_publication_requires_change_note(tmp_path: Path) -> None:
    store, validation = _store_with_passed_publication_validation(tmp_path)
    with pytest.raises(ProofAgentError) as exc:
        store.publish_knowledge_source(
            source_id="ks_policy",
            validation_id=validation.validation_id,
            change_note="",
            actor="operator",
        )
    assert exc.value.code == "PA_CONFIG_001"


def test_publish_writes_record_and_published_snapshot_pointer(tmp_path: Path) -> None:
    store, validation = _store_with_passed_publication_validation(tmp_path)
    record = store.publish_knowledge_source(...)
    source = store.get_knowledge_source("ks_policy")
    assert source.published_snapshot_id == record.snapshot_id
    assert store.list_knowledge_source_publications("ks_policy") == [record]


def test_reusing_publication_validation_conflicts(tmp_path: Path) -> None:
    store, validation = _store_with_passed_publication_validation(tmp_path)
    store.publish_knowledge_source(...)
    with pytest.raises(ProofAgentError) as exc:
        store.publish_knowledge_source(...)
    assert exc.value.code == "PA_CONFIG_002"
```

Use existing helper patterns from `tests/test_knowledge_snapshot_store.py` for ready documents and frozen snapshots.

- [ ] **Step 2: Run publication tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_source_publication.py -q
```

Expected: fail because contracts/store methods do not exist.

- [ ] **Step 3: Add contracts**

In `proof_agent/contracts/agent_configuration.py`, add:

```python
class KnowledgeSourcePublicationValidation(FrozenModel):
    validation_id: str
    source_id: str
    snapshot_id: str
    source_draft_version_id: str
    candidate_digest: str
    status: Literal["passed"]
    smoke_query: str
    candidate_count: int
    citation_count: int
    created_at: str
    created_by: str


class KnowledgeSourcePublicationRecord(FrozenModel):
    publication_id: str
    source_id: str
    snapshot_id: str
    source_draft_version_id: str
    validation_id: str
    change_note: str
    published_at: str
    published_by: str
    document_count: int
    smoke_query: str
    smoke_result_summary: Mapping[str, Any] = Field(default_factory=FrozenDict)
```

Add serializers for `smoke_result_summary` using the existing FrozenDict pattern.

- [ ] **Step 4: Add store paths and read/write helpers**

In `proof_agent/configuration/local_store.py`, add path helpers:

```python
def _knowledge_source_publication_validations_root(self, source_id: str) -> Path: ...
def _knowledge_source_publication_validation_path(self, source_id: str, validation_id: str) -> Path: ...
def _knowledge_source_publications_root(self, source_id: str) -> Path: ...
def _knowledge_source_publication_path(self, source_id: str, publication_id: str) -> Path: ...
```

Add:

```python
def get_knowledge_source_publication_validation(...)
def list_knowledge_source_publication_validations(...)
def list_knowledge_source_publications(...)
def publish_knowledge_source(...)
```

For this task, publication validation records can be created by test helper/private writer; Task 5 adds real smoke validation.

- [ ] **Step 5: Implement `publish_knowledge_source()`**

Inside store lock:

- require source exists;
- require validation exists and status is `passed`;
- require validation source id matches;
- derive current candidate and reject source draft/candidate drift;
- reject empty `change_note`;
- reject any existing publication with the same `validation_id`;
- create `publication_id = f"kspub_{uuid4().hex[:8]}"`;
- write record;
- update `source.published_snapshot_id`.

- [ ] **Step 6: Run publication store tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_source_publication.py -q
```

Expected: pass for publish-only cases.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/contracts/agent_configuration.py proof_agent/contracts/__init__.py \
  proof_agent/configuration/local_store.py tests/test_knowledge_source_publication.py
git commit -m "feat: persist knowledge source publications"
```

---

## Task 5: Add Local Index Publication Smoke Validation

**Files:**
- Create: `proof_agent/control/knowledge/source_publication.py`
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `tests/test_knowledge_source_publication.py`
- Modify: `tests/test_local_index_provider.py` if a helper is reusable

- [ ] **Step 1: Write failing smoke validation tests**

In `tests/test_knowledge_source_publication.py`, add:

```python
def test_validate_publication_requires_latest_snapshot(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    with pytest.raises(ProofAgentError) as exc:
        store.validate_local_index_source_publication(
            source_id="ks_policy",
            smoke_query="What is covered?",
            actor="operator",
        )
    assert exc.value.code == "PA_CONFIG_001"


def test_validate_publication_rejects_zero_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # monkeypatch smoke retrieval callable to return ()
    ...


def test_validate_publication_persists_passed_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # monkeypatch smoke retrieval callable to return cited local_index evidence
    validation = store.validate_local_index_source_publication(...)
    assert validation.status == "passed"
    assert validation.candidate_count == 1
```

Allow injection of a smoke retriever into the store method or route through a small service object so tests do not need to build a real LlamaIndex artifact for every case.

- [ ] **Step 2: Run smoke tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_source_publication.py -q
```

Expected: fail because validation method/service does not exist.

- [ ] **Step 3: Create smoke retrieval service**

Create `proof_agent/control/knowledge/source_publication.py`:

```python
LOCAL_KNOWLEDGE_CITATION_RE = re.compile(
    r"^knowledge://source/[^/]+/document/[^/]+/revision/[^/#]+#.+$"
)


@dataclass(frozen=True)
class LocalIndexPublicationSmokeResult:
    candidates: tuple[EvidenceChunk, ...]
    citation_count: int


def validate_local_index_publication_smoke(
    *,
    source: KnowledgeSource,
    snapshot: KnowledgeSourceSnapshotManifest,
    artifact_root: Path,
    smoke_query: str,
    top_k: int = 3,
) -> LocalIndexPublicationSmokeResult:
    ...
```

Build provider params:

```python
params = {
    "snapshot_path": artifact_root / "knowledge_sources" / source.source_id / "snapshots" / snapshot.snapshot_id,
    "artifact_root": artifact_root,
    "document_selection_budget": source.params.get("document_selection_budget", 8),
}
if "routing_model" in source.params:
    params["routing_model"] = source.params["routing_model"]
elif "ingestion_model" in source.params:
    params["ingestion_model"] = source.params["ingestion_model"]
```

Call `LocalIndexProvider.from_config(KnowledgeConfig(provider="local_index", params=params))` and `retrieve(smoke_query, top_k=top_k)`.

Fail with `ProofAgentError("PA_CONFIG_001", ...)` when:

- query is empty;
- retrieval returns no candidates;
- no candidate has a citation;
- no citation matches Local Knowledge Citation URI shape.

- [ ] **Step 4: Wire store validation to service**

In `LocalAgentConfigurationStore.validate_local_index_source_publication()`:

- acquire store lock for source/snapshot/candidate identity checks;
- release before expensive retrieval if needed, but capture immutable source/snapshot inputs first;
- run smoke service;
- reacquire lock and recheck source draft version/candidate digest before writing validation;
- persist `KnowledgeSourcePublicationValidation`.

If keeping the lock through retrieval is simpler for this local-store slice, document in a comment that this is acceptable only because A scope is local single-user and future production queue work can split the lock.

- [ ] **Step 5: Run smoke validation tests**

Run:

```bash
uv run --extra dev --extra tree python -m pytest tests/test_knowledge_source_publication.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/control/knowledge/source_publication.py \
  proof_agent/configuration/local_store.py tests/test_knowledge_source_publication.py
git commit -m "feat: validate local index source publication"
```

---

## Task 6: Add Publication API Routes

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `tests/test_agent_configuration_api.py`

- [ ] **Step 1: Write failing API tests**

In `tests/test_agent_configuration_api.py`, add:

```python
def test_source_publication_validation_and_publish_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    _create_local_index_source(client, params={"ingestion_model": {"provider": "deterministic", "name": "routing"}})
    frozen = _freeze_ready_snapshot(client)
    monkeypatch smoke service to return cited evidence

    validation = client.post(
        "/api/config/knowledge-sources/ks_local_index/publication/validate",
        json={"smoke_query": "What is the policy?", "actor": "operator"},
    )
    published = client.post(
        "/api/config/knowledge-sources/ks_local_index/publication/publish",
        json={
            "validation_id": validation.json()["validation_id"],
            "change_note": "First production publication.",
            "actor": "operator",
        },
    )

    assert validation.status_code == 200
    assert published.status_code == 200
    assert client.get("/api/config/knowledge-sources/ks_local_index").json()["published_snapshot_id"] == frozen["snapshot_id"]
```

Add validation for missing `change_note` returning 422 or 400.

- [ ] **Step 2: Run API tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_agent_configuration_api.py -q
```

Expected: fail because routes do not exist.

- [ ] **Step 3: Add request models**

In `proof_agent/delivery/configuration_api.py`:

```python
class KnowledgeSourcePublicationValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    smoke_query: str = Field(min_length=1)
    actor: str = "local-user"


class KnowledgeSourcePublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_id: str = Field(min_length=1)
    change_note: str = Field(min_length=1)
    actor: str = "local-user"
```

- [ ] **Step 4: Add routes**

Add:

```python
@router.post("/config/knowledge-sources/{source_id}/publication/validate")
def validate_knowledge_source_publication(...): ...

@router.post("/config/knowledge-sources/{source_id}/publication/publish")
def publish_knowledge_source(...): ...

@router.get("/config/knowledge-sources/{source_id}/publications")
def list_knowledge_source_publications(...): ...

@router.get("/config/knowledge-sources/{source_id}/publication-validations")
def list_knowledge_source_publication_validations(...): ...
```

Use `_proof_agent_http_exception()` for `ProofAgentError`.

- [ ] **Step 5: Extend Source payload**

Update `_knowledge_source_payload()` to include:

```python
payload["publication_count"] = len(store.list_knowledge_source_publications(source.source_id))
```

Do not expose raw smoke result content beyond summaries.

- [ ] **Step 6: Run API tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_agent_configuration_api.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/delivery/configuration_api.py tests/test_agent_configuration_api.py
git commit -m "feat: expose knowledge source publication api"
```

---

## Task 7: Add Configuration Store Resolver And Persist Resolved Bindings In Versions

**Files:**
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/bootstrap/knowledge_resolution.py`
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/delivery/published_agents.py`
- Modify: `tests/test_knowledge_binding_resolver.py`
- Modify: `tests/test_published_agent_versions.py`
- Modify: `tests/test_agent_configuration_api.py`

- [ ] **Step 1: Write failing resolver tests**

In `tests/test_knowledge_binding_resolver.py`, add:

```python
def test_configuration_store_resolver_rejects_unpublished_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_knowledge_source(...)
    manifest = _manifest_with_shared_ref("ks_policy")

    with pytest.raises(ProofAgentError) as exc:
        ConfigurationStoreKnowledgeBindingResolver(store).resolve(manifest)

    assert exc.value.code == "PA_CONFIG_002"


def test_configuration_store_resolver_maps_published_local_index_snapshot(tmp_path: Path) -> None:
    store, publication = _store_with_published_snapshot(tmp_path)
    manifest = _manifest_with_shared_ref("ks_policy")
    resolved = ConfigurationStoreKnowledgeBindingResolver(store).resolve(manifest)
    binding = resolved.bindings[0]
    assert binding.source_scope == "shared"
    assert binding.source_version_id == publication.snapshot_id
    assert binding.provider == "local_index"
    assert "snapshot_path" in binding.provider_params
    assert "artifact_root" in binding.provider_params
```

- [ ] **Step 2: Run resolver tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_binding_resolver.py -q
```

Expected: fail because Configuration Store resolver does not exist.

- [ ] **Step 3: Add resolver implementation**

In `proof_agent/bootstrap/knowledge_resolution.py`, add:

```python
class ConfigurationStoreKnowledgeBindingResolver:
    def __init__(self, store: LocalAgentConfigurationStore) -> None:
        self._store = store

    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        resolved = []
        for binding in manifest.knowledge_bindings:
            ref = binding.source_ref
            if ref.scope != "shared":
                raise ProofAgentError(...)
            source = self._store.get_knowledge_source(ref.source_id)
            if source is None or source.published_snapshot_id is None:
                raise ProofAgentError(...)
            snapshot = self._store.get_knowledge_source_snapshot(
                source_id=source.source_id,
                snapshot_id=source.published_snapshot_id,
            )
            if snapshot is None:
                raise ProofAgentError(...)
            provider_params = _provider_params_for_published_source(
                store_root=self._store.root_dir,
                source=source,
                snapshot=snapshot,
            )
            resolved.append(...)
        return ResolvedKnowledgeBindingSet(bindings=tuple(resolved))
```

For `local_index`, provider params:

```python
{
    "snapshot_path": self._store.root_dir / "knowledge_sources" / source.source_id / "snapshots" / snapshot.snapshot_id,
    "artifact_root": self._store.root_dir,
    "routing_model": source.params.get("routing_model") or source.params.get("ingestion_model"),
    "document_selection_budget": source.params.get("document_selection_budget", 8),
}
```

Reject missing routing/ingestion model for `local_index` with `PA_CONFIG_001`.

- [ ] **Step 4: Persist resolved bindings in PublishedAgentVersion**

In `proof_agent/contracts/agent_configuration.py`, add:

```python
resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None
```

to `PublishedAgentVersion`.

Update serializers/imports carefully to avoid circular imports. If importing from
`contracts.knowledge_resolution` into `contracts.agent_configuration` creates a cycle, move resolved
contracts into `agent_configuration.py` or keep them in `manifest.py`. Prefer the smallest cycle-free
placement.

- [ ] **Step 5: Update Draft validation and publish paths**

In `proof_agent/delivery/configuration_api.py`:

- `validate_config_draft()` should compile the draft package, load its manifest, resolve shared bindings with `ConfigurationStoreKnowledgeBindingResolver`, and pass `resolved_knowledge_bindings` into `run_with_langgraph()` or into composition if the runner accepts it after Task 8.
- `publish_config_draft()` should persist the resolved set used by the validation run. If the validation record does not store the resolved set yet, add it to `AgentValidationRecord` or store validation metadata in `operation_audit`. Preferred: add `resolved_knowledge_bindings` to `AgentValidationRecord`.

- [ ] **Step 6: Update version read/write tests**

In `tests/test_published_agent_versions.py`, assert a published version contains resolved knowledge bindings and they do not change after a Source publishes a newer snapshot.

- [ ] **Step 7: Run resolver and publication tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest \
  tests/test_knowledge_binding_resolver.py \
  tests/test_published_agent_versions.py \
  tests/test_agent_configuration_api.py -q
```

Expected: pass after Task 8 wiring; if runner wiring is still missing, keep this task's tests focused on store persistence and resolver output, then complete runtime execution in Task 8.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/contracts/agent_configuration.py proof_agent/bootstrap/knowledge_resolution.py \
  proof_agent/configuration/local_store.py proof_agent/delivery/configuration_api.py \
  proof_agent/delivery/published_agents.py tests/test_knowledge_binding_resolver.py \
  tests/test_published_agent_versions.py tests/test_agent_configuration_api.py
git commit -m "feat: resolve published knowledge bindings"
```

---

## Task 8: Thread Resolved Bindings Through Runtime Execution

**Files:**
- Modify: `proof_agent/runtime/langgraph_runner.py`
- Modify: `proof_agent/runtime/graph.py`
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/delivery/api.py`
- Modify: `proof_agent/delivery/customer_api.py`
- Modify: `proof_agent/delivery/customer_adapters.py`
- Modify: `proof_agent/delivery/published_agents.py`
- Modify: `tests/test_run_execution_api.py`
- Modify: `tests/test_customer_run_api.py`
- Modify: `tests/test_insurance_customer_service_example.py`

- [ ] **Step 1: Write failing production execution tests**

Add a test to `tests/test_run_execution_api.py`:

```python
def test_published_agent_execution_uses_persisted_resolved_knowledge_bindings(tmp_path: Path) -> None:
    store = _store_with_published_agent_and_resolved_bindings(tmp_path)
    # Publish a newer Source snapshot after the Agent Version is active.
    # Run production API.
    # Assert the run used the old resolved source_version_id captured in the Agent Version.
```

Use a local_markdown package resolver path if local_index fixture cost is high; the behavior under test is resolved-set pinning.

- [ ] **Step 2: Run execution tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest \
  tests/test_run_execution_api.py tests/test_customer_run_api.py -q
```

Expected: fail because runtime paths only pass `agent.yaml`.

- [ ] **Step 3: Extend runner signature**

In `proof_agent/runtime/langgraph_runner.py`, add optional:

```python
resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None
knowledge_binding_resolver: KnowledgeBindingResolver | None = None
```

Pass them into `compose_harness_invocation()`.

- [ ] **Step 4: Update execution API paths**

When `PublishedAgentRegistry.resolve()` returns a configured Agent Version, include the persisted `resolved_knowledge_bindings` on `PublishedAgent`.

Update `run_agent()` / customer run adapters to pass that resolved set to `run_with_langgraph()`.

Standalone configured file paths keep using default package resolver.

- [ ] **Step 5: Update validation path**

In `validate_config_draft()`, pass the Configuration Store resolver or resolved set into `run_with_langgraph()` so validation behavior matches Agent publication behavior.

- [ ] **Step 6: Run execution tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest \
  tests/test_run_execution_api.py \
  tests/test_customer_run_api.py \
  tests/test_insurance_customer_service_example.py -q
```

Expected: pass.

- [ ] **Step 7: Run deterministic demo**

Run:

```bash
uv run --extra dev proof-agent demo
```

Expected: standalone package path still works.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/runtime/langgraph_runner.py proof_agent/runtime/graph.py \
  proof_agent/runtime/react_graph.py proof_agent/delivery/api.py \
  proof_agent/delivery/customer_api.py proof_agent/delivery/customer_adapters.py \
  proof_agent/delivery/published_agents.py tests/test_run_execution_api.py \
  tests/test_customer_run_api.py tests/test_insurance_customer_service_example.py
git commit -m "feat: run published agents with resolved knowledge bindings"
```

---

## Task 9: Update Dashboard API Types And Knowledge Source Workspace

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/pages/KnowledgePage.tsx`
- Create: `dashboard/src/pages/KnowledgeDetailPage.tsx`
- Modify: `dashboard/src/router.tsx`
- Modify: `dashboard/src/pages/__tests__/KnowledgePage.test.tsx`
- Create: `dashboard/src/pages/__tests__/KnowledgeDetailPage.test.tsx`

- [ ] **Step 1: Write failing frontend tests**

Update `KnowledgePage.test.tsx`:

```tsx
it('does not render the legacy index path input', async () => {
  vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
  render(<MemoryRouter><KnowledgePage /></MemoryRouter>)
  expect(await screen.findByText('Knowledge Sources')).toBeInTheDocument()
  expect(screen.queryByLabelText(/Index Path/i)).not.toBeInTheDocument()
})
```

Create `KnowledgeDetailPage.test.tsx`:

```tsx
it('runs publication validation then publish', async () => {
  // mock fetch source, candidate snapshot, validate, publish
  // assert smoke query and change note controls exist
})
```

- [ ] **Step 2: Run frontend tests and verify failure**

Run:

```bash
cd dashboard && npm test -- KnowledgePage KnowledgeDetailPage
```

Expected: fail because detail page/routes/client calls do not exist and legacy input remains.

- [ ] **Step 3: Extend API types**

In `dashboard/src/api/types.ts`, add:

```ts
export interface KnowledgeSourcePublicationValidation { ... }
export interface KnowledgeSourcePublicationRecord { ... }
export interface CandidateKnowledgeSourceSnapshot { ... }
export interface KnowledgeSourceSnapshotManifest { ... }
```

Extend `KnowledgeSource`:

```ts
source_draft_version_id?: string | null
latest_snapshot_id?: string | null
published_snapshot_id?: string | null
publication_count?: number
```

- [ ] **Step 4: Add client calls**

In `dashboard/src/api/client.ts`, add:

```ts
export function fetchKnowledgeSource(sourceId: string): Promise<KnowledgeSource> { ... }
export function fetchCandidateKnowledgeSourceSnapshot(sourceId: string): Promise<CandidateKnowledgeSourceSnapshot> { ... }
export function validateKnowledgeSourcePublication(sourceId: string, payload: { smoke_query: string; actor?: string }): Promise<KnowledgeSourcePublicationValidation> { ... }
export function publishKnowledgeSource(sourceId: string, payload: { validation_id: string; change_note: string; actor?: string }): Promise<KnowledgeSourcePublicationRecord> { ... }
export function fetchKnowledgeSourcePublications(sourceId: string): Promise<{ data: KnowledgeSourcePublicationRecord[]; meta: { total: number } }> { ... }
```

- [ ] **Step 5: Replace stale `/knowledge` create UI**

In `KnowledgePage.tsx`:

- remove `indexPath` state and `DEFAULT_LOCAL_INDEX_PATH`;
- collect Source name, Source ID, ingestion provider, ingestion model name, credential env field, document selection budget, worker concurrency;
- send params like:

```ts
params: {
  ingestion_model: {
    provider: ingestionProvider,
    name: ingestionModelName,
    params: credentialEnv ? { api_key_env: credentialEnv } : {},
  },
  document_selection_budget: Number(documentSelectionBudget),
  worker_concurrency: Number(workerConcurrency),
}
```

Keep model forms compact; do not add remote Source UI in this slice.

- [ ] **Step 6: Add detail page**

Create `KnowledgeDetailPage.tsx` with sections:

- Overview;
- Provider summary;
- Documents upload/status using existing upload/list endpoints;
- Publication with candidate read, validate form, publish form, publication list.

Avoid nested cards. Use full-width sections or simple bordered panels consistent with the existing dashboard.

- [ ] **Step 7: Add route**

In `dashboard/src/router.tsx`:

```tsx
<Route path="/knowledge/:sourceId" element={<KnowledgeDetailPage />} />
```

Make list rows link to `/knowledge/${source.source_id}`.

- [ ] **Step 8: Run frontend tests and build**

Run:

```bash
cd dashboard && npm test -- KnowledgePage KnowledgeDetailPage
cd dashboard && npm run build
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add dashboard/src/api/types.ts dashboard/src/api/client.ts \
  dashboard/src/pages/KnowledgePage.tsx dashboard/src/pages/KnowledgeDetailPage.tsx \
  dashboard/src/router.tsx dashboard/src/pages/__tests__/KnowledgePage.test.tsx \
  dashboard/src/pages/__tests__/KnowledgeDetailPage.test.tsx
git commit -m "feat: add knowledge source publication workspace"
```

---

## Task 10: Update Agent Knowledge Binding UI

**Files:**
- Modify: `dashboard/src/components/agent/KnowledgeModuleEditor.tsx`
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `tests/test_agent_configuration_api.py`

- [ ] **Step 1: Write failing API test for shared source binding**

In `tests/test_agent_configuration_api.py`, update binding tests to expect:

```yaml
knowledge_bindings:
  - binding_id: ks_policy_binding
    source_ref:
      scope: shared
      source_id: ks_policy
```

Assert no shared provider params are inserted into Draft Agent YAML.

Add:

```python
def test_bind_unpublished_source_is_rejected(tmp_path: Path) -> None:
    ...
    response = client.post(...knowledge-bindings...)
    assert response.status_code == 400
    assert "published" in response.text
```

- [ ] **Step 2: Run API binding tests and verify failure**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_agent_configuration_api.py -q
```

Expected: fail because API still copies provider params.

- [ ] **Step 3: Update binding API**

In `_bind_source_in_agent_yaml()`:

- remove source insertion into `package_knowledge_sources`;
- ensure the manifest has `package_knowledge_sources: []` when absent;
- insert binding with:

```python
binding_entry = {
    "binding_id": binding_id,
    "source_ref": {"scope": "shared", "source_id": source.source_id},
    "failure_mode": request.failure_mode,
    "fusion_weight": request.fusion_weight,
}
```

Before inserting, require `source.published_snapshot_id is not None`.

Update unbind to remove only `knowledge_bindings[]`; do not remove package-local Sources.

- [ ] **Step 4: Update frontend binding parser**

In `KnowledgeModuleEditor.tsx`, replace regex for `source_id:` with parsing under `source_ref`.

If regex becomes brittle, use existing YAML utility or add a typed helper in `dashboard/src/utils/agentYaml.ts`. Keep the parser limited to display and test it.

Filter bindable Sources:

```ts
const publishedSources = knowledgeSources.filter((source) => source.published_snapshot_id)
```

Show disabled/unpublished count with a concrete reason.

- [ ] **Step 5: Update frontend tests**

In `AgentDetailPage.test.tsx`, assert binding payload still sends `source_id` to API, but rendered contract/binding display uses shared Source refs and unpublished Sources are not selectable.

- [ ] **Step 6: Run API and frontend tests**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_agent_configuration_api.py -q
cd dashboard && npm test -- AgentDetailPage
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/delivery/configuration_api.py tests/test_agent_configuration_api.py \
  dashboard/src/components/agent/KnowledgeModuleEditor.tsx \
  dashboard/src/pages/AgentDetailPage.tsx dashboard/src/api/client.ts \
  dashboard/src/pages/__tests__/AgentDetailPage.test.tsx
git commit -m "feat: bind agents to published knowledge sources"
```

---

## Task 11: Documentation And Final Verification

**Files:**
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`
- Do not modify: `docs/zh/**`

- [ ] **Step 1: Update English docs**

Update:

- `docs/technical-design.md` Knowledge Hub section with Source publication and `package_knowledge_sources[] + source_ref`.
- `docs/developer-guide.md` with the Local Index production loop:
  - create Source;
  - upload;
  - `knowledge-worker --once`;
  - freeze candidate;
  - validate publication;
  - publish;
  - bind to Agent;
  - validate/publish Agent.
- `docs/development-progress.md` current gap table after implementation.

- [ ] **Step 2: Run focused backend tests**

Run:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree python -m pytest \
  tests/test_config_loader.py \
  tests/test_knowledge_binding_resolver.py \
  tests/test_knowledge_source_publication.py \
  tests/test_agent_configuration_api.py \
  tests/test_agent_configuration_store.py \
  tests/test_knowledge_snapshot_store.py \
  tests/test_composition.py \
  tests/test_run_execution_api.py -q
```

Expected: pass.

- [ ] **Step 3: Run frontend tests and build**

Run:

```bash
cd dashboard && npm test
cd dashboard && npm run build
```

Expected: pass.

- [ ] **Step 4: Run deterministic regression**

Run:

```bash
uv run --extra dev proof-agent demo
uv run --extra dev --extra dashboard proof-agent react-demo
```

Expected demo outcomes remain:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

Expected ReAct outcomes remain:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
clarify: WAITING_FOR_USER_CLARIFICATION
tool_required: WAITING_FOR_APPROVAL
```

- [ ] **Step 5: Run full quality gates**

Run:

```bash
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
git diff --check
```

Expected: pass.

- [ ] **Step 6: Commit docs and verification updates**

```bash
git add docs/technical-design.md docs/developer-guide.md docs/development-progress.md
git commit -m "docs: document knowledge hub production loop"
```

---

## Execution Notes

- Do not preserve a compatibility path for old Dashboard-generated `knowledge_sources[]` or `index_path` state.
- Do not delete source-controlled fixtures when performing the Local Configuration Store reset.
- Keep deterministic standalone packages runnable through `package_knowledge_sources[]`.
- Keep Source publication separate from Agent publication.
- Keep Source smoke validation out of RunStore production history.
- If a task exposes a larger refactor, stop at the smallest boundary that keeps this production loop working and tested.
