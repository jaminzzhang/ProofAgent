# Knowledge Source Lifecycle Management Design

## Scope

This design completes the Knowledge Hub lifecycle boundary for reusable Knowledge Sources:

```text
create Source
  -> configure provider
  -> publish or bind when eligible
  -> archive as the default delete-like action
  -> restore when needed
  -> permanently delete only empty archived Sources
```

The slice covers backend contracts, Local Configuration Store behavior, configuration API routes,
minimal Dashboard lifecycle controls, and documentation. It does not add a full Audit tab,
artifact cleanup worker, retained Source purge, full Source metadata editor, RBAC, export/import
implementation, or broader provider-contract rewrites.

## Current Baseline

Knowledge Hub already supports shared Source creation, local-index document intake, candidate
snapshot freeze, Source publication, published-source Agent binding, and resolved binding
persistence on Published Agent Versions.

The gap is lifecycle governance:

- `KnowledgeSource` has no lifecycle field.
- Source archive, restore, deletion eligibility, and physical deletion are not implemented.
- Source mutation routes do not have an archived guard.
- Dashboard does not distinguish active and archived Sources.
- Existing docs define archive/restore/physical deletion, but code only supports active Sources.

## Domain Decisions

### Visible Lifecycle States

Every reusable Knowledge Source has exactly one visible lifecycle state:

- `ACTIVE`
- `ARCHIVED`

There is no `DELETED` lifecycle state. Physical deletion is an irreversible guarded removal
operation, not a Source state.

### Archive Is The Default Delete-Like Action

The product labels the default delete-like action as **Archive Source**, not Delete.

Archiving moves the Source to `ARCHIVED`. It blocks:

- new Agent binding;
- Agent validation and publication when a Draft still binds the archived Source;
- Source provider changes;
- document upload, replacement, retry, routing metadata edits, and snapshot freeze;
- Source publication validation and Source publication;
- remote connection validation and retrieval preview.

Archiving still allows:

- read/list/detail;
- viewing documents, snapshots, publications, validations, and audit;
- unbinding from Draft Agents;
- restore;
- manifest export;
- physical-deletion eligibility checks.

Existing Published Agent Versions keep running because they execute against pinned resolved
snapshot or remote configuration versions. Existing Draft Agent bindings are not automatically
removed; they remain visible blockers until explicitly unbound or the Source is restored.

### Restore Is A Lifecycle Toggle

Restore returns an archived Source to `ACTIVE` without changing any Draft Agent, Published Agent
Version, Source Draft, publication, or resolved version.

If the Source already has a published snapshot or remote configuration version, it becomes eligible
for new Draft binding again. If it has no published resource, it remains an active draft Source.
Restore does not require fresh Source publication validation because archived Sources cannot mutate
publication-bound inputs while archived.

### Physical Deletion Is Narrow

The danger-zone action is labeled **Permanently delete Source**.

V1 executes physical deletion only for mistakenly created empty Sources. A Source is eligible only
when it is already `ARCHIVED` and all blockers are clear:

- no Draft Agent binding;
- no Published Agent Version resolved binding;
- no publication record;
- no frozen snapshot;
- no retained managed document;
- no retained quarantined upload;
- no retained ingestion job;
- no audit-retention blocker.

The deletion audit record must be written to a global configuration-audit location before deleting
the Source storage directory, so the audit survives the deletion.

### Draft Version Boundary

`source_draft_version_id` changes only when publication-bound Source state changes:

- provider configuration;
- remote retrieval mapping;
- publication-bound Source routing metadata;
- document routing metadata;
- candidate-snapshot membership.

It does not change for:

- general display/governance metadata;
- Archive;
- Restore;
- worker leases;
- retry counters;
- rejected uploads that do not alter the publication candidate.

Archive and Restore are configuration audit events and bindability guards, not Source Draft Version
changes.

### Metadata And Provider Configuration

The public Source contract keeps:

```yaml
provider: local_index | local_markdown | http_json
params: {...}
```

Backend validation, Dashboard forms, and docs remain provider-specific. This slice should organize
provider validation and UI fields for `local_markdown`, `local_index`, and `http_json`, but it
should not introduce a public typed provider union.

General Source metadata such as name, description, and tags is display/governance metadata by
default. Editing it is audited but does not stale Source publication validation unless a field is
explicitly promoted into Source Routing Metadata or customer-safe citation projection.

### Reference Summary

`KnowledgeSourceReferenceSummary` is the shared projection for archive confirmation and deletion
eligibility. It includes:

- Draft Agent binding count;
- Published Agent Version count;
- publication count;
- frozen snapshot count;
- retained managed document count;
- quarantined upload count;
- ingestion job count;
- audit-retention blocker.

Archive uses the summary to show impact without blocking Archive. Physical Deletion uses the same
summary as blockers.

### Local Store Compatibility

No local-store compatibility path is provided for generated Source JSON missing `lifecycle_state`.
Breaking Knowledge Source configuration changes require explicit `config-reset` and local
configuration rebuild. Source-controlled examples, tests, docs, and retained RunStore audit output
are not deleted by reset.

## API Shape

Use explicit lifecycle routes:

```text
POST   /api/config/knowledge-sources/{source_id}/archive
POST   /api/config/knowledge-sources/{source_id}/restore
GET    /api/config/knowledge-sources/{source_id}/deletion-eligibility
DELETE /api/config/knowledge-sources/{source_id}
```

`DELETE` means Physical Deletion only. The UI should not use it for the default delete-like action.

## Dashboard Shape

Knowledge Hub should minimally show:

- `ACTIVE` or `ARCHIVED` on list/detail;
- **Archive Source** for active Sources;
- **Restore Source** for archived Sources;
- a danger-zone **Permanently delete Source** action that is disabled unless eligibility is clear;
- deletion blockers when ineligible;
- archived guards for upload, publication, provider mutation, and binding selection.

## ADR Need

This lifecycle model is hard to reverse, surprising without context, and the result of a real
trade-off between operator cleanup, rollback safety, and audit retention. It merits a short ADR
before or alongside implementation.
