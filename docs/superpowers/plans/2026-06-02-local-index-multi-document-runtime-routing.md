# Local Index Multi-Document Runtime Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the registered Local Index runtime's historical single-artifact `snapshot.v1` path with bounded `local_index.snapshot.v2` multi-document routing, selected-revision artifact loading, fail-closed retrieval, and trace-safe document-routing summaries.

**Architecture:** Keep the registered runtime provider v2-only. Resolve explicit `snapshot_path` and `artifact_root`, validate the immutable manifest before storage access, route over a bounded trace-safe document projection through the Source-owned model, and load only selected revision artifacts. Keep LlamaIndex-specific loading inside `LocalIndexProvider`; let the Control Plane consume a provider-owned one-shot summary without learning artifact mechanics.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, LlamaIndex TreeIndex, Proof Agent `ModelProvider`, strict JSON normalization, immutable file-backed manifests, pytest, Ruff, mypy

---

## Scope Boundary

Implement Slice B from:

- `docs/adr/0017-mutable-candidate-snapshot-projection.md`
- `docs/superpowers/specs/2026-06-02-local-index-multi-document-runtime-routing-design.md`

This is a direct v2-only registered runtime cutover. Do not preserve a dual-read
`local_index.snapshot.v1` compatibility path inside `LocalIndexProvider.from_config()`.

Do not add:

- formal Knowledge Source Publication or `published_snapshot_id` advancement;
- Published Agent Version snapshot pinning;
- routing-smoke or citation-resolution publication validation;
- routing-metadata edit API or Dashboard UI;
- continuous worker polling;
- atomic batch upload;
- the trusted `http_json` adapter.

Direct `LocalIndexProvider(...)` construction may retain its existing single-index utility methods
for management-plane and focused provider tests. The registered `from_config()` runtime path must
consume `snapshot.v2` only.

## File Map

**Create:**

- `proof_agent/capabilities/knowledge/local_index_routing.py` - optional-LlamaIndex-safe metadata soft filter, bounded routing-model request, strict selection validation, and trace-safe summary projection.
- `tests/test_local_index_routing.py` - focused document-router tests with a fake `ModelProvider`.

**Modify:**

- `proof_agent/capabilities/knowledge/contracts.py` - add the strict `KnowledgeDocumentRoutingSelection` contract.
- `proof_agent/capabilities/knowledge/__init__.py` - export the new routing selection contract.
- `proof_agent/bootstrap/manifest.py` - resolve `snapshot_path` and `artifact_root` as Source-owned path params.
- `proof_agent/bootstrap/validation.py` - reject historical `index_path`; require v2 runtime params and validate `document_selection_budget`.
- `tests/test_config_loader.py` - prove Agent Package migration behavior and v2 path resolution.
- `proof_agent/capabilities/knowledge/ingestion/artifacts.py` - add optional-dependency-safe minimum runtime artifact integrity validation.
- `tests/test_knowledge_ingestion_artifacts.py` - cover runtime artifact identity checks.
- `proof_agent/capabilities/knowledge/local_index_snapshot.py` - replace v1 sidecar loading with v2 manifest loading and containment validation.
- `tests/test_local_index_snapshot.py` - replace v1 tests with v2 manifest tests.
- `proof_agent/capabilities/knowledge/local_index.py` - route v2 documents, load selected revision artifacts read-only, merge evidence, attach stable identity and citations, and expose one-shot summaries.
- `tests/test_local_index_provider.py` - preserve direct-constructor tests while replacing registered-runtime tests with v2 behavior.
- `proof_agent/control/knowledge/retrieval_service.py` - consume provider summaries on success and failure; emit direct-provider error results; attach bound-provider summaries to `provider_calls[]`.
- `tests/test_knowledge_retrieval_service.py` - verify direct, bound, failure, and agentic-round trace summary integration.
- `docs/technical-design.md` - record implemented v2 multi-document runtime routing and revised sequence.
- `docs/developer-guide.md` - migrate runtime configuration and describe routing behavior.
- `docs/development-progress.md` - mark Slice B complete and keep remaining gaps explicit.
- `docs/migration/pageindex-to-local-index.md` - replace historical registered-runtime `index_path` guidance with v2 configuration.
- `proof_agent/evaluation/demo/fixtures/agentic_rag_example/agent.yaml` - migrate the illustrative Local Index Source config.
- `proof_agent/evaluation/demo/fixtures/agentic_rag_example/README.md` - migrate fixture guidance and distinguish management-plane direct construction from registered runtime config.

## Task 1: V2 Runtime Config And Strict Routing Selection Contract

**Files:**

