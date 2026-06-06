# Knowledge Source Lifecycle Management

Knowledge Hub reusable Sources use exactly two visible lifecycle states: `ACTIVE` and `ARCHIVED`.
There is no `DELETED` state. Permanent deletion is an irreversible storage removal operation, not a
state that can still be listed or restored.

Archive is the default delete-like action. It preserves history, publications, snapshots, documents,
resolved Published Agent Version references, and configuration audit while blocking new writes:
document intake, routing metadata edits, candidate freeze, Source publication, new Agent binding,
Draft Agent validation, and Draft Agent publication against an archived shared Source. Existing
Published Agent Versions keep running because they execute against pinned resolved Knowledge Binding
Sets captured at Agent publication time. Draft Agent bindings are not removed automatically; they
remain visible blockers until an operator unbinds them or restores the Source.

Restore moves an archived Source back to `ACTIVE` without changing the Source Draft version,
publications, snapshots, Draft Agents, Published Agent Versions, or resolved binding records. If the
Source already has a published local snapshot or remote configuration version, it is immediately
eligible for new bindings again. Restore does not require a new Source publication validation because
archived Sources cannot mutate publication-bound inputs while archived.

Permanent deletion is intentionally narrow. V1 allows it only for empty archived Sources with no
Draft Agent bindings, no Published Agent Version resolved references, no publications, no snapshots,
no retained managed documents, no quarantined uploads, no ingestion jobs, and no audit-retention
blocker. The deletion audit record is written to root-level configuration audit before the Source
directory is removed, so the deletion event survives the removal.

The local Configuration Store does not provide compatibility fallback for generated Source JSON that
omits `lifecycle_state`. Operators must reset and rebuild stale local configuration data instead of
running dual-read semantics that hide lifecycle gaps.
