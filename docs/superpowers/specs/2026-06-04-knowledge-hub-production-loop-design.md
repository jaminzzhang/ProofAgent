# Knowledge Hub Production Loop Design

## Scope

This design makes Knowledge Hub complete enough to use for one production `local_index` Knowledge
Source loop:

```text
create Source
  -> configure Local Index provider
  -> upload document
  -> run ingestion worker
  -> freeze candidate snapshot
  -> validate Source publication with a smoke query
  -> publish Source
  -> bind published Source to Agent Draft
  -> validate Agent
  -> publish Agent
  -> run Published Agent Version
```

The slice follows the selected scope A: Local Index production loop first. It does not add
continuous worker polling, atomic batch upload, document replacement/archive/retry operations,
routing metadata editing, hierarchical routing beyond the existing bounded first 100 candidates,
trusted `http_json`, full Source version diff/rollback, export/import, RBAC, or production Approval
Console behavior.

## Current Baseline

The repository already has the Local Index foundations required for this slice:

- quarantine upload staging for one Dashboard-managed file;
- asynchronous Markdown and text-based PDF validation;
- immutable revision artifact construction;
- persisted bounded retries and source worker concurrency;
- one-shot `knowledge-worker --once`;
- candidate snapshot derivation;
- foundation validation and immutable `local_index.snapshot.v2` freeze;
- preview-only `latest_snapshot_id`;
- v2 runtime load, bounded metadata-first document routing, selected artifact retrieval, and
  trace-safe routing summaries through the Control Plane retrieval service.

The current gap is the production boundary. A foundation-frozen snapshot is still a development
input. `published_snapshot_id` remains unset, Source publication does not exist, Dashboard
`/knowledge` still exposes stale `index_path` behavior, and Agent binding currently copies Source
provider params into package YAML instead of using an explicit Source reference and resolving
published Source versions through a clear composition boundary.

## Goals

- Add formal Local Index Source publication validation with an editable smoke query.
- Add formal Source publication and a minimal publication record.
- Set `KnowledgeSource.published_snapshot_id` only after Source publication succeeds.
- Add a Knowledge Binding Resolver abstraction so standalone packages and Dashboard-managed Agents
  resolve through the same runtime shape without ambiguous Source semantics.
- Keep standalone Agent Packages working for deterministic demos and local fixtures through
  explicit `package_knowledge_sources[]`.
- Remove stale Dashboard `index_path` creation behavior.
- Make Dashboard-managed Agent binding select only published Sources.
- Add an explicit Local Configuration Store reset path for generated local config state.

## Non-Goals

- No compatibility path for old Dashboard-generated `index_path` data.
- No migration script that dual-reads old local Configuration Store state.
- No deletion of source-controlled examples, tests, docs, or retained RunStore audit history.
- No full Knowledge Hub V1 remote Source implementation.
- No final-answer model call during Source publication validation.

## Domain Decisions

### Source Publication Requires Smoke Retrieval

Foundation validation is not enough for production binding. A Local Index Source publication
validation must prove that the frozen snapshot can be used by the registered runtime retrieval
path.

The validation binds:

```text
source_id
source_draft_version_id
candidate_digest
snapshot_id
smoke_query
```

It must:

- resolve the latest frozen READY snapshot for the Source;
- verify the current candidate snapshot has not drifted from the frozen snapshot identity;
- execute Local Index runtime retrieval through the same manifest load, document routing, selected
  artifact retrieval, and candidate merge path used at Agent runtime;
- keep Source-owned routing-model calls inside the Control Plane `before_model_call` policy and
  safe trace projection;
- require at least one normalized candidate evidence result;
- require cited evidence;
- require at least one citation that parses as a Local Knowledge Citation URI.

It must not:

- call a final-answer model;
- create a production RunStore run;
- count as an Agent Validation Run;
- publish or mutate the Source pointer.

### Source Publication Writes A Record

Publishing a Source writes a minimal `Knowledge Source Publication Record` and then updates
`published_snapshot_id`. The record stores:

