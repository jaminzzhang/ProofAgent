# Knowledge And Evidence

Knowledge And Evidence contains the language for Knowledge Sources, Agent bindings, retrieval, ingestion, evidence admission, citations, and Local Index behavior.

## Language

**Local Index Reingestion Required**:
The visible Source Draft condition set when a local index ingestion-configuration change could affect generated index artifacts. Existing published snapshots remain usable, but a replacement candidate snapshot cannot be published until required document revisions have been reingested successfully.
_Avoid_: Silent old-artifact reuse, immediate published-snapshot mutation, routing-only configuration change

**Knowledge Ingestion Configuration Fingerprint**:
The stable identifier derived from local index ingestion model configuration and artifact-affecting ingestion parameters. A Knowledge Document Revision index artifact is compatible only when its content hash and Knowledge Ingestion Configuration Fingerprint match.
_Avoid_: Routing model fingerprint, filename key, mutable cache identity

**Knowledge Artifact Build Spec**:
The immutable secret-safe artifact-build input snapshot persisted with one Knowledge Ingestion Job when a validated revision is promoted. It captures provider and engine identity, exact parser fingerprint identity, immutable original content hash, Parsed Knowledge Document Text integrity hash, and the declared ingestion-model configuration with credential environment-variable references only. Fingerprint calculation and worker execution consume this same snapshot so later Source Draft edits cannot mutate queued work.
_Avoid_: Live Source configuration reread, raw credential value, routing-model settings, mutable queued-build input

**Secret-Safe Knowledge Configuration Validation**:
The recursive configuration-persistence guard that rejects secret-bearing parameter names before Knowledge Source configuration or Knowledge Artifact Build Spec storage. Environment-variable reference keys ending in `_env` are permitted, while raw credential-bearing fields such as `api_key`, `authorization`, `bearer`, `password`, `secret`, `access_token`, or `provider_api_key` fail with `PA_SECRET_001`.
_Avoid_: Top-level-only scan, raw secret persistence, error-message echo of secret values, worker-only secret rejection

**Incremental Local Index Reingestion**:
The rebuild behavior that queues only Knowledge Document Revisions in the current Candidate Knowledge Source Snapshot that lack a compatible index artifact for their content hash plus Knowledge Ingestion Configuration Fingerprint. Routing-model changes, Knowledge Document Selection Budget changes, and routing-metadata edits do not trigger index rebuilding.
_Avoid_: Mandatory full-corpus rebuild, routing-only rebuild, stale-artifact publication

**Knowledge Ingestion Worker Policy**:
The local index worker execution policy: one unified atomic store claim compares quarantine-validation and artifact-build tasks and returns a store-to-worker claim-selection envelope containing an optional task plus diagnostics; claim-time per-Source concurrency defaults to 2 and is configurable from 1 through 8 through integer `params.worker_concurrency`; the selector counts non-expired `processing` tasks of both kinds, skips a Source at its limit while continuing oldest-ready-first selection across eligible tasks, uses claim-token ownership with renewable persisted leases and bounded provider calls, performs at most 2 automatic retries per revision with persisted backoff for recoverable failures, fails non-recoverable intake or configuration errors immediately, and recovers persisted queues after worker restart without rebuilding compatible artifacts. Source configuration persistence rejects an invalid `worker_concurrency` with `PA_INGESTION_001`; claim repeats validation defensively for manually altered or legacy records, skips an invalid Source without starving valid Sources, and collects a value-safe diagnostic rather than silently clamping. Each one-shot result is a worker-to-CLI envelope containing an optional task outcome plus diagnostics; CLI prints diagnostics before any task outcome and does not print `no queued knowledge tasks` when diagnostics exist. Store-lock timeout fails the current API or CLI operation with `PA_INGESTION_004` without attempting another state write. Artifact-key lock contention is expected deduplication behavior: the worker defers the job for 5 seconds without counting a build failure, then a later worker rechecks cache. `attempt_count` counts claims; `auto_retry_count` counts recoverable build failures and alone enforces the 2-retry limit. Worker concurrency affects scheduling only and does not participate in artifact fingerprinting. A renewal failure immediately stops the stale worker from starting further provider calls, artifact publication, or task-state commits. Work that already completed during an in-flight bounded provider call or atomic rename may leave a reusable published artifact for the new owner to validate and reuse.
_Avoid_: Unbounded concurrency, starvation-prone queue priority, infinite retry, in-memory-only task state, timestamp-only claim ownership, stale-worker state commit, post-renewal-failure provider call, duplicate compatible build

**Continuous Knowledge Worker**:
The service-owned polling mode for Knowledge Ingestion Worker that repeatedly advances quarantined upload validation and local index artifact-build jobs until an explicit stop boundary. It may sleep when the durable queue is empty, reuse the same lease, retry, diagnostic, and ownership policy as one-shot execution, and surface value-safe progress for operators; it does not automatically freeze a Candidate Knowledge Source Snapshot, publish a Knowledge Source, or mutate Published Agent Versions.
_Avoid_: API-request-held indexing loop, auto-publish worker, in-memory scheduler, Agent runtime background task

**Knowledge Ingestion Failure Classification**:
The stable error classification shown in Dashboard for a failed Knowledge Document Revision. Unsupported format, scanned PDF, missing configuration, and missing credentials are non-recoverable without operator action; model timeout, transient rate limiting, and temporary network failure are recoverable and eligible for bounded automatic retry.
_Avoid_: Raw stack trace, silent retry loop, one generic failure message

**Operator Knowledge Document Upload Validation**:
The asynchronous server-side quarantine gate for Dashboard-managed local index files. The upload API performs request-envelope protection and stores bytes under a system-generated quarantine path without trusting filename, extension, or declared MIME type. The quarantine validator then accepts UTF-8 `.md` and text-based `.pdf` files whose embedded font encodings or CMaps can be extracted to meaningful Unicode text by the configured parser, verifies MIME type and content signature consistency, limits one file to 50 MB, limits one PDF to 500 pages, and limits one batch to 50 files while preserving the 500-document Source capacity. It rejects zip archives, directory uploads, nested attachments, encrypted PDFs, scanned PDFs, macro-bearing files, executable content, and unsupported files into Rejected Knowledge Upload Retention.
_Avoid_: Browser-only validation, synchronous managed-storage promotion, extension-only trust, archive extraction, customer attachment intake

**Knowledge Document Upload Quarantine**:
The isolation area where an operator-uploaded file remains until Operator Knowledge Document Upload Validation succeeds. Storage uses a system-generated path and a sanitized display filename; a rejected upload receives a stable error code and creates neither Knowledge Document Revision nor Knowledge Ingestion Job.
_Avoid_: Original-filename storage path, direct ingestion queue insertion, failed-upload candidate snapshot

**Quarantined Knowledge Upload**:
The persisted operator-upload intake record processed by asynchronous Operator Knowledge Document Upload Validation. It may become a validated Managed Knowledge Document Original plus Knowledge Document Revision and Knowledge Ingestion Job, or a rejected upload retained only for troubleshooting.
_Avoid_: Knowledge Document Revision, Knowledge Ingestion Job, candidate snapshot entry

**Quarantined Knowledge Upload Promotion**:
The crash-replay-safe transition that turns one validated Quarantined Knowledge Upload into one Managed Knowledge Document Original, Parsed Knowledge Document Text derivative, Knowledge Document Revision, and Knowledge Ingestion Job. It uses identities derived deterministically from the upload identity and a durable atomic commit marker; an ingestion worker may claim the resulting job only after that marker exists.
_Avoid_: Duplicate revision after retry, partially visible ingestion job, random retry identity, Knowledge Source Publication

