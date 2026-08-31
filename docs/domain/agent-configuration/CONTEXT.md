# Agent Configuration

Agent Configuration contains the language for Agent Contract authoring, Draft Agents, publication, validation, and effective runtime configuration.

## Language

**Agent Contract Capability Configuration**:
The unified public Agent Contract YAML `capabilities:` structure that declares governed capability domains, including tools, memory, and future skills, before Agent Publication resolves Workflow Stage Availability.
_Avoid_: Internal-only capability profile, scattered top-level capability toggles, per-stage enable switches

**Agent Contract Skills Capability Configuration**:
The `capabilities.skills` Agent Contract section that declares Business Flow Skill Pack Bindings and other future Skill Pack bindings as governed capabilities rather than Workflow Template topology.
_Avoid_: workflow.skills, workflow.stages skill entries, top-level skills, runtime skill discovery

**Direct Capability Contract Migration**:
The breaking Agent Contract migration that replaces top-level `tools` and `memory` capability declarations with top-level `capabilities:` in one cutover.
_Avoid_: Dual-read capability fields, silent legacy migration, split capability source of truth

**Disabled Capability Configuration**:
A Draft Agent's retained active configuration fields under a capability domain whose `enabled` flag is false; it is inactive, visible as a validation blocker, and excluded from Published Agent Version snapshots unless the capability is restored.
_Avoid_: Dormant tool file, dormant memory provider, hidden future reactivation

**Explicit Capability Enablement**:
The required `enabled: true|false` declaration for every Workflow Template-relevant capability domain under Agent Contract YAML `capabilities:`.
_Avoid_: Missing means disabled, implicit default, Dashboard-inferred capability state

**Enabled Capability Readiness**:
The validation condition that an enabled capability domain has the active configuration required to provide at least one governed capability instance to Workflow Template Execution.
_Avoid_: Enabled empty shell, prompt-only capability, deferred runtime discovery

**Effective Workflow Stage Configuration**:
The neutral resolved per-stage configuration value for available Workflow Template Stages, produced from Workflow Template Descriptor defaults, Workflow Stage Availability, Effective Workflow Stage Context Option Allowlist, and Agent Contract overrides.
_Avoid_: Raw override only, disabled-stage config archive, latest descriptor lookup, runtime graph state

**Effective Workflow Stage Configuration Stage**:
A typed entry inside Effective Workflow Stage Configuration for one available Workflow Template Stage, with a stable stage identity and bounded prompt, context, descriptor, and source-override facts.
_Avoid_: Arbitrary stage dictionary, unavailable-stage placeholder, runtime graph node payload

**Published Effective Workflow Stage Configuration Snapshot**:
The immutable full Effective Workflow Stage Configuration value captured inside a Published Agent Version alongside the Workflow Stage Configuration Override entries and Workflow Template Descriptor Version.
_Avoid_: Recompute from latest descriptor, run-only projection, override-only publication record

**Published Effective Workflow Stage Configuration Runtime Input**:
The run-scoped Effective Workflow Stage Configuration value and trace-safe reference metadata copied from a Published Effective Workflow Stage Configuration Snapshot for Workflow Template Execution.
_Avoid_: Latest descriptor reconstruction, raw manifest stage config, Dashboard-only explanation snapshot

**Package-Local Workflow Stage Configuration Runtime Input**:
The run-scoped Effective Workflow Stage Configuration for package-local or configured Agent execution, built from the latest Agent Contract YAML structure and current Workflow Template Descriptor without Published Agent Version snapshot semantics.
_Avoid_: Legacy Agent Contract compatibility path, Published Effective Workflow Stage Configuration Snapshot, historical replay guarantee

**Resolved Workflow Stage Runtime Configuration**:
The Control Plane resolver output that groups Workflow Stage Availability, Effective Workflow Stage Configuration, Workflow Stage Configuration Runtime Source, trace-safe configuration summary, and template-specific planner action admission facts for one run or publication.
_Avoid_: Harness dependency composition, Published Agent Version storage record, Runtime Plane graph state

