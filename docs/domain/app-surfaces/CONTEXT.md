# Application Surfaces

Application Surfaces contains the language for Dashboard, Unified Chat, Knowledge Hub UI, list pagination, approval queue filters, and navigation terminology.

## Language

**Dashboard-Managed MCP Tool Source**:
A reusable Shared Asset Library Tool Source for an MCP server, administered through Dashboard configuration and bound to Agents through Agent Tool Bindings.
_Avoid_: Package-local fixture, inline Agent-owned production connection, unvalidated shared MCP endpoint

**Dashboard Stage Configuration Surface Cutover**:
The Slice 1 rename of Dashboard and Agent Configuration API public surfaces to workflow stage language, including request and response fields, helper names, UI labels, fixtures, and tests.
_Avoid_: Backend-only schema migration, node-labeled inspector, mixed nodes/stages API payload

**Models Workspace**:
The Dashboard configuration workspace for administering Shared Model Connections as reusable model access assets.
_Avoid_: Provider model catalog, Agent Model module, runtime model endpoint

**Dashboard Model Configuration**:
The Dashboard configuration workspace may directly configure Model Role Configuration values for final answers, ReAct planning, and Harness review, including named Model Providers such as DeepSeek. Dashboard editing still writes Agent Contract fields and must preserve the same secret, validation, and Harness-normalization boundaries as YAML editing.
_Avoid_: Dashboard-only model semantics, provider credential storage, bypassing Agent Contract validation

**Dashboard DeepSeek Model Selection**:
Dashboard DeepSeek configuration uses provider selection plus editable model names with recommended current DeepSeek model values, not a hard model-name allowlist. API keys remain environment variable references, not stored credentials.
_Avoid_: Fixed DeepSeek model dropdown, frontend-only provider inventory, storing DeepSeek API keys

**Dashboard Unified Model Strategy**:
A Dashboard UI shortcut that applies the same Primary Model settings to all three roles (Answer, Planner, Reviewer) simultaneously without introducing a single global model field in the Agent Contract.
_Avoid_: Single global Agent model, hidden model reuse

**Dashboard Model Parameter Editing**:
Dashboard Model Configuration may edit shared Model Role Configuration parameters such as API key environment variable, base URL environment variable, temperature, maximum output tokens, and timeout for final answer, planner, and reviewer roles. It must not expose raw credential fields or provider-specific reasoning controls in V1.
_Avoid_: raw API key input, provider secret storage, DeepSeek-only reasoning parameter passthrough

**Run Detail Approval Action**:
The first Approval Console action surface embedded in a Run Detail view. It resolves a single run's pending approval through Approval Checkpoint Resume and refreshes that run projection after approve or deny; it is not a global approval queue.
_Avoid_: Frontend-scanned approval queue, separate follow-up run, page reload as state management

**Global Approval Queue Projection**:
An operator-facing Dashboard API projection and `/approvals` triage page that lists unresolved PendingApproval items across runs for approval work triage. Its primary object is the pending approval request, enriched with run metadata for navigation; it is not a filtered Run list, stats payload, or approval execution surface. The first version sorts by `created_at` descending, returns parameter keys and count rather than raw parameters, marks expired items without writing trace, paginates with `limit` and `offset`, and navigates to Run Detail Approval Action for approve or deny.
_Avoid_: Frontend-scanned run history, stats-expanded queue, run summary as approval command object, direct approve or deny from the queue page

**Assisted QA Chat Frontend**:
An operator-facing chat surface for submitting enterprise QA questions and reviewing governed answer suggestions, evidence, approval state, and audit links.
_Avoid_: Direct customer chatbot, observability dashboard

**Unified Chat Frontend**:
A shared browser chat surface that presents consistent design and conversation flow for operator and customer chat modes while preserving audience-specific response projections.
_Avoid_: Merged internal/customer permissions, customer-visible audit console

**Internal Governance Dashboard**:
The internal observability surface for inspecting governed runs, traces, receipts, stats, and escalation handoff records.
_Avoid_: Customer Service Chat Frontend, customer response UI, full admin console