```text
publication_id
source_id
snapshot_id
source_draft_version_id
validation_id
change_note
published_at
published_by
document_count
smoke_query
smoke_result_summary
```

`change_note` is required. Reusing the same validation after a successful publish should fail with
a stable conflict rather than silently creating duplicate publication history.

Publishing a Source does not update Draft Agents or Published Agent Versions. It only creates an
upgrade opportunity.

### Knowledge Binding Resolver Removes Ambiguity

The runtime should not infer provider configuration directly from mutable Dashboard Source Drafts,
and the Agent Contract should not use one field name for both package-local Sources and shared
Knowledge Hub assets. Composition introduces a `KnowledgeBindingResolver` boundary that turns
binding intent into a `ResolvedKnowledgeBindingSet`.

Agent bindings target an explicit `source_ref`:

```yaml
knowledge_bindings:
  - binding_id: enterprise_qa_knowledge_binding
    source_ref:
      scope: package
      source_id: enterprise_qa_knowledge
```

or:

```yaml
knowledge_bindings:
  - binding_id: policy_binding
    source_ref:
      scope: shared
      source_id: ks_policy
```

`scope: package` resolves against `package_knowledge_sources[]`. `scope: shared` resolves against
published Knowledge Hub Sources through the Configuration Store. A binding does not rely on an
implicit lookup rule.

Two inputs are supported:

#### Package-Local Resolver

Used by CLI, deterministic demos, and standalone Agent Packages.

Input:

```text
AgentManifest.package_knowledge_sources[]
AgentManifest.knowledge_bindings[].source_ref(scope="package")
```

The package-local Source set is explicit:

```yaml
package_knowledge_sources:
  - source_id: enterprise_qa_knowledge
    provider: local_markdown
    params:
      path: ./knowledge
```

These Sources are not reusable Knowledge Hub assets and are not published through Source
Publication. This keeps no-network deterministic demos working without a Configuration Store
dependency.

#### Configuration Store Resolver

Used by Dashboard validation, Agent publication, and production execution from configured Agents.

Input:

```text
Agent Draft knowledge_bindings[].source_ref(scope="shared")
Knowledge Source Store
Published Source snapshots/configuration versions
```

Every binding must resolve to a published Source version. Unpublished Sources, foundation-only
snapshots, archived Sources, missing snapshots, and malformed runtime configs fail closed.

For `local_index`, the resolver derives runtime config from the published snapshot:

```text
snapshot_path
artifact_root
routing_model
document_selection_budget
```

The runtime provider receives this resolved config and does not know whether it came from a
standalone package or the Configuration Store.

Published Agent Versions persist the resolved binding set. Later Source publications never change
an existing Published Agent Version.

### Local Configuration Store Reset Is Explicit

Old generated local Configuration Store state is cleared through an explicit reset command or
script, not by manual deletion hidden inside another task.

The reset clears generated state under `runs/config`, including Draft Agents, Published Agent
Versions, Knowledge Sources, local-index artifacts, snapshots, and compiled configuration packages.
It does not delete examples, tests, docs, `runs/history`, `runs/latest`, or other retained audit
artifacts.

## Store And API Design

### Store Methods

Add publication validation:

```python
validate_local_index_source_publication(
    source_id: str,
    smoke_query: str,
    actor: str,
) -> KnowledgeSourcePublicationValidation
```

Behavior:

- requires a `local_index` Source;
- requires `latest_snapshot_id`;
- loads the matching frozen `local_index.snapshot.v2` manifest;
- rejects stale candidate/source draft token drift;
- executes Source-level smoke retrieval;
- persists a passed validation or raises a stable `ProofAgentError`.

Add Source publication:

```python
publish_knowledge_source(
    source_id: str,
    validation_id: str,
    change_note: str,
    actor: str,
) -> KnowledgeSourcePublicationRecord
```

Behavior:

- requires a non-empty `change_note`;
- requires the validation to belong to the Source and still match the current Source draft token,
  candidate digest, and snapshot id;
- rejects a reused validation after publication with a stable conflict;
- writes the publication record;
- updates `KnowledgeSource.published_snapshot_id`;
- does not mutate Draft Agents or Published Agent Versions.