**Unavailable Stage Configuration**:
A Draft Agent's retained configuration for a Workflow Template Stage that is currently unavailable because its required capability is disabled; it is inactive, visible as a validation blocker, and excluded from Published Agent Version snapshots unless the capability is restored.
_Avoid_: Silently ignored stage config, hidden future reactivation, published disabled-stage config

**Direct Workflow Stage Contract Migration**:
The breaking Agent Contract migration that adopts `workflow.stages[]` directly in one cutover and rejects legacy public stage aliases.
_Avoid_: Dual-read workflow stage fields, node/stage aliasing, hidden legacy stage config

**Published Effective Workflow Stage Configuration Runtime Consumption Slice**:
The implementation slice that makes run-start Workflow Template Execution consume resolved Workflow Stage Availability and Effective Workflow Stage Configuration facts instead of raw Agent Contract stage overrides, while preserving static Runtime Adapter topology.
_Avoid_: Validation full-capture rewrite, historical descriptor registry, second runtime implementation, dynamic runtime graph generation

**Harness Invocation**:
A resolved execution request that combines an Agent Contract, selected Workflow Template, and governed capabilities for one run.
_Avoid_: Raw manifest, SDK runtime state

**Run Execution API**:
A Delivery entry point that starts a governed Harness run from an application surface such as the Assisted QA Chat Frontend.
_Avoid_: Dashboard read API, direct model endpoint

**Agent Configuration API**:
The configuration boundary for Draft Agents, reusable configuration assets, validation, publication, rollback, import, and export.
_Avoid_: Dashboard read API, production run execution API, arbitrary manifest runner

**Agent Configuration Workspace Module**:
The Control-owned application module that presents one stable interface for Agent configuration lifecycle use cases and keeps scope, concurrency, audit, and lifecycle rules out of Delivery and persistence adapters.
_Avoid_: Router-owned workflow, Local store facade, production-only configuration service

**Agent Lifecycle Persistence Seam**:
The focused `ConfigurationUnitOfWork` and `AgentLifecycleRepository` boundary used by the Agent Configuration Workspace Module for revisioned Draft, Published Version, active pointer, and audit persistence without exposing Local or PostgreSQL mechanics.
_Avoid_: Concrete store import in Delivery, filesystem path contract, database session in Control

**Agent Configuration Validation Executor**:
An injected adapter that compiles and executes one Draft Agent and returns trace-safe validation evidence; the Agent Configuration Workspace Module remains responsible for revision CAS, Validation Record creation, lifecycle audit, and publication separation.
_Avoid_: Route-owned Harness orchestration, executor-owned Draft overwrite, validation means publication

**Agent Configuration Publication Validator**:
An injected adapter that checks package materialization and live local-asset publication constraints without writing a Published Agent Version, changing the Active Agent Version, or appending lifecycle audit; the Agent Configuration Workspace Module remains the ordinary Draft publication authority.
_Avoid_: Validator-owned activation, Delivery-owned publication transaction, formal production Phase F publisher

**Draft Agent**:
An editable Agent configuration version inside the Agent Configuration Workspace that may be saved, validated, and test-run before publication.
_Avoid_: Published Agent, arbitrary runtime manifest, unvalidated production Agent

**Draft KSS Release Binding Candidate**:
The secret-free authoring intent stored on one Draft Agent that identifies one exact KSS Knowledge Space, Knowledge Base, Knowledge Base Version, and queryable Knowledge Base Release. It is validated against the live KSS catalog when saved but is not executable and does not change the Active Agent Version.
_Avoid_: Resolved Knowledge Source Service Binding, manifest knowledge binding, mutable latest release pointer, runtime activation

**Production KSS Binding Profile**:
Deployment-owned configuration that supplies the binding identity, versioned KSS client credential reference, ProofAgent Admission Scorer identity and revision, and required failure mode. Phase F combines it with an exact Draft KSS Release Binding Candidate only after live revalidation.
_Avoid_: Draft secret, Dashboard-editable credential, Agent Contract field, KSS catalog authority

[KNOWN | HIGH] TDD-05A adds this as a strict, immutable server-side contract. It
rejects undeclared Release identity, non-Knowledge credentials and unversioned secret
handles. It is not Dashboard configuration and does not make a Draft executable.