**Managed Knowledge Document Original**:
The validated original PDF or Markdown file retained with one Knowledge Document Revision in managed storage separately from generated index artifacts. It supports reingestion, citation verification, and audit-safe operator inspection until reference and retention checks allow cleanup.
_Avoid_: Index-only retention, quarantine file, public attachment URL, mutable original

**Parsed Knowledge Document Text**:
The normalized Unicode text derivative retained with one validated Knowledge Document Revision after Quarantined Knowledge Upload validation. It is parser-metadata-bound input for index artifact construction and reingestion, with its own derivative content hash for integrity verification; it is not the Managed Knowledge Document Original, the revision content-hash identity, or a runtime evidence payload.
_Avoid_: Raw upload, index artifact, trace evidence content, parser-independent cache

**Knowledge Document Original Download Audit**:
The configuration-operation audit record written when an authorized operator downloads a Managed Knowledge Document Original. Download requires `knowledge_source.view`.
_Avoid_: Anonymous download, raw-file runtime trace, unaudited file export

**Rejected Knowledge Upload Retention**:
The short quarantine retention window for a file rejected by Operator Knowledge Document Upload Validation: 24 hours for troubleshooting, followed by automatic cleanup of quarantined bytes without promoting them into long-term managed document storage or audit content. The minimal rejected-upload record retains its stable error code and purge timestamp for operator status visibility.
_Avoid_: Permanent rejected-file retention, revision creation, candidate snapshot inclusion, indefinite raw-byte retention

**Local Knowledge Citation URI**:
The stable internal citation for a local index evidence chunk, for example `knowledge://source/{source_id}/document/{document_id}/revision/{revision_id}#page=12` for PDF or a section anchor for Markdown. It identifies governed source material without exposing a storage path.
_Avoid_: Filesystem path, public file URL, mutable latest-document link

**Knowledge Citation Preview**:
The permission-protected Dashboard action that opens cited source material from Run Detail or retrieval preview and navigates to PDF page or Markdown section anchor. Citation preview access is audited separately from Managed Knowledge Document Original download.
_Avoid_: Anonymous file access, raw storage URL, unaudited download

**No Accepted Evidence Outcome**:
The governed retrieval outcome when no Candidate Evidence becomes Accepted Evidence after routing, provider retrieval, fusion, citation enforcement, and evidence admission, or when a selected required Knowledge Binding fails. It follows insufficient-evidence or refusal behavior and does not permit free-form final-answer generation, invented citations, or source-backed claims.
_Avoid_: Best-effort answer, empty Sources list, hallucinated citation, silent provider failure

**Remote Citation Link Allowlist**:
The protocol and domain validation policy that determines whether an external remote Knowledge Source citation URL may be rendered as a clickable Dashboard or customer-facing link. A citation that fails validation remains visible as non-clickable source text.
_Avoid_: Arbitrary external link, javascript URL, secret-bearing URL

**Knowledge Source Publication Validation**:
The Source Draft-version-bound precondition for Knowledge Source Publication. Any relevant Draft configuration change invalidates the prior result and requires validation again before publication.
_Avoid_: Agent Validation Run, one-time Source validation, configuration-drift publication

**Foundation Knowledge Source Publication Validation**:
The incremental local-index publication check that binds one Knowledge Source Draft Version and proves at least one READY revision, compatible artifacts for every candidate revision, and no pending required reingestion. It may freeze a development-stage READY snapshot for subsequent routing work, but it does not claim production readiness before routing-model tests, smoke retrieval, and citation resolution validation are added.
_Avoid_: Production-ready validation, upload-success publication, unversioned partial check, routing smoke test

**Local Index Source Publication Validation**:
The local index publication check that requires at least one READY Knowledge Document Revision, no pending required reingestion, compatible artifacts for every revision included in the Candidate Knowledge Source Snapshot, successful ingestion and routing model configuration tests, and one editable smoke query proving routing, retrieval, and citation resolution.
_Avoid_: Upload-success publication, partial required rebuild, citation-free smoke test

**Remote Knowledge Source Publication Validation**:
The remote Source publication check that binds one Source Draft Version to a validated remote configuration. It requires adapter-supported health-check verification when available, successful authentication, target index or namespace validation when declared, response normalization validation, and one smoke query proving normalized candidate evidence plus citation or adequate Structured Remote Source Reference. Generic adapters such as `http_json` may publish a mutable external `remote_config` after smoke retrieval validation; adapters that cannot prove retrieval normalization remain preview-only.
_Avoid_: Stale health check, mapping-only validation, pretending remote config is a local snapshot

**Knowledge Source Publication Confirmation**:
The operator confirmation shown immediately before Knowledge Source Publication. It identifies the Source Draft and prior published version, summarizes local document additions, replacements, archives, and READY count or remote adapter, target, consistency mode, and verification time, shows smoke-query validation result and referencing Agent count, requires a `change_note`, and states that publication creates Draft Agent upgrade availability without mutating existing Published Agent Versions.
_Avoid_: One-click publish, silent Agent upgrade, missing change note, validation-detail omission

**Knowledge Source Rollback Draft**:
The new Source Draft created from a selected historical published Knowledge Source snapshot or configuration version. It requires review, fresh Knowledge Source Publication Validation, and explicit Knowledge Source Publication to produce a new version; it never mutates history or automatically changes Agent bindings.
_Avoid_: Published-version mutation, active-pointer rewind, automatic Agent rollback

**Knowledge Source Manifest Export**:
The audited secret-free export available for every Knowledge Source. It includes metadata, provider type, parameters, environment-variable references, published version information, declarative mappings, and routing configuration without credential values, original documents, or index artifacts.
_Avoid_: Secret export, full local bundle, index-cache archive

**Local Knowledge Source Offline Bundle**:
The optional audited export for a local index Knowledge Source that contains a Knowledge Source manifest plus validated Managed Knowledge Document Originals and content hashes. It excludes credential values and excludes cached index artifacts by default.
_Avoid_: Default export, trusted external index, secret-bearing archive

**Knowledge Source Import Draft**:
The Source Draft created by audited manifest or offline-bundle import. Remote Sources require fresh connection test, validation, and publication. Local bundle files pass upload validation again and reingest according to Knowledge Ingestion Configuration Fingerprint; imported index artifacts are never trusted directly.
_Avoid_: Implicit publication, external index trust, credential import

**Knowledge Source Configuration API**:
The shared-asset API under `/api/config/knowledge-sources` for listing, creating, filtering, reading, updating Drafts, archiving, restoring, document operations, version history and diff, rollback-Draft creation, validation, publication, remote connection testing, retrieval preview, export, and import. It owns Source provider parameters and lifecycle instead of embedding them in Agent Draft YAML.
_Avoid_: Dashboard observability API, Agent Draft provider params, execution endpoint

**Agent Knowledge Binding Configuration API**:
The Agent Draft configuration boundary that stores `knowledge_bindings[]` with shared Agent Knowledge Source References plus Agent-level blended-retrieval settings, then resolves published snapshot or configuration versions during Agent validation and publication. It stores binding intent only and never owns Knowledge Source provider parameters.
_Avoid_: Inline provider config, Source lifecycle API, latest-at-runtime lookup