- Modify: `proof_agent/capabilities/knowledge/contracts.py:1-52`
- Modify: `proof_agent/capabilities/knowledge/__init__.py:5-42`
- Modify: `proof_agent/bootstrap/manifest.py:25-105`
- Modify: `proof_agent/bootstrap/validation.py:469-493`
- Modify: `tests/test_retrieval_contracts.py`
- Modify: `tests/test_config_loader.py:137-184`

- [ ] **Step 1: Write failing routing-contract tests**

Add to `tests/test_retrieval_contracts.py`:

```python
from proof_agent.capabilities.knowledge.contracts import (
    KnowledgeDocumentRoutingSelection,
)


def test_knowledge_document_routing_selection_serializes_strict_ids() -> None:
    selection = KnowledgeDocumentRoutingSelection(
        selected_document_ids=("doc_policy", "doc_claims"),
        reason="Both documents may answer the question.",
    )

    assert selection.model_dump(mode="json") == {
        "selected_document_ids": ["doc_policy", "doc_claims"],
        "reason": "Both documents may answer the question.",
    }
```

Add a validation test proving an unknown response field is rejected. This contract is stricter
than the shared frozen-contract default because model output must not silently widen.

- [ ] **Step 2: Write failing v2 config-loader tests**

Replace `test_local_index_knowledge_source_loads_with_index_path()` in
`tests/test_config_loader.py` with:

```python
def test_local_index_knowledge_source_loads_with_v2_runtime_paths(tmp_path: Path) -> None:
    ...
    params:
      snapshot_path: ./config/knowledge_sources/ks_policy/snapshots/kssnapshot_001
      artifact_root: ./config
      document_selection_budget: 12
    ...
    assert manifest.knowledge_sources[0].params["snapshot_path"] == (
        tmp_path / "config" / "knowledge_sources" / "ks_policy" / "snapshots" / "kssnapshot_001"
    ).resolve()
    assert manifest.knowledge_sources[0].params["artifact_root"] == (
        tmp_path / "config"
    ).resolve()
    assert manifest.knowledge_sources[0].params["document_selection_budget"] == 12
```

Add:

```python
def test_local_index_knowledge_source_rejects_historical_index_path(tmp_path: Path) -> None:
    ...
    params:
      index_path: ./indexes/policies
    ...
    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)
    assert exc.value.code == "PA_CONFIG_001"
    assert "snapshot_path" in exc.value.fix
    assert "artifact_root" in exc.value.fix


@pytest.mark.parametrize("budget", [0, 21, "8"])
def test_local_index_knowledge_source_rejects_invalid_document_selection_budget(
    tmp_path: Path,
    budget: object,
) -> None:
    ...
    assert exc.value.code == "PA_CONFIG_001"
```

- [ ] **Step 3: Run focused tests and confirm the red state**

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_retrieval_contracts.py \
  tests/test_config_loader.py -q