**Dashboard Shell**:
The shared internal web workspace that hosts both observability views and Agent configuration views while preserving separate API boundaries for observation, configuration, and execution.
_Avoid_: Single backend API surface, customer-facing console, ungoverned execution UI

**Agent-Centric Dashboard Shell**:
A Dashboard Shell information architecture where each Agent detail view combines monitoring, configuration, validation, versioning, and contract inspection for that Agent.
_Avoid_: Settings-only configuration, detached builder app, global-only run dashboard

**Dashboard Workflow Lens**:
The shared Dashboard information pattern for understanding Workflow Template Stage configuration, validation behavior, and run execution facts in their proper contexts without creating a mixed top-level Workflow workspace.
_Avoid_: Standalone workflow builder, merged configuration-and-monitoring page, editable runtime graph surface

**Dashboard Workflow Run Projection**:
The Run Detail read projection that organizes trace-safe Workflow Template Execution facts by Workflow Template Stage for Dashboard Workflow Lens, while leaving raw trace events, receipts, evidence, model usage, and approvals available as drilldown artifacts.
_Avoid_: Frontend-parsed JSONL stage view, ReAct-only governance tab, runtime state projection

**Agent Detail Page**:
The Agent-focused Focus Mode page opened from the Agents workspace for one Draft Agent, occupying the browser window with Agent-local navigation and the selected Agent sub-area.
_Avoid_: Detached builder app, second global Dashboard shell, compressed Dashboard content panel, draft-only form page

**Agent Overview**:
The default Agent Detail Page sub-area that summarises Agent identity, draft/version state, and compact monitoring signals before deeper configuration or lifecycle work.
_Avoid_: General tab, full Monitor view, configuration-only landing state

**Agent Configuration Workspace**:
A Dashboard-hosted configuration surface for drafting, validating, testing, and publishing Agent Contracts, Workflow Template settings, Knowledge Provider settings, Tool Contracts, policy, memory, and response disclosure settings.
_Avoid_: Dashboard API execution path, direct arbitrary manifest execution, prompt-only Agent setup

**Agent Configuration MVP**:
The first implementation scope that proves the import, Draft Agent edit, validation, publication, monitoring, versioning, and rollback loop before deep editing for every configuration module.
_Avoid_: Full no-code platform, complete RBAC product, all-module deep editor

**Agent Configuration Permission Model**:
The Operator Permission Vocabulary slice for Agent Configuration API boundaries. `agent.view` gates Agent configuration reads and Workflow Template descriptors; `agent.edit` gates Agent import, Draft Agent edits, Contract View updates, workflow stage updates, and Agent Knowledge Binding attach or detach; `agent.validate` gates Draft Agent validation runs and Workflow Stage Context Preview; `agent.publish` gates publish and rollback. Agent Configuration command requests do not carry actor fields; Configuration Operation Audit records the Operator Identity Context resolved by the API.
_Avoid_: Full tenant RBAC, frontend-only permission check, request-body actor, untracked local edits

**Configuration Operation Audit**:
The audit metadata that records who created, changed, validated, published, or rolled back Agent configuration.
_Avoid_: Run trace, Governance Receipt, invisible config mutation

**Contract View**:
An advanced Agent Configuration Workspace view that shows and optionally edits the Agent Contract and related policy/tool contract files compiled from the same Draft Agent state.
_Avoid_: Separate configuration source, export-only YAML, hidden runtime config

**Agent Creation Wizard**:
A guided first-time setup flow that helps an Agent owner create a Draft Agent by selecting purpose, Workflow Template, Knowledge Provider, governed capabilities, and validation path.
_Avoid_: Runtime graph editor, production publish action, generic settings page

**Agent Configuration Module**:
One of the eight editable sub-features in the Agent Configuration Workspace: General, Workflow, Knowledge, Tools, Policy, Model, Memory, and Response. Each module owns a focused set of Agent Contract fields and uses a hybrid forms plus code editor.
_Avoid_: Agent Lifecycle Tab, free-form settings page, monolithic configuration form

**Dashboard Memory Configuration Module**:
The Agent Configuration Module for configuring an Agent's memory storage, Memory Scope eligibility, and memory-recall context budget policy without creating a separate top-level Context workspace. It distinguishes retained memory records from admitted Working Context and keeps final-answer evidence authority with Knowledge or authorized Tool results.
_Avoid_: Dashboard Context module, memory as evidence, prompt-only memory toggle