**Direct Knowledge Contract Migration**:
The one-time breaking cutover from inline Agent `knowledge.provider + params` configuration and ambiguous Agent `knowledge_sources[]` to explicit package-local `package_knowledge_sources[]` plus Agent `knowledge_bindings[]` with Agent Knowledge Source References. Because no Agent deployment compatibility is required, loader, Dashboard, examples, fixtures, and tests migrate together and the new loader rejects the legacy inline and ambiguous shared-provider shapes.
_Avoid_: Legacy dual-read path, automatic compatibility Source creation, mixed contract versions

**Knowledge Source**:
A reusable knowledge asset or connection that owns its Knowledge Provider configuration and can be bound to one or more Agents.
_Avoid_: Retrieval Strategy, Accepted Evidence, Agent-only knowledge setting, provider-free asset

**Knowledge Source Lifecycle State**:
The reusable Knowledge Source lifecycle status. Every reusable Knowledge Source has exactly one visible lifecycle state: `ACTIVE` permits editing, publication, and new Agent binding, while `ARCHIVED` blocks new binding and new Agent publication without breaking existing Published Agent Version execution against pinned snapshots or configuration versions. Physical deletion is a guarded removal operation, not a `DELETED` lifecycle state.
_Avoid_: Knowledge Source Index State, deleted Source state, physical deletion, automatic Agent mutation

**Knowledge Source Archive**:
The default operator-facing delete action for a reusable Knowledge Source, labeled as Archive Source rather than Delete. It is a reversible configuration operation that moves a Knowledge Source to `ARCHIVED`, blocks new Agent binding and new Agent publication through that Source, preserves retained snapshots, configuration versions, artifacts, and Published Agent references, and shows affected Published Agents in Dashboard. Existing Published Agent Versions continue running against their pinned resolved Source snapshot or configuration version. Existing Draft Agent bindings are not automatically removed; they remain visible as validation and publication blockers until explicitly unbound or the Source is restored. An archived Source may still be inspected, audited, exported, unbound from Draft Agents, restored, and checked for physical-deletion eligibility, but it may not receive provider changes, document changes, new publication validation, Source publication, retrieval preview, or connection validation.
_Avoid_: Hard delete, delete button as default, snapshot purge, silent production breakage, hidden continued editing

**Knowledge Source Restore**:
The configuration operation that returns an archived Knowledge Source to `ACTIVE` without automatically changing any Draft Agent or Published Agent Version binding, Source Draft, publication, or resolved version. If the Source already has a published snapshot or remote configuration version, it becomes eligible for new Draft Agent binding again; if it has no published resource, it remains an active draft Source until normal publication. Restore does not require fresh Source publication validation because archived Sources cannot receive provider, document, retrieval-preview, connection-validation, or publication changes while archived.
_Avoid_: Automatic Agent upgrade, snapshot mutation, publication bypass, forced revalidation

**Knowledge Source Physical Deletion**:
The separate dangerous deletion action for audited irreversible removal, labeled as Permanently delete Source. It is allowed only when the Source is already `ARCHIVED` and has no Draft Agent binding, no Published Agent Version resolved binding, no publication record, no frozen snapshot, no retained managed document, no retained quarantined upload, no retained ingestion job, and no audit-retention requirement. In V1, Physical Deletion executes only for mistakenly created empty Sources after writing a global Knowledge Configuration Operation Audit record that survives removal of the Source storage directory; Archive is the terminal lifecycle for retained Sources. It is never the default delete action in Knowledge Hub and appears only as a disabled-by-default danger-zone action with explicit blockers when ineligible.
_Avoid_: Archive action, default delete button, retained Source purge, referenced artifact cleanup, rollback-breaking purge

**Knowledge Source Reference Summary**:
The shared impact and deletion-eligibility projection for one Knowledge Source. It includes Draft Agent binding count, Published Agent Version count, publication count, frozen snapshot count, retained managed document count, quarantined upload count, ingestion job count, and whether audit retention blocks deletion. Archive confirmation uses it to show impact without blocking Archive, while Physical Deletion eligibility uses it as blockers that must all be clear after the Source is archived.
_Avoid_: Raw Agent YAML dump, full audit log, best-effort warning text, runtime retrieval trace

**Knowledge Configuration Operation Audit**:
The trace-safe configuration history for Knowledge Source and Agent Knowledge Binding administration. It records actor, timestamp, target source or Agent, prior and resulting version identifiers, document intake and replacement actions, retry, Knowledge Source Archive, Knowledge Source Restore, Knowledge Source Physical Deletion eligibility and deletion decisions, Source publication, remote verification, binding changes, retrieval override changes, and explicit source upgrades without storing raw document content, secrets, or complete remote responses. Source lifecycle operations are first-class configuration operations rather than generic updates; Archive and Physical Deletion require a reason or change note, Restore may include one, and Physical Deletion audit must survive removal of the Source's own storage directory.
_Avoid_: Runtime retrieval trace, raw document archive, secret log, unversioned activity feed

**Knowledge Retrieval Runtime Facts**:
The trace-safe retrieval facts recorded in Trace, Governance Receipt, and RunStore: resolved source snapshot or configuration versions, routed sources and local document revisions, provider call status, degraded retrieval, upstream revision observations, WRRF ordering, exact-dedup provenance, evidence admission scores, citations, and context-budget truncation. They exclude raw document content, secrets, and complete remote responses.
_Avoid_: Configuration audit, raw evidence dump, secret log, provider-response archive

**Knowledge Retrieval Plan Summary**:
The trace-safe two-stage retrieval plan record for one run. It includes binding candidates, selected bindings, local document candidates and selected documents when applicable, provider call outcomes, and compact unselected summaries without raw evidence content.
_Avoid_: Raw provider results, complete document metadata dump, receipt-sized trace

**Knowledge Binding Candidate Summary**:
The Knowledge Retrieval Plan Summary entry for one Agent-bound Knowledge Source before source routing. It records source id, alias, tags, lifecycle state, resolved published version, failure mode, and fusion weight.
_Avoid_: Provider credentials, raw source content, full Source Draft

**Selected Knowledge Binding Summary**:
The Knowledge Retrieval Plan Summary entry for one source selected for provider retrieval. It records binding id, source id, selection reason, routing score or ordering when available, failure mode, and whether the binding is required or advisory.
_Avoid_: Hidden source fan-out, unbounded routing trace, raw LLM routing prompt

**Knowledge Provider Call Summary**:
The trace-safe result summary for one provider call: success or failure, latency, candidate count, stable error code when failed, and upstream revision observation when available.
_Avoid_: Complete remote response, raw document content, secret-bearing diagnostics

**Agent Knowledge Binding**:
The Agent-specific configuration that authorizes and parameterizes how a Draft Agent, Published Agent Version, or Package-Local Agent execution may use a Knowledge Source through an Agent Knowledge Source Reference without selecting that source's Knowledge Provider.
_Avoid_: Knowledge Source, Knowledge Provider configuration, global retrieval defaults

**Agent Knowledge Source Reference**:
The explicit target inside one Agent Knowledge Binding that names whether the binding resolves to a Package-Local Knowledge Source or to a published shared Knowledge Source. It removes implicit lookup rules between package execution and Knowledge Hub execution.
_Avoid_: Provider params, Source Draft copy, runtime latest lookup, Structured Remote Source Reference

**Package-Local Knowledge Source**:
The Knowledge Source definition carried in `package_knowledge_sources[]` inside a standalone Agent Package for deterministic demos, local development fixtures, or package-scoped execution outside the Dashboard Configuration Store. It is resolved by the same Knowledge Binding Resolver as shared Sources, but it is not a reusable Knowledge Hub asset and is not published through Knowledge Source Publication.
_Avoid_: Shared Knowledge Source, legacy inline provider config, Dashboard-managed Source Draft

