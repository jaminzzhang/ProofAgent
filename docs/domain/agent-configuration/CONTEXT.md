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

**Draft Agent**:
An editable Agent configuration version inside the Agent Configuration Workspace that may be saved, validated, and test-run before publication.
_Avoid_: Published Agent, arbitrary runtime manifest, unvalidated production Agent

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
[FRAME | HIGH] The immutable candidate-bound authority required for every Published Agent Version containing a Resolved Hybrid Knowledge Binding; it binds the exact Draft Contract Bundle and Resolved Knowledge Binding Set to distinct Shadow, Capacity, Sealed Acceptance, and Recovery artifact references and is frozen into the published version.
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