**Formal Production Agent Candidate**:
The exact input to formal production Agent publication, rooted in one named Draft Agent revision and completed by a deployment-owned Production KSS Binding Profile plus candidate-bound release evidence before activation.
_Avoid_: Independent manifest candidate, mutable latest Draft, Dashboard-ready state, environment-selected Release

[KNOWN | HIGH] TDD-05A adds a read-only Control assembler and immutable candidate
contract containing the exact Agent/Draft/revision, reviewable Contract Bundle,
Draft-owned KSS tuple, live catalog revision, resolved binding and two distinct
digests. TDD-05B adds Control-owned integrity revalidation and consumes this object
for candidate-bound Phase F preparation. TDD-05F adds a new application-only formal
publisher core that consumes it. TDD-05H adds the durable public command, and TDD-05I
makes the production API its only composition root while removing the old manifest
production entry.

**Formal Production Agent Phase F Record**:
An immutable record that binds Shadow, Capacity, Acceptance and Recovery evidence to
one exact Formal Production Agent Candidate digest and its Knowledge Release digest,
then requires an independent Phase F authority decision.
_Avoid_: Generic release evidence detached from the Draft root, mutable evidence set,
Phase F means publication

**Provisional Production Agent Version**:
The candidate-bound output of successful Phase F preparation. It retains the exact
Draft revision, resolved KSS binding, Phase F Record and effective Workflow Stage
configuration, and uses preparation metadata rather than publication metadata.
_Avoid_: Published Agent Version, Active Agent Version, executable latest candidate

[KNOWN | HIGH] TDD-05B creates both strict contracts without persistence side effects.
It does not register a KSS Reference, run online smoke, write a Published Version or
change the Active Agent Version.

**Formal Production Agent Reference Staging**:
The Reference-first Control result that retains one exact Phase F preparation and the
matching active KSS Release Reference for the future Published Agent Version identity.
It proves registration ordering only; it is not executable and does not grant
publication or activation authority.
_Avoid_: Published Agent Version, Active Agent Version, compensating Reference delete,
best-effort registration

[KNOWN | HIGH] TDD-05C adds this strict contract and an injected registrar port. The
Phase F Record also binds the provisional version and validation run identities before
the cross-service call. TDD-05D adds the concrete, dedicated HTTPS guarded registrar;
it preserves the Control-owned key and exact request, rejects redirects and response
drift, and maps the authenticated KSS wire receipt into this contract. The current
formal publisher core consumes this staging through TDD-05F; TDD-05I supplies its
dedicated versioned Reference service-client credential in production composition.

**Formal Production Agent Query Grant Staging**:
The Control result created after exact Reference registration and before formal online
smoke. It retains the validated Reference staging and one strict active KSS Query Grant
receipt whose Release and Knowledge Space match the Formal Candidate. It proves the
runtime client received policy-bounded query authority; it does not publish or activate
the Agent.
_Avoid_: caller-selected Grant policy, Reference-only smoke input, Grant means Active
Agent, compensating revoke without authority

[KNOWN | HIGH] TDD-05M adds this strict contract and Control stager. The only
provisioning request field is the Candidate's exact Release. KSS continues to own
client, Space derivation, strategies, budget and scope policy. Receipt failure or drift
stops before online smoke and final storage. A successful Grant remains durable if a
later step fails; selective revocation and reconciliation remain separate work.

**Formal Production Agent Online Smoke Qualification**:
The application-only Control result produced after exact Query Grant staging. Its
strict `v2` contract retains that staging, a Control-derived smoke request, and a
matching validator result with a governed citation outcome plus distinct exact trace
and receipt artifacts. It is evidence for a later publication attempt, not a Published
or Active Agent Version.
_Avoid_: smoke passed means published, caller-selected latest Release, best-effort
identity match, compensating Reference delete

[KNOWN | HIGH] TDD-05E adds this strict contract and a single online validator port.
The service has no Agent Store, Active pointer, audit writer or KSS deregistrar. A
failed or uncertain smoke therefore returns a stable rejection, leaves the registered
Reference in KSS, and cannot publish or activate an Agent. TDD-05F consumes only a
successful qualification. TDD-05G supplies the concrete governed execution runner;
environment-backed live KSS/model validation remains subsequent work.