**Agent Lifecycle Tab**:
One of the four operational tabs in the Agent detail view: Validate & Test, Versions, Contract View, and Monitor. Lifecycle tabs operate on the Draft Agent or Published Agent Version rather than editing configuration fields.
_Avoid_: Agent Configuration Module, inline publishing action, detached monitoring dashboard

**Configuration Module Editor**:
The hybrid forms plus code editing interface for each Agent Configuration Module. Forms expose common settings; a YAML toggle reveals the underlying Agent Contract fragment for advanced editing. Both representations compile back into the same Draft Agent state.
_Avoid_: Raw YAML only, drag-drop canvas, natural-language policy editor

**Validation Workspace**:
The Validate & Test interface combining quick test, test suite, and validation history. Users craft test questions, run validation, inspect governed run results, compare multiple validation runs, and decide whether a Draft Agent is ready for publication.
_Avoid_: Single-shot test runner, detached monitoring view, production run execution

**Shared Asset Library**:
The reusable asset collections for Knowledge Sources, Tool Sources, and Policy Rule Configurations that multiple Agents can bind to. Agents reference shared assets through Agent Knowledge Bindings, Agent Tool Bindings, and Policy Rule Configuration rather than duplicating definitions.
_Avoid_: Agent-scoped asset definition, inline-only configuration, duplicated policy rules

**Knowledge Hub**:
The product-facing name for the Shared Asset Library capabilities that administer reusable Knowledge Sources and their Agent Knowledge Bindings. It is a configuration and governance surface, not a separate Agent runtime or evidence-admission path.
_Avoid_: Knowledge Provider, retrieval engine, ungoverned RAG layer, second execution path

**Knowledge Source Workspace**:
The global Dashboard Shared Asset Library surface at `/knowledge` for listing, creating, filtering, and administering reusable Knowledge Sources across Agents. It evolves the existing Knowledge page rather than adding a parallel `/knowledge-sources` route.
_Avoid_: Agent-only YAML browser, `/knowledge-sources` route, inline document manager inside one Agent

**Knowledge Source Detail Workspace**:
The Dashboard detail surface at `/knowledge/:sourceId` for administering one reusable Knowledge Source through Overview, Documents, Versions, Provider, and Audit tabs. Agent Knowledge modules link to this surface instead of embedding full document management.
_Avoid_: Agent-embedded file manager, Source detail modal, provider-only settings page

**Knowledge Source Workspace List Projection**:
The operational list projection at `/knowledge` that shows Source name, description, tags, provider type, lifecycle state, local index or remote verification availability, current published snapshot or configuration version, local READY and total document counts or remote target index or namespace, referencing Agent count, and warning indicators for unpublished changes, failed ingestion, or stale remote verification. It supports filtering by name, tag, provider, lifecycle, and warning state.
_Avoid_: Agent YAML excerpt list, provider-only inventory, unfilterable asset table

**Knowledge Source Creation Wizard**:
The `/knowledge` guided Source Draft setup flow that first selects one of three source-intake paths: upload local documents into `local_index`, connect remote knowledge through `http_json` or another registered remote adapter, or register an existing local `local_markdown` source for development, migration, and deterministic demos. The wizard creates or updates a Source Draft; validation and explicit Knowledge Source Publication remain separate steps.
_Avoid_: Automatic Source publication, Agent-scoped upload, provider-free setup, remote-only wizard

**Knowledge Source Documents Tab**:
The `local_index` Knowledge Source Detail Workspace tab for operating up to 500 Knowledge Documents. It supports batch PDF and Markdown upload, filtering and pagination, revision-state visibility, single-document replacement, failed-revision retry, routing-metadata editing, archive, revision history, bulk failed-revision retry, bulk archive, bulk tag editing, and a persistent Candidate Knowledge Source Snapshot summary with an explicit Publish Source action.
_Avoid_: Unpaginated file dump, filename-only status, implicit publication, one-document-only upload