**Knowledge Binding Resolver**:
The composition boundary that turns Agent Knowledge Binding intent plus Agent Knowledge Source References into one Resolved Knowledge Binding Set before governed execution. It resolves Package-Local Knowledge Sources from standalone packages and published shared Knowledge Sources from the Configuration Store, keeping provider parameters out of Dashboard-managed Agent Drafts while preserving standalone Agent Package execution.
_Avoid_: Runtime latest lookup, direct Source Draft provider copy, loader compatibility shim

**Draft Knowledge Binding Resolution**:
The Draft Agent behavior that resolves an unpinned Agent Knowledge Binding to the latest published Knowledge Source snapshot or configuration version while showing the currently resolved version in Dashboard.
_Avoid_: Published Agent drift, unpublished source version, hidden resolution

**Published Knowledge Binding Resolution**:
The immutable Published Agent Version record of each Agent Knowledge Binding's resolved Knowledge Source snapshot or configuration version and resolved binding settings. A later Knowledge Source publication cannot silently change it.
_Avoid_: Latest-at-runtime lookup, mutable Agent version, source publication side effect

**Resolved Knowledge Binding Set**:
The execution-time collection of resolved Agent Knowledge Bindings used by a governed Agent run. For shared Knowledge Sources it includes immutable source snapshot or configuration version references plus resolved binding settings; for Package-Local Knowledge Sources it includes package-scoped provider configuration. Dashboard-managed Draft Agent provider parameters never appear here as mutable Source Draft copies.
_Avoid_: Draft binding intent, latest Source lookup, inline provider configuration, ambiguous source lookup

**Knowledge Binding Upgrade Available**:
The Dashboard-visible condition where a Knowledge Source has a newer published snapshot or configuration version than the one resolved by a Draft Agent or Published Agent Version. Applying the upgrade updates a Draft Agent and requires Agent Validation Run plus Agent Publication for a new Published Agent Version.
_Avoid_: Automatic production upgrade, silent rebinding, validation bypass

**Knowledge Binding Retrieval Override**:
The bounded Agent Knowledge Binding customization for source use: provider retrieval `top_k`, Knowledge Binding Fusion Weight, Knowledge Binding Failure Mode, and Knowledge Source Routing Metadata hints. Missing values inherit the Knowledge Source defaults, and Published Agent Version snapshots capture the resolved values.
_Avoid_: Provider endpoint override, credential override, index or namespace override, ingestion override, admission scorer override

**Knowledge Binding Fusion Weight**:
The Agent Knowledge Binding-specific positive weight used by Weighted Reciprocal Rank Fusion when that binding participates in one Agent's Cross-Source Evidence Fusion. The default is 1.0.
_Avoid_: Knowledge Source global priority, Provider-Native Relevance Score, Evidence Admission Score, zero or negative weight

**Knowledge Binding Failure Mode**:
The Agent Knowledge Binding-specific retrieval failure policy: `required` fails the whole retrieval when the selected binding cannot produce a valid result, while `advisory` permits governed degraded retrieval from other selected bindings. The default is `required`.
_Avoid_: Silent partial retrieval, provider-global failure policy, automatic best effort

**Degraded Knowledge Retrieval**:
A traceable retrieval condition where one or more selected advisory Agent Knowledge Bindings failed, but remaining selected bindings may continue through normal Cross-Source Evidence Fusion and Control Plane evidence admission.
_Avoid_: Silent fallback, Accepted Evidence, successful provider call, bypassing Evidence Threshold

**Agent Knowledge Binding Set**:
The Agent-specific collection of one or more Agent Knowledge Bindings available for governed multi-source retrieval.
_Avoid_: Single provider config, implicit global source list, provider registry

**Knowledge Binding Strategy**:
The governed strategy that determines how an Agent routes across and combines evidence from its Agent Knowledge Binding Set.
_Avoid_: Provider configuration, unbounded multi-source search, implicit fallback, single-source-only retrieval

**Retrieval Intent**:
A ReAct Planner proposal that the current run needs evidence retrieval for a question or rewritten query. It is not permission to select providers, endpoints, snapshots, or credentials; Knowledge Source Routing remains a Control Envelope step.
_Avoid_: Knowledge Source Routing, provider selection, executable retrieval call

**Multi-Source Blended Retrieval**:
The governed retrieval behavior that selects one or more bound Knowledge Sources, retrieves normalized candidate evidence from each selected source, and merges the candidates before Control Plane evidence admission.
_Avoid_: Priority-only fallback, unbounded fan-out, provider-specific merge

**Knowledge Retrieval Service**:
The Control Plane service that executes governed retrieval for Enterprise QA and Controlled ReAct workflows. It owns Knowledge Source Routing, provider call coordination, required or advisory failure handling, cross-source fusion, citation enforcement, evidence admission, and trace-safe retrieval summaries.
_Avoid_: Knowledge Provider Adapter, Runtime graph node, direct provider call, answer generator

**Knowledge Provider Adapter**:
The provider-specific implementation that invokes one local or remote knowledge technology stack for one selected Knowledge Source and converts its retrieval results into normalized Candidate Evidence.
_Avoid_: Knowledge Source, Agent binding, answer model, cross-source fusion, evidence admission

**Candidate Evidence Identity**:
The normalized trace-safe identifier set carried by Candidate Evidence: evidence id, source id, source version id, binding id, provider name, optional document id, optional revision id, optional chunk id, citation, provider-native score, fusion rank, admission score, and allowlisted metadata.
_Avoid_: Raw provider payload, filesystem path, secret-bearing metadata, provider-native id only

**Candidate Evidence Contribution**:
One source-specific contribution retained when Exact Cross-Source Evidence Deduplication merges matching candidates. It records the contributing Knowledge Source, source version, Agent Knowledge Binding, provider, local document or remote chunk identifiers when available, provider-local rank, provider-native score, binding fusion weight, and citation.
_Avoid_: Provenance loss, first-result-only merge, raw provider response

**Cross-Source Evidence Fusion**:
The provider-neutral runtime step that combines normalized Candidate Evidence from selected Knowledge Sources backed by one or more Knowledge Provider Adapters before Control Plane evidence admission.
_Avoid_: Raw provider response concatenation, answer generation, provider-specific merge, unbounded fan-out

**Canonical Evidence Deduplication Key**:
The deterministic tuple of canonical citation or trusted-formatted Structured Remote Source Reference plus normalized content hash used to identify one exactly repeated Candidate Evidence chunk across selected Knowledge Sources.
_Avoid_: Content hash alone, semantic similarity score, provider-native id alone, LLM deduplication

**Exact Cross-Source Evidence Deduplication**:
The V1 Cross-Source Evidence Fusion step that merges Candidate Evidence only when their Canonical Evidence Deduplication Keys match exactly. The merged candidate retains every contributing Knowledge Source, Agent Knowledge Binding, and citation while Weighted Reciprocal Rank Fusion combines their contributions.
_Avoid_: Content-only collapse, semantic deduplication, provenance loss, first-result-wins

**Provider-Native Relevance Score**:
The backend-specific relevance value returned by a Knowledge Provider Adapter for source-local ordering and audit trace. Provider-native scores from heterogeneous adapters are not assumed to be directly comparable.
_Avoid_: Cross-source fusion score, Evidence Threshold, universal confidence score