```

Expected: FAIL because `KnowledgeDocumentRoutingSelection`, `snapshot_path`, `artifact_root`, and
the v2-only bootstrap validation are not implemented.

- [ ] **Step 4: Add the strict routing selection contract**

Import `ConfigDict` from Pydantic and add to
`proof_agent/capabilities/knowledge/contracts.py`:

```python
class KnowledgeDocumentRoutingSelection(FrozenModel):
    """Strict routing-model output for bounded Local Index document selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selected_document_ids: tuple[str, ...]
    reason: str
```

Export it from `proof_agent/capabilities/knowledge/__init__.py`.

- [ ] **Step 5: Resolve v2 runtime path params**

Change `proof_agent/bootstrap/manifest.py`:

```python
PATH_PARAM_KEYS = {
    "path",
    "snapshot_path",
    "artifact_root",
    "mock_results_path",
}
```

Do not retain `index_path` as a registered Local Index runtime path.

- [ ] **Step 6: Validate v2-only bootstrap config**

Change the `local_index` branch in `proof_agent/bootstrap/validation.py`:

```python
if provider == "local_index":
    if "index_path" in params:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "local_index params.index_path is no longer supported.",
            "Configure params.snapshot_path and params.artifact_root for local_index.snapshot.v2.",
            artifact_path=manifest_path,
        )
    _required_param(params, "snapshot_path", provider, manifest_path, field_prefix=field_prefix)
    _required_param(params, "artifact_root", provider, manifest_path, field_prefix=field_prefix)
    _validate_document_selection_budget(params, manifest_path=manifest_path)
    return
```

Add:

```python
def _validate_document_selection_budget(
    params: Mapping[str, Any],
    *,
    manifest_path: Path,
) -> None:
    value = params.get("document_selection_budget", 8)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 20:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "local_index document_selection_budget must be an integer from 1 through 20.",
            "Set params.document_selection_budget to an integer from 1 through 20.",
            artifact_path=manifest_path,
        )
```

- [ ] **Step 7: Re-run focused tests**

Run the Task 1 pytest command again.

Expected: PASS.

- [ ] **Step 8: Run Ruff and diff check**

Run:

```bash
uv run --extra dev ruff check \
  proof_agent/capabilities/knowledge/contracts.py \
  proof_agent/capabilities/knowledge/__init__.py \
  proof_agent/bootstrap/manifest.py \
  proof_agent/bootstrap/validation.py \
  tests/test_retrieval_contracts.py \
  tests/test_config_loader.py
git diff --check
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add \
  proof_agent/capabilities/knowledge/contracts.py \
  proof_agent/capabilities/knowledge/__init__.py \
  proof_agent/bootstrap/manifest.py \
  proof_agent/bootstrap/validation.py \
  tests/test_retrieval_contracts.py \
  tests/test_config_loader.py
git commit -m "Require local index snapshot v2 runtime config"
```

## Task 2: V2 Snapshot Loader And Runtime Artifact Integrity

**Files:**

- Modify: `proof_agent/capabilities/knowledge/ingestion/artifacts.py:1-73`
- Modify: `tests/test_knowledge_ingestion_artifacts.py`
- Modify: `proof_agent/capabilities/knowledge/local_index_snapshot.py`
- Replace tests in: `tests/test_local_index_snapshot.py`

- [ ] **Step 1: Write failing runtime artifact-integrity tests**

Extend `tests/test_knowledge_ingestion_artifacts.py`:

```python
from proof_agent.capabilities.knowledge.ingestion.artifacts import (
    is_runtime_compatible_local_index_artifact,
)


def test_runtime_artifact_integrity_requires_manifest_content_hash(tmp_path: Path) -> None:
    ...
    assert is_runtime_compatible_local_index_artifact(
        artifact_path,
        content_hash=spec.content_hash,
    )
    assert not is_runtime_compatible_local_index_artifact(
        artifact_path,
        content_hash="c" * 64,
    )
```

Also cover missing required file, malformed sidecar, wrong schema, wrong provider, wrong engine name,
and empty `engine_version`, `parser_identity`, or `ingestion_config_fingerprint`.

- [ ] **Step 2: Replace v1 loader tests with failing v2 tests**

Rewrite `tests/test_local_index_snapshot.py` around helpers that write a
`KnowledgeSourceSnapshotManifest` JSON file:

```python
def _snapshot_document(
    *,
    document_id: str = "doc_policy",
    artifact_path: str = "artifacts/policy/fingerprint",
) -> KnowledgeSourceSnapshotDocument:
    return KnowledgeSourceSnapshotDocument(
        document_id=document_id,
        revision_id=f"rev_{document_id}",
        filename=f"{document_id}.md",
        content_type="text/markdown",
        content_hash="a" * 64,
        artifact_path=artifact_path,
    )


def test_load_ready_snapshot_manifest_returns_sorted_trace_safe_descriptor(tmp_path: Path) -> None:
    ...
    snapshot = load_ready_snapshot_manifest(snapshot_path, artifact_root=artifact_root)
    assert snapshot.snapshot_id == "kssnapshot_001"
    assert [document.document_id for document in snapshot.documents] == [
        "doc_alpha",
        "doc_beta",
    ]
    assert snapshot.documents[0].artifact_path == (
        artifact_root / "artifacts" / "alpha" / "fingerprint"
    ).resolve()
```

Add rejection tests for:

- missing `snapshot.json`;
- malformed JSON;
- historical `artifact_meta.json` v1 directory;
- non-READY or non-v2 manifest;
- empty documents;
- duplicate `document_id`;
- empty `document_id`, `revision_id`, filename, or artifact path;
- absolute artifact path;
- `../` artifact-root escape;
- symlink artifact-root escape where supported by the platform.

- [ ] **Step 3: Run focused tests and confirm red**

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_knowledge_ingestion_artifacts.py \
  tests/test_local_index_snapshot.py -q
```

Expected: FAIL because runtime artifact integrity and the v2 loader do not exist.

- [ ] **Step 4: Add minimum runtime artifact integrity**

Extend `proof_agent/capabilities/knowledge/ingestion/artifacts.py`:

```python
def is_runtime_compatible_local_index_artifact(
    artifact_path: Path,
    *,
    content_hash: str,
) -> bool:
    """Validate the self-described immutable revision artifact before runtime open."""

    if not artifact_path.is_dir():
        return False
    if any(not (artifact_path / filename).is_file() for filename in REQUIRED_LLAMA_INDEX_FILES):
        return False
    metadata = _read_json_object(artifact_path / ARTIFACT_META_FILENAME)
    return metadata is not None and (
        metadata.get("schema_version") == ARTIFACT_SCHEMA_VERSION
        and metadata.get("provider") == "local_index"
        and metadata.get("engine_name") == "llama-index-tree"
        and _is_non_empty_string(metadata.get("engine_version"))
        and _is_non_empty_string(metadata.get("parser_identity"))
        and metadata.get("content_hash") == content_hash
        and _is_non_empty_string(metadata.get("ingestion_config_fingerprint"))
    )
```

Add a private `_is_non_empty_string()`.

- [ ] **Step 5: Replace the v1 loader with a v2 descriptor**

Rewrite `proof_agent/capabilities/knowledge/local_index_snapshot.py` with frozen dataclasses:

```python
@dataclass(frozen=True)
class LocalIndexRuntimeDocument:
    document_id: str
    revision_id: str
    filename: str
    content_type: str
    content_hash: str
    artifact_path: Path
    routing_metadata: Mapping[str, Any]


@dataclass(frozen=True)
class LocalIndexRuntimeSnapshot:
    snapshot_id: str
    source_id: str
    state: str
    validation_level: str
    documents: tuple[LocalIndexRuntimeDocument, ...]
```

Expose:

```python
def load_ready_snapshot_manifest(
    snapshot_path: Path,
    *,
    artifact_root: Path,
) -> LocalIndexRuntimeSnapshot:
    """Load one immutable local_index.snapshot.v2 manifest before storage access."""
```

Implementation order:

1. reject a directory that has v1 `artifact_meta.json` but no `snapshot.json` with a migration fix;
2. read and parse `snapshot.json`;
3. validate through `KnowledgeSourceSnapshotManifest.model_validate()`;
4. require non-empty documents;
5. reject duplicate ids;
6. resolve every relative artifact reference beneath `artifact_root`;
7. sort runtime documents by `document_id`;
8. return the trace-safe runtime descriptor.

Do not import LlamaIndex.

- [ ] **Step 6: Re-run focused tests**

Run the Task 2 pytest command again.

Expected: PASS.

- [ ] **Step 7: Prove optional-dependency-safe import**

Run:

```bash
uv run --extra dev python -c \
  'import sys; import proof_agent.capabilities.knowledge.local_index_snapshot; assert "llama_index" not in sys.modules'
```

Expected: PASS.

- [ ] **Step 8: Run Ruff and diff check**

Run:

```bash
uv run --extra dev ruff check \
  proof_agent/capabilities/knowledge/ingestion/artifacts.py \
  proof_agent/capabilities/knowledge/local_index_snapshot.py \
  tests/test_knowledge_ingestion_artifacts.py \
  tests/test_local_index_snapshot.py
git diff --check
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add \
  proof_agent/capabilities/knowledge/ingestion/artifacts.py \
  proof_agent/capabilities/knowledge/local_index_snapshot.py \
  tests/test_knowledge_ingestion_artifacts.py \
  tests/test_local_index_snapshot.py
git commit -m "Load local index snapshot v2 manifests"
```

## Task 3: Bounded Knowledge Document Router

**Files:**

- Create: `proof_agent/capabilities/knowledge/local_index_routing.py`
- Create: `tests/test_local_index_routing.py`

- [ ] **Step 1: Write failing metadata soft-filter tests**

Create `tests/test_local_index_routing.py` with a fake `ModelProvider` that records
`ModelRequest` objects and returns strict JSON `ModelResponse` values.

Add:

```python
def test_document_router_sends_only_metadata_matches_when_available() -> None:
    result = route_snapshot_documents(
        "claim reimbursement",
        documents=(
            _document("doc_travel", filename="travel-policy.md"),
            _document(
                "doc_claims",
                filename="claims-guide.md",
                routing_metadata={"tags": ["claim"], "ignored": "must-not-leak"},
            ),
        ),
        routing_model=_model('{"selected_document_ids":["doc_claims"],"reason":"match"}'),
        selection_budget=8,
        snapshot_id="kssnapshot_001",
    )
    request_payload = json.loads(model.requests[0].messages[0].content)
    assert [item["document_id"] for item in request_payload["document_candidates"]] == [
        "doc_claims"
    ]
    assert "ignored" not in request_payload["document_candidates"][0]["routing_metadata"]
    assert [document.document_id for document in result.selected_documents] == ["doc_claims"]
```

Add another test proving no metadata match falls back to the full stable `document_id`-sorted set.

- [ ] **Step 2: Write failing bounded-input and trace-summary tests**

Cover:

- more than `100` eligible documents truncates to the first stable `document_id` page;
- `candidate_truncated` is `True`;
- `candidate_count`, `routed_candidate_count`, `selected_count`, and `selection_budget` are correct;
- filename projection uses safe basename rather than an input path;
- routing metadata limits values to the allowlist, `20` scalar values per document, and `300`
  characters per scalar value;
- trace-safe summary excludes artifact paths, document content, raw model output, and model reason.

- [ ] **Step 3: Write failing strict-output tests**

Parametrize:

```python
[
    ("not-json", "model_output_json_parse_failed"),
    ('{"selected_document_ids":["doc_unknown"],"reason":"x"}', "unknown"),
    ('{"selected_document_ids":["doc_a","doc_a"],"reason":"x"}', "duplicate"),
    ('{"selected_document_ids":["doc_a","doc_b"],"reason":"x"}', "budget"),
    ('{"selected_document_ids":[],"reason":"x","unexpected":true}', "contract"),
]
```

Each must raise `ProofAgentError` with code `PA_KNOWLEDGE_002`.

Add a valid empty selection test:

```python
assert result.selected_documents == ()
assert result.summary["document_routing"]["selection_reason"] == "routing_empty"
```

- [ ] **Step 4: Run router tests and confirm red**

Run:

```bash
uv run --extra dev python -m pytest tests/test_local_index_routing.py -q
```

Expected: FAIL because the router module does not exist.

- [ ] **Step 5: Implement the optional-LlamaIndex-safe router**

Create `proof_agent/capabilities/knowledge/local_index_routing.py`.

Use:

```python
MAX_ROUTING_MODEL_DOCUMENT_CANDIDATES = 100
MAX_ROUTING_METADATA_SCALARS = 20
MAX_ROUTING_METADATA_SCALAR_CHARS = 300
ROUTING_METADATA_KEYS = (
    "title",
    "description",
    "tags",
    "document_type",
    "business_category",
)
```

Add:

```python
@dataclass(frozen=True)
class LocalIndexDocumentRoutingResult:
    selected_documents: tuple[LocalIndexRuntimeDocument, ...]
    summary: Mapping[str, Any]


def route_snapshot_documents(
    query: str,
    *,
    documents: tuple[LocalIndexRuntimeDocument, ...],
    routing_model: ModelProvider,
    selection_budget: int,
    snapshot_id: str,
) -> LocalIndexDocumentRoutingResult:
    ...
```

Construct a `ModelRequest` with:

```python
ModelRequest(
    messages=(ModelMessage(role=ModelRole.USER, content=json.dumps(prompt_payload)),),
    provider=routing_model.provider_name,
    model=routing_model.model_name,
    response_format="json",
    metadata={"role": ModelCallRole.ROUTING.value},
)
```

Normalize with:

```python
selection = parse_model_contract(
    response.content,
    KnowledgeDocumentRoutingSelection,
    ModelCallRole.ROUTING.value,
)
```

Wrap `ModelOutputNormalizationError` and model-call failures as value-safe
`ProofAgentError("PA_KNOWLEDGE_002", ...)`.

- [ ] **Step 6: Re-run router tests**

Run the Task 3 pytest command again.

Expected: PASS.

- [ ] **Step 7: Prove router import stays lightweight**

Run:

```bash
uv run --extra dev python -c \
  'import sys; import proof_agent.capabilities.knowledge.local_index_routing; assert "llama_index" not in sys.modules'
```

Expected: PASS.

- [ ] **Step 8: Run Ruff and diff check**

Run:

```bash
uv run --extra dev ruff check \
  proof_agent/capabilities/knowledge/local_index_routing.py \
  tests/test_local_index_routing.py
git diff --check
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add \
  proof_agent/capabilities/knowledge/local_index_routing.py \
  tests/test_local_index_routing.py
git commit -m "Add bounded local index document routing"
```

## Task 4: V2 Multi-Document Local Index Runtime Provider

**Files:**

- Modify: `proof_agent/capabilities/knowledge/local_index.py:24-475`
- Modify: `tests/test_local_index_provider.py:44-567`

- [ ] **Step 1: Replace registered-runtime tests with failing v2 tests**

Keep existing direct-constructor build, load, retrieve, `list_structure()`, and
`retrieve_at_scope()` tests. Replace historical `from_config()` tests with:

```python
def test_from_config_requires_v2_snapshot_paths_and_does_not_open_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_path, artifact_root = _write_v2_snapshot(tmp_path)
    loaded_artifacts = []
    monkeypatch.setattr(
        local_index_module,
        "_load_runtime_revision_index",
        lambda *args, **kwargs: loaded_artifacts.append(args) or object(),
    )
    ...
    provider = LocalIndexProvider.from_config(
        KnowledgeConfig(
            provider="local_index",
            params={
                "snapshot_path": snapshot_path,
                "artifact_root": artifact_root,
                "routing_model": {"provider": "deterministic", "name": "routing-model"},
            },
        )
    )
    assert provider.runtime_snapshot is not None
    assert loaded_artifacts == []
```

Add direct-adapter rejection tests for historical `index_path`, missing runtime paths, and invalid
`document_selection_budget`.

- [ ] **Step 2: Write failing selected-load and evidence-identity tests**

Patch the document router to return selected runtime documents and patch the revision-index loader
or retrieval helper to record artifact paths and return deterministic `NodeWithScore`-like
candidates.

Assert:

- only selected artifact paths load;
- unselected artifacts do not load;
- merged candidates apply final `top_k` after all selected-document results;
- ties use deterministic document/revision/chunk ordering;
- each returned chunk has `source_version_id`, `document_id`, `revision_id`, `chunk_id`,
  `provider_name="local_index"`, and a stable `knowledge://source/...` citation;
- no artifact path appears in chunk metadata or citation.

- [ ] **Step 3: Write failing empty-routing and fail-closed tests**

Cover:

- valid empty selection returns `()`;
- provider exposes a consumable `routing_empty` summary;
- second consume returns `None`;
- first selected document success followed by second selected artifact validation failure raises
  `PA_KNOWLEDGE_002` and returns no partial evidence;
- TreeIndex storage load failure and retrieval failure both raise `PA_KNOWLEDGE_002`;
- failure summary uses bounded `selected_document_failed` and stable error code without exception
  text.

- [ ] **Step 4: Run provider tests and confirm red**

Run:

```bash
uv run --extra dev --extra tree python -m pytest tests/test_local_index_provider.py -q
```

Expected: FAIL because registered runtime still opens one v1 artifact and has no v2 routing path.

- [ ] **Step 5: Refactor `LocalIndexProvider` constructor state**

Extend `LocalIndexProvider.__init__()` with optional runtime-only fields while preserving direct
construction:

```python
def __init__(
    self,
    ingestion_model: ProofAgentLLM | None,
    routing_model: ProofAgentLLM,
    index_path: Path | None = None,
    *,
    routing_provider: ModelProvider | None = None,
    runtime_snapshot: LocalIndexRuntimeSnapshot | None = None,
    document_selection_budget: int = 8,
) -> None:
```

Keep direct single-index utility methods guarded by `index_path is not None`.

- [ ] **Step 6: Make registered `from_config()` v2-only**

Replace `_index_path_from_params()` with:

```python
def _runtime_snapshot_paths_from_params(params: Mapping[str, Any]) -> tuple[Path, Path]:
    if "index_path" in params:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            "Local Index params.index_path is no longer supported.",
            "Configure params.snapshot_path and params.artifact_root for local_index.snapshot.v2.",
        )
    return (
        _required_path_param(params, "snapshot_path"),
        _required_path_param(params, "artifact_root"),
    )
```

Validate `document_selection_budget` with default `8` and range `1..20`. Load the v2 manifest,
resolve the Source-owned raw `ModelProvider` once, wrap that same instance in `ProofAgentLLM` for
selected TreeIndex reads, and return a provider without eagerly opening any revision artifact.
Retain the raw provider separately for `route_snapshot_documents()`; do not reach through
`ProofAgentLLM._provider`.

- [ ] **Step 7: Add selected revision artifact loading**

Add private helpers:

```python
def _load_runtime_revision_index(
    document: LocalIndexRuntimeDocument,
    *,
    routing_model: ProofAgentLLM,
) -> TreeIndex:
    if not is_runtime_compatible_local_index_artifact(
        document.artifact_path,
        content_hash=document.content_hash,
    ):
        raise _snapshot_load_failure("Selected Local Index revision artifact is incompatible.")
    ...


def _retrieve_from_runtime_revision(
    index: TreeIndex,
    *,
    query: str,
    top_k: int,
) -> tuple[NodeWithScore, ...]:
    ...
```

The runtime branch of `retrieve()`:

1. clears prior summary;
2. routes the query with the retained raw `ModelProvider`;
3. stores the fresh trace-safe routing summary;
4. returns `()` for valid empty selection;
5. loads and retrieves every selected revision;
6. converts nodes with snapshot/document/revision identity;
7. discards partial candidates and stores a bounded failure summary on any error;
8. sorts merged candidates stably and applies final `top_k`.

- [ ] **Step 8: Add stable v2 evidence citation projection**

Refactor `_node_to_evidence_chunk()` to accept optional runtime identity:

```python
source_version_id=snapshot.snapshot_id
document_id=document.document_id
revision_id=document.revision_id
chunk_id=node.id_
source=f"knowledge://source/{snapshot.source_id}/document/{document.document_id}"
citation=(
    f"knowledge://source/{snapshot.source_id}/document/{document.document_id}"
    f"/revision/{document.revision_id}#node={node.id_}"
)
```

Do not add artifact or storage paths to evidence metadata.

- [ ] **Step 9: Add one-shot summary consumption**

Add:

```python
def consume_retrieval_summary(self) -> Mapping[str, Any] | None:
    summary = self._retrieval_summary
    self._retrieval_summary = None
    return summary
```

- [ ] **Step 10: Re-run provider tests**

Run the Task 4 pytest command again.

Expected: PASS.

- [ ] **Step 11: Run Ruff, mypy, and diff check**

Run:

```bash
uv run --extra dev --extra tree ruff check \
  proof_agent/capabilities/knowledge/local_index.py \
  tests/test_local_index_provider.py
uv run --extra dev --extra tree mypy proof_agent/capabilities/knowledge
git diff --check
```

Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add \
  proof_agent/capabilities/knowledge/local_index.py \
  tests/test_local_index_provider.py
git commit -m "Route local index snapshot v2 documents"
```

## Task 5: Control Plane Trace-Safe Provider Summary Integration

**Files:**

- Modify: `proof_agent/control/knowledge/retrieval_service.py:360-870`
- Modify: `tests/test_knowledge_retrieval_service.py:20-673`

- [ ] **Step 1: Extend the fake provider and write failing direct-summary tests**

Extend `FakeKnowledgeProvider`:

```python
def __init__(..., summary: dict[str, Any] | None = None) -> None:
    self.summary = summary

def consume_retrieval_summary(self) -> dict[str, Any] | None:
    summary = self.summary
    self.summary = None
    return summary
```

Add:

```python
def test_single_provider_retrieval_result_includes_one_shot_document_summary(...) -> None:
    ...
    assert retrieval_result["payload"]["document_routing"]["snapshot_id"] == "kssnapshot_001"
    assert provider.consume_retrieval_summary() is None
```

- [ ] **Step 2: Write failing bound-provider summary tests**

Add a mixed retrieval test where one selected provider exposes:

```python
{
    "document_candidates": [...],
    "selected_documents": [...],
    "document_routing": {...},
}
```

Assert the summary appears inside that provider's `provider_calls[]` entry and not as a sibling
summary for a different provider.

- [ ] **Step 3: Write failing error and agentic-round summary tests**

Cover:

- direct provider failure emits `retrieval_result` with `status="error"` and the consumed bounded
  summary before re-raising;
- bound advisory failure attaches summary to the failed provider call and continues;
- bound required failure attaches summary and fails closed;
- planner/evaluator-backed agentic retrieval records distinct Local Index summaries on every
  round-correlated `retrieval_result`;
- no summary leaks into a later provider call after consumption.

- [ ] **Step 4: Run retrieval-service tests and confirm red**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_retrieval_service.py -q
```

Expected: FAIL because retrieval service does not consume provider summaries.

- [ ] **Step 5: Add optional summary consumption**

Add:

```python
def _consume_provider_retrieval_summary(
    provider: KnowledgeProvider,
) -> dict[str, Any]:
    consume = getattr(provider, "consume_retrieval_summary", None)
    if not callable(consume):
        return {}
    summary = consume()
    return dict(summary) if isinstance(summary, Mapping) else {}
```

For the direct provider path:

```python
try:
    evidence = self._knowledge_provider.retrieve(query, top_k=request.top_k)
except Exception as exc:
    summary = _consume_provider_retrieval_summary(self._knowledge_provider)
    self._emit_basic_retrieval_result(
        (),
        step_id=step_id,
        round_id=round_id,
        status="error",
        summary=summary,
        no_evidence_reason_code="required_provider_failure",
    )
    raise
summary = _consume_provider_retrieval_summary(self._knowledge_provider)
```

Extend `_emit_basic_retrieval_result()` with `status`, `summary`, and optional
`no_evidence_reason_code`.

- [ ] **Step 6: Attach summaries to bound provider calls**

After every bound-provider success or failure, consume that provider's summary and merge it into:

```python
_successful_provider_call(bound, len(chunks), summary=summary)
_failed_provider_call(bound, exc, summary=summary)
```

Do not expose exception text.

- [ ] **Step 7: Re-run retrieval-service tests**

Run the Task 5 pytest command again.

Expected: PASS.

- [ ] **Step 8: Run related workflow regression tests**

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_knowledge_retrieval_service.py \
  tests/test_workflow_enterprise_qa.py \
  tests/test_workflow_react_enterprise_qa.py -q
```

Expected: PASS.

- [ ] **Step 9: Run Ruff and diff check**

Run:

```bash
uv run --extra dev ruff check \
  proof_agent/control/knowledge/retrieval_service.py \
  tests/test_knowledge_retrieval_service.py
git diff --check
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add \
  proof_agent/control/knowledge/retrieval_service.py \
  tests/test_knowledge_retrieval_service.py
git commit -m "Trace local index document routing summaries"
```

## Task 6: Runtime Fixture And Documentation Migration

**Files:**

- Modify: `docs/technical-design.md:642-675`
- Modify: `docs/developer-guide.md:333-431`
- Modify: `docs/development-progress.md:19-84`
- Modify: `docs/migration/pageindex-to-local-index.md`
- Modify: `proof_agent/evaluation/demo/fixtures/agentic_rag_example/agent.yaml`
- Modify: `proof_agent/evaluation/demo/fixtures/agentic_rag_example/README.md`

- [ ] **Step 1: Migrate the illustrative Agent package**

Replace runtime config:

```yaml
params:
  snapshot_path: ./config/knowledge_sources/enterprise_qa_knowledge/snapshots/kssnapshot_example
  artifact_root: ./config
  document_selection_budget: 8
```

Keep `ingestion_model` and `routing_model` as Source-owned declarations. Note in the README that
the illustrative package requires an operator-frozen `snapshot.v2` manifest before execution.

- [ ] **Step 2: Update developer guide**

Replace the v1 sidecar example with a `snapshot.json` manifest example. Document:

- explicit `snapshot_path + artifact_root`;
- v2-only runtime cutover;
- metadata soft-filter fallback;
- bounded `100`-candidate routing-model input;
- `document_selection_budget` default `8`, range `1..20`;
- strict JSON routing-model output;
- selected-document fail-closed behavior;
- trace-safe `document_candidates[]` and `selected_documents[]`.

- [ ] **Step 3: Update technical design and progress**

Mark `local_index.snapshot.v2` multi-document routing as implemented. Keep these gaps explicit:

- formal Source publication;
- continuous worker polling;
- batch upload;
- trusted `http_json`;
- routing metadata editing and hierarchical routing beyond `100` candidates.

Update the implementation sequence so runtime multi-document routing is no longer listed as
pending.

- [ ] **Step 4: Update migration guide**

Separate:

- management-plane direct `LocalIndexProvider(..., index_path=...)` utility construction, where
  still retained;
- registered Agent Package runtime config, which must use `snapshot_path + artifact_root`;
- the v2-only migration error for historical `params.index_path`.

- [ ] **Step 5: Run documentation and fixture checks**

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_config_loader.py \
  tests/test_composition.py -q
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  docs/technical-design.md \
  docs/developer-guide.md \
  docs/development-progress.md \
  docs/migration/pageindex-to-local-index.md \
  proof_agent/evaluation/demo/fixtures/agentic_rag_example/agent.yaml \
  proof_agent/evaluation/demo/fixtures/agentic_rag_example/README.md
git commit -m "Document local index snapshot v2 routing"
```

## Task 7: Full Verification

**Files:**

- Verify only unless a regression fix is needed.

- [ ] **Step 1: Run focused Slice B verification**

Run:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree --extra openai \
  python -m pytest \
  tests/test_retrieval_contracts.py \
  tests/test_config_loader.py \
  tests/test_knowledge_ingestion_artifacts.py \
  tests/test_local_index_snapshot.py \
  tests/test_local_index_routing.py \
  tests/test_local_index_provider.py \
  tests/test_knowledge_retrieval_service.py \
  tests/test_workflow_enterprise_qa.py \
  tests/test_workflow_react_enterprise_qa.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full extras test suite**

Run:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree --extra openai \
  python -m pytest tests/ -q
```

Expected: PASS with no skipped PDF coverage when ingestion extras are available.

- [ ] **Step 3: Run static checks**

Run:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree --extra openai \
  mypy proof_agent
uv run --extra dev ruff check proof_agent tests
git diff --check
```

Expected: PASS.

- [ ] **Step 4: Run deterministic demos**

Run:

```bash
uv run --extra dev proof-agent demo
uv run --extra dev --extra dashboard proof-agent react-demo
```

Expected:

```text
Proof Agent demo
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL

Proof Agent ReAct demo
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
clarify: WAITING_FOR_USER_CLARIFICATION
tool_required: WAITING_FOR_APPROVAL
```

- [ ] **Step 5: Prove optional Local Index modules remain lazy**

Run:

```bash
uv run --extra dev python -c \
  'import sys; import proof_agent.capabilities.knowledge.local_index_snapshot; import proof_agent.capabilities.knowledge.local_index_routing; assert "llama_index" not in sys.modules'
```

Expected: PASS.

- [ ] **Step 6: Inspect final branch**

Run:

```bash
git status --short --branch
git log --oneline --decorate -10
```

Expected: clean worktree with the Slice B commits visible.
