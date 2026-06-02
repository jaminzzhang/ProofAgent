# Local Index Multi-Document Runtime Routing Design

## Scope

This slice consumes the immutable `local_index.snapshot.v2` manifest introduced by the Local Index
snapshot-freeze foundation. It makes the registered `local_index` runtime provider route one query
to a bounded set of document revisions, load only the selected reusable revision artifacts, merge
their candidate evidence, and expose trace-safe document-routing summaries through the existing
governed retrieval result.

This is a direct runtime cutover to `local_index.snapshot.v2`. The runtime provider no longer
accepts the historical `local_index.snapshot.v1` single-artifact sidecar or `params.index_path`.
Existing development fixtures and documentation migrate to the explicit v2 runtime shape.

This slice does not add formal Knowledge Source Publication, advance `published_snapshot_id`,
pin Source snapshots into Published Agent Versions, add routing-smoke or citation-resolution
publication validation, edit routing metadata through API or Dashboard UI, poll workers
continuously, batch uploads, or add the trusted `http_json` adapter.

## Product Boundary

Slice A created immutable development-stage frozen manifests:

```text
managed READY document revisions
  -> derived candidate snapshot
  -> foundation validation
  -> frozen local_index.snapshot.v2 manifest
  -> latest_snapshot_id for preview and routing development
```

Slice B consumes one explicitly configured frozen manifest:

```text
local_index.snapshot.v2 manifest
  -> trace-safe document candidate projection
  -> metadata soft filter
  -> bounded routing-model selection
  -> selected revision artifact load
  -> selected-document retrieval
  -> candidate evidence merge
  -> existing Control Plane retrieval result and evidence admission
```

The runtime adapter remains read-only. It never scans mutable managed document state, rebuilds an
index, changes snapshot pointers, or treats a foundation-frozen snapshot as production-published.

## Domain Decisions

### Direct V2-Only Runtime Cutover

The v2 manifest is the only runtime shape supported after this slice. The Local Index provider
requires:

```yaml
params:
  snapshot_path: ./config/knowledge_sources/ks_policy/snapshots/kssnapshot_001
  artifact_root: ./config
  routing_model:
    provider: openai
    name: gpt-4o-mini
    params:
      api_key_env: OPENAI_API_KEY
```

`snapshot_path` points to a directory containing `snapshot.json`.

`artifact_root` points to the configuration-store root against which each manifest
`documents[].artifact_path` is resolved. Artifact references are relative paths and must remain
contained beneath `artifact_root` after resolution. The runtime does not infer this root from
directory parents.

`params.index_path` is no longer accepted by the registered runtime provider. A v1 artifact
directory or historical v1 sidecar fails closed with an actionable migration error.

When the historical field appears in an Agent Package, bootstrap validation rejects it with
`PA_CONFIG_001` before provider construction. A direct `LocalIndexProvider.from_config()` call
rejects the same historical field with `PA_KNOWLEDGE_001`. This preserves the repository's
existing distinction between invalid Agent Contract configuration and adapter runtime failure.

### Snapshot Loader Validates Before Storage Open

The v2 manifest loader validates:

- `snapshot.json` exists, is readable JSON, and matches `KnowledgeSourceSnapshotManifest`;
- `schema_version` is exactly `local_index.snapshot.v2`;
- `state` is exactly `READY`;
- the document list is non-empty;
- each document has a non-empty unique `document_id`, non-empty `revision_id`, non-empty
  `filename`, and non-empty relative `artifact_path`;
- each resolved artifact path remains contained beneath `artifact_root`;
- each selected artifact is opened only after the manifest has passed structural validation.

The loader returns a trace-safe immutable runtime snapshot descriptor. It may retain resolved
artifact paths internally for adapter use, but trace summaries must never expose them.

The v2 manifest intentionally does not repeat artifact compatibility metadata. Slice A foundation
validation verified reusable artifacts before freeze. Runtime still validates required artifact
files and a minimum sidecar identity before opening selected LlamaIndex storage so filesystem
corruption fails closed during retrieval. The selected artifact sidecar must be a JSON object with:

```text
schema_version = local_index.artifact.v1
provider = local_index
engine_name = llama-index-tree
engine_version = non-empty string
parser_identity = non-empty string
content_hash = manifest document content_hash
ingestion_config_fingerprint = non-empty string
```

The runtime does not reconstruct the management-plane `KnowledgeArtifactBuildSpec` or ingestion
job. It verifies the immutable artifact's self-description against the frozen manifest identity.