**Weighted Reciprocal Rank Fusion**:
The V1 Cross-Source Evidence Fusion algorithm that ranks normalized Candidate Evidence by combining each selected Knowledge Source's provider-local result ranks with resolved source weights. It does not compare Provider-Native Relevance Scores across heterogeneous adapters.
_Avoid_: Raw score sorting, Evidence Threshold, evidence admission, LLM reranking

**Cross-Source Fusion Rank**:
The provider-neutral order produced by Weighted Reciprocal Rank Fusion for bounded candidate selection before Control Plane evidence admission.
_Avoid_: Accepted Evidence, Provider-Native Relevance Score, evidence confidence

**Evidence Admission Score**:
The conservative normalized value from 0 through 1 used by the Control Envelope Evidence Threshold to decide whether one Candidate Evidence chunk may become Accepted Evidence. A Knowledge Provider Adapter may provide the value only when it can map its backend semantics reliably; otherwise the candidate requires an approved admission scorer or remains inadmissible.
_Avoid_: Provider-Native Relevance Score, Cross-Source Fusion Rank, universal backend score, missing-value fallback

**Direct Evidence Score Contract Migration**:
The one-time breaking replacement of overloaded `EvidenceChunk.score` with optional `provider_native_score`, fusion-generated `fusion_rank`, and optional `admission_score`. Validator, graph state, Trace, RunStore, Governance Receipt, providers, fixtures, and tests migrate together; no single-provider score alias remains.
_Avoid_: Legacy score alias, raw-score thresholding, mixed score semantics

**Accepted Evidence Context Assembly**:
The post-admission step that prepares only Accepted Evidence, with citations and source attribution, as context for the final-answer LLM.
_Avoid_: Sending raw Candidate Evidence to the LLM, provider response passthrough, retrieval without evidence admission

**Accepted Evidence LLM Context Item**:
The fixed prompt-safe projection of one Accepted Evidence chunk sent to the final-answer LLM. It includes evidence id, source label, citation label, content, confidence band derived from Evidence Admission Score, source type, and context rank. It excludes provider-native score, numeric fusion rank, internal source or version ids, revision ids, raw provider payload, and original file paths.
_Avoid_: Raw Candidate Evidence object, internal citation URI, raw score prompt injection, provider response passthrough

**Accepted Evidence Confidence Band**:
The low, medium, or high qualitative projection of Evidence Admission Score used in Accepted Evidence LLM Context Item. It is prompt guidance only and is not a substitute for Evidence Threshold evaluation.
_Avoid_: Provider-native score, fusion rank, numeric admission score in prompt

**Accepted Evidence Context Chunk Budget**:
The Agent-level limit for how many Accepted Evidence chunks Accepted Evidence Context Assembly may send to the final-answer LLM: default 12 and configurable from 1 through 40.
_Avoid_: Knowledge Source quota, provider retrieval top_k, unlimited context chunks

**Accepted Evidence Context Token Budget**:
The Agent-level approximate token limit for Accepted Evidence Context Assembly: default 6000 and configurable from 500 through 20000.
_Avoid_: Answer token limit, provider retrieval top_k, unlimited evidence context

**Accepted Evidence Context Budget Truncation**:
The traceable outcome where one or more already-admitted candidates remain outside final-answer LLM context because Accepted Evidence Context Assembly reached its chunk or token budget while iterating in Cross-Source Fusion Rank order.
_Avoid_: Evidence rejection, per-source quota, silent truncation, provider failure

**Knowledge Source Routing**:
The Control Envelope query-time selection step that narrows an Agent Knowledge Binding Set to a bounded set of eligible Knowledge Sources before provider-specific retrieval. It is deterministic by default and uses metadata, single-binding shortcuts, and configured routing hints before any optional routing model.
_Avoid_: Knowledge Document Routing, querying every source, implicit global search, ReAct provider selection

**Knowledge Source Routing Metadata**:
The binding and explicitly routing-scoped Source metadata used to select Knowledge Sources for a query, including alias, routing description, routing tags, business domain, and priority hints. General Knowledge Source display or governance metadata does not automatically participate in Source routing.
_Avoid_: Knowledge Source Metadata Configuration, Knowledge Document Routing Metadata, provider secrets, raw evidence content

**Knowledge Source Metadata Configuration**:
The display and governance metadata for a reusable Knowledge Source, such as name, description, and tags used for Dashboard filtering, ownership, and administration. Editing this metadata is audited but does not change the Knowledge Source Draft Version unless the field is explicitly promoted into Knowledge Source Routing Metadata or customer-safe citation projection.
_Avoid_: Knowledge Source Routing Metadata, provider params, publication validation input by default

**Knowledge Source Selection Budget**:
The Agent Knowledge Binding Set routing limit for how many Knowledge Sources may enter provider-specific retrieval for one query: default 3 and configurable from 1 through 8.
_Avoid_: Knowledge Document Selection Budget, Agent Retrieval Strategy top_k, unlimited provider fan-out, source capacity

**Knowledge Provider**:
A capability that retrieves candidate evidence and returns normalized evidence chunks.
_Avoid_: Answer engine, agent runtime

**Knowledge Provider Registry**:
The capability registry that resolves the named Knowledge Provider owned by a Knowledge Source.
_Avoid_: Agent-selected provider, hard-coded retriever selection

**Knowledge Hub V1 Provider Set**:
The target set of Knowledge Provider families supported by Knowledge Hub V1: Local Markdown Provider for deterministic development fixtures, Local Index Provider for production local indexed knowledge, and trusted remote adapters such as HTTP JSON Knowledge Provider. Historical PageIndex and Local Vector providers are outside this set.
_Avoid_: Legacy provider registry, experimental adapter list, provider compatibility mode

**Knowledge Source Provider Configuration**:
The Source-owned provider family and provider-specific parameter set declared as `provider + params` in the Knowledge Source configuration contract. The public contract stays provider-neutral, while backend validation, Dashboard forms, and documentation are provider-specific for `local_markdown`, `local_index`, and `http_json`; ordinary Agent Knowledge Bindings never copy or edit these provider parameters.
_Avoid_: Strongly typed public provider union, Agent-owned provider params, raw unvalidated params editor

**Knowledge Provider Adapter Descriptor**:
The trusted registry entry that declares one Knowledge Provider Adapter's name, configuration schema, Dashboard form metadata, and supported capabilities.
_Avoid_: Arbitrary uploaded script, provider secret storage, Agent Knowledge Binding, runtime result

**Knowledge Provider Capability**:
A declared adapter behavior used for configuration validation and orchestration planning, including `retrieve`, `health_check`, `snapshot_pin`, and `admission_score`.
_Avoid_: Prompt instruction, implicit SDK behavior, unvalidated runtime assumption

**HTTP JSON Knowledge Provider**:
The trusted generic remote Knowledge Provider Adapter that invokes a configured HTTP retrieval endpoint and normalizes either the default Remote Retrieval Protocol or a validated declarative response mapping into Candidate Evidence.
_Avoid_: Arbitrary remote code execution, vendor SDK passthrough, raw response injection

**Remote Retrieval Protocol**:
The default versioned HTTP JSON request and response shape supported by the HTTP JSON Knowledge Provider without custom mapping. It accepts bounded retrieval inputs such as `query`, `top_k`, and optional `upstream_revision`, and returns candidate items with content plus either citation or a structured source reference.
_Avoid_: Provider-native response passthrough, unversioned implicit shape, executable transform

