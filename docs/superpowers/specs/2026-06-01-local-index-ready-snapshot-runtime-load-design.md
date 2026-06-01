# Local Index READY Snapshot Runtime Load Design

## Scope

This slice makes the registered `local_index` Knowledge Provider executable at runtime against
an already-published READY snapshot. It does not add ingestion workers, Source publication APIs,
document routing, snapshot pinning in Published Agent Versions, or Dashboard controls.

## Runtime Contract

`knowledge_sources[].params.index_path` points to one immutable published local index snapshot
directory. The directory contains LlamaIndex native persistence files plus `artifact_meta.json`.

`artifact_meta.json` uses this minimum runtime shape:

```json
{
  "schema_version": "local_index.snapshot.v1",
  "snapshot_id": "snapshot_enterprise_policy_001",
  "state": "READY",
  "provider": "local_index",
  "engine_name": "llama-index-tree",
  "engine_version": "0.12"
}
```

Runtime rejects a missing, malformed, non-READY, wrong-provider, or wrong-engine sidecar before
opening LlamaIndex storage. The snapshot loader returns trace-safe snapshot identity metadata for
future retrieval summaries without exposing storage paths.

## Model Resolution

Runtime retrieval needs a source-owned routing model only. `LocalIndexProvider.from_config()`
resolves `params.routing_model`, falling back to `params.ingestion_model` to preserve the ADR-0015
inheritance rule. Each model mapping uses the existing `ModelConfig` shape:

```yaml
routing_model:
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key_env: OPENAI_COMPATIBLE_API_KEY
    base_url_env: OPENAI_COMPATIBLE_BASE_URL
```

`LocalIndexProvider` keeps an optional ingestion LLM for management-plane `build_index()`.
Runtime composition never calls `build_index()`.

## Failure Rules

Configuration or snapshot validation failures raise `PA_KNOWLEDGE_001` with an actionable fix.
LlamaIndex load failures raise `PA_KNOWLEDGE_002`. Existing Control Plane retrieval handling
continues to apply binding-level required or advisory failure behavior.

## Tests

- `from_config()` resolves a routing model, inherits ingestion model when needed, validates the
  READY sidecar, and loads storage.
- Missing or non-READY sidecars fail before LlamaIndex storage load.
- A provider created for runtime has no ingestion model and cannot build an index on demand.
- Existing direct build, load, retrieve, structure, and scoped retrieval tests remain valid.