[KNOWN | HIGH] TDD-05M removes the Reference-staging-only smoke input. Both Control
and the concrete runner now require the Query Grant staging and revalidate its nested
Candidate, Reference and Grant identities before governed execution.

**Formal Production Agent Online Smoke Runner**:
The Delivery adapter that receives one Control-derived strict smoke request together
with its exact validated Query Grant staging, revalidates their immutable identities,
executes the provisional Agent package through the governed validation path, and
returns exact outcome, cited-evidence count, Trace and Receipt artifact references.
_Avoid_: caller-reported pass, mutable candidate lookup, Production run, publisher or
activation authority

[KNOWN | HIGH] TDD-05G implements this boundary. The provisional Contract Bundle is
materialized into a private read-only temporary package with safe relative paths;
execution uses `RunPurpose.VALIDATION`, the exact validation run identity, frozen KSS
and Workflow Stage facts, and injected Institution Authorization. Trace/Receipt are
bounded and exact-read-back retained. Control, not the runner, owns the cited-answer
Gate.

**Formal Production Agent Publication Evidence**:
The strict immutable envelope retained by one Published Agent Version that binds its
exact source Draft revision, approved Phase F Record, active KSS Release Reference
receipt and exact online smoke result to the same version, validation run and Release.
_Avoid_: detached checklist, caller-reported smoke, latest Release lookup, mixed-run
evidence

**Formal Production Agent Publisher Core**:
The application-only orchestrator that captures the current Active pointer expectation
before external Reference, Query Grant and smoke calls, then atomically enforces Draft
revision and Active pointer CAS while persisting the immutable Published Version,
activation and publication audit in one Configuration UoW.
_Avoid_: transaction held over network calls, best-effort activation, compensating KSS
Reference delete, public command without durable idempotency

[KNOWN | HIGH] TDD-05F implements both boundaries. Concurrent Draft or Active change
and audit/storage failure roll back all final Version/activation/audit state, while an
already registered KSS Reference remains for trusted reconciliation. TDD-05G provides
the concrete online runner; TDD-05H adds a persisted-idempotency public command whose
success receipt shares the final transaction. TDD-05I requires that command in
production API composition and removes the old manifest production CLI/composition.
Environment-backed live upstream proof and stuck-command recovery remain absent.

**Formal Production Agent Publication Command**:
The permission-protected, actor-scoped and durably idempotent server command that binds
one exact Agent/Draft/revision request to the Formal Publisher Core and returns a
stable in-progress, succeeded or failed receipt. Production exposes it only through
the API composition root and requires all exact external and persistence dependencies
at startup.
_Avoid_: independent manifest CLI, caller-supplied Binding Profile, in-memory retry,
optional production command dependency

**Agent Knowledge Release Catalog Projection**:
A trace-safe, read-only Agent Configuration Workspace projection of KSS readiness and exact Release identities used to author or review a Draft KSS Release Binding Candidate.
_Avoid_: Copied KSS authority, cached executable binding, source-management API, local Knowledge catalog

**Agent Configuration Store**:
The configuration-system store for Draft Agents, version history, validation results, publication metadata, and reviewable contract snapshots.
_Avoid_: RunStore, Conversation Store, arbitrary local filesystem path

**Local Agent Configuration Store**:
The development-and-test Agent Configuration Store implementation using local directories and JSON/contract files while preserving a replaceable store boundary.
_Avoid_: Production Transactional State Store, router-owned file layout, hidden in-memory drafts

**Agent Package Import**:
The migration path that converts an existing reviewable Agent Package into a Draft Agent while preserving its contract files and unsupported advanced fields.
_Avoid_: Direct production overwrite, arbitrary manifest execution, lossy UI conversion

**Example Agent Template**:
A static reviewable Agent Package used as a starting point for import, validation, documentation, demos, or tests before publication.
_Avoid_: Published Agent, production Agent, execution allowlist

**Published Agent Version**:
An immutable published snapshot of an Agent Contract or Agent Package, including resolved stage availability and effective stage configuration, that application-facing execution surfaces can resolve by stable Agent identity and version.
_Avoid_: Mutable draft, latest filesystem path, frontend-selected manifest