**Remote Knowledge Source Provider Tab**:
The layered Provider tab for a remote Knowledge Source. Its default form exposes adapter, endpoint, environment-variable credential references, index or namespace, timeout, and default `top_k`. Its advanced section exposes protocol version, Remote Retrieval Request Mapping, Remote Retrieval Response Mapping, and Structured Remote Source Reference mapping only when the selected adapter supports them. Typed remote adapters prefer descriptor-driven forms, while `http_json` exposes bounded mapping editors.
_Avoid_: Raw JSON-only setup, arbitrary script editor, one-size-fits-all adapter form

**Remote Knowledge Source Connection Test**:
The non-publishing Provider-tab action that validates remote connectivity, authentication, target index or namespace existence, and configured response normalization shape.
_Avoid_: Knowledge Source Publication, production retrieval, best-effort save

**Remote Knowledge Source Retrieval Preview**:
The non-publishing Provider-tab action that runs a bounded example query and shows normalized Candidate Evidence, citations, Provider-Native Relevance Scores, and Remote Knowledge Revision Observations without making the Source bindable.
_Avoid_: Raw remote response dump, Agent Validation Run, implicit Source publication

**Local Index Provider Tab**:
The layered Provider tab for a `local_index` Knowledge Source. Its default form exposes ingestion model provider, model, environment-variable credential references, inherited Knowledge Routing Model Configuration, and Knowledge Document Selection Budget defaulting to 8. Its advanced section exposes an explicit routing-model override, timeout, retry count, and worker concurrency. Documents and routing metadata remain in Knowledge Source Documents Tab.
_Avoid_: File list inside provider settings, Agent answer model reuse, raw credential storage, flat advanced form

**Local Index Model Configuration Test**:
The non-ingesting Provider-tab action that validates local index ingestion and routing model configuration plus referenced credential availability without rebuilding document indexes.
_Avoid_: Knowledge Source Ingestion, Source publication, full-corpus rebuild

**Knowledge Source Versions Tab**:
The Knowledge Source Detail Workspace history surface for published snapshots or configuration versions. It shows publication time, actor, `change_note`, validation result, referencing Agent count, and version diff actions.
_Avoid_: Mutable current-state-only view, hidden validation history, Agent version list

**Sidebar Navigation Section**:
The two top-level sections in the Dashboard Shell sidebar: MONITORING for observability views (Overview, Runs, Handoffs, Approvals) and CONFIGURATION for design-time views (Agents, Policies, Knowledge Sources, Tools). Each section groups related navigation items under a visible header.
_Avoid_: Flat navigation list, mixed monitoring and configuration items, role-based sections

**Internal Handoff Monitor**:
The V1 dashboard projection for reviewing Customer Escalation Handoff records and drilling into their governed run details.
_Avoid_: Ticket workflow, SLA queue, assignment console

**Agent Control Platform Console**:
A future administrative console for RBAC, tenant management, multi-Agent configuration, approval operations, and platform governance.
_Avoid_: Internal Governance Dashboard, Customer Service Web Chat

**Customer Service Chat Frontend**:
The customer-facing chat mode with customer-safe response and citation projection.
_Avoid_: Operator console, internal support tool

**Page**:
The 1-based index of the currently displayed slice of list results.
_Avoid_: Backend offset, browser route

**Page Size**:
The number of rows rendered per Page in a paginated Dashboard list.
_Avoid_: Total count, result offset

**Offset**:
The zero-based count of results skipped before the current Page begins in a paginated Dashboard list.
_Avoid_: Page number, total count

**Last Page**:
The highest valid Page for a result set at the current Page Size.
_Avoid_: Empty-state page, backend offset

**Approval Status (view filter)**:
A Dashboard Approval Queue filter that scopes rows as pending, expired, or all without changing the approval lifecycle state.
_Avoid_: PendingApproval lifecycle state

**Pending (queue view)**:
An Approval Queue row whose `expires_at` has not passed while no ApprovalDecision has been recorded.
_Avoid_: PendingApproval lifecycle state

**Expired (queue view)**:
An Approval Queue row whose `expires_at` has passed while no ApprovalDecision has been recorded.
_Avoid_: Resolved approval, default triage view