### Metadata Filtering Is A Soft Candidate Reduction

Knowledge Document Routing starts from the immutable manifest document set. The first stage is a
deterministic metadata soft filter:

- the safe filename basename, stem, and normalized filename tokens always participate as
  trace-safe routing terms;
- only `title`, `description`, `tags`, `document_type`, and `business_category` values from
  `routing_metadata` participate;
- routing metadata values are projected as bounded strings: at most `20` scalar values per
  document and at most `300` characters per scalar value;
- a document is considered a metadata match when any normalized term occurs in the normalized
  query;
- when one or more documents match, only matching documents proceed to routing-model selection;
- when no document matches, all manifest documents remain eligible for routing-model selection.

This behavior allows Slice A frozen manifests, whose routing metadata currently defaults to an
empty mapping, to remain usable while later Dashboard work adds operator-editable metadata.

### Routing-Model Candidate Input Is Bounded

The routing model receives at most `100` candidate documents per query.

Candidates are sorted by `document_id` before truncation so retries are deterministic. When
metadata filtering produced matches, the sorted matched set is truncated. When metadata filtering
produced no matches, the sorted full manifest set is truncated.

Trace records:

```text
candidate_count
routed_candidate_count
candidate_truncated
```

`candidate_count` is the total manifest document count. `routed_candidate_count` is the number of
documents actually supplied to the routing model after soft filtering and the `100`-candidate cap.
`candidate_truncated` is `true` when eligible candidates exceeded that cap.

This slice accepts the trade-off that a source with more than `100` weakly described documents may
not route to a document outside the stable first page. Future routing metadata editing or an
explicit hierarchical routing slice can improve coverage without weakening the bounded contract.

### Routing-Model Output Uses A Strict JSON Contract

Add a provider-neutral frozen routing selection contract:

```python
class KnowledgeDocumentRoutingSelection(FrozenModel):
    selected_document_ids: tuple[str, ...]
    reason: str
```

The Local Index document router calls the Source-owned routing model resolved from
`params.routing_model`, falling back to `params.ingestion_model` as in the existing provider.
The request uses `response_format="json"` and includes only:

- the query;
- the document-selection budget;
- the bounded trace-safe candidate projection: `document_id`, safe filename basename, and the
  allowlisted bounded routing-metadata projection.

It does not include document content, storage paths, artifact references, or raw credentials.

The response is normalized through the existing `parse_model_contract()` helper. The router then
requires:

- every selected id exists in the routed candidate set;
- selected ids are unique;
- selected count does not exceed the document-selection budget.

Malformed JSON, invalid contract shape, unknown ids, duplicate ids, or over-budget selection raise
`PA_KNOWLEDGE_002` and fail retrieval closed. The model's raw response and free-form reason are not
written to Trace.

An empty valid selection is not an adapter failure. It returns zero evidence and emits a
trace-safe `routing_empty` summary. The existing Control Plane then follows the governed
no-evidence path.

### Knowledge Document Selection Budget

The Source owns `params.document_selection_budget`:

```text
default: 8
minimum: 1
maximum: 20
```

This is distinct from:

- the `100` routing-model candidate input cap;
- Agent-level Knowledge Source Selection Budget;
- binding-level provider retrieval `top_k`;
- final retrieval strategy evidence `top_k`.

Invalid values fail configuration with `PA_KNOWLEDGE_001` before retrieval.

### Selected Revision Artifact Retrieval

For every selected manifest document, the Local Index provider:

1. resolves the contained artifact path beneath `artifact_root`;
2. validates required reusable artifact files and `artifact_meta.json` shape;
3. loads that revision's persisted TreeIndex read-only with `ProofAgentLLM(routing_model)`;
4. retrieves candidate evidence for the query;
5. normalizes evidence with snapshot, document, and revision identity.

The adapter must not load unselected artifacts.

If any selected artifact is missing, malformed, unloadable, or fails during retrieval, the whole
Local Index provider call raises `PA_KNOWLEDGE_002`. Any evidence already retrieved from earlier
selected documents is discarded. Existing binding-level required or advisory handling remains a
Control Plane concern.

### Candidate Evidence Merge

Document-level results are merged inside the Local Index provider:

- retain provider-native relevance scores from LlamaIndex;
- sort by descending provider-native relevance score;
- use deterministic tie-breakers: `document_id`, `revision_id`, `chunk_id`, then `source`;
- apply the provider call's final `top_k` after merge;
- return candidate `EvidenceChunk` objects only.