**Remote Retrieval Request Mapping**:
The versioned, declarative HTTP JSON Knowledge Provider configuration that projects the bounded retrieval inputs `query`, `top_k`, and optional `upstream_revision` as whole-value placeholders into an allowed HTTP method, headers, query parameters, and JSON body. Secret-bearing headers reference environment variables only.
_Avoid_: String interpolation, dynamic URL path, arbitrary template variables, loops, conditions, functions, network callbacks, script execution, raw secret value

**Remote Retrieval Response Mapping**:
The versioned, declarative HTTP JSON Knowledge Provider configuration that uses JSON Pointer paths to project a non-standard remote response into normalized Candidate Evidence fields, Structured Remote Source Reference fields, and optional Remote Knowledge Revision Observation values.
_Avoid_: JSONPath wildcard, filter, recursive query, arbitrary script, code execution, unvalidated JSON passthrough, Evidence Admission bypass

**Remote Retrieval Response Mapping Verification**:
The fail-closed validation step that resolves a Remote Retrieval Response Mapping against a health-check sample response, requires an array result pointer, and requires normalized content plus either citation or a structurally complete Structured Remote Source Reference that Trusted Citation Formatting can convert into citation for every admitted candidate shape.
_Avoid_: Runtime-only discovery, best-effort field omission, raw response passthrough

**Structured Remote Source Reference**:
The normalized, trace-safe citation basis assembled from allowlisted remote result fields such as document id, page, and chunk id when the upstream result lacks one complete citation field. An HTTP JSON Knowledge Provider response mapping may project these fields under `source_ref`; it may not expose the raw provider payload as citation data.
_Avoid_: Arbitrary citation template, raw provider payload, missing source attribution

**Trusted Citation Formatting**:
The adapter-owned deterministic formatting rule that converts a Structured Remote Source Reference into an Evidence Citation. Dashboard administrators may select supported source-reference fields but may not author arbitrary citation templates.
_Avoid_: Operator-authored string template, LLM citation generation, citation-free evidence admission

**Local Markdown Provider**:
A Knowledge Provider that retrieves evidence from local Markdown files.
_Avoid_: Local provider

**Local Vector Provider**:
A historical local vector-index adapter removed from the Knowledge Hub V1 target architecture. New local production knowledge should use Local Index Provider, while deterministic development fixtures should use Local Markdown Provider.
_Avoid_: Local Index Provider, Knowledge Hub V1 provider, vector build lifecycle

**Remote Knowledge Provider**:
A Knowledge Provider that retrieves evidence from an external knowledge service or remote index.
_Avoid_: Remote Agentic RAG

**Remote Knowledge Source Configuration Version**:
The immutable Proof Agent-managed version of a Remote Knowledge Source's adapter selection, provider parameters, and environment-variable credential references.
_Avoid_: Upstream corpus revision, raw credential storage, mutable draft connection

**Pinned Remote Knowledge Source**:
A Remote Knowledge Source whose adapter supports `snapshot_pin` and whose published configuration records an immutable upstream corpus revision for retrieval and replay.
_Avoid_: Local Knowledge Source Snapshot, mutable external source, observed revision only

**Mutable External Knowledge Source**:
A Remote Knowledge Source whose upstream technology stack cannot pin an immutable corpus revision. It may be bound and queried, but exact historical replay is not guaranteed.
_Avoid_: Pinned Remote Knowledge Source, immutable snapshot, silent replay guarantee

**Remote Knowledge Revision Observation**:
The trace-safe upstream revision, etag, or observation timestamp returned or recorded for one Remote Knowledge Source retrieval attempt.
_Avoid_: Proof Agent-managed configuration version, immutable revision guarantee, raw provider response

**Remote Knowledge Source Verification**:
The pre-publication adapter health check that validates a Remote Knowledge Source's connectivity, authentication, target index or namespace, and response normalization against its immutable configuration version.
_Avoid_: Agent Validation Run, runtime retrieval attempt, unchecked connection save, secret persistence

**Stale Remote Knowledge Source Verification**:
The visible condition where a previously successful Remote Knowledge Source Verification has exceeded its validity window. It warns operators and blocks new publication or rebinding until refreshed, but does not immediately interrupt already-published Agent execution.
_Avoid_: Runtime hard stop, silent expiration, healthy verification, mutable external revision change

**Remote Search Provider**:
A Remote Knowledge Provider that retrieves normalized evidence from a remote search service.
_Avoid_: Remote provider, remote vector provider, vendor-named provider

**PageIndex Provider**:
A historical remote retrieval endpoint integration removed from the target architecture by ADR-0015. Existing references are migration context only; new Knowledge Sources must use `local_index` for local indexed knowledge or a remote adapter such as `http_json` for remote retrieval.
_Avoid_: Current remote provider, Local Index Provider, remote Knowledge Hub default

**Local Index Provider**:
A Knowledge Provider that retrieves candidate evidence from locally persisted tree indexes built by LlamaIndex TreeIndex. Supports structured retrieval interfaces (`list_structure()`, `retrieve_at_scope()`) in addition to standard `retrieve()`. Uses ProofAgentLLM bridge to route all LLM calls through Proof Agent's ModelProvider protocol for unified governance.
_Avoid_: PageIndex Provider, Local Vector Provider, final answer generator, remote retrieval service

**RetrievalPlanner**:
An orchestrator component that drives a multi-round agentic retrieval loop inside one governed retrieval execution. It may rewrite retrieval queries and assess evidence sufficiency, but it does not select Knowledge Sources, call tools, generate final answers, or alter the outer Controlled ReAct Workflow route.
_Avoid_: ReAct planner, final answer model, source router, tool calling loop

**RetrievalCapabilities**:
A data contract that declares what structured retrieval operations a KnowledgeProvider supports. Fields: `supports_structure_listing`, `supports_scoped_retrieval`. Planner uses capabilities flags (not isinstance) to dispatch structured vs basic retrieval.
_Avoid_: runtime type checking, isinstance protocol, adapter descriptor

**StructuredKnowledgeProvider**:
A Protocol extension of KnowledgeProvider that adds `list_structure()` and `retrieve_at_scope()` methods. Implemented by Local Index Provider. Other providers implement only the base KnowledgeProvider protocol.
_Avoid_: KnowledgeProvider base protocol, runtime_checkable decorator

**ProofAgentLLM**:
A bridge adapter that extends LlamaIndex's CustomLLM base class. Routes all LLM calls from LlamaIndex TreeIndex operations (ingestion node summaries, tree traversal routing) through Proof Agent's ModelProvider protocol. Implements sync interfaces (complete, chat) and explicitly disables async (acomplete, achat). Ensures unified trace, policy gates, and token estimation for all LLM usage.
_Avoid_: direct LlamaIndex LLM usage, async LLM calls, bypass governance

**RetrievalAction**:
A frozen dataclass representing the Planner's structured decision after each retrieval round. V1 supports three action types: `rewrite` (generate new query and continue), `sufficient` (evidence adequate, stop), `abort` (evidence inadequate, stop). Trace records action decisions for audit.
_Avoid_: unstructured text output, implicit continuation, tool calling

**DocumentNode**:
A frozen dataclass returned by `list_structure()` representing a node in the document tree. Contains node_id, title, summary, depth, child_ids, and metadata (tags, document_type, business_category). Enables Planner to reason about document structure before scoped retrieval.
_Avoid_: raw tree traversal, full document content, internal storage paths

**max_rounds**:
A RetrievalConfig field (default 3) that caps the RetrievalPlanner's iterative retrieval loop. Independent from `react.max_actions` (which governs ReAct Action Proposals). Hard limit ensures bounded LLM cost and execution time.
_Avoid_: max_actions, infinite loop, unbounded retrieval