### API Routes

Add:

```text
POST /api/config/knowledge-sources/{source_id}/publication/validate
POST /api/config/knowledge-sources/{source_id}/publication/publish
GET  /api/config/knowledge-sources/{source_id}/publications
GET  /api/config/knowledge-sources/{source_id}/publication-validations
```

Request body for validation:

```json
{
  "smoke_query": "What documents are required for inpatient reimbursement?",
  "actor": "dashboard"
}
```

Request body for publish:

```json
{
  "validation_id": "kspubval_1234abcd",
  "change_note": "Publish first reviewed policy corpus.",
  "actor": "dashboard"
}
```

### Existing API Fixes

- `POST /api/config/knowledge-sources` no longer accepts or encourages `index_path` for
  Dashboard-managed `local_index` Sources.
- Source params for Dashboard-managed `local_index` Sources are Source-owned management config:
  ingestion model, routing model, document selection budget, worker concurrency, and future
  ingestion-affecting options.
- Runtime `snapshot_path + artifact_root` is derived from publication/resolution, not manually
  entered in the create Source form.

## Runtime Composition Design

Add contracts for resolved knowledge:

```python
class ResolvedKnowledgeBinding(FrozenModel):
    binding_id: str
    source_scope: Literal["package", "shared"]
    source_id: str
    source_version_id: str
    provider: str
    provider_params: Mapping[str, Any]
    alias: str | None = None
    failure_mode: str
    fusion_weight: float
    top_k: int | None = None
    routing_metadata: Mapping[str, Any]

class ResolvedKnowledgeBindingSet(FrozenModel):
    bindings: tuple[ResolvedKnowledgeBinding, ...]
```

Add a resolver protocol:

```python
class KnowledgeBindingResolver(Protocol):
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet: ...
```

Composition changes:

- `compose_harness_invocation()` accepts either a resolver or a precomputed
  `ResolvedKnowledgeBindingSet`.
- The default resolver for standalone package execution is package-local.
- Dashboard validation, Agent publish, and production execution pass the Configuration Store
  resolver or a persisted resolved set.
- `BlendedKnowledgeProvider` is constructed from `ResolvedKnowledgeBindingSet`.

Agent publication changes:

- Draft Agent state stores `knowledge_bindings[]` with `source_ref(scope="shared")` plus retrieval
  settings, not Source provider params.
- Draft validation resolves latest published Sources.
- Agent publication persists the resolved binding set used by validation.
- Production execution of a Published Agent Version uses that persisted set.
- Agent rollback restores the resolved set captured by the selected version.
- Source publication creates `Knowledge Binding Upgrade Available` state but does not mutate the
  Agent.

## Dashboard Design

### `/knowledge`

The list becomes an operational Source projection:

- name;
- provider;
- lifecycle;
- `published_snapshot_id`;
- `latest_snapshot_id`;
- READY and total document counts;
- warnings for unpublished changes, failed ingestion, or missing publication.

Create Source becomes a small wizard for this slice:

- provider fixed to `local_index` for the production loop;
- Source name and Source ID;
- ingestion model provider/name/env reference params;
- routing model override optional, default inherits ingestion model;
- document selection budget;
- worker concurrency.

The current `index_path` input is removed.

### `/knowledge/:sourceId`

Create a minimal detail workspace with four operational areas:

- `Overview`: lifecycle, published snapshot, latest preview snapshot, document counts, and
  referencing Agent count as a placeholder if the backend does not have the projection yet.
- `Provider`: edit Source-owned Local Index config. In this slice, config changes may block
  publication through validation rather than adding full reingestion UI.
- `Documents`: one-file upload, Quarantined Upload state, Ingestion Job state, and managed
  document state. The UI may show the `knowledge-worker --once` command rather than starting a
  continuous worker.
- `Publication`: candidate snapshot summary, validation form with smoke query, publish form with
  required change note, and recent publication records.

### Agent Knowledge Module