Each returned Local Index evidence chunk carries:

```text
source_version_id = snapshot_id
document_id
revision_id
chunk_id when available
provider_name = local_index
provider_native_score
admission_score
citation
```

Local Index citations use a stable internal URI without artifact paths:

```text
knowledge://source/{source_id}/document/{document_id}/revision/{revision_id}#node={chunk_id}
```

This slice preserves the current provider-local score-to-admission-score mapping. Calibrated
admission scoring remains a later extension.

## Components

### Runtime Snapshot Loader

Refactor `proof_agent/capabilities/knowledge/local_index_snapshot.py` into the v2 runtime loader.
It should own manifest read, contract validation, duplicate-id checks, artifact-root containment,
and trace-safe runtime descriptor construction.

### Knowledge Document Router

Add `proof_agent/capabilities/knowledge/local_index_routing.py`. It should own:

- soft metadata filtering;
- stable sort and `100`-candidate input cap;
- strict routing-model request construction;
- `parse_model_contract()` normalization;
- post-normalization id, uniqueness, and budget checks;
- trace-safe routing summary construction.

The router depends only on contracts and the Proof Agent `ModelProvider` protocol. It must not
import LlamaIndex.

### Revision Artifact Reader

Keep LlamaIndex-specific artifact loading behind `LocalIndexProvider`. Extract a small private
reader or internal helper if needed so tests can prove that only selected paths are loaded and
selected-document failure discards partial evidence.

### Local Index Provider

`LocalIndexProvider.from_config()` becomes runtime-v2-only:

```text
snapshot_path + artifact_root
  -> load v2 runtime snapshot descriptor
  -> resolve routing model
  -> validate document_selection_budget
  -> return read-only runtime provider
```

Direct management-plane construction used by existing builder-oriented provider tests may remain
available through `__init__()` for backwards-compatible test and utility use. The registered
runtime `from_config()` path is v2-only and must not call the old single-artifact `load_index()`.

`retrieve()` routes and loads selected revision artifacts when a runtime v2 snapshot descriptor is
present. The existing single-index methods used by direct management-plane construction may remain
available where they do not create a registered runtime compatibility path.

### Control Plane Trace Summary Integration

Extend the Knowledge Provider protocol with an optional duck-typed one-shot summary method:

```python
def consume_retrieval_summary(self) -> Mapping[str, Any] | None: ...
```

Do not require every provider to implement it. The Knowledge Retrieval Service checks for a
callable method after each provider call and merges returned fields into that step's existing
`retrieval_result.payload`.

The Local Index provider clears its stored summary when consumed. Every `retrieve()` attempt
replaces prior summary state before returning or raising, preventing summaries from leaking across
requests. The Knowledge Retrieval Service consumes the summary on both success and failure paths.
For a direct provider failure it emits an error `retrieval_result`; for a bound provider failure it
adds the summary to that failed `provider_calls[]` entry before existing required/advisory handling.

For bound-provider retrieval, the trace-safe Local Index summary belongs inside that provider's
`provider_calls[]` entry. For a directly configured single provider, merge it into the top-level
`retrieval_result.payload`. This preserves each step's existing trace shape while keeping local
document routing facts correlated with the selected provider call.

## Trace-Safe Summary Shape

Local Index retrieval exposes:

```json
{
  "document_candidates": [
    {
      "document_id": "doc_policy",
      "revision_id": "rev_001",
      "filename": "policy.md",
      "routing_metadata_keys": ["tags"],
      "metadata_matched": true,
      "selection_reason": "metadata_match"
    }
  ],
  "selected_documents": [
    {
      "document_id": "doc_policy",
      "revision_id": "rev_001",
      "selection_reason": "routing_model_selected"
    }
  ],
  "document_routing": {
    "snapshot_id": "kssnapshot_001",
    "candidate_count": 14,
    "routed_candidate_count": 4,
    "selected_count": 2,
    "candidate_truncated": false,
    "selection_budget": 8,
    "selection_reason": "routing_model_selected"
  }
}
```

`document_candidates[]` contains the bounded candidate set shown to the routing model, not every
manifest entry when truncation occurs. Unselected entries record compact reasons only.

Trace summaries must not contain:

- document content;
- artifact paths or storage paths;
- routing-model raw output;
- free-form routing-model reason text;
- credentials or environment-variable values.