**Nested ReAct Retrieval Loop**:
The allowed composition where one Controlled ReAct retrieval action invokes `retrieval.strategy: agentic` and therefore contains an inner RetrievalPlanner loop. The outer ReAct Action Budget and inner `max_rounds` budget are independent and both remain enforced.
_Avoid_: Single shared loop counter, RetrievalPlanner-controlled ReAct routing, unbounded nested planning

**Local Index Snapshot Retrieval**:
The bounded retrieval behavior that routes a query to eligible Knowledge Document revisions in one resolved snapshot, searches the selected revisions via LlamaIndex TreeIndex tree traversal, merges normalized candidate evidence, and fails closed if any selected document search fails.
_Avoid_: Unbounded corpus scan, silent partial retrieval, cross-source search

**Local Index Runtime Load**:
The runtime behavior that opens the published READY local index artifacts referenced by a resolved Knowledge Source Snapshot. It never creates or rebuilds indexes during an Agent run.
_Avoid_: Runtime index build, on-demand ingestion, mutable source folder scan

**Knowledge Document Routing**:
The query-time selection step that narrows a resolved Knowledge Source Snapshot to a bounded set of Knowledge Document revisions before document-level retrieval.
_Avoid_: Searching every document, implicit folder scan, cross-source retrieval

**Knowledge Document Routing Metadata**:
The operator-managed and ingestion-derived title, description, tags, document type, and business category used to filter and select Knowledge Documents before document-level retrieval. Dashboard and API edits are routing-only: they advance the Knowledge Source Draft token and candidate snapshot digest without triggering reingestion or rebuilding revision artifacts.
_Avoid_: Evidence content, raw credentials, unreviewable hidden profile

**Knowledge Document Selection Budget**:
The Knowledge Source routing limit for how many document revisions may enter document-level tree index search for one query: default 8 and configurable from 1 through 20.
_Avoid_: Agent Retrieval Strategy top_k, unlimited fallback expansion, source document capacity

**Index-Backed Knowledge Source**:
A reusable Knowledge Source whose uploaded documents are transformed into locally persisted LlamaIndex TreeIndex tree indexes through the `local_index` provider.
_Avoid_: Agent-scoped upload, retrieval result, raw document folder

**Knowledge Source Document Capacity**:
The maximum number of Knowledge Documents retained by one Knowledge Source; V1 targets up to 500 documents per source.
_Avoid_: Selected document count per query, unlimited corpus size, Agent binding count

**Knowledge Source Document Capacity Reservation**:
The temporary Source-capacity slot held by one queued or processing Quarantined Knowledge Upload before promotion. Staging checks and reserves capacity atomically with the local queue lock; accepted promotion hands the slot to its managed Knowledge Document, while rejection releases it immediately even though quarantined bytes remain under Rejected Knowledge Upload Retention.
_Avoid_: Pending-upload capacity bypass, rejected-upload slot retention, non-atomic concurrent staging

**Atomic Knowledge Document Batch Upload**:
The Dashboard-managed intake operation that stages one through 50 files for one `local_index` Knowledge Source through a single batch request. It validates every request envelope, reserves Source document capacity for the full batch under the queue lock, publishes quarantine records as one visible batch, and then lets each Quarantined Knowledge Upload proceed independently through asynchronous validation and ingestion.
_Avoid_: Frontend loop over single-file upload, partial-capacity staging, synchronous batch indexing, batch-wide ingestion state

**Knowledge Document**:
An operator-managed file that belongs to exactly one Knowledge Source and has its own ingestion status and provider-backed index artifact.
_Avoid_: Knowledge Source, customer attachment, evidence chunk

**Knowledge Document Revision**:
An immutable uploaded-file version under one stable Knowledge Document identity. Explicit file replacement creates a new revision id, while prior revisions remain available to retained Knowledge Source Snapshots and Published Agent Versions until eligible for cleanup.
_Avoid_: In-place file overwrite, filename identity, mutable index artifact

**Knowledge Document Content Hash Reuse**:
The idempotent Knowledge Source Ingestion behavior that reuses an existing provider-backed index artifact when an uploaded Knowledge Document revision has the same content hash and compatible ingestion configuration as an existing revision.
_Avoid_: Filename-based overwrite, duplicate index build, cross-configuration artifact reuse

**Knowledge Revision Artifact Reference**:
The linkage from one READY Knowledge Document Revision to one compatible reusable local index artifact identified by content hash plus Knowledge Ingestion Configuration Fingerprint. It preserves revision provenance without duplicating artifact bytes or making a reusable artifact revision-owned.
_Avoid_: Revision-owned artifact copy, mutable latest artifact, revision identity inside reusable artifact metadata

**Atomic Knowledge Artifact Publication**:
The concurrency-safe local-index artifact build behavior for one content hash plus Knowledge Ingestion Configuration Fingerprint key. A worker validates the cache, acquires the artifact-key advisory lock on miss, validates again, builds only inside a sibling temporary directory carrying artifact-key and creation metadata, writes the reusable artifact sidecar last, and atomically renames the complete directory into its final path. Other workers may reuse only a fully validated published artifact. Housekeeping may remove an old temporary directory only while holding the corresponding artifact-key lock non-blockingly, so it cannot delete an active build.
_Avoid_: Duplicate compatible build, partial artifact read, direct final-directory write, revision-owned cache lock, age-only temporary cleanup

**Local Knowledge Worker File Lock Boundary**:
The foundation-slice local-filesystem synchronization boundary implemented with `filelock.FileLock`. Store transitions acquire `{store_root}/.locks/store.lock` with a 5-second timeout and fail the current operation with `PA_INGESTION_004` without attempting another state write when unavailable. Artifact builds acquire `{store_root}/.locks/artifacts/{sha256(artifact_key)}.lock` non-blockingly; contention defers the token-owned job for 5 seconds without counting a build failure. Housekeeping uses the same non-blocking artifact-key attempt. Lock files live outside atomically renamed artifact directories, and temporary artifact directories remain sibling paths on the same filesystem as their final directories. Shared NFS and distributed synchronization belong to a later queue adapter.
_Avoid_: Lock inside renamed artifact directory, infinite store-lock wait, age-only cleanup, distributed-filesystem assumption

**Knowledge Document Ingestion State**:
The independent lifecycle state of one Knowledge Document revision during Knowledge Source Ingestion: `QUEUED`, `PROCESSING`, `READY`, or `FAILED`. A failed document may be retried, replaced, or archived without discarding other READY document revisions.
_Avoid_: Knowledge Source Index State, Knowledge Ingestion Job status, silent omission

**Knowledge Document Archive**:
The reversible lifecycle state that removes a Knowledge Document from candidate snapshots while preserving referenced revisions and index artifacts.
_Avoid_: Physical deletion, immediate active-snapshot mutation, hard purge

**Unreferenced Knowledge Artifact Cleanup**:
The audited physical deletion of Knowledge Document revisions and index artifacts that are not referenced by any retained Knowledge Source Snapshot or Published Agent Version.
_Avoid_: Archive action, active revision deletion, rollback-breaking purge

**Knowledge Source Snapshot**:
An immutable READY view of indexed Knowledge Document revisions. It may be frozen for preview and routing-smoke development or formally published for Agent Knowledge Bindings; only a Published Knowledge Source Snapshot is production-bindable.
_Avoid_: Mutable upload folder, Draft Agent version, partial rebuild, implicitly bindable frozen snapshot