- List only published Sources as bindable.
- Show unpublished Sources disabled with a concrete reason.
- Show upgrade availability when a bound Source has a newer `published_snapshot_id`.
- Do not write shared Source provider params into Draft Agent YAML.
- Contract View should show binding intent and optionally a read-only resolved Source summary, not
  mutable shared Source provider config.
  Shared bindings use `source_ref(scope="shared")`; package-local Source definitions are hidden from
  Dashboard-managed Drafts.

## Testing Strategy

### Reset

- Reset deletes `runs/config`.
- Reset does not delete `runs/history`, `runs/latest`, examples, tests, or docs.
- Reset requires an explicit scope.

### Source Publication Validation

- Missing `latest_snapshot_id` fails closed.
- Foundation snapshot cannot publish without publication validation.
- Candidate digest drift invalidates validation.
- Source draft version drift invalidates validation.
- Smoke retrieval with zero evidence fails.
- Smoke retrieval with missing citation fails.
- Smoke retrieval with unparseable citation fails.
- Valid smoke retrieval persists a validation record.

### Source Publication

- Missing `change_note` fails.
- Stale validation fails.
- Reused validation conflicts.
- Successful publish writes a record and updates `published_snapshot_id`.
- Successful publish does not mutate Draft Agent or Published Agent Version state.

### Resolver

- Loader accepts `package_knowledge_sources[]` and `knowledge_bindings[].source_ref`.
- Loader rejects legacy shared/provider ambiguity where Dashboard-managed Agent Drafts embed shared
  Source provider params.
- Package-local resolver keeps deterministic examples runnable.
- Configuration Store resolver rejects unpublished Sources.
- Configuration Store resolver rejects archived Sources.
- Configuration Store resolver maps published `local_index` snapshots to runtime
  `snapshot_path + artifact_root`.
- Published Agent Version persists resolved binding set.
- Source publication after Agent publication does not change existing production execution.

### Dashboard

- Create Source form does not send `index_path`.
- Publication validation and publish actions call the new API routes.
- Agent binding UI disables unpublished Sources.
- Upgrade available state is visible when a newer published Source exists.

### Verification Commands

Focused backend tests:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree python -m pytest \
  tests/test_agent_configuration_api.py \
  tests/test_agent_configuration_store.py \
  tests/test_knowledge_snapshot_store.py \
  tests/test_local_index_provider.py \
  tests/test_composition.py -q
```

Frontend:

```bash
cd dashboard && npm test
cd dashboard && npm run build
```

Regression:

```bash
uv run --extra dev proof-agent demo
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
```

## Implementation Sequence

1. Add explicit Local Configuration Store reset command and clear generated `runs/config` state
   through that command.
2. Add publication validation and publication record contracts.
3. Add store persistence and API routes for Source publication validation and publication.
4. Add Source-level smoke retrieval service that uses the runtime Local Index path without final
   answer generation.
5. Migrate Agent Contract models, loader, examples, and fixtures to `package_knowledge_sources[]`
   plus `knowledge_bindings[].source_ref`.
6. Add `ResolvedKnowledgeBindingSet` and `KnowledgeBindingResolver`.
7. Change `BlendedKnowledgeProvider` and `compose_harness_invocation()` to consume resolved
   bindings.
8. Change Dashboard-managed Agent validation/publication/execution to resolve and persist published
   Source bindings instead of copying Source provider params into Agent YAML.
9. Update `/knowledge` and add `/knowledge/:sourceId` minimal detail workspace.
10. Update Agent Knowledge module binding behavior.
11. Update English docs and development progress.
12. Run focused and regression verification.

## Documentation Updates

Update only English docs during development:

- `docs/technical-design.md`: record Source publication boundary and Knowledge Binding Resolver.
- `docs/developer-guide.md`: document the Local Index production loop and reset command.
- `docs/development-progress.md`: update current gaps after implementation.

ADR-0018 records the final Agent Knowledge Source Reference contract shape. ADR-0001, ADR-0009,
ADR-0015, ADR-0016, and ADR-0017 already establish the other core trade-offs: Source-owned provider
configuration, direct breaking migration, Local Index runtime snapshots, provider set, and
foundation snapshot versus production publication boundary.