## Failure Matrix

| Condition | Behavior |
| --- | --- |
| missing `snapshot_path` or `artifact_root` | `PA_KNOWLEDGE_001` |
| historical `index_path` in Agent Package | `PA_CONFIG_001` bootstrap migration error |
| historical `index_path` passed directly to runtime adapter | `PA_KNOWLEDGE_001` migration error |
| missing, malformed, non-v2, or non-READY `snapshot.json` | `PA_KNOWLEDGE_001` before storage open |
| empty snapshot document set or duplicate document ids | `PA_KNOWLEDGE_001` before storage open |
| absolute or escaping artifact reference | `PA_KNOWLEDGE_001` before storage open |
| invalid `document_selection_budget` | `PA_KNOWLEDGE_001` |
| routing-model malformed JSON, invalid contract, unknown id, duplicate id, or over-budget ids | `PA_KNOWLEDGE_002` |
| routing-model valid empty selection | zero evidence with `routing_empty` summary |
| selected artifact missing or malformed | `PA_KNOWLEDGE_002`, no partial evidence |
| selected TreeIndex storage load or retrieval failure | `PA_KNOWLEDGE_002`, no partial evidence |

Routing-model and selected-document failure summaries use a bounded `selection_reason` such as
`routing_model_failed` or `selected_document_failed` plus a stable `error_code`. They do not store
exception text, model reason text, or raw model output.

## TDD Verification

### V2 Loader

- valid snapshot returns a trace-safe descriptor;
- v1 sidecar and `params.index_path` are rejected as migration errors;
- missing, malformed, non-READY, empty, duplicate-document, absolute-path, and escaping-path
  manifests fail before storage load;
- manifest order does not change deterministic document order.

### Document Router

- filename and recursive routing metadata values participate in normalized matching;
- metadata matches reduce the model candidate set;
- no metadata match falls back to the sorted full manifest candidate set;
- more than `100` eligible documents truncates deterministically and records the flag;
- default and configured document-selection budgets are enforced;
- strict JSON normalization accepts valid selection and fails closed for malformed, unknown,
  duplicate, and over-budget ids;
- empty valid selection returns a trace-safe `routing_empty` summary.

### Multi-Document Runtime Retrieval

- only selected revision artifacts are loaded;
- selected document evidence is merged deterministically and final `top_k` applies after merge;
- returned evidence carries snapshot, document, revision, chunk, and stable citation identity;
- any selected artifact load or retrieval failure discards partial evidence and raises
  `PA_KNOWLEDGE_002`;
- direct management-plane single-index construction remains usable where retained.

### Trace Integration

- direct single-step retrieval merges one-shot document routing summary into top-level
  `retrieval_result.payload`;
- bound Local Index retrieval merges the summary into the matching `provider_calls[]` entry;
- planner/evaluator-backed agentic retrieval records a fresh summary for every round;
- routing-model and selected-document failure paths emit bounded error summaries without partial
  evidence;
- consumed summaries do not appear in later unrelated retrievals;
- trace payloads never contain artifact paths, document content, or raw routing-model output.

### Regression

Run:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree --extra openai \
  python -m pytest tests/ -q
uv run --extra dev --extra dashboard --extra ingestion --extra tree --extra openai \
  mypy proof_agent
uv run --extra dev ruff check proof_agent tests
uv run --extra dev proof-agent demo
uv run --extra dev --extra dashboard proof-agent react-demo
git diff --check
```

## Documentation Updates

Update:

- `docs/technical-design.md`
- `docs/developer-guide.md`
- `docs/development-progress.md`
- `docs/migration/pageindex-to-local-index.md`
- development fixtures that still show `params.index_path`

Document the v2-only runtime cutover, explicit `snapshot_path + artifact_root`, the metadata
soft-filter fallback, the `100`-candidate routing input cap, the `1..20` document-selection budget,
strict JSON routing-model output, selected-document fail-closed behavior, and trace-safe routing
summaries.

## Deferred Work

- formal Knowledge Source Publication and `published_snapshot_id`;
- Source snapshot pinning in Published Agent Versions;
- routing-model connectivity test, routing-smoke retrieval, and citation-resolution publication
  validation;
- routing metadata editing API and Dashboard UI;
- hierarchical or batched routing beyond the bounded `100`-candidate input;
- citation preview endpoint and customer-safe citation projection;
- continuous worker polling;
- atomic batch upload;
- trusted `http_json` remote adapter.