**Active Agent Version**:
The Published Agent Version currently selected for default application-facing execution for a stable Agent identity.
_Avoid_: Latest draft, mutable production config, frontend-selected version

**Agent Version Rollback**:
The governed operation that changes a Published Agent's Active Agent Version back to an earlier immutable Published Agent Version.
_Avoid_: Editing old versions, deleting publication history, restoring a draft as production

**Published Agent**:
An approved Agent configuration version exposed to application surfaces through a stable agent identifier after validation and publication.
_Avoid_: Draft Agent, arbitrary manifest path, uploaded config

**Published Agent Runtime Facts**:
The internal execution-only facts resolved with a Published Agent, including immutable Published Agent Version identity, resolved Knowledge Binding facts, Workflow Stage Availability, and Published Effective Workflow Stage Configuration Runtime Input.
_Avoid_: Published Agent Directory Entry, customer-safe metadata, mutable Draft Agent fields

**Published Agent Chat Access**:
The ability for chat surfaces to create conversations against a Published Agent by stable Agent identity while preserving audience-specific execution APIs and response projections.
_Avoid_: Frontend manifest selection, one shared chat permission model, draft chat access

**Published Agent Directory**:
An application-facing discovery projection that lists Published Agents available to a chat audience without exposing manifest paths or Draft Agent state.
_Avoid_: Agent Configuration API, frontend allowlist, manifest browser

**Published Agent Directory Entry**:
The chat-safe metadata snapshot for one Published Agent, including stable Agent identity, display name, purpose, active version identity, and customer-facing availability.
_Avoid_: Draft Agent summary, manifest path, validation run detail

**Direct Agent Chat Entry**:
A chat entry path that starts or prepares a conversation for a Published Agent from a stable Agent identity without requiring selection from the Published Agent Directory first.
_Avoid_: Manifest URL, draft preview link, frontend-only agent id

**Agent Publication**:
The governed transition that promotes a validated Draft Agent into a Published Agent Version available to Run Execution API or Customer Run API callers.
_Avoid_: Save draft, direct run, frontend-only enablement

**Knowledge Release Record**:
[FRAME | HIGH] The immutable candidate-bound authority required for every knowledge-enabled Published Agent Version containing a Resolved Knowledge Source Service Binding; it binds the exact Draft Contract Bundle and Resolved Knowledge Binding Set to distinct Shadow, Capacity, Sealed Acceptance, and Recovery artifact references and is frozen into the published version.
_Avoid_: Release checklist, mutable latest report, CI status, request-supplied approval, artifact directory

**Knowledge Release Evidence Authority**:
[FRAME | HIGH] The independently configured deployment authority that verifies all four exact Knowledge Release Record artifact references before the Configuration Store may register the record.
_Avoid_: Request boolean, record self-attestation, Configuration Store inference, CI badge, operator checklist

**Agent Validation Run**:
A pre-publication governed run or validation pass that checks a Draft Agent's contract, retrieval behavior, workflow behavior, policy decisions, and receipt preview.
_Avoid_: Production run, frontend preview only, unchecked smoke test

**Run Purpose**:
The run metadata classification that distinguishes production, validation, and preview runs while keeping all governed runs in RunStore.
_Avoid_: Separate preview log, hidden test execution, metric-only tag

**Local Configuration Store Reset**:
The development-environment cleanup action that clears generated local Agent Configuration Store state, including Draft Agents, Published Agent Versions, Knowledge Sources, local-index artifacts, snapshots, and compiled configuration packages, without deleting source-controlled examples, tests, documentation, or retained run audit history. Breaking Knowledge Source or Agent Contract configuration changes, including stage/capability contract cutovers, do not carry a legacy local-store compatibility path; stale generated local Configuration Store data is reset and rebuilt.
_Avoid_: Source migration, production data deletion, RunStore audit purge, fixture cleanup, legacy local-store dual-read

**Workflow Stage Configuration Override**:
An Agent Contract entry that overrides editable fields for a Workflow Template Stage while leaving omitted stages on descriptor defaults.
_Avoid_: Runtime node definition, graph rewrite