**Knowledge Source Snapshot Manifest**:
The immutable manifest for one READY local-index Knowledge Source Snapshot. It records trace-safe document and revision identities, routing metadata, and references to reusable Knowledge Revision Artifacts without copying artifact directories or rebuilding indexes during snapshot freeze or publication.
_Avoid_: Snapshot-owned artifact copy, merged publication index, mutable artifact path list, runtime folder scan

**Frozen Knowledge Source Snapshot**:
An immutable development-stage READY Knowledge Source Snapshot created from a foundation-validated Candidate Knowledge Source Snapshot. It may support preview and routing-smoke development through the Source's latest snapshot pointer, but it is not production-bindable and cannot become a Resolved Knowledge Snapshot Binding until full Knowledge Source Publication Validation succeeds.
_Avoid_: Published Knowledge Source Snapshot, production-bindable snapshot, implicit Source publication, mutable candidate projection

**Published Knowledge Source Snapshot**:
A fully validated immutable READY Knowledge Source Snapshot selected by the Source's production-bindable published snapshot pointer through explicit Knowledge Source Publication. Agent Knowledge Bindings may resolve it, while later Source publications do not silently mutate bindings already captured by Published Agent Versions.
_Avoid_: Frozen Knowledge Source Snapshot, latest snapshot pointer, mutable Source Draft, automatic binding upgrade

**Candidate Knowledge Source Snapshot**:
The derived mutable Source Draft projection of READY Knowledge Document revisions eligible for snapshot freeze and later Knowledge Source Publication. It is calculated from managed document state rather than persisted as a second mutable record, excludes `QUEUED`, `PROCESSING`, `FAILED`, and archived revisions while Dashboard explicitly lists those exclusions, and freezes into an immutable Frozen Knowledge Source Snapshot only after foundation validation.
_Avoid_: Persisted candidate.json mirror, immutable candidate version per worker transition, silent partial snapshot, active snapshot mutation, failed document inclusion, empty publication

**Knowledge Source Draft Version**:
The change-token identity of one editable Knowledge Source Draft state used to bind Knowledge Source Publication Validation. It changes when source provider configuration, remote retrieval mapping, publication-bound Source routing metadata, document routing metadata, or candidate-snapshot membership changes, but not for general Knowledge Source Metadata Configuration, lifecycle toggles such as Archive and Restore, worker leases, retry counters, or rejected uploads that do not alter the publication candidate. Archive and Restore are Knowledge Configuration Operation Audit events and bindability guards, not Source Draft Version changes.
_Avoid_: Published snapshot id, immutable draft history, lifecycle state, display metadata version, worker-attempt id, candidate hash only

**Knowledge Source Publication**:
The explicit operator action that promotes a fully validated immutable READY Knowledge Source Snapshot into a Published Knowledge Source Snapshot selected by the Source's production-bindable published snapshot pointer for use by Agent Knowledge Bindings.
_Avoid_: Foundation snapshot freeze, automatic activation, document upload, Agent Publication

**Resolved Knowledge Snapshot Binding**:
The immutable Knowledge Source Snapshot reference captured for one Agent Knowledge Binding when a Published Agent Version is created.
_Avoid_: Latest snapshot lookup, mutable source pointer, Draft Agent preview

**Knowledge Source Ingestion**:
The design-time lifecycle that accepts operator-managed documents and creates or refreshes a provider-backed Knowledge Source index.
_Avoid_: Retrieval Step, customer attachment analysis, Agent Knowledge Binding

**Operator Knowledge Document Intake**:
The Dashboard design-time upload boundary for text-based PDF and Markdown Knowledge Documents managed by internal operators.
_Avoid_: Text-Only Customer Intake, OCR pipeline, arbitrary attachment upload

**Knowledge Ingestion Job**:
A persisted asynchronous unit of Knowledge Source Ingestion work with QUEUED, RUNNING, SUCCEEDED, FAILED, or CANCELLED status.
_Avoid_: HTTP request lifetime, in-memory callback, Harness run

**Knowledge Ingestion Worker**:
The replaceable worker process that claims persisted Knowledge Ingestion Jobs and builds provider-backed index artifacts outside Dashboard API request handling.
_Avoid_: Dashboard API background callback, Run Execution API worker, production queue requirement

**Knowledge Source Index State**:
The bindability state of an ingested Knowledge Source: `PENDING` when it has no published snapshot and ingestion is outstanding, `READY` when it has a bindable published snapshot even if Draft document revisions are processing or failed, or `FAILED` when it has no bindable snapshot and operator action is required.
_Avoid_: Run outcome, retrieval result, silent best effort

**Remote Search Fixture Adapter**:
A first-stage Remote Search Provider implementation that normalizes fixture data instead of performing network calls.
_Avoid_: Production remote search integration

**Knowledge First Stage**:
The implementation stage that makes the new Knowledge contract executable for single-step retrieval while reserving Agentic RAG contracts.
_Avoid_: Complete Agentic RAG implementation

**Retrieval Capability Error**:
An error that indicates a recognized Retrieval Strategy is not executable in the current build.
_Avoid_: Configuration shape error

**Agentic RAG**:
A controlled retrieval workflow that may plan, rewrite, rerank, or perform multiple retrieval steps before answer generation.
_Avoid_: Knowledge provider

**Planner Model**:
A model used by Agentic RAG to produce retrieval plans or query candidates.
_Avoid_: Answer model

**Retrieval Strategy**:
The Agent Contract policy for how retrieval is orchestrated before evidence admission.
_Avoid_: Knowledge provider params

**Evidence Threshold**:
The Retrieval Strategy requirement for how many candidate chunks and what minimum Evidence Admission Score can become Accepted Evidence.
_Avoid_: Provider setting

**Retrieval Plan Gate**:
The policy enforcement point that decides whether Agentic RAG may create or use a retrieval plan.
_Avoid_: Generic retrieval gate

**Retrieval Step Gate**:
The policy enforcement point that decides whether a specific retrieval step may run.
_Avoid_: Generic retrieval gate

**Retrieval Step**:
A workflow step that executes one governed retrieval attempt through a Knowledge Provider.
_Avoid_: KnowledgeProvider.retrieve

**Retrieval Plan Event**:
A trace event that records a controlled summary of an Agentic RAG retrieval plan.
_Avoid_: Raw planner payload

**Retrieval Step Event**:
A trace event that records a governed retrieval attempt before its result is evaluated.
_Avoid_: Provider debug log

**Single-Step Retrieval Fallback**:
An explicit Retrieval Strategy option that downgrades Agentic RAG to one governed retrieval attempt after planner or step failure.
_Avoid_: Silent fallback

**Evidence Chunk**:
A retrieved source fragment that can support, or fail to support, a final answer.
_Avoid_: Context blob, prompt context

**Candidate Evidence**:
An Evidence Chunk returned by a Knowledge Provider before Control Plane admission.
_Avoid_: Accepted evidence

**Accepted Evidence**:
An Evidence Chunk admitted by Control Plane evidence evaluation.
_Avoid_: Retrieved evidence

**Evidence Citation**:
A trace-safe reference that identifies where an Evidence Chunk came from.
_Avoid_: Citation text embedded in content

**Evidence Metadata**:
Trace-safe supplemental facts about an Evidence Chunk.
_Avoid_: Raw SDK response, secret-bearing metadata

**Evidence Summary**:
An audit-safe representation of evidence source, citation, Provider-Native Relevance Score, Cross-Source Fusion Rank, Evidence Admission Score, and admission status without raw content.
_Avoid_: Evidence content dump
