# Proof Agent

Proof Agent is a Controlled Agent Harness Framework for enterprise Agent delivery. Its domain language centers on governed execution, evidence-backed answers, tool approval, and auditability.

## Language

> **ADR-0015 Terminology Update**: Per [ADR-0015](docs/adr/0015-agentic-rag-with-retrieval-planner-and-local-tree-index.md), the remote `pageindex` provider is removed from the target architecture and `local_pageindex` is renamed to `local_index` (Local Index Provider) with LlamaIndex TreeIndex as the underlying engine. Key terms: **RetrievalPlanner**, **RetrievalCapabilities**, **ProofAgentLLM**, **DocumentNode**, **RetrievalAction**, **max_rounds**. `PageIndex` appears only as historical migration terminology.

**Controlled Agent Harness Framework**:
The product category for Proof Agent: a framework that governs Agent execution through an explicit Control Envelope.
_Avoid_: Harness Agent framework, Agent wrapper

**Agent Framework Deliverable**:
The reusable Proof Agent framework surface shipped alongside reference Agents, including contracts, Workflow Templates, policy, tools, memory, trace, receipt, APIs, examples, and documentation.
_Avoid_: Single chatbot app, one-off customer-service implementation

**Control Envelope**:
The enterprise control shell around an Agent run.
_Avoid_: Wrapper, guardrail layer

**Agent Contract**:
The public configuration contract that declares an Agent's purpose, workflow, knowledge, model, policy, tools, memory, and audit behavior.
_Avoid_: Internal config, runtime config

**Agent Contract Capability Configuration**:
The unified public Agent Contract YAML `capabilities:` structure that declares governed capability domains, including tools and memory, before Agent Publication resolves Workflow Stage Availability.
_Avoid_: Internal-only capability profile, scattered top-level capability toggles, per-stage enable switches

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

**Agent Package**:
A reviewable delivery artifact containing an Agent Contract plus its policy, tools, knowledge references, fixtures, and domain adapters.
_Avoid_: Database-only Agent, uploaded manifest path, loose config bundle

**Tool Contract**:
The public capability contract that declares a governed tool's purpose, risk level, read/write class, authorization conditions, parameter bounds, and audit behavior.
_Avoid_: Runtime adapter, provider-native tool schema, prompt instruction

**Tool Source**:
A reusable tool connection or local tool package that can expose one or more governed Tool Contracts.
_Avoid_: Tool Contract, Agent Tool Binding, direct model function

**Tool Source Permission Model**:
The Operator Permission Vocabulary slice for reusable tool assets. `tool_source.view` gates Tool Source descriptors and Source reads. `tool_source.edit` gates Tool Source creation and update. `tool_source.archive` gates Archive and Restore. Tool Source API command requests do not carry actor fields; the API resolves Operator Identity Context server-side before calling the configuration store, and Tool Source create, update, archive, and restore operations write Configuration Operation Audit with the resolved operator.
_Avoid_: One tool admin boolean, Agent edit permission reuse, request-body actor

**Tool Source Descriptor**:
The Dashboard-managed plugin-like contract that describes a reusable Tool Source's provider type, configuration schema, credential references, available Tool Contracts, validation behavior, and binding options.
_Avoid_: Ad hoc tool form, hardcoded Dashboard tool config, executable plugin script

**Agent Tool Binding**:
The Agent-specific configuration that enables selected Tool Contracts and constrains their proposal scope, approval behavior, call budget, and authorization conditions.
_Avoid_: Tool Source, ungoverned tool list, provider-native tool call

**Local Tool Handler**:
An Agent-package-owned Python callable referenced from `tools.yaml` for deterministic local demos or fixtures behind Tool Gateway.
_Avoid_: Framework-owned business tool registry, ungoverned function call

**Untrusted Web Search Tool**:
A governed Tool Gateway capability that searches the public web to provide realtime external context outside the controlled Knowledge Source boundary.
_Avoid_: Web Knowledge Source, remote_search provider, uncontrolled browser plugin

**Untrusted Web Context**:
The non-controlled external context returned by the Untrusted Web Search Tool, explicitly marked as untrusted and kept distinct from Evidence admitted from Knowledge Sources; it cannot establish a governed answered outcome.
_Avoid_: Accepted Evidence, Candidate Evidence, Knowledge, citation-backed source

**Untrusted Web Supplement**:
The fixed customer-visible response section that presents Untrusted Web Context with an explicit warning that it is not verified by controlled Knowledge Sources.
_Avoid_: Sources list, citation section, controlled answer, verified supplement

**Web Search Query Sanitization**:
The deterministic Harness step that rewrites a proposed web search query by replacing sensitive values with safe placeholders before the Untrusted Web Search Tool can receive it.
_Avoid_: LLM query rewrite, best-effort masking, user-trust-based redaction

**Search Vendor Adapter**:
A replaceable provider implementation behind the Untrusted Web Search Tool that normalizes one public search vendor's response into Untrusted Web Context.
_Avoid_: Knowledge Provider, browser automation, scraping plugin, Search Vendor as Agent capability

**Workflow Template**:
A reusable governed flow shape for a class of Agents, such as enterprise question answering.
_Avoid_: One-off orchestrator branch, runtime graph

**Workflow Template Execution**:
The governed execution of one selected Workflow Template during a run, including Control Envelope stage semantics without owning Runtime Plane mechanics.
_Avoid_: Runtime graph execution, template-specific node class, orchestrator branch

**Workflow Template Execution Result**:
The typed governed facts produced by one Workflow Template Execution, including completion, terminal outcome, approval pause, clarification need, evidence basis, and safe response facts.
_Avoid_: Runtime state dict, LangGraph final state, Dashboard projection

**Workflow Template Execution Input**:
The typed run-scoped input for Workflow Template Execution, including the selected template identity, Agent Contract facts, optional Published Agent Version references, conversation context, Effective Workflow Stage Configuration value, and trace-safe configuration source metadata.
_Avoid_: Raw manifest path, latest descriptor lookup, Runtime Plane graph state

**Approval Pause**:
The trace-safe Workflow Template Execution fact that a governed run is waiting for an operator approval decision before a proposed tool action can continue.
_Avoid_: LangGraph interrupt, approval UI state, direct tool execution permission

**Clarification Need**:
The trace-safe Workflow Template Execution fact that a governed run is waiting for the user to provide missing information before the workflow can continue.
_Avoid_: Approval pause, generic waiting state, final refusal

**React Enterprise QA Template Execution Boundary**:
The behavior-preserving Slice 2 boundary that introduces a typed Workflow Template Execution interface around React Enterprise QA while keeping Runtime Plane graph scheduling internal.
_Avoid_: Runtime graph rewrite, stage logic rewrite, Published snapshot runtime cutover

**ReAct Enterprise QA Workflow Execution**:
The concrete Control Plane execution object for React Enterprise QA and React Enterprise QA V2 that returns Workflow Stage Result Envelopes while leaving Runtime Plane scheduling mechanics to adapters.
_Avoid_: Generic ReAct workflow execution, Runtime Plane graph builder, template descriptor

**Workflow Stage Result**:
The typed Control Envelope facts produced by one Workflow Template Stage for use inside a Workflow Template Execution.
_Avoid_: Arbitrary state fragment, public runtime graph node output, loose dict mutation

**Workflow Stage Result Envelope**:
The Slice 2 typed envelope for Workflow Stage Result values, carrying stage id, stage status, optional terminal outcome, trace-safe summary, and produced governed fact references while deferring per-stage result union design.
_Avoid_: Raw runtime state dict, complete per-stage union, untyped stage output

**Workflow Stage Continuation State**:
The internal state carried by a Workflow Stage Result Envelope so a Runtime Plane adapter can schedule the next step, route branches, checkpoint, or resume without treating runtime state as governed execution facts.
_Avoid_: Workflow Stage Result Summary, public execution result, Dashboard projection, trace payload

**Workflow Execution Contract Module**:
The public contracts module for Workflow Template Execution facts, including execution results, stage result envelopes, approval pause, clarification need, and runtime-continuation boundaries.
_Avoid_: Run artifact contract module, ReAct-only contract module, Runtime Plane state schema

**Workflow Stage Configuration Contract Module**:
The neutral contract home for Workflow Stage Availability Set, Effective Workflow Stage Configuration, and Workflow Stage Configuration Runtime Source facts shared by Agent Publication and Workflow Template Execution.
_Avoid_: Published-Agent-only contract module, Runtime Plane state schema, Dashboard projection contract

**Workflow Stage Result Runtime Adapter**:
The thin Runtime Plane adapter that converts a Workflow Stage Result plus internal continuation state into the state update shape required by a scheduler such as LangGraph.
_Avoid_: Control Plane fact source, public execution result, stage business logic owner

**Workflow Runtime Adapter**:
The Runtime Plane implementation that schedules a Workflow Template Execution with a concrete runtime while translating runtime-neutral Workflow Template Execution facts into runtime-specific graph, checkpoint, interrupt, or resume mechanics.
_Avoid_: Control Plane semantic owner, Workflow Template Descriptor, Agent Contract interpreter

**Workflow Stage Result Summary**:
The trace-safe summary inside a Workflow Stage Result Envelope, limited to governed fact names, statuses, counts, lengths, ids, decision enums, and redaction metadata.
_Avoid_: Raw prompt text, raw selected context, raw evidence content, raw tool payload, complete provider response, Runtime Plane state dict

**Workflow Stage Availability**:
The resolved enabled or disabled status of a Workflow Template Stage for one Agent Contract, derived from template support and configured capabilities rather than arbitrary topology editing.
_Avoid_: Free-form stage disabling, runtime graph editing, hidden branch flag

**Workflow Stage Availability Rule**:
The backend-owned rule on a Workflow Template Stage that declares whether the stage is always available or requires a named Agent capability domain.
_Avoid_: Stage id convention, Agent-owner enable switch, runtime graph mutation

**Workflow Stage Availability Set**:
The typed resolved Workflow Stage Availability for every registered stage, frozen into the Published Agent Version at publication and copied into each run before Workflow Template Execution starts.
_Avoid_: Per-stage ad hoc availability checks, mutable runtime flags, Dashboard-only enabled state

**Workflow Template Stage**:
A registered governed stage within a Workflow Template, visible in configuration, Dashboard explanation, trace summaries, and Published Agent interpretation.
_Avoid_: Workflow node, LangGraph node, arbitrary runtime step

**React Enterprise QA Stage Set**:
The governed Workflow Template Stages for React Enterprise QA: plan, clarification, retrieval_review, retrieval, model_answer, tool_review, tool, memory, and response; V2 adds intent_resolution before plan.
_Avoid_: LangGraph node list, every policy check, every helper function

**Tool Stage Group**:
The paired tool_review and tool Workflow Template Stages that are enabled together only when the Agent Contract exposes governed tool capability.
_Avoid_: Tool stage without review, review stage without tool, provider-native tool execution

**Workflow Template Descriptor**:
The backend-owned, read-only description of a registered Workflow Template's stages, stage availability rules, branch relationships, governed handoff points, editable Prompt fields, and allowed context options used by Dashboard to render Workflow Relationship Map and Workflow Stage Panel.
_Avoid_: Frontend-hardcoded workflow graph, Agent-authored node registry, runtime graph source of truth

**Workflow Template Descriptor Version**:
The immutable version identifier for the Workflow Template Descriptor used to validate, render, publish, and later explain a Published Agent Version's Workflow Stage Prompt Configuration.
_Avoid_: Latest template lookup for historical runs, mutable Dashboard graph version, frontend descriptor version

**Workflow Template Stage Configuration**:
The editable `workflow.stages[]` per-stage settings exposed by a registered Workflow Template while preserving the template's governed stage types, ordering constraints, and Control Envelope semantics.
_Avoid_: Free-form runtime graph editing, arbitrary node creation, prompt-defined workflow

**Workflow Stage Configuration Override**:
An entry in Agent Contract `workflow.stages[]` that records only explicit Agent-owner overrides for one Workflow Template Stage.
_Avoid_: Full copied descriptor stage config, empty stage placeholder, hidden topology edit

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

**Workflow Stage Configuration Runtime Source**:
The trace-safe category that identifies whether a run's Effective Workflow Stage Configuration came from a Published Agent Version snapshot or from package-local latest Agent Contract resolution.
_Avoid_: Raw manifest path, Dashboard tab state, storage lookup mechanism

**Resolved Workflow Stage Runtime Configuration**:
The Control Plane resolver output that groups Workflow Stage Availability, Effective Workflow Stage Configuration, Workflow Stage Configuration Runtime Source, trace-safe configuration summary, and template-specific planner action admission facts for one run or publication.
_Avoid_: Harness dependency composition, Published Agent Version storage record, Runtime Plane graph state

**Workflow Stage Configuration Identifier**:
The required `id` field on each `workflow.stages[]` item that references one registered Workflow Template Stage.
_Avoid_: legacy id aliases, display label, runtime graph node id

**Unavailable Stage Configuration**:
A Draft Agent's retained configuration for a Workflow Template Stage that is currently unavailable because its required capability is disabled; it is inactive, visible as a validation blocker, and excluded from Published Agent Version snapshots unless the capability is restored.
_Avoid_: Silently ignored stage config, hidden future reactivation, published disabled-stage config

**Direct Workflow Stage Contract Migration**:
The breaking Agent Contract migration that adopts `workflow.stages[]` directly in one cutover and rejects legacy public stage aliases.
_Avoid_: Dual-read workflow stage fields, node/stage aliasing, hidden legacy stage config

**Stage Terminology Code Cutover Scope**:
The implementation rename scope that moves public and domain-facing Workflow Template configuration code from node terms to stage terms while preserving Runtime Plane graph node terminology where it describes actual runtime graph mechanics.
_Avoid_: Renaming LangGraph nodes to stages, leaving public contract models as nodes, mixed node/stage domain API

**Dashboard Stage Configuration Surface Cutover**:
The Slice 1 rename of Dashboard and Agent Configuration API public surfaces to workflow stage language, including request and response fields, helper names, UI labels, fixtures, and tests.
_Avoid_: Backend-only schema migration, node-labeled Stage Panel, mixed nodes/stages API payload

**Workflow Stage Prompt Configuration**:
The Agent-owner-editable business Prompt and structured context settings attached to a registered Workflow Template Stage so Proof Agent can provide fuller task context while preserving Harness-owned control prompts, stage order, policy gates, validators, and trace semantics.
_Avoid_: Prompt-defined workflow, raw chain-of-thought instruction, hidden policy override, arbitrary node prompt

**Workflow Stage Prompt Field Set**:
The first allowed prompt fields under `workflow.stages[].prompt`: `business_context`, `task_instructions[]`, and `output_preferences[]`.
_Avoid_: system_prompt, developer_prompt, raw_prompt, role_guidance, persona override

**Business Context Addendum**:
The runtime injection form of Workflow Stage Prompt Configuration appended to a governed stage's structured model context after Proof Agent's Harness-owned control prompt and Structured Control Context, without replacing JSON contracts, action sets, policy authority, validators, or Tool Gateway behavior.
_Avoid_: System prompt override, developer prompt override, control prompt replacement, policy bypass context

**Harness Prompt Authority Boundary**:
The rule that Proof Agent owns model system and developer prompt authority for governed workflow stages; Agent-authored stage prompt fields can only contribute bounded Business Context Addendum values.
_Avoid_: Agent-authored system_prompt, developer_prompt, raw_prompt, hidden control prompt override

**Workflow Stage Panel**:
The first UI representation of Workflow Template Stage Configuration as an ordered, expandable stage list rather than a drag-and-drop canvas.
_Avoid_: Free-form workflow canvas, runtime graph layout, node layout source of truth

**Workflow Relationship Map**:
The Dashboard-visible, read-only representation of a Workflow Template's stage order, branch conditions, predecessor and successor relationships, and governed handoff points so Agent owners can understand how stage Prompt configuration affects surrounding execution context.
_Avoid_: Editable runtime graph, drag-and-drop edge editor, hidden workflow source of truth

**Workflow Control Layer Map**:
The primary Dashboard workflow view that renders the backend-owned Workflow Relationship Map as the stable Harness execution layer, including registered stages, predecessor and successor relationships, review gates, tool and retrieval boundaries, and per-stage Prompt configuration entry points.
_Avoid_: Business process diagram only, editable topology, runtime-generated graph source

**Workflow Business Plan Layer**:
The secondary Dashboard workflow view that renders a Dynamic Insurance Business Subplan as business-facing steps anchored to the Workflow Control Layer Map, showing inferred intent, missing inputs, evidence needs, allowed retrieval, allowed read-tool proposals, source-authority expectations, and response projection needs without becoming a runtime graph.
_Avoid_: Harness topology replacement, executable BPMN, tool-call transcript, raw chain-of-thought

**Workflow Plan-to-Stage Mapping**:
The Dashboard explanation link between one Dynamic Insurance Business Subplan step and the governed Workflow Template Stage or stages that will handle it. A business step may map to several Harness stages, and a Harness stage may support several business steps, but the mapping never creates new execution edges.
_Avoid_: Edge editor, hidden branch rule, model-controlled workflow rewrite

**Workflow Stage Context Option Configuration**:
The descriptor-allowed boolean map under `workflow.stages[].context` that selects which Structured Control Context summaries may be included for one Workflow Template Stage.
_Avoid_: Free-form context injection, raw prompt include list, model-selected context

**Effective Workflow Stage Context Option Allowlist**:
The per-stage context option allowlist after applying Workflow Template Descriptor rules and resolved capability availability for one Draft or Published Agent.
_Avoid_: Base descriptor allowlist only, disabled-capability context flag, ignored false option

**Workflow Stage Context Preview**:
The Dashboard configuration preview that renders a redacted, length-bounded sample of Harness Control Prompt summary, selected Structured Control Context, and Business Context Addendum for one Workflow Template Stage without calling a model, executing a tool, or writing run trace.
_Avoid_: Test run, model preview call, raw prompt dump, execution simulation

**Workflow Stage Prompt Validation**:
The Draft Agent and Agent Validation Run checks that ensure Workflow Stage Prompt Configuration references only registered stage ids, editable Prompt fields, allowed context options, safe bounded text, and runtime assembly paths that cannot replace Harness-owned control prompts or bypass governance.
_Avoid_: Prompt lint only, optional UI warning, runtime-only prompt repair

**Model-Bearing Workflow Stage**:
A Workflow Template Stage whose governed execution includes a model call, so its Business Context Addendum may enter that stage's Harness-normalized model request as structured context after the Harness-owned control prompt.
_Avoid_: Any node with text settings, direct prompt executor, model-owned policy node

**Non-Model Governed Stage**:
A Workflow Template Stage that does not directly call a model, where Workflow Stage Prompt Configuration can only affect adjacent reviewed context summaries, deterministic wording preferences, or trace-safe configuration summaries without changing retrieval, tool, memory, policy, validator, or response execution logic.
_Avoid_: Hidden model call, prompt-driven tool execution, prompt-driven retrieval behavior

**Controlled ReAct Workflow**:
A Workflow Template where a model proposes reasoning steps and action proposals, while the Control Envelope governs whether each step may execute.
_Avoid_: Autonomous ReAct agent, direct model executor

**Intent Resolution**:
The governed understanding step that turns a user turn and admitted conversation context into an audit-safe summary of user goal, domain intent, known facts, missing fields, ambiguities, risk flags, and the recommended next action before ReAct planning.
_Avoid_: Raw chain-of-thought, hidden thinking, unstructured intent guess

**Intent Resolution Contract**:
The structured output contract for Intent Resolution, distinct from Reasoning Summary because it describes user intent and ambiguity rather than the rationale for a selected ReAct action.
_Avoid_: Reused Reasoning Summary, planner scratchpad, free-form intent notes

**React Enterprise QA Template**:
The V1 Controlled ReAct Workflow Template for enterprise question answering.
_Avoid_: Replacing Enterprise QA Template, generic autonomous agent template

**React Enterprise QA Template V2**:
The versioned Controlled ReAct Workflow Template that adds Intent Resolution before ReAct planning while preserving historical interpretation of earlier Published Agent Versions.
_Avoid_: Runtime feature flag for v1, mutable latest template behavior

**Insurance QA Evaluation Target**:
A concrete Agent evaluation target that applies the React Enterprise QA Template to the Insurance Service QA Domain and measures both business answer quality and Control Envelope behavior.
_Avoid_: react-insurance-qa Agent, template-only evaluation, generic QA benchmark

**Evaluation Case**:
The smallest expected-assertion unit in Evaluation Analysis, applied to one Evaluation Subject and judged against expected business outcome, answer quality, evidence, policy, tool, and audit assertions.
_Avoid_: Question-only test, raw chat turn, journey-level score

**Evaluation Subject**:
A safe reference to one completed governed run and its available artifacts, such as trace, receipt, run metadata, and audience-safe response projection.
_Avoid_: Evaluation Case, question to execute, raw run dump

**Evaluation Subject Manifest**:
A reviewable index that maps Evaluation Cases or Scenario steps to completed Evaluation Subjects, keeping run references for provenance while making explicit artifact references the Evaluation Analyzer input.
_Avoid_: Suite file, run command, raw Dashboard export

**Evaluation Response Projection**:
The audience-safe caller-visible response selected for answer-quality and wording evaluation, distinct from internal trace and receipt artifacts used as audit basis.
_Avoid_: Raw final_output, trace response, internal audit basis

**Evaluation Subject Export**:
A generated linked manifest or frozen bundle produced from an observability surface such as Dashboard or RunStore, preserving completed-run artifact references or copies without making that surface an evaluator.
_Avoid_: Dashboard evaluation, production metric mutation, evaluation execution

**Evaluation Scenario**:
An ordered group of Evaluation Cases that represents a multi-turn, clarification, approval, retry, or customer journey flow and adds scenario-level assertions across the linked runs.
_Avoid_: Single run, raw conversation transcript, ungoverned benchmark

**Scenario Governed Resolution**:
The pass/fail result for an Evaluation Scenario, requiring every scenario step to pass its Evaluation Gates, continuation linkage to be proven, and every scenario-level assertion to pass.
_Avoid_: Last-run-only success, step-count-weighted pass rate, transcript-level impression

**Governed Resolution Rate**:
The top-level Agent evaluation metric: the share of Evaluation Cases that reach the correct governed resolution and satisfy required business, evidence, policy, tool, trace, receipt, and redaction assertions.
_Avoid_: Answer accuracy, chatbot helpfulness score, ungoverned pass rate

**Deterministic Evaluation Gate**:
A structured must-pass Evaluation Case assertion derived from governed run artifacts, such as outcome, evidence, policy, tool approval, trace, receipt, redaction, and safety facts.
_Avoid_: LLM judge replacement, subjective quality score, best-effort reviewer opinion

**Control Envelope Coverage Gate**:
A deterministic Evaluation Gate that verifies the expected capability path emitted the minimum governance events needed to prove it did not bypass the Control Envelope.
_Avoid_: Required trace event checklist, manual no-bypass review, workflow success

**Response Projection Safety Gate**:
A deterministic Evaluation Gate that verifies the evaluated caller-visible projection respects its audience boundary and does not expose internal governance, trace, tool, or customer-sensitive details.
_Avoid_: Redaction check, final-output validator, customer tone score

**Evaluation Node Result**:
A trace-derived diagnostic result for one stable Control Envelope stage, optionally mapped to a Workflow Template node, explaining observed events, key facts, status, and likely failure ownership without replacing Evaluation Gates.
_Avoid_: Required trace event list, workflow execution node, runtime graph state

**Evaluation Artifact Sufficiency**:
The trust label describing whether an Evaluation Subject has enough completed-run artifacts and structured fields for a gate or node result to be assessed without inference.
_Avoid_: Best-effort compatibility, inferred pass, missing-data warning

**Audited Evaluation Judge**:
A model or human judge that produces traceable diagnostic scores for answer quality, completeness, expression, and business-step coverage without overriding Deterministic Evaluation Gates.
_Avoid_: Policy authority, evidence gate replacement, unlogged quality vote

**Evaluation-Safe Judge Projection**:
The redacted input view for an Audited Evaluation Judge, limited to the question, caller-visible response, expected resolution, taxonomy labels, accepted evidence summaries, safe tool summaries, actual outcome, gate summary, and rubric.
_Avoid_: Raw trace dump, raw prompt, raw model output, unredacted customer payload

**Judge-Led Diagnostic Scoring**:
An evaluation mode where an Audited Evaluation Judge leads qualitative scoring and ranking after Deterministic Evaluation Gates have been applied.
_Avoid_: Judge-led governance, LLM-as-judge release gate, deterministic gate bypass

**Evaluation Quality Score**:
The Audited Evaluation Judge score for answer correctness, completeness, groundedness clarity, user usefulness, and safe wording, reported after Deterministic Evaluation Gates and never used to override them.
_Avoid_: Governance pass rate, policy decision, evidence admission score

**Evaluation Release Threshold**:
The V1 publication bar for an Insurance QA Evaluation Target: complete deterministic safety and governance gate pass, sufficient artifacts, low run error rate, and high overall Governed Resolution Rate.
_Avoid_: Accuracy-only launch bar, judge-only launch decision, unverifiable quality claim

**Evaluation Suite**:
A named group of Evaluation Cases or Evaluation Scenarios with a specific operational purpose, such as smoke validation, release gating, safety regression, or production monitoring.
_Avoid_: Undifferentiated benchmark, one-off question file, mixed release and monitoring sample

**Evaluation Suite Source**:
The location from which an Evaluation Suite is resolved, with explicit CLI paths taking precedence over built-in framework suites and future Agent-package-owned suites.
_Avoid_: Demo questions file, hidden default benchmark, dashboard-only suite selection

**Evaluation Curation**:
The process of turning production samples into formal Evaluation Cases through redaction, deduplication, taxonomy labeling, expected-resolution labeling, evidence or tool-basis annotation, risk classification, and human confirmation; LLM-assisted prelabeling may inform but not replace confirmation for release or safety suites.
_Avoid_: Raw production replay, judge-only labeling, unreviewed monitoring sample

**Domain Evaluation Reviewer**:
The curator role that confirms expected business outcome, required business claims, evidence basis, and forbidden claim categories for promoted Evaluation Cases.
_Avoid_: Judge, Harness reviewer, label preclassifier

**Harness Evaluation Reviewer**:
The curator role that confirms expected governed resolution, required gates, execution surface, risk class, and policy or tool expectations for promoted Evaluation Cases.
_Avoid_: Domain reviewer, PolicyEngine, automatic evaluator

**Evaluation Failure Owner**:
The primary repair ownership label assigned to a failed Evaluation Case, such as knowledge gap, retrieval failure, planning failure, policy failure, tool governance failure, answer generation failure, audit failure, label or curation issue, or judge diagnostic issue.
_Avoid_: Generic failed test, blame-free untriaged metric, score-only regression

**Evaluation Repair Recommendation**:
A non-executing repair brief produced for a failed Evaluation Case, naming the suspected root cause, repair action, affected artifact, severity, rerun requirement, and linked trace or receipt references without producing directly applicable changes.
_Avoid_: Automatic production fix, patch suggestion, self-modifying Agent, unreviewed policy or knowledge change

**Evaluation Artifact Set**:
The artifacts produced by Evaluation Analysis: a human-readable Evaluation Report, machine-readable per-case Evaluation Result JSONL, and an Evaluation Analysis Receipt that records Agent version, suite version, judge configuration, gate version, sample provenance, and audit basis.
_Avoid_: Governance Receipt replacement, dashboard-only chart, ad hoc test log

**Evaluation Analysis Receipt**:
The audit-oriented receipt for one Evaluation Analysis, explaining the suite, subject manifest, artifact sufficiency, gate version, judge mode, provenance, and analysis basis.
_Avoid_: Governance Receipt, Evaluation Run Receipt, run trace

**Evaluation Analyzer**:
The post-run evaluation capability that reads existing governed run artifacts and safe response projections to produce Evaluation Artifact Set files without creating Agent runs.
_Avoid_: Harness runner, evaluation execution path, hidden workflow executor

**Evaluation Run Producer**:
An optional helper that creates governed run artifacts through existing execution surfaces before Evaluation Analysis, without owning evaluation semantics.
_Avoid_: Evaluation Analyzer, alternate Harness runtime, dashboard-owned execution

**Scenario Evaluation Analysis**:
The post-run analysis capability that evaluates an Evaluation Scenario as ordered linked Evaluation Subjects, using only explicit subject references, safe projections, and completed-run artifacts.
_Avoid_: Scenario execution runner, durable checkpoint resume claim, raw transcript replay

**Scenario Safe Reference**:
A limited reference from a later Evaluation Scenario step to a prior step's safe projection, such as run id, outcome, final output summary, customer turn id, safe sources, or approval state.
_Avoid_: Raw trace JSONPath, raw model output reference, arbitrary fixture script

**Evaluation Execution Surface**:
The execution boundary used for an Evaluation Case or Evaluation Scenario, such as direct Harness execution, Run Execution API conversation execution, or Customer Run API execution.
_Avoid_: Hidden shortcut, unrecorded API bypass, mixed audience projection

**Evaluation Store**:
The storage boundary for Evaluation Artifact Set files and linked case run artifacts, separate from ordinary production run history while preserving references to each governed case run.
_Avoid_: RunStore replacement, production run metric pollution, dashboard-only evaluation cache

**Evaluation Version Boundary**:
The versioned evaluation context that must be fixed for trustworthy comparison: Agent version, Evaluation Suite version, Evaluation Gate version, Judge Rubric version, and resolved Knowledge Snapshot or Tool Contract versions.
_Avoid_: Unversioned benchmark trend, silent rubric change, comparing migrated suites as regression

**Evaluation Case Taxonomy**:
The canonical classification dimensions for Evaluation Cases: user intent type, expected governed resolution, governance risk class, and exercised capability path.
_Avoid_: Flat question list, ad hoc benchmark category, prompt-only test label

**Evaluation Gate Set**:
The release-oriented Deterministic Evaluation Gate group for an Evaluation Case: Outcome Gate, Evidence Support Gate, Forbidden Claim Gate, Policy Gate, Tool Governance Gate, Audit Artifact Gate, and Redaction/Safety Gate.
_Avoid_: Single accuracy check, subjective rubric only, trace-blind benchmark

**Evaluation Gate Profile**:
A versioned selection of required and diagnostic Evaluation Gates for a Suite purpose, such as smoke, release, safety, or monitoring analysis.
_Avoid_: Hardcoded gate list, hidden release bar, judge rubric

**Evaluation Gate Automation Level**:
The implementation maturity label for an Evaluation Gate, distinguishing fully automated structural checks from semi-automated semantic checks that require Audited Evaluation Judge or human diagnostic support.
_Avoid_: Pretend-complete automation, regex-only semantic judgment, unmarked manual gate

**Evaluation Response Assertion**:
A limited assertion over the caller-visible response projection, such as required key terms, forbidden wording, or response language, used only as a supplement to artifact-derived Evaluation Gates.
_Avoid_: Exact answer match, prompt snapshot test, evidence-free quality gate

**Forbidden Claim Category**:
A semantic risk label for prohibited answer content, such as payment guarantee, approval likelihood, coverage decision, cross-customer disclosure, or process-bypass advice.
_Avoid_: Forbidden phrase, exact wording assertion, safety score

**Required Business Claim**:
A case-labeled business fact, process step, limitation, or next action that the evaluated response is expected to cover and ground in accepted evidence or authorized tool results.
_Avoid_: Keyword assertion, exact answer, judge-only preference

**Evaluation Process Metrics**:
The trace-derived diagnostic metrics grouped by Control Envelope stage: planning, retrieval, policy and review, tool governance, answer validation, and auditability.
_Avoid_: Raw LLM logs, one-off latency counters, unstructured debug notes

**Operational Evaluation Metrics**:
The evaluation-adjacent operating metrics for latency, model token usage, tool and retrieval call counts, approval wait rate, fail-closed rate, run error rate, and cost per resolved case, reported separately from Governed Resolution Rate.
_Avoid_: Quality score, governance pass rate, hidden launch blocker

**Deterministic ReAct Demo**:
A no-API-key acceptance path for the React Enterprise QA Template using deterministic planner and review providers.
_Avoid_: Remote-only ReAct demo, provider-dependent MVP

**ReAct Planner**:
The planning capability that turns user input, system prompt, and admitted context into Reasoning Summary and ReAct Action Proposal values.
_Avoid_: Final answer model, Harness Review Subagent

**LLM ReAct Planner**:
A ReAct Planner implementation that uses a configured Model Provider to produce Harness-normalized ReAct Action Proposal values.
_Avoid_: Deterministic ReAct Planner, provider-native tool executor

**ReAct Planner Config**:
The Agent Contract section that configures the ReAct Planner independently from the final answer model and Harness Review Subagent.
_Avoid_: Hidden planner defaults, overloaded answer model config

**Business Agent AI Core**:
The business-facing AI capability that plans actions or generates final answer content inside a governed Agent run.
_Avoid_: Harness decision maker, uncontrolled AI core

**Harness Decision Assistance**:
The control-facing AI capability that advises Harness review decisions without becoming the final policy authority.
_Avoid_: Business Agent AI Core, model self-approval

**Model Provider Registry**:
The shared capability registry that resolves model providers for final answers, planning, and Harness review roles.
_Avoid_: Role-specific provider registry

**Shared Model Connection**:
A reusable live model connection configuration that Agents and Knowledge Sources can reference for real model calls without duplicating provider, model identifier, endpoint, or credential reference.
_Avoid_: Model Provider Registry entry, Agent-only model settings, prompt model alias, role tuning parameters

**Shared Model Connection Lifecycle**:
The Active, Archived, and deletion-eligible states for a Shared Model Connection; archived connections cannot be newly selected or used for new production publication, but existing live references may continue resolving until explicitly changed.
_Avoid_: Published model version, silent hard delete, immutable model release

**Model Connection Impact Review**:
The pre-save Dashboard review that shows which Draft Agents, Published Agents, and Knowledge Sources will be affected by a Shared Model Connection change because those references resolve live.
_Avoid_: Agent republish gate, hidden model update, immutable dependency review

**Models Workspace**:
The Dashboard configuration workspace for administering Shared Model Connections as reusable model access assets.
_Avoid_: Provider model catalog, Agent Model module, runtime model endpoint

**Model Connection Configuration API**:
The Agent Configuration API resource family for creating, updating, testing, archiving, restoring, and reference-checking Shared Model Connections. Model Connection command requests do not carry actor fields; the API resolves Operator Identity Context server-side and records the resolved operator in Configuration Operation Audit for create, update, archive, restore, and physical deletion, and in Model Connection validation and smoke-test records for test commands.
_Avoid_: Dashboard read API, provider model inventory API, direct model execution API, request-body actor

**Model Connection Permission Model**:
The Operator Permission Vocabulary slice for reusable model access assets. `model_connection.view` gates list, detail, reference summary, and deletion-eligibility reads. `model_connection.edit` gates creation and update after impact confirmation. `model_connection.validate` gates validation and smoke-test commands. `model_connection.archive` gates Archive, Restore, and physical deletion. V1 local single-user mode may grant all by default, but API checks and Dashboard actions preserve the distinctions for future RBAC.
_Avoid_: One model admin boolean, Agent permission reuse, frontend-only permission check

**Model Credential Reference**:
A secret-safe pointer from a Shared Model Connection to the credential material needed for provider authentication, such as an environment variable name or future secret-store reference.
_Avoid_: Raw API key, stored provider secret, exported credential value

**Environment Model Credential Reference**:
The V1 Model Credential Reference type that stores an environment variable name for provider authentication while keeping the credential value outside Proof Agent configuration.
_Avoid_: Dashboard-stored API key, local secret vault, exported credential material

**Model Connection Parameters**:
The provider, model identifier, endpoint, credential reference, provider account scope, and default timeout values that define how Proof Agent connects to a Shared Model Connection.
_Avoid_: Model Usage Parameters, Agent role tuning, Knowledge retrieval tuning

**Model Usage Parameters**:
The call-site settings that define how an Agent role or Knowledge Source uses a selected Shared Model Connection for a specific purpose, such as temperature, output token limits, timeout overrides, retrieval `top_k`, or source-level routing and ingestion tuning.
_Avoid_: Model Connection Parameters, provider credential, shared endpoint setting

**Model Connection Resolution Record**:
A trace-safe audit fact that records which Shared Model Connection values and call-specific usage parameters were resolved for one model call without pinning future runs to that connection state.
_Avoid_: Published model snapshot, raw credential record, hidden provider state

**Model Connection Resolution Failure**:
A fail-closed condition where a Shared Model Connection or custom model configuration cannot resolve its provider, model identifier, endpoint, credential reference, or supported adapter for a model call.
_Avoid_: Silent fallback model, deterministic fallback, best-effort provider rewrite

**Model Connection Validation**:
A local configuration check that verifies a Shared Model Connection or custom model configuration is structurally valid and can resolve required credential references without calling a remote provider.
_Avoid_: Remote model call, Agent Validation Run, hidden connectivity check

**Model Connection Smoke Test**:
A manually triggered remote provider probe for a Shared Model Connection or custom model configuration that records trace-safe success or failure facts without becoming a default CI, demo, or publication gate.
_Avoid_: Automatic network dependency, stored prompt transcript, production run

**Shared Model Connection Provider Set**:
The supported provider names for Shared Model Connections are derived from the Model Provider Registry, while the Models Workspace may expose only providers with production-ready connection forms as selectable creation options.
_Avoid_: Frontend-only provider list, separate model provider registry, placeholder provider as ready integration

**Knowledge Source Model Connection Configuration**:
The Source-owned selection of Shared Model Connections used by a Knowledge Source for ingestion, routing, or other source-level model calls, with source-specific usage parameters configured on the Knowledge Source.
_Avoid_: Agent Knowledge Binding model override, copied provider credentials, per-Agent index model setting

**Knowledge Source Custom Model Configuration**:
A Knowledge Source-owned model configuration entered directly for ingestion, routing, or another source-level model purpose instead of selecting a Shared Model Connection, using the same secret-safe credential reference rules.
_Avoid_: Agent Knowledge Binding model override, Shared Model Connection, raw API key configuration

**Named OpenAI-Compatible Model Provider**:
A first-class Model Provider name that resolves through the OpenAI-compatible adapter while carrying provider-specific defaults such as API key environment variable and base URL.
_Avoid_: Generic OpenAI-compatible example, provider-specific control plane

**DeepSeek Model Provider**:
The named OpenAI-compatible Model Provider for DeepSeek API calls. It is a formal Agent Contract provider for final answer generation, ReAct planning, and Harness review assistance, while all outputs still pass through Harness-normalized contracts, validators, PolicyEngine, and trace rules.
_Avoid_: DeepSeek-specific Harness semantics, provider-native tool execution, openai_compatible-only example

**DeepSeek Model Name Policy**:
Proof Agent recommends current DeepSeek model names in examples and documentation but does not hard-code a DeepSeek model allowlist in Agent Contract validation. Model inventory is provider-owned and may change without changing Harness semantics.
_Avoid_: Offline-blocking provider inventory lookup, stale hard-coded model list, silently rewriting model names

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

**External Model Smoke Test**:
An optional manually triggered verification path that calls a real remote model provider only when the operator supplies the required API key and explicitly opts in. It is not part of the deterministic demo or default CI gate.
_Avoid_: default CI remote model call, hidden network dependency, mandatory provider credential

**Model Reasoning Control**:
A future model-provider capability for declaring provider-specific reasoning or thinking controls without weakening Proof Agent's Reasoning Summary, control prompts, trace safety, or output normalization boundaries. V1 DeepSeek support does not expose provider-specific reasoning controls.
_Avoid_: Unbounded extra_body passthrough, provider-specific hidden reasoning mode, raw chain-of-thought capture

**Model Role Configuration**:
The Agent-specific configuration for each model call role, including final answer generation, ReAct planning, and Harness review assistance.
_Avoid_: Single global Agent model, hidden model reuse, provider-native agent config

**Agent Model Connection Binding**:
The Agent-specific selection that maps one model call role, such as Answer, Planner, or Reviewer, to a live Shared Model Connection while preserving role-specific usage parameters, governance, and validation behavior.
_Avoid_: Single global Agent model connection, copied provider credentials, provider-native agent config

**Agent Custom Model Configuration**:
An Agent-owned model configuration entered directly for one model call role instead of selecting a Shared Model Connection, using the same secret-safe credential reference rules.
_Avoid_: Shared Model Connection, raw API key configuration, provider model catalog entry

**Harness-Normalized Model Output**:
Model output parsed into Proof Agent contracts before it can affect workflow, review, tool, or answer behavior.
_Avoid_: Native provider command, raw model action

**Model Output JSON Contract**:
The requirement that planner and reviewer model outputs be valid JSON objects representing Proof Agent contracts.
_Avoid_: Natural-language control output, inferred JSON

**Model Call Role**:
The trace-safe label that distinguishes why a model provider was called during a governed run.
_Avoid_: Role-specific trace event type

**Harness Control Prompt**:
A Proof Agent-maintained prompt that defines control-plane output rules for planner or reviewer model calls.
_Avoid_: Agent-authored control prompt, business instruction

**Structured Control Context**:
Harness-constructed, redacted, policy-relevant context admitted into a planner or reviewer model call.
_Avoid_: Raw transcript, raw evidence dump, arbitrary business prompt injection

**Model Output Normalization Failure**:
A fail-closed condition where model output cannot be parsed or validated as the required Proof Agent contract.
_Avoid_: Best-effort repair, silent fallback

**Native Tool Call Adapter**:
A future adapter that converts provider-native tool call payloads into Harness-governed action proposals.
_Avoid_: Direct provider tool execution, provider-controlled Tool Gateway

**ReAct Action Proposal**:
A model-proposed next action that is not executable until admitted by Harness policy.
_Avoid_: Tool call, approved action, model decision

**ReAct Action Set**:
The fixed V1 set of allowed ReAct action types: ask clarification, plan retrieval, run retrieval step, propose tool call, generate final answer, escalate, or stop.
_Avoid_: Free-form action name, arbitrary model command

**Effective ReAct Action Set**:
The run-specific, planner-facing subset of the ReAct Action Set admitted by Workflow Stage Availability, Tool Proposal Scope, and Control Envelope preconditions before ReAct planning.
_Avoid_: Prompt-only action hint, model-selected capability set, runtime-only branch list, generic Workflow Template fact

**Workflow Stage Availability Event**:
The run-level trace fact that records the Workflow Stage Availability Set and Effective ReAct Action Set without pretending disabled stages executed.
_Avoid_: Per-disabled-stage execution event, hidden capability omission, Dashboard-only availability

**Tool Proposal Scope**:
The run-specific set of Tool Contract identifiers that a ReAct Planner may mention in ReAct Action Proposal values before Harness policy decides whether execution is allowed.
_Avoid_: Tool execution permission, provider-native tool list, prompt-only allowlist

**Auto Review Mode**:
A Harness operating mode where configured rules and, when enabled, a Harness Review Subagent review control nodes without human approval unless a decision requires it.
_Avoid_: Unconstrained autonomous mode

**Harness Review Subagent**:
An LLM-backed subagent inside the Control Plane that reviews Harness control nodes in Auto Review Mode and returns a typed review result.
_Avoid_: Business Agent, final answer agent, uncontrolled self-approval

**LLM Harness Review Subagent**:
A Harness Review Subagent implementation that uses a configured Model Provider to produce Harness-normalized Review Decision values.
_Avoid_: Deterministic Harness Review Subagent, final answer model

**Review Subagent Config**:
The Agent Contract section that configures the Harness Review Subagent independently from the final answer model.
_Avoid_: Reusing answer model config, hidden reviewer defaults

**Review Decision**:
A typed suggestion from the Harness Review Subagent that must be validated by PolicyEngine before it becomes a PolicyDecision.
_Avoid_: Final policy decision, direct approval

**Review Failure Policy**:
The fail-closed behavior used when the Harness Review Subagent times out, errors, emits invalid output, or conflicts with deterministic policy.
_Avoid_: Silent allow, best-effort continuation

**Auto Review Scope**:
The set of Harness control nodes that the Harness Review Subagent may review in V1.
_Avoid_: All workflow stages, unrestricted review surface

**Reasoning Summary**:
An audit-safe structured summary of ReAct planning intent, observations, candidate actions, selected action, rationale, risk flags, and required evidence.
_Avoid_: Raw chain-of-thought, hidden reasoning transcript

**Action Proposal Event**:
A trace event that records an audit-safe ReAct Action Proposal before Harness review.
_Avoid_: Tool execution event, final policy decision

**Review Decision Event**:
A trace event that records the Harness Review Subagent's Review Decision before PolicyEngine validation.
_Avoid_: Final policy decision event

**Review Override Event**:
A trace event that records PolicyEngine overriding or rejecting a Review Decision.
_Avoid_: Silent rule conflict

**Workflow Stage Configuration Trace Summary**:
The default trace-safe record of a run's Workflow Stage configuration source and per-stage configuration summary: source, reference when available, descriptor version, stage ids, configured prompt field names, bounded lengths and counts, context option names, and redaction status.
_Avoid_: Full prompt text, full context payload, raw validation dump

**Workflow Stage Trace Capture Mode**:
The validation/test-run request switch that controls whether run trace stores only Workflow Stage Configuration Trace Summary or additionally captures full stage Prompt, selected context values, and intermediate Workflow Stage Result details for verification.
_Avoid_: Always-on verbose trace, production raw prompt archive, chain-of-thought capture

**Workflow Template Execution Resume Metadata**:
The Runtime Plane metadata retained for resuming a paused Workflow Template Execution, including a protected reference to the run-start Workflow Template Execution Input needed for checkpoint resume without exposing full Prompt or context values through ordinary trace, receipt, RunStore detail, or Dashboard projection.
_Avoid_: Ordinary trace content, Governance Receipt section, Dashboard run detail payload

**Sensitive Validation Capture Artifact**:
The access-controlled validation/test artifact produced when Workflow Stage Trace Capture Mode records full stage Prompt, selected context values, or intermediate Workflow Stage Result details.
_Avoid_: Ordinary trace event, customer-support-visible run detail, default receipt export

**Sensitive Validation Capture Retention**:
The retention policy for Sensitive Validation Capture Artifacts: default short TTL of 7 days, with explicit audit retention only when requested and authorized.
_Avoid_: Ordinary trace retention, permanent prompt archive, hidden validation payload storage

**Agent Contract Stage Capability Implementation Sequence**:
The implementation order for the React Enterprise QA contract refactor: contract schema cutover; descriptor, availability, and effective configuration publication; runtime execution consumption of frozen configuration; validation trace capture and sensitive artifact handling.
_Avoid_: One giant migration, runtime-first refactor, trace capture before contract stability

**Published Effective Workflow Stage Configuration Runtime Consumption Slice**:
The implementation slice that makes run-start Workflow Template Execution consume resolved Workflow Stage Availability and Effective Workflow Stage Configuration facts instead of raw Agent Contract stage overrides, while preserving static Runtime Adapter topology.
_Avoid_: Validation full-capture rewrite, historical descriptor registry, second runtime implementation, dynamic runtime graph generation

**Contract Schema Cutover Test Gate**:
The tests-first gate for Slice 1 that locks the accepted and rejected Agent Contract YAML shapes before loader, API, Dashboard, examples, and fixtures are migrated.
_Avoid_: Manual schema migration, UI-first rename, untested legacy rejection

**Small-Step Verification Cadence**:
The implementation discipline for the Agent Contract stage/capability refactor: every small behavior change must add or update targeted tests, run those tests immediately, and only then proceed to the next change.
_Avoid_: Batch refactor before tests, final-only verification, unverified schema churn

**Clarification Requested Event**:
A trace event that records a Clarification Request and the missing information categories.
_Avoid_: Approval event, refusal event

**Governance Detail Projection**:
A response/API projection that may include Reasoning Summary and review results for operator inspection without changing trace completeness.
_Avoid_: Trace storage toggle, raw debugging dump

**Response Detail Policy**:
The Agent Contract policy that sets the maximum governance detail a backend response may expose.
_Avoid_: Frontend-only visibility flag, unrestricted API projection

**Policy Rule Configuration**:
The structured Agent-specific policy settings that compile into policy rules for enforcement points, conditions, decisions, and audit reason templates.
_Avoid_: Natural-language policy, frontend-only guardrail, prompt instruction

**Customer-Safe Response Projection**:
A customer-facing response shape that exposes only the governed reply, safe source references, clarification needs, or safe follow-up acknowledgement while hiding internal trace, receipt, policy, review, tool, and handoff details. It may differ from the internal run final output when customer-safety wording requires projection.
_Avoid_: Governance Detail Projection, raw Run Detail, internal audit response

**Institution Specialist Response Projection**:
An operator-facing assisted-service response shape for Institution Insurance Specialist runs that may include the answer, source basis, missing-information boundaries, authorized-read availability, and safe audit links according to Response Detail Policy.
_Avoid_: Customer-safe response, raw trace dump, direct external customer wording

**External Wording Draft**:
An optional staff-reviewed wording suggestion that an Institution Insurance Specialist may adapt for a customer or agent, containing only externally appropriate business explanation and safe source references while hiding internal system names, Tool Contract identifiers, tool parameters, authorization details, policy rule names, review results, trace, and receipt details.
_Avoid_: Autonomous customer reply, internal operator answer, legal commitment, tool transcript

**Customer-Safe Source Label**:
A customer-visible source reference that names the business record category or customer-owned record without exposing internal tool names, trace identifiers, receipt identifiers, authorization reasons, or raw payloads.
_Avoid_: Tool name, trace link, receipt link, raw record payload

**Customer-Facing Business Claim**:
Any customer-visible statement about policy rules, coverage, status, timing, amount, eligibility, required action, or service next steps.
_Avoid_: Greeting, clarification prompt, escalation notice

**Insurance Product Term Interpretation**:
An evidence-backed customer-facing explanation or analysis of insurance product terms, policy clauses, coverage language, exclusions, deductibles, waiting periods, or customer obligations.
_Avoid_: Personalized coverage decision, payment guarantee, unsupported legal advice

**Insurance Service Process Guidance**:
An evidence-backed customer-facing explanation or analysis of insurance service workflows, claim submission steps, document requirements, review stages, status meanings, or safe next-step options.
_Avoid_: Transactional action, SLA commitment, claim outcome decision

**Outcome Optimization Advice**:
Customer-facing advice that predicts, optimizes, or improves the likelihood of a claim, coverage, eligibility, approval, or payment outcome for a specific customer case.
_Avoid_: Evidence-backed document checklist, generic service process guidance

**Safe Process Guidance Reframe**:
A customer-safe response pattern that declines to assess outcome likelihood or optimize a case outcome, then answers with evidence-backed document checklists, preparation steps, or service process guidance.
_Avoid_: Direct refusal only, outcome prediction, rule evasion advice

**Personalized Insurance Service Request**:
A customer-facing request that asks about the authenticated customer's own policy, claim, eligibility, coverage, payable amount, deadline, status, or next required action.
_Avoid_: Generic product term question, generic service process question

**Personalized Coverage Or Payment Decision**:
A customer-specific conclusion about whether a claim is covered, eligible, payable, how much will be paid, or when payment is guaranteed.
_Avoid_: Evidence-backed term explanation, read-only status lookup, service process guidance

**Safe Conversational Text**:
Customer-facing text that contains no business claim, such as greetings, acknowledgements, clarification prompts, refusals, temporary failure wording, or escalation notices.
_Avoid_: Unsupported policy explanation, unsupported service commitment

**Customer Response Language Policy**:
The customer-facing language rule that limits V1 replies to Chinese or English while preserving evidence and tool support requirements.
_Avoid_: Unbounded multilingual support, free translation layer

**Evidence-Bound Translation**:
A customer-facing translation of already-supported business claims that preserves the source meaning, source references, and evidence boundary.
_Avoid_: New business explanation, localized commitment, unsupported interpretation

**Customer Journey Acceptance Suite**:
A fixed set of customer-facing scenarios used to validate V1 autonomous service behavior across product-term interpretation, service-process guidance, anonymous access, authenticated lookup, refusal, clarification, internal handoff, retrieval failure, and supported languages.
_Avoid_: Single-question demo, ad hoc manual testing

**Customer Feedback Signal**:
A customer-provided thumbs up/down rating and optional comment attached to a conversation turn for internal observation only, linked through conversation id, turn id, and the turn's governed run id. It is not a Case Memory source in V1.
_Avoid_: Training signal, automatic policy update, online learning input

**Customer Response Snapshot**:
The exact customer-visible response projection stored with a conversation turn and linked to the governed run that produced it, including cases where customer-safety wording differs from the internal run final output. It is an audit artifact, not a Case Memory payload.
_Avoid_: Recomputed response, internal run detail, raw trace replay

**Private Pilot Customer Service Bot**:
The V1 release posture for autonomous customer service: a controlled enterprise pilot with limited users, fixed Published Agents, bounded knowledge, internal audit, and non-public-scale operations.
_Avoid_: Public internet production bot, full contact-center platform

**Customer Run Progress State**:
A customer-safe execution status that describes the current governed stage without streaming unvalidated model content.
_Avoid_: Token streaming, raw trace event stream, provider stream

**ReAct Action Budget**:
The configured upper bound on ReAct Action Proposals admitted during one Controlled ReAct Workflow run.
_Avoid_: Unlimited loop, best-effort loop

**Qualified Step**:
A named sequence item inside a specific process, such as Retrieval Step or Evaluation Scenario step; Proof Agent does not use bare Step to describe Workflow Template structure.
_Avoid_: Workflow Step, generic step, runtime node

**Evidence-First ReAct**:
A Controlled ReAct Workflow policy where the default first executable action is retrieval unless the question requires clarification or a governed tool proposal.
_Avoid_: Direct answer first, tool first by default

**Clarification Request**:
A governed response asking the user for missing information required before retrieval, tool use, or answer generation can proceed.
_Avoid_: Refusal, approval request, model fallback answer

**Waiting For User Clarification**:
The run outcome used when a Clarification Request is needed before the Agent can continue.
_Avoid_: Refused no evidence, waiting for approval

**Clarification Continuation Run**:
A follow-up Harness run that carries user-provided clarification through Controlled Conversation Context after an earlier run requested clarification.
_Avoid_: Checkpoint resume, same-run continuation

**Harness Invocation**:
A resolved execution request that combines an Agent Contract, selected Workflow Template, and governed capabilities for one run.
_Avoid_: Raw manifest, SDK runtime state

**Run Execution API**:
A Delivery entry point that starts a governed Harness run from an application surface such as the Assisted QA Chat Frontend.
_Avoid_: Dashboard read API, direct model endpoint

**Customer Run API**:
A customer-facing Delivery entry point that starts governed customer-service runs and returns Customer-Safe Response Projection values.
_Avoid_: Internal Chat API, Dashboard read API, raw run execution response

**Agent Configuration API**:
The configuration boundary for Draft Agents, reusable configuration assets, validation, publication, rollback, import, and export.
_Avoid_: Dashboard read API, production run execution API, arbitrary manifest runner

**Customer Run Adapter**:
An Agent-package-owned adapter that handles domain-specific customer-service intents, customer authorization fixtures, resource disambiguation, customer-safe wording, and optional trace annotations before the generic Customer Run API stores the Customer-Safe Response Projection.
_Avoid_: Framework-owned insurance logic, prompt-only customer routing, frontend-defined customer safety

**Draft Agent**:
An editable Agent configuration version inside the Agent Configuration Workspace that may be saved, validated, and test-run before publication.
_Avoid_: Published Agent, arbitrary runtime manifest, unvalidated production Agent

**Agent Configuration Store**:
The configuration-system store for Draft Agents, version history, validation results, publication metadata, and reviewable contract snapshots.
_Avoid_: RunStore, Conversation Store, arbitrary local filesystem path

**Local Agent Configuration Store**:
The first Agent Configuration Store implementation using local directories and JSON/contract files while preserving a replaceable store boundary.
_Avoid_: Production database requirement, router-owned file layout, hidden in-memory drafts

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

**Customer-Facing Published Agent**:
A Published Agent whose Agent Contract declares a customer section and may therefore be exposed through the Customer Service Chat Frontend.
_Avoid_: Agent-id allowlist, purpose-text inference, operator-only Published Agent

**Agent Publication**:
The governed transition that promotes a validated Draft Agent into a Published Agent Version available to Run Execution API or Customer Run API callers.
_Avoid_: Save draft, direct run, frontend-only enablement

**Agent Validation Run**:
A pre-publication governed run or validation pass that checks a Draft Agent's contract, retrieval behavior, workflow behavior, policy decisions, and receipt preview.
_Avoid_: Production run, frontend preview only, unchecked smoke test

**Run Purpose**:
The run metadata classification that distinguishes production, validation, and preview runs while keeping all governed runs in RunStore.
_Avoid_: Separate preview log, hidden test execution, metric-only tag

**Approval Pause**:
The Control Envelope fact that a governed run has stopped in `WAITING_FOR_APPROVAL` because a Tool Contract requires an external approval decision.
_Avoid_: LangGraph interrupt, runtime checkpoint, callback wait

**Approval Checkpoint Resume**:
The governed continuation of the original run after an external approval decision resolves a PendingApproval, resuming the stored runtime checkpoint and appending the terminal approval event to the original run trace.
_Avoid_: Approval Continuation Run, new follow-up run, silent retry

**Pending Approval Operation Source**:
The `PendingApproval` projection used by Approval Console actions to identify an unresolved approval request. Approval Console may display `ApprovalState`, but approve and deny actions must target `PendingApproval.approval_id`, not trace event ids or status-only approval projections.
_Avoid_: ApprovalState as command target, trace event id as approval id, inferred approval action

**Approval Resolution Actor**:
The operator identity resolved from Operator Identity Context for an approve or deny command and persisted on terminal approval trace events.
_Avoid_: Anonymous approval, customer-supplied approval authority, trace event without resolver identity

**Operator Identity Context**:
The internal operator identity and permission set admitted at API command boundaries for Dashboard, operator chat, configuration, knowledge, model, and approval operations.
_Avoid_: Per-form actor field, frontend-only role flag, customer authorization context

**Local Operator Identity Provider**:
The V1 local-mode source of Operator Identity Context, granting a deterministic local operator identity and local all-access permissions without trusting actor fields supplied by frontend request bodies.
_Avoid_: Dashboard-supplied actor, anonymous local command, production authentication substitute

**Operator Permission Vocabulary**:
The named internal permissions used by Operator Identity Context, initially covering approval resolution, run viewing, Agent configuration, Knowledge Source administration, Model Connection administration, and Tool Source administration while local mode grants the full set.
_Avoid_: Generic admin flag, frontend-only permission labels, resource operation without a named permission

**Run Detail Approval Action**:
The first Approval Console action surface embedded in a Run Detail view. It resolves a single run's pending approval through Approval Checkpoint Resume and refreshes that run projection after approve or deny; it is not a global approval queue.
_Avoid_: Frontend-scanned approval queue, separate follow-up run, page reload as state management

**Global Approval Queue Projection**:
An operator-facing Dashboard API projection and `/approvals` triage page that lists unresolved PendingApproval items across runs for approval work triage. Its primary object is the pending approval request, enriched with run metadata for navigation; it is not a filtered Run list, stats payload, or approval execution surface. The first version sorts by `expires_at` ascending, returns parameter keys and count rather than raw parameters, marks expired items without writing trace, paginates with `limit` and `offset`, and navigates to Run Detail Approval Action for approve or deny.
_Avoid_: Frontend-scanned run history, stats-expanded queue, run summary as approval command object, direct approve or deny from the queue page

**Enterprise QA Reference Agent**:
The first production-shaped Agent built with Proof Agent to validate governed enterprise question answering.
_Avoid_: The framework, generic chatbot

**Insurance Customer Service Agent**:
The V1 customer-facing Published Agent for read-only insurance service automation.
_Avoid_: Assisted insurance QA example, generic enterprise QA, direct claims decisioning

**Institution Insurance Specialist**:
The internal insurance institution staff member who uses Assisted Service Mode to answer business consultation, customer or agent questions, policy wording interpretation, report questions, policy lookup, and claim lookup requests across configured insurance business lines.
_Avoid_: End customer, agent-facing self-service user, customer-service bot persona

**Insurance Business Line Scope**:
The Agent Package boundary that limits which insurance business line knowledge, Tool Contracts, source systems, report datasets, policy records, and claim records an Institution Insurance Specialist Agent may use for a given deployment.
_Avoid_: Harness-coded product line, workflow template fork, free-form user-selected data scope

**Read-Only Institution Assistance**:
An Institution Insurance Specialist Agent scope where the Agent may answer business questions and retrieve authorized business facts for staff, but cannot change insurance business state.
_Avoid_: Autonomous transaction handling, customer self-service scope, direct policy or claim operations

**Institution Business Read Tool**:
A governed Tool Contract exposed to an Institution Insurance Specialist Agent for authorized read-only access to report, policy, claim, customer, agent, or business-line records without changing business state.
_Avoid_: Write tool, transaction tool, generic web search, ungoverned system query

**Institution Authorization Context**:
The trace-safe institution staff permission summary admitted into an assisted-service Harness run as Structured Control Context, including institution, branch, role, business-line scope, and data-scope constraints used by PolicyEngine and Tool Gateway.
_Avoid_: Raw staff credential, customer authorization context, prompt-only permission note

**Public Insurance Knowledge Query**:
A generic insurance question that can be answered from public or enterprise-approved knowledge sources without reading customer, agent, policy, claim, report, or other scoped business records.
_Avoid_: Business-system lookup, personalized customer answer, scoped report query

**Insurance Specialist Intent Taxonomy**:
The baseline intent set for Institution Insurance Specialist planning: business consultation or rule basis, customer or agent question answering, policy wording interpretation, report or operating-metric lookup, policy lookup, claim lookup, and mixed multi-step questions that combine clarification, retrieval, and authorized read tools. It is a configuration and evaluation anchor, not a closed list of insurance-related user intents.
_Avoid_: Free-form planner action space, product-line-specific topology, model-only routing

**Dynamic Insurance Business Subplan**:
A trace-safe plan artifact produced by the LLM ReAct Planner for insurance-related Institution Insurance Specialist requests, describing inferred business intent, missing information, evidence needs, allowed knowledge retrieval, allowed read-tool proposals, source-authority expectations, and response-shaping needs while still executing through the fixed Controlled ReAct Workflow nodes.
_Avoid_: Workflow Template topology, executable policy, direct tool execution, raw chain-of-thought

**Unmodeled Insurance Specialist Intent Signal**:
A trace-safe LLM-classified signal that the user's request may fall outside the Insurance Specialist Intent Taxonomy. It may inform a Dynamic Insurance Business Subplan, clarification, refusal, operator explanation, analytics, or future configuration design, but it does not expand the ReAct Action Set, Tool Proposal Scope, Workflow Template topology, or PolicyEngine authority for the current run.
_Avoid_: New executable action, automatic tool unlock, hidden topology change, prompt-defined policy

**Insurance Source Authority Order**:
The business-source precedence used by an Institution Insurance Specialist Agent when sources could conflict: authorized business-system records answer current state, policy wording and operational documents answer rules and interpretation, report systems answer statistical or management metrics with their period and calculation basis, and unresolved conflicts produce an explicit source-conflict answer rather than an invented reconciliation.
_Avoid_: Prompt-only preference, model arbitration, silent source merging, latest-looking answer

**Assisted Service Mode**:
An operating mode where the Agent produces governed answer suggestions for human staff rather than directly replying to end customers.
_Avoid_: Fully autonomous customer service, direct customer chatbot

**Autonomous Customer Service Mode**:
An operating mode where the Agent sends governed replies directly to end customers through a customer-facing surface.
_Avoid_: Assisted service mode, staff-only answer suggestion

**Assisted QA Chat Frontend**:
An operator-facing chat surface for submitting enterprise QA questions and reviewing governed answer suggestions, evidence, approval state, and audit links.
_Avoid_: Direct customer chatbot, observability dashboard

**Customer Service Chat Frontend**:
A customer-facing chat surface that submits customer messages to a Published Agent and returns governed replies, refusals, clarification requests, or safe follow-up acknowledgements.
_Avoid_: Assisted QA Chat Frontend, observability dashboard

**Customer Service Web Chat**:
The V1 Customer Service Chat Frontend delivered as a browser-based customer chat surface.
_Avoid_: Omnichannel customer service, channel adapter

**Unified Chat Frontend**:
A shared browser chat surface that presents consistent design and conversation flow for operator and customer chat modes while preserving audience-specific response projections.
_Avoid_: Merged internal/customer permissions, customer-visible audit console

**Text-Only Customer Intake**:
The V1 customer-service input boundary where customers submit text messages but not files, images, audio, or other attachments.
_Avoid_: Attachment analysis, customer document upload, OCR intake

**Anonymous Customer Session**:
A customer-facing conversation that is not bound to a verified customer identity and may only receive generic evidence-backed policy answers.
_Avoid_: Authenticated customer session, staff conversation

**Authenticated Customer Session**:
A customer-facing conversation bound to a verified customer identity and an explicit authorization scope.
_Avoid_: Anonymous customer session, raw login token

**Customer Authorization Context**:
The trace-safe customer identity and permission summary admitted into a customer-facing Harness run as Structured Control Context for policy, planner/reviewer, Tool Gateway, trace, and receipt behavior.
_Avoid_: Raw identity token, customer profile dump, tool credential

**Customer-Owned Resource Handle**:
A generic trace-safe identifier for a customer-owned business resource, with the resource type and id supplied by a Customer Run Adapter or future Customer Identity Adapter.
_Avoid_: Framework-owned policy id, framework-owned claim id, raw customer record

**Customer-Owned Resource Resolution**:
The deterministic match between a customer request, Customer Authorization Context, normalized input parameters, and any Owned Resource Handle Index data that identifies exactly one customer-owned account, policy, claim, or service record for a customer-specific read.
_Avoid_: Planner guess, most-recent default, broad customer profile lookup

**Customer Resource Resolution Basis**:
The internal audit record explaining how Customer-Owned Resource Resolution identified exactly one resource, including the handle index source, matched trace-safe resource identifier, matching rule, and whether disambiguation was skipped.
_Avoid_: Customer-visible authorization reason, raw resource payload, planner rationale

**Customer Resource Disambiguation Prompt**:
A customer-safe Clarification Request that presents bounded, minimal option handles for customer-owned resources so the customer can select exactly one resource for a Single-Resource Customer Read.
_Avoid_: Bulk status listing, raw resource export, hidden default selection

**Customer-Safe Resource Handle**:
A customer-visible resource identifier fragment or short descriptor used for disambiguation, such as a fixture-provided id, last-four identifier, date, or resource type label, without exposing status, amount, coverage, internal customer id, raw payload fields, or authorization details.
_Avoid_: Raw resource id, internal customer id, status-bearing summary

**Owned Resource Handle Index**:
A trace-safe set of customer-owned resource handles and optional resource counts supplied by Customer Authorization Context, Mock Customer Persona fixtures, or a future Customer Identity Adapter for disambiguation before a Single-Resource Customer Read.
_Avoid_: Policy status result list, claim status result list, bulk tool lookup cache

**Customer Disambiguation Option Mapping**:
A short-lived conversation-scoped mapping from customer-visible option handles in a Customer Resource Disambiguation Prompt to trace-safe customer-owned resource identifiers, linked to the originating run and Customer Response Snapshot and valid only for the current clarification sequence.
_Avoid_: Customer Authorization Context, Case Memory, bulk resource index

**Mock Authenticated Customer Session**:
A deterministic V1 authentication stand-in that supplies a verified customer identity and authorization scope without integrating a production identity provider.
_Avoid_: Production OAuth session, anonymous customer session, raw bearer token

**Mock Customer Persona**:
A deterministic customer identity and owned-resource fixture used to prove customer authorization behavior in V1.
_Avoid_: Single hard-coded customer, production customer record

**Cross-Customer Access Attempt**:
A customer-facing request that tries to read another customer's account, policy, claim, or service data and must create an internal Customer Escalation Handoff after the customer-specific read is blocked.
_Avoid_: Valid customer lookup, generic policy question

**Customer Identity Adapter**:
A future adapter boundary that converts production identity-provider assertions into Customer Authorization Context.
_Avoid_: Harness-owned OAuth flow, raw identity provider token

**Read-Only Customer Service**:
A customer-service scope where the Agent may answer questions and retrieve customer-specific facts but cannot change business state.
_Avoid_: Transactional customer service, self-service operations

**Customer-Specific Read Tool**:
A governed tool that retrieves facts about the authenticated customer's own account, policy, claim, or service status without changing business state.
_Avoid_: Write tool, transaction tool, generic knowledge retrieval

**Single-Resource Customer Read**:
A customer-specific read that targets exactly one customer-owned account, policy, claim, or service record after Customer-Owned Resource Resolution.
_Avoid_: Bulk customer resource listing, broad account export, guessed default resource

**Policy-Authorized Read Tool**:
A Customer-Specific Read Tool that runs inside a governed Harness run and that PolicyEngine may allow automatically when customer identity, authorization scope, tool risk, and parameters satisfy V1 read-only rules.
_Avoid_: Human-approved customer lookup, ungoverned tool call

**Policy Status Lookup Tool**:
A Policy-Authorized Read Tool that retrieves the authenticated customer's policy status without changing business state.
_Avoid_: Generic customer lookup, policy modification tool

**Claim Status Lookup Tool**:
A Policy-Authorized Read Tool that retrieves the authenticated customer's claim status without changing business state or deciding claim outcome.
_Avoid_: Claim submission tool, claim approval tool, payment commitment

**Authorized Tool Result**:
A trace-safe, redacted result returned by Tool Gateway after PolicyEngine and tool authorization checks allow a governed tool call, with customer-facing references projected through Customer-Safe Source Label values.
_Avoid_: Accepted Evidence, raw tool payload, ungoverned tool response

**Customer Tool Authorization Denial**:
An internal deterministic denial recorded when PolicyEngine or Tool Gateway refuses a customer-specific read before execution because identity, ownership, parameter, risk, or Tool Contract authorization conditions are not satisfied.
_Avoid_: Customer-visible policy explanation, raw tool error, model refusal

**Customer Tool Execution Failure**:
An internal failure recorded when an authorized customer-specific read cannot complete because Tool Gateway, adapter, dependency, timeout, or runtime execution failed after authorization.
_Avoid_: Customer Tool Authorization Denial, insufficient evidence, raw tool error

**Customer Tool Retry Run**:
A new governed Customer Run API turn that retries a customer-specific read after a Customer Tool Execution Failure while linking to the failed run for audit continuity.
_Avoid_: Tool replay, reused authorization, same-run retry

**Customer Tool Failure Series**:
The linked sequence of Customer Tool Execution Failure and Customer Tool Retry Run records for the same conversation, customer-owned resource, and tool intent.
_Avoid_: Automatic handoff, hidden retry loop, merged failure

**Transactional Customer Action**:
A customer-service action that changes business state, creates obligations, submits requests, modifies records, or makes payment or coverage commitments.
_Avoid_: Read-only lookup, policy explanation

**Transactional Insurance Operation**:
An institution-facing or customer-facing insurance operation that changes business state, creates obligations, submits requests, modifies records, approves or settles claims, changes policy status, adjusts premium or commission, sends outbound messages, or creates external work items.
_Avoid_: Read-only report lookup, read-only policy lookup, read-only claim lookup, clause interpretation

**Payment Or Coverage Guarantee Request**:
A customer-facing request that asks the Agent to guarantee claim payment, coverage, reimbursement amount, eligibility, deadline, or service commitment before governed evidence and authorized review support such a claim.
_Avoid_: Evidence-backed policy explanation, authorized read-only status lookup

**Customer Escalation Handoff**:
An internal traceable follow-up record created when the Agent cannot safely complete a customer-facing run autonomously and the reason is operationally significant, security-relevant, or explicitly configured for follow-up.
_Avoid_: Customer-visible escalated-to-human outcome, real ticket creation, silent failure

**Handoff-Safe Customer Wording**:
Customer-facing text used when an internal handoff is created, phrased as a safe service acknowledgement or limitation without exposing internal escalation status.
_Avoid_: Escalated to human, agent failed, internal queue status

**Customer Handoff Event**:
A trace event that records creation of an internal Customer Escalation Handoff without changing the customer-visible final outcome.
_Avoid_: Final outcome, customer-visible escalation status, ticket event

**Handoff Reason**:
A fixed reason code explaining why a Customer Escalation Handoff was created.
_Avoid_: Free-form handoff note, customer-visible explanation

**Handoff Trigger Policy**:
The governed rule set that decides which customer-service conditions create an internal Customer Escalation Handoff.
_Avoid_: Frontend-defined trigger, prompt-defined trigger, arbitrary user-defined escalation

**Handoff Projection**:
An internal Dashboard/RunStore read projection that shows Customer Escalation Handoff records for monitoring and run-detail drilldown.
_Avoid_: Customer-Safe Response Projection, ticket workflow state

**Controlled Conversation Context**:
Conversation history and short-lived clarification state admitted into a new Harness run only after policy, redaction, length, and relevance checks.
_Avoid_: Raw transcript injection, unrestricted chat memory

**Conversation Store**:
The local conversation timeline store that links chat turns to governed run artifacts.
_Avoid_: RunStore, persistent enterprise memory

**Controlled Agent Memory**:
The governed memory capability set that lets an Agent retain, retrieve, and admit prior information only through explicit Control Envelope checks.
_Avoid_: Unrestricted agent memory, raw chat history, automatic self-learning

**Hybrid Memory Framework**:
A Controlled Agent Memory design that can use multiple memory provider adapters without binding product memory layers to any provider's native taxonomy.
_Avoid_: Vendor-owned memory taxonomy, hidden prompt cache, framework-defined governance

**Memory Provider Adapter**:
A Capability Layer adapter that connects an external or internal memory engine to Proof Agent memory contracts without giving that engine authority over Harness decisions.
_Avoid_: Direct memory backend, model-owned memory, uncontrolled memory plugin

**Agent Memory Configuration**:
The Agent-specific memory settings that choose a Memory Provider Adapter and configure governed memory scopes, retention, record limits, restricted-data handling, and lifecycle controls.
_Avoid_: Reusable memory asset, Accepted Evidence source, cross-Agent memory pool

**Case Memory**:
Memory scoped to one case, task, customer issue, or conversation journey, containing admitted structured case facts or bounded trace-safe summaries rather than complete customer-visible messages.
_Avoid_: Persistent user profile, audit log, raw conversation transcript

**Case Memory Lifecycle Controls**:
The governed controls for inspecting, deleting, expiring, and auditing Case Memory without exposing internal memory contents to customers.
_Avoid_: Customer-visible memory management, unrestricted memory admin, raw memory dump

**Case Focus**:
The current case's active topics, requested report views, filters, or unresolved areas of interest used for follow-up understanding inside Case Memory.
_Avoid_: Persistent user interest profile, marketing preference, cross-session behavioral profile

**Institution Specialist Case Memory**:
Case Memory for an Institution Insurance Specialist run that may retain current task focus, question source, report period, filters, clarified identifiers, business-line scope, and response-format preferences inside the current case or conversation only. It must not become a long-lived source of customer identity facts, agent facts, policy status, claim status, report values, tool payloads, or clause-interpretation conclusions.
_Avoid_: Staff profile, customer profile, policy or claim source of truth, report cache, tool-result memory

**Persistent User Memory**:
Long-lived memory about a user or customer that may be reused across conversations only when consent, retention, deletion, redaction, tenant boundary, and policy admission rules are defined.
_Avoid_: Case Memory, customer transcript archive, automatic behavioral profile

**Customer Persistent User Memory**:
Persistent User Memory scoped to a customer reference and reused across customer conversations only for governed long-lived preferences, recurring interests, and follow-up context.
_Avoid_: Operator profile, Case Memory, report result cache, policy or claim source of truth

**Customer Memory Interest Profile**:
A Customer Persistent User Memory subset that records durable attention areas, preferred report views, and interaction preferences without storing business result values or sensitive customer facts.
_Avoid_: Report cache, customer data profile, marketing persona, raw transcript summary

**Customer Memory Consent**:
The explicit permission boundary that allows Customer Persistent User Memory to be read or written for a customer reference across customer conversations.
_Avoid_: Authentication state, generic privacy banner, tool authorization, marketing consent

**Customer Memory Lifecycle Controls**:
The governed controls for exporting, deleting, auditing, and disabling Customer Persistent User Memory at the customer reference boundary.
_Avoid_: Single-turn correction UI, raw provider memory browser, customer data export of business records

**Memory Subject Reference**:
A provider-neutral identifier for the subject a memory is about; Customer Persistent User Memory uses the customer reference as its Memory Subject Reference.
_Avoid_: Case id, raw customer identity document, provider user id, authentication token

**Shared Memory**:
Long-lived organizational memory shared across users or Agents after governance admission.
_Avoid_: Knowledge Provider, uncontrolled internal notes, model fine-tuning data

**Memory Admission**:
The Control Plane decision that determines whether retrieved memory may enter the Structured Control Context or model request for a governed run.
_Avoid_: Automatic memory injection, raw memory recall

**Customer Conversation Retention Policy**:
The rule that limits how long customer-facing conversation text is kept for user experience and follow-up resolution.
_Avoid_: Permanent customer transcript storage, audit retention policy

**Audit Retention Boundary**:
The separation between short-lived customer conversation text and longer-lived trace-safe run audit facts.
_Avoid_: Raw transcript archive, unrestricted audit log

**Run Artifact Consistency**:
The requirement that Trace, Governance Receipt, run metadata, and read projections describe the same governed run facts.
_Avoid_: Post-finalize trace mutation, receipt drift, projection-only audit fact

**Internal Governance Dashboard**:
The internal observability surface for inspecting governed runs, traces, receipts, stats, and escalation handoff records.
_Avoid_: Customer Service Chat Frontend, customer response UI, full admin console

**Dashboard Shell**:
The shared internal web workspace that hosts both observability views and Agent configuration views while preserving separate API boundaries for observation, configuration, and execution.
_Avoid_: Single backend API surface, customer-facing console, ungoverned execution UI

**Agent-Centric Dashboard Shell**:
A Dashboard Shell information architecture where each Agent detail view combines monitoring, configuration, validation, versioning, and contract inspection for that Agent.
_Avoid_: Settings-only configuration, detached builder app, global-only run dashboard

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

**Customer-Safe Knowledge Citation Projection**:
The customer-visible citation representation that shows a safe source name and page or section where appropriate without exposing internal revision ids, storage paths, provider secrets, or operator-only metadata.
_Avoid_: Internal citation URI, filesystem path, hidden-source omission

**Customer Citation Marker**:
The short inline customer-facing reference marker such as `[1]` or `[2]` that points to a deduplicated Customer-Safe Knowledge Citation Projection in the answer's Sources list.
_Avoid_: Internal citation URI, provider id, revision id, confidence disclosure

**Customer Sources List**:
The customer-facing end-of-answer list that maps Customer Citation Markers to safe source name, page or section, and safe document title. Repeated references to the same safe source location share one marker.
_Avoid_: Provider details, internal ids, mutable-external technical warning, raw URL without allowlist

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

**Knowledge Source Versions Tab**:
The Knowledge Source Detail Workspace history surface for published snapshots or configuration versions. It shows publication time, actor, `change_note`, validation result, referencing Agent count, and version diff actions.
_Avoid_: Mutable current-state-only view, hidden validation history, Agent version list

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

**Local Configuration Store Reset**:
The development-environment cleanup action that clears generated local Agent Configuration Store state, including Draft Agents, Published Agent Versions, Knowledge Sources, local-index artifacts, snapshots, and compiled configuration packages, without deleting source-controlled examples, tests, documentation, or retained run audit history. Breaking Knowledge Source or Agent Contract configuration changes, including stage/capability contract cutovers, do not carry a legacy local-store compatibility path; stale generated local Configuration Store data is reset and rebuilt.
_Avoid_: Source migration, production data deletion, RunStore audit purge, fixture cleanup, legacy local-store dual-read

**Sidebar Navigation Section**:
The two top-level sections in the Dashboard Shell sidebar: MONITORING for observability views (Overview, Runs, Handoffs, Approvals) and CONFIGURATION for design-time views (Agents, Policies, Knowledge Sources, Tools). Each section groups related navigation items under a visible header.
_Avoid_: Flat navigation list, mixed monitoring and configuration items, role-based sections

**Internal Handoff Monitor**:
The V1 dashboard projection for reviewing Customer Escalation Handoff records and drilling into their governed run details.
_Avoid_: Ticket workflow, SLA queue, assignment console

**Agent Control Platform Console**:
A future administrative console for RBAC, tenant management, multi-Agent configuration, approval operations, and platform governance.
_Avoid_: Internal Governance Dashboard, Customer Service Web Chat

**Insurance Service QA Domain**:
The first customer-service domain for the Enterprise QA Reference Agent, covering insurance product term interpretation, service process guidance, policy questions, and authenticated read-only service lookups.
_Avoid_: Generic enterprise QA, direct claims decisioning

**Harness RAG**:
An evidence-backed RAG flow governed by the Control Envelope.
_Avoid_: Plain RAG, uncontrolled RAG

**Plain RAG**:
A retrieve-then-generate flow without Harness policy gates or evidence admission.
_Avoid_: Harness RAG

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

**Knowledge Source Permission Model**:
The configuration capability boundary for reusable knowledge assets. `knowledge_source.view` gates Source, document, upload, job, candidate snapshot, frozen snapshot, publication validation, publication, and deletion-eligibility reads. `knowledge_source.edit` gates Source creation, document upload, document routing metadata edits, ingestion retry, foundation validation, snapshot freeze, and restore. `knowledge_source.publish` gates publication validation and publication. `knowledge_source.archive` gates Archive and Knowledge Source Physical Deletion. Knowledge Source API command requests do not carry actor fields; the API resolves Operator Identity Context server-side and records the resolved operator in Knowledge Configuration Operation Audit. V1 local single-user mode may grant all capabilities by default, but API operations, Dashboard actions, and audit records preserve the distinctions for future RBAC.
_Avoid_: One knowledge admin boolean, Agent permission reuse, runtime retrieval authorization, request-body actor

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

**Merged Evidence Admission Evaluation**:
The fail-closed admission rule for an exactly deduplicated Candidate Evidence chunk: WRRF contributions may combine for ranking, but duplicate retrieval hits do not increase Evidence Admission Score. An approved admission scorer evaluates the merged normalized chunk once when configured; otherwise the merged candidate uses the minimum available calibrated Evidence Admission Score from its contributing sources. Contributors without a calibrated admission score remain traceable but do not participate in score aggregation, and a merged candidate with no valid admission score remains inadmissible.
_Avoid_: Score boosting from duplicate hits, maximum-score selection, averaging incomparable scores, missing-score fallback

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

**Knowledge Source Implementation Sequence**:
The agreed implementation order for the Dashboard Knowledge Source capability: contract and loader migration first, then Source store and API, local index ingestion, multi-source retrieval runtime, Dashboard workspace, and finally fixtures and tests migration.
_Avoid_: UI-first partial model, compatibility shim first, runtime fusion before contracts

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

**Knowledge Source Routing Model Configuration**:
The optional Agent-specific query-time model provider configuration used after deterministic Knowledge Source Routing cannot make a clear bounded selection. It must route through Proof Agent ModelProvider governance, emit trace-safe routing facts, and fail closed without querying every source.
_Avoid_: Knowledge Routing Model Configuration, Agent answer model, provider configuration, raw credential storage

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

**Knowledge Ingestion Model Configuration**:
The Knowledge Source-specific model provider configuration used by the Knowledge Ingestion Worker to build provider-backed index artifacts.
_Avoid_: Agent answer model, raw credential storage, deterministic demo dependency

**Knowledge Routing Model Configuration**:
The Knowledge Source-specific query-time model provider configuration used for Knowledge Document Routing, inheriting Knowledge Ingestion Model Configuration by default while allowing an explicit override.
_Avoid_: Agent planner model, raw credential storage, mandatory separate model

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

## Relationships

- Proof Agent is a **Controlled Agent Harness Framework**.
- V1 ships both an **Agent Framework Deliverable** and the **Insurance Customer Service Agent** reference implementation.
- The **Insurance Customer Service Agent** must validate the **Agent Framework Deliverable** without becoming the whole product.
- An **Agent Contract** selects a **Workflow Template** for a run.
- A **Workflow Template Execution** executes exactly one selected **Workflow Template** inside the **Control Envelope**.
- A **Workflow Template Execution** is run-scoped; registered **Workflow Template Stages** are governed stages, not separate execution entry points.
- A **Workflow Template Execution** applies **Workflow Stage Prompt Configuration** as **Business Context Addendum** and allowed **Structured Control Context** without replacing Harness-owned control prompts.
- Agent Contract `workflow.stages[]` stores **Workflow Stage Configuration Override** entries only; available stages omitted from the array use descriptor defaults when building **Effective Workflow Stage Configuration**.
- Agent Publication stores **Workflow Stage Configuration Override** entries, the **Workflow Template Descriptor Version**, and a full **Published Effective Workflow Stage Configuration Snapshot** so historical run explanation does not depend on reconstructing descriptor defaults later.
- The first **Workflow Stage Prompt Field Set** is limited to `business_context`, `task_instructions[]`, and `output_preferences[]`; role or persona guidance must be expressed through those bounded business fields rather than a separate `role_guidance` field.
- **Workflow Stage Context Option Configuration** uses descriptor-allowed boolean keys under `workflow.stages[].context`; missing keys inherit descriptor defaults, explicit `true` includes the option, and explicit `false` disables the option for that stage.
- **Effective Workflow Stage Context Option Allowlist** removes context options whose prerequisite capability is unavailable; published Agent Contract YAML must not contain those context keys even with value `false`, and Draft Agents treat them as inactive blockers until cleared or the capability is restored.
- Default run trace records **Workflow Stage Configuration Trace Summary** plus Published Agent Version or **Published Effective Workflow Stage Configuration Snapshot** reference, not full stage Prompt or selected context payloads.
- When **Workflow Stage Trace Capture Mode** is enabled for validation, Proof Agent may record full stage Prompt values, selected context values, and intermediate **Workflow Stage Result** details, but still must not record raw chain-of-thought, secrets, raw evidence content, raw tool payloads, complete provider responses, or Runtime Plane state dictionaries.
- **Workflow Stage Trace Capture Mode** full capture is allowed only for Agent Validation Runs or explicit test runs; production and customer-facing runs are forced to summary-only trace behavior.
- **Workflow Stage Trace Capture Mode** belongs to the Agent Validation Run or explicit test-run request, not to the Published Agent Version or production Agent Contract snapshot.
- **Workflow Stage Trace Capture Mode** is an observability request policy, not a field in **Workflow Template Execution Input**; Workflow Template Execution runs from the same semantic input regardless of whether the run records summary-only trace or a gated validation capture artifact.
- Full capture output is a **Sensitive Validation Capture Artifact**: access requires `agent.validate` or stronger configuration permission, ordinary run viewers and customer support viewers cannot see it, ordinary receipts or exports exclude it, and Dashboard exposes it only through an explicit validation detail reveal.
- **Sensitive Validation Capture Retention** gives Sensitive Validation Capture Artifacts a default 7-day TTL while ordinary Workflow Stage Configuration Trace Summary, receipt facts, and validation pass/fail results remain under normal run artifact retention; deleting expired full capture must not change the governed run outcome or summary trace.
- Extending Sensitive Validation Capture Retention through `retain_for_audit` requires an explicit authorized validation/test-run request and must show the artifact expiry or audit-retention status in Dashboard.
- **Agent Contract Stage Capability Implementation Sequence** proceeds in four slices: direct contract schema cutover; descriptor, availability, and effective configuration publication; Workflow Template Execution consumption of frozen configuration; validation trace capture with Sensitive Validation Capture Artifact retention and access controls.
- `ReActWorkflowNodes` is excluded from the first **Stage Terminology Code Cutover Scope** because it currently acts as runtime graph handler assembly; renaming or splitting it belongs to the Workflow Template Execution consumption slice.
- **Harness Prompt Authority Boundary** means `workflow.stages[].prompt` must not expose `system_prompt`, `developer_prompt`, or `raw_prompt`; loaders and validation reject those fields because they imply control prompt authority rather than business context.
- A **Workflow Template Execution** produces governed execution facts, while the Run Execution surface owns artifact finalization, Governance Receipt rendering, and RunStore persistence.
- A **Workflow Template Execution Result** contains governed execution facts such as outcome, final output, approval pause, clarification request, evidence basis, governance summaries, stage results, model usage summary, and trace-safe references; it must not contain artifact paths, RunStore detail payloads, Dashboard projections, raw Runtime Plane state, raw Prompt/context payloads, or full-capture artifacts.
- Slice 2 uses a **Workflow Stage Result Envelope** for React Enterprise QA stages instead of defining a complete per-stage result union; analyzing whether to introduce a complete union of stage-specific result contracts is a later TODO.
- **Workflow Stage Result Summary** follows ordinary trace and receipt safety: raw Prompt text, selected context text, raw evidence content, raw tool payloads, complete provider responses, raw chain-of-thought, Runtime Plane state dictionaries, secrets, and secret-looking values are excluded even when the result is used inside Workflow Template Execution.
- React Enterprise QA Slice 2 stage handlers should return **Workflow Stage Result Envelope** values as their Control Plane facts; a **Workflow Stage Result Runtime Adapter** may convert those results into LangGraph state deltas for scheduling, routing, checkpoint, and interrupt mechanics.
- **Workflow Stage Continuation State** may carry typed governed objects or state-safe dictionaries needed for subsequent stage execution, but it is not part of ordinary trace, receipt, Dashboard projection, or Workflow Template Execution Result facts.
- A **Workflow Template Execution** may produce an **Approval Pause**; the Runtime Plane may implement that pause with checkpoint or interrupt mechanics, but those mechanics are not the approval authority.
- A **Workflow Template Execution Result** carries **Approval Pause** as a first-class governed fact when execution is waiting for approval; Runtime Plane interrupt payloads are derived from that fact rather than defining it.
- A **Workflow Template Execution Result** carries **Clarification Need** separately from **Approval Pause** because waiting for user information and waiting for operator tool approval are different governed states.
- **Workflow Execution Contract Module** is the home for Workflow Template Execution contracts; `contracts/run.py` remains for run artifact results, and `contracts/react_workflow.py` remains for ReAct-specific action and reasoning contracts.
- **Workflow Stage Configuration Contract Module** is the neutral home for stage availability, effective configuration, and runtime source facts shared by Agent Publication and Workflow Template Execution, so neither Published Agent Version storage nor Runtime Plane adapters own those facts.
- The slice after React Enterprise QA Slice 2 makes **Published Effective Workflow Stage Configuration Runtime Input** the source of truth for Workflow Template Execution stage configuration, rather than recomputing effective stage configuration from latest descriptor defaults or raw manifest overrides at run time.
- Configuration Store **Published Agent Version** execution must fail closed when its **Published Effective Workflow Stage Configuration Snapshot** is missing, while package-local or configured Agent execution may use a **Package-Local Workflow Stage Configuration Runtime Input** built from the latest supported Agent Contract structure.
- **Workflow Template Execution Input** carries the Effective Workflow Stage Configuration value for execution and **Workflow Stage Configuration Runtime Source** metadata for trace-safe explanation; ordinary trace and receipt projections record only source/reference and summary, not full Prompt or selected context values.
- **Workflow Template Execution Input** carries only template-generic run facts; template-specific planner admission facts such as **Effective ReAct Action Set** remain inputs to the concrete Workflow Template Execution that needs them.
- React Enterprise QA stage Prompt and context consumers read Effective Workflow Stage Configuration from **Workflow Template Execution Input**; raw Agent Contract `workflow.stages[]` overrides are not the runtime source for Workflow Template Execution.
- **Effective Workflow Stage Configuration** is the neutral value used by **Workflow Template Execution Input**; **Published Effective Workflow Stage Configuration Snapshot** is the Published Agent Version capture of that value, not the general runtime type for package-local execution.
- **Effective Workflow Stage Configuration** is made of typed **Effective Workflow Stage Configuration Stage** entries rather than arbitrary mappings, so stage identity, descriptor version, available context options, Prompt configuration, context selection, and source override facts have stable contract boundaries.
- Agent Publication and package-local Workflow Template Execution use the same Control Plane **Effective Workflow Stage Configuration** resolution semantics; Runtime Plane adapters and Configuration Store storage details do not independently reinterpret stage defaults, availability, context allowlists, or overrides.
- **Effective Workflow Stage Configuration** contains available stage configuration only; unavailable stage explanations belong to **Workflow Stage Availability Set** and trace-safe availability summaries, not to executable stage Prompt or context configuration.
- **Workflow Stage Availability Set** is a typed Workflow Template Execution input fact, not an ad hoc runtime helper; Runtime Adapters consume it for routing and fail-closed guards without reinterpreting capability configuration.
- **Published Agent Version** stores **Workflow Stage Availability Set** separately from **Published Effective Workflow Stage Configuration Snapshot**; the snapshot serializes only the available-stage **Effective Workflow Stage Configuration** value, while availability explains unavailable stages.
- **Published Agent Runtime Facts** carry the resolved Workflow Stage Availability and Published Effective Workflow Stage Configuration Runtime Input from Published Agent resolution into Workflow Template Execution; Published Agent Directory projections do not expose those execution-only facts.
- A paused **Workflow Template Execution** resumes with the same **Workflow Template Execution Input** selected at run start; approval resume must not recompute Effective Workflow Stage Configuration from mutable descriptors, package-local YAML, or Configuration Store state.
- **Workflow Template Execution Resume Metadata** may retain a protected reference and integrity summary for the full run-start **Workflow Template Execution Input** for checkpoint resume, but ordinary trace, Governance Receipt, RunStore detail, Dashboard projections, and customer-facing surfaces expose only trace-safe Workflow Stage configuration summaries and references.
- Approval resume fails closed when the referenced run-start **Workflow Template Execution Input** is unavailable, fails integrity validation, or no longer matches the executable Workflow Template Descriptor Version selected for the resumed run.
- Before Workflow Template Execution starts, ordinary trace records a run-level **Workflow Stage Configuration Trace Summary** for the selected **Workflow Template Execution Input**; this summary does not include full Prompt text, selected context values, intermediate Workflow Stage Result details, or Sensitive Validation Capture Artifact content.
- The common governed run entry point creates the run-scoped **Workflow Template Execution Input** after the run id is selected, while Control Plane Effective Workflow Stage Configuration resolution supplies the value and Delivery supplies Published Agent Version facts when available.
- **Resolved Workflow Stage Runtime Configuration** is the single Control Plane output used to freeze Agent Publication stage facts, build package-local runtime inputs, wrap Published Agent Runtime Facts for execution, emit Workflow Stage Configuration Trace Summary, and provide template-specific action admission such as Effective ReAct Action Set.
- Workflow Template Execution requires the selected executable Workflow Template Descriptor Version to match the **Workflow Template Execution Input** descriptor version and fails closed on mismatch; versioned historical executable descriptor registries are a separate future concern.
- **Published Effective Workflow Stage Configuration Runtime Consumption Slice** includes typed stage configuration contracts, Workflow Stage Availability Rules, Resolved Workflow Stage Runtime Configuration, Published Agent Runtime Facts, package-local latest runtime input, Workflow Template Execution Input runtime consumption, trace-safe run-level summary, ReAct availability and action-set guards, approval resume run-start input references, and Control Plane decoupling from LangGraph mechanics.
- Full validation capture artifact realignment, historical executable descriptor registry, dynamic Runtime Adapter topology, complete stage-specific result unions, second runtime support, and stale local-store compatibility migrations are outside the **Published Effective Workflow Stage Configuration Runtime Consumption Slice**.
- React Enterprise QA may keep a static LangGraph topology in this slice, but availability routing and fail-closed decisions are Control Plane Workflow Template Execution semantics exposed through runtime-neutral facts; LangGraph node registration, checkpointing, interrupts, and state deltas remain **Workflow Runtime Adapter** mechanics.
- Control Plane Workflow Template Execution must not directly depend on LangGraph interrupts, state dictionaries, or scheduler APIs; **Workflow Runtime Adapter** implementations translate runtime-neutral approval pauses, continuations, and stage results into concrete runtime mechanics.
- React Enterprise QA Workflow Template Execution stage handlers own Workflow Stage Availability and Effective ReAct Action Set admission before runtime routing; Runtime Adapters route only from already-admitted Workflow Stage Result continuation facts.
- **ReAct Enterprise QA Workflow Execution** is the concrete Slice 2 execution object for `react_enterprise_qa` and `react_enterprise_qa_v2`; a generic ReAct workflow execution abstraction is deferred until multiple ReAct templates need it.
- A **Workflow Template Execution Result** is the external execution Interface; **Workflow Stage Result** values remain inside Workflow Template Execution and must not leak as Runtime Plane state dictionaries.
- The public Agent Contract, Workflow Template Descriptor, trace facts, Dashboard configuration, tests, and examples use **Workflow Template Stage** language directly; Proof Agent does not dual-read legacy public stage aliases during the stage migration.
- **Direct Workflow Stage Contract Migration** adopts Agent Contract `workflow.stages[]` in one breaking change; loaders, Dashboard, examples, fixtures, tests, and stage prompt configuration APIs migrate together and reject legacy public stage fields.
- **Stage Terminology Code Cutover Scope** includes Agent Contract models, manifest loader, validation, Workflow Template descriptors, configuration APIs, Dashboard helpers, examples, fixtures, and tests; Runtime Plane graph nodes may continue using graph node terminology when they refer to actual LangGraph or runtime graph mechanics.
- **Dashboard Stage Configuration Surface Cutover** changes Agent Configuration API request and response fields to `stages`, renames Dashboard helpers to stage terminology, updates UI labels from Node Panel to Stage Panel, and migrates Dashboard tests and fixtures in the same Slice 1 cutover.
- Slice 1 does not provide a legacy Agent Contract migration script or codemod; source-controlled examples, fixtures, tests, and docs are edited directly, while stale generated local Agent Configuration Store data is cleared with **Local Configuration Store Reset** and recreated.
- **Contract Schema Cutover Test Gate** must fail before implementation for `workflow.stages[]` with `id`, rejection of legacy public stage aliases, `capabilities.tools`, `capabilities.memory`, rejection of legacy top-level `tools` and `memory`, disabled capability active config blockers, enabled tools with no valid Tool Contract, and enabled memory provider readiness.
- **Small-Step Verification Cadence** applies throughout the Agent Contract Stage Capability Implementation Sequence: each slice is broken into targeted test, minimal implementation, targeted verification, then broader regression before moving to the next slice.
- Each `workflow.stages[]` item uses **Workflow Stage Configuration Identifier** field `id`; loaders reject legacy id aliases, missing ids, duplicate ids, and ids that are not registered by the selected Workflow Template Descriptor.
- **Workflow Template Stage** names stable workflow structure; **Qualified Step** names a sequence item inside a specific process and must not replace stage terminology.
- Stage transition rules belong to **Workflow Template Execution**; **Workflow Template Descriptor** explains the public topology, and Runtime Plane Adapters only schedule mechanics such as graph execution, checkpoint, interrupt, and resume.
- **Workflow Stage Availability** may disable a stage only through template-defined capability rules; it must not become arbitrary stage or edge editing.
- **Workflow Stage Availability** is derived from capability configuration, not from per-stage enable switches; stage-local configuration may edit Prompt or allowed context only for stages that the resolved capability set makes available.
- A **Workflow Stage Availability Rule** belongs to the **Workflow Template Descriptor**, while the **Agent Contract** supplies capability facts used to resolve the **Workflow Stage Availability Set** for one Agent.
- **Workflow Stage Availability** is separate from whether a Workflow Template Stage is required; availability decides whether the stage may execute for an Agent, while requiredness describes template interpretation for available stages.
- **Agent Contract Capability Configuration** is the public YAML source for governed capability availability; Proof Agent should migrate scattered `tools` and `memory` capability declarations into this unified Agent Contract YAML structure instead of hiding capability normalization in an internal-only layer.
- **Direct Capability Contract Migration** replaces top-level Agent Contract `tools` and `memory` capability declarations with `capabilities.tools` and `capabilities.memory` in one breaking change; loaders, Dashboard, examples, fixtures, and tests migrate together and reject legacy top-level capability fields.
- Agent Contract YAML uses top-level `capabilities:` for governed capability availability; `capabilities.tools.enabled` controls the **Tool Stage Group**, and `capabilities.memory.enabled` controls memory stage availability for templates that include a memory stage.
- Agent Contract YAML keeps `knowledge_bindings[]` as a separate Agent Knowledge Binding domain, not `capabilities.knowledge`, because React Enterprise QA retrieval stages are template-required evidence behavior; missing or invalid knowledge bindings are validation or retrieval failures, not stage availability choices.
- **Explicit Capability Enablement** is required for every capability domain referenced by the selected Workflow Template's availability rules; missing domain or missing `enabled` is a schema or validation error, not `enabled: false`.
- **Enabled Capability Readiness** applies to enabled tool capability: `capabilities.tools.enabled: true` must resolve at least one valid **Tool Contract** from `capabilities.tools.file`, otherwise Agent Validation and Agent Publication fail closed.
- **Enabled Capability Readiness** applies to enabled memory capability: `capabilities.memory.enabled: true` requires a memory provider; provider-specific schema decides whether scopes are required, and scoped memory configuration must enable at least one memory scope.
- A disabled capability domain must be clean in published Agent Contract YAML: `enabled: false` may not carry active configuration fields such as `tools.file`, memory provider, or memory scopes. **Disabled Capability Configuration** may remain only as inactive Draft Agent state that blocks Agent Validation and Agent Publication until cleared or re-enabled.
- **Workflow Stage Availability Set** is resolved during Agent Publication from the Agent Contract, Workflow Template, and configured capabilities, frozen into the Published Agent Version, then copied into each run and consumed by Workflow Template Execution as a frozen run input.
- **Workflow Template Descriptor** declares supported stages and availability rules, while **Agent Contract** declares capabilities and **Published Agent Version** stores the resolved **Workflow Stage Availability Set**; normal run execution must not dynamically reinterpret stage availability from mutable template code.
- **Unavailable Stage Configuration** may remain in a Draft Agent only as inactive, Dashboard-visible configuration that blocks Agent Validation and Agent Publication until the Agent owner either clears it or restores the required capability.
- Draft Agent save may retain **Unavailable Stage Configuration** as an inactive blocker for operator repair, but Agent Validation and Agent Publication fail closed until the stage's required capability is restored and the Draft Agent validates again or the unavailable configuration is cleared.
- **Published Agent Version** snapshots must not contain effective configuration for unavailable stages; Proof Agent must not silently ignore disabled-stage config or reactivate old config when a capability is enabled later.
- **Workflow Stage Availability Event** is emitted once per run before Workflow Template Execution starts; disabled stages do not emit normal stage execution events.
- Workflow Template Execution must not route to or execute unavailable Workflow Template Stages; if a model or scheduler output selects an unavailable stage or action, the Control Envelope fails closed rather than treating the stage as silently skipped.
- **Effective ReAct Action Set** is the ReAct-specific planner action admission fact derived from **Workflow Stage Availability Set** and Tool Proposal Scope; it is separate from generic Workflow Stage Availability and excludes tool proposal actions when Tool Stage Group is unavailable.
- ReAct planning fails closed when a planner returns a **ReAct Action Proposal** outside the **Effective ReAct Action Set**; internal continuation actions are not exposed as planner-facing candidate actions.
- TODO: align the deterministic **Enterprise QA Template** with the **Workflow Template Execution** Interface after the React Enterprise QA execution seam is stable; the first refactor keeps Enterprise QA behavior as the regression baseline.
- The **Workflow Template Stage** terminology cutover must land before deepening the **Workflow Template Execution** seam so behavior-preserving contract migration and execution-ownership refactoring remain testable separately.
- **Workflow Template Stages** are reserved for Agent-owner-visible configuration, explanation, audit, or evaluation points; internal policy checks, validators, model requests, helper functions, and Runtime Plane nodes are not automatically stages.
- The **React Enterprise QA Stage Set** keeps memory and response as stages because memory governance and response projection are Control Envelope facts, not incidental return code.
- The memory stage is part of the **React Enterprise QA Stage Set**, not a mandatory stage for every future Workflow Template; other templates must explicitly include memory when memory governance is part of their Control Envelope shape.
- Memory stage availability is capability-gated; disabled-by-capability means the Agent Contract did not enable memory for that stage, while blocked-by-policy means memory was enabled but a specific memory write was denied by the Control Envelope.
- The **React Enterprise QA Stage Set** keeps retrieval_review separate from retrieval, and tool_review separate from tool, so review context, review decisions, capability execution, and approval pauses remain explainable as distinct Control Envelope facts.
- The **Tool Stage Group** must be enabled or disabled as a pair; a run must not execute tool without tool_review, and tool_review must not be editable when the tool stage is unavailable.
- When the **Tool Stage Group** is disabled, **Effective ReAct Action Set** excludes tool proposal actions; any model output outside the Effective ReAct Action Set fails closed as a Control Envelope violation.
- Retrieval_review and retrieval remain available in **React Enterprise QA Stage Set** because evidence-first retrieval is part of the template's governed promise; missing or invalid Knowledge Bindings are validation or retrieval failures, not stage availability choices.
- Response stage configuration is projection-only: it may affect allowed wording and trace-safe context summaries, but it must not change governed outcome, evidence admission, approval state, customer-safe boundaries, Governance Detail Projection caps, trace facts, or receipt facts.
- A **Controlled ReAct Workflow** is a **Workflow Template**.
- The **React Enterprise QA Template** is separate from the existing **Enterprise QA Template** so deterministic Enterprise QA remains the regression baseline.
- The **React Enterprise QA Template** must include a **Deterministic ReAct Demo** before remote model paths are required.
- V1 **Autonomous Customer Service Mode** uses the **React Enterprise QA Template** as its primary customer-facing Workflow Template.
- The existing **Enterprise QA Template** remains the deterministic regression baseline and compatibility path.
- The **React Enterprise QA Template** uses a **ReAct Planner** configured by **ReAct Planner Config**.
- A **LLM ReAct Planner** is a separate ReAct Planner implementation and must not replace the **Deterministic ReAct Demo** path.
- A **LLM ReAct Planner** is the first LLM-backed implementation priority for **Business Agent AI Core**.
- V1 **Autonomous Customer Service Mode** is real-LLM capable through configured model roles while the deterministic model, planner, and reviewer remain the release gate.
- The **ReAct Planner**, **Harness Review Subagent**, and final answer model are separate roles even when a deterministic demo implementation shares local code.
- **Business Agent AI Core** includes final answer generation and **ReAct Planner** behavior.
- **Harness Decision Assistance** includes **Harness Review Subagent** behavior.
- A **LLM Harness Review Subagent** is a separate Harness Review Subagent implementation and must not replace deterministic review behavior used by tests and demos.
- A **LLM Harness Review Subagent** follows the **LLM ReAct Planner** implementation pattern for model calls, output normalization, validation, and fail-closed tracing.
- **Business Agent AI Core** and **Harness Decision Assistance** may use the same **Model Provider Registry** while remaining separately configured instances.
- **Business Agent AI Core** is configured through existing final answer `model` and **ReAct Planner Config** fields, not through a new top-level `ai_core` field.
- **Harness Decision Assistance** is configured through **Review Subagent Config**, not through a new top-level `ai_core` field.
- **Model Provider Registry** provider names describe external model channels, not Proof Agent role names.
- Final answer generation, **LLM ReAct Planner**, and **LLM Harness Review Subagent** choose their role through their Agent Contract section, not through role-specific provider names.
- V1 LLM integration uses **Harness-Normalized Model Output** for final answers, **ReAct Action Proposal** values, and **Review Decision** values.
- Planner and reviewer paths use a **Model Output JSON Contract** and should request JSON output from the selected **Model Provider Registry** entry when supported.
- A **Model Output JSON Contract** may be parsed from a full JSON response or a single fenced JSON object, but must not be inferred from natural language.
- V1 planner, reviewer, and final answer model calls are non-streaming so validation and audit can complete before output is treated as valid.
- A **Model Output Normalization Failure** must stop or constrain the current control path rather than guessing the intended model behavior.
- A **Model Output Normalization Failure** from a **LLM ReAct Planner** fails the planning path closed and is traced with the parse or validation reason.
- A **Model Output Normalization Failure** from a **LLM Harness Review Subagent** follows **Review Failure Policy**.
- A **Model Output Normalization Failure** from final answer generation is handled as output validation failure and must not be shown as a valid answer.
- Provider-native tool call payloads must not execute tools directly; a future **Native Tool Call Adapter** must convert them into Harness-governed proposals first.
- Final answer generation, **LLM ReAct Planner**, and **LLM Harness Review Subagent** all emit model call trace events with a **Model Call Role**.
- A **Model Call Role** distinguishes model calls such as `final_answer`, `react_planner`, and `harness_review` while preserving shared model usage accounting.
- A **LLM ReAct Planner** and **LLM Harness Review Subagent** use **Harness Control Prompt** templates maintained by Proof Agent.
- An **Agent Contract** may configure model provider, model name, and provider parameters for planner and reviewer roles, but must not replace the **Harness Control Prompt** in V1.
- **Harness Control Prompt** inputs come from **Structured Control Context**, not raw user transcripts, raw evidence content, secrets, or arbitrary Agent-authored prompt overrides.
- **Structured Control Context** may include user question, Agent purpose, ReAct Action Budget, allowed actions, tool risk summary, evidence state, conversation summary, enforcement point, and policy-relevant metadata.
- A model may produce a **ReAct Action Proposal**, but only **Auto Review Mode** or another Harness review path can admit it for execution.
- Every **ReAct Action Proposal** must use the fixed **ReAct Action Set**; non-enumerated actions are denied and traced.
- Every tool-call **ReAct Action Proposal** must name a tool inside the run's **Tool Proposal Scope**, which is derived from the **Agent Contract** tool scope and matching **Tool Contract** definitions.
- **Auto Review Mode** may use a **Harness Review Subagent** as a Control Plane component.
- A **Harness Review Subagent** reviews Harness control nodes; it does not generate the final user answer.
- A **Harness Review Subagent** is configured by **Review Subagent Config**, not by the final answer model config.
- A **Harness Review Subagent** produces a **Review Decision**.
- A **Review Decision** becomes effective only after `PolicyEngine` validates it against deterministic rules and emits the final `PolicyDecision`.
- A **Review Failure Policy** must fail closed: tool review falls back to `require_approval`, model call review falls back to `deny` or `escalate`, and retrieval review may use explicit single-step fallback only when configured.
- Invalid or conflicting **Review Decision** output is traced as review error or override and cannot silently allow execution.
- V1 **Auto Review Scope** covers `before_retrieval_plan`, `before_retrieval_step`, `before_tool_call`, and `before_model_call`.
- `before_answer` remains governed primarily by deterministic evidence and citation rules; a **Harness Review Subagent** may advise but cannot replace evidence validation.
- **Harness Decision Assistance** may advise on `before_answer`, but cannot override failed evidence admission, citation validation, or final output validation.
- A **Controlled ReAct Workflow** records **Reasoning Summary**, not raw chain-of-thought.
- **Intent Resolution** records an audit-safe intent summary before ReAct planning; it does not expose raw chain-of-thought.
- **Intent Resolution Contract** and **Reasoning Summary** are separate audit-safe summaries: the former captures understood user intent, while the latter captures selected ReAct action rationale.
- **Intent Resolution** may recommend the next action category, but it cannot create executable retrieval plans, tool calls, or final answers; the **ReAct Planner** still emits the governed **ReAct Action Proposal**.
- V2 **Intent Resolution** requires deterministic contract validation and trace recording, but does not add an independent Auto Review node because executable actions remain governed by existing review and policy nodes.
- V2 **Intent Resolution** reuses **ReAct Planner Config** for model configuration while remaining a distinct model-call role and audit fact from ReAct planning.
- A **Controlled ReAct Workflow** records **Action Proposal Event**, **Review Decision Event**, **Review Override Event**, and **Clarification Requested Event** where applicable.
- `policy_decision` remains the final governance trace event after `PolicyEngine` validation.
- Backend response settings may expose or hide **Governance Detail Projection**, but trace still records the full audit-safe facts.
- **Response Detail Policy** sets the maximum **Governance Detail Projection** allowed for an Agent; API requests may request less detail but cannot exceed it.
- **Intent Resolution** may appear in internal trace, receipt, Dashboard, or operator governance details when allowed by **Response Detail Policy**, but it must not appear in ordinary customer-facing response text.
- A **Customer-Safe Response Projection** is required for **Customer Service Chat Frontend** responses and must not expose **Governance Detail Projection**, trace links, receipt links, internal policy decisions, review results, or raw tool parameters.
- A **Customer-Safe Response Projection** must not expose **Customer Escalation Handoff** as an `ESCALATED_TO_HUMAN` customer-visible outcome.
- A **Customer-Safe Response Projection** may expose **Authorized Tool Result** support only through **Customer-Safe Source Label** values, not through tool names, trace identifiers, receipt identifiers, internal authorization reasons, or raw tool payloads.
- A **Customer-Safe Response Projection** may differ from the internal run final output for safety, audience, or handoff wording, but the exact customer-visible projection must be recorded as a **Customer Response Snapshot** linked to the run.
- Every **Customer-Facing Business Claim** must be supported by **Accepted Evidence** or an **Authorized Tool Result**.
- **Insurance Product Term Interpretation** and **Insurance Service Process Guidance** are in V1 scope when every business claim is supported by **Accepted Evidence** or an **Authorized Tool Result** and the answer avoids personalized coverage decisions, payment guarantees, **Outcome Optimization Advice**, transactional action, or unsupported legal advice.
- V1 **Insurance Service Process Guidance** may provide evidence-backed document checklists, preparation steps, and process expectations, but must not claim to improve approval likelihood, predict case success, or frame guidance as outcome optimization.
- When a customer asks for **Outcome Optimization Advice**, V1 should use a **Safe Process Guidance Reframe** when possible: state that it cannot assess or promise approval likelihood, then provide evidence-backed required materials, preparation steps, and service process guidance.
- If a customer persists in asking for outcome prediction, **Personalized Coverage Or Payment Decision**, payment guarantee, or rule evasion advice after a **Safe Process Guidance Reframe**, V1 returns a customer-safe refusal or follows the applicable **Handoff Trigger Policy**.
- An **Anonymous Customer Session** may receive generic **Insurance Product Term Interpretation** and **Insurance Service Process Guidance** when the answer is evidence-backed and does not become a **Personalized Insurance Service Request**.
- A **Personalized Insurance Service Request** requires an **Authenticated Customer Session** before customer-specific answers, resource disambiguation, read tools, eligibility discussion, payable amount discussion, or personalized next-step guidance can proceed.
- Authentication and read-only status lookup do not authorize a **Personalized Coverage Or Payment Decision** in V1; the Agent may explain relevant terms, service process, and authorized status facts, but must not conclude coverage, eligibility, payable amount, or guaranteed payment timing.
- **Safe Conversational Text** may appear without evidence only when it does not add business facts or commitments.
- V1 uses a **Customer Response Language Policy** that supports Chinese and English customer replies only; other languages are future localization work.
- V1 allows **Evidence-Bound Translation** from English evidence or tool output into Chinese customer replies, but translated **Customer-Facing Business Claim** values must remain supported by **Accepted Evidence** or **Authorized Tool Result** values.
- **Evidence-Bound Translation** must not add business facts, commitments, deadlines, amounts, eligibility decisions, or policy interpretations beyond the accepted source; customer-safe source references continue to point to the original evidence or tool result.
- V1 is accepted through a **Customer Journey Acceptance Suite**, not only through isolated single-question outcomes.
- V1 **Customer Journey Acceptance Suite** is a release gate and must cover anonymous generic answers, **Insurance Product Term Interpretation**, **Insurance Service Process Guidance**, authenticated single-resource status lookup, multi-resource disambiguation, clarification continuation, ordinal disambiguation replies, cross-customer refusal plus handoff, tool authorization denial, tool execution failure plus retry, ordinary insufficient evidence without handoff, payment or coverage guarantee handoff, and Chinese **Evidence-Bound Translation**.
- During development, the **Customer Journey Acceptance Suite** may run in two layers: always-on customer-safe smoke assertions for current behavior, and V1 release-gate assertions that enumerate unmet release requirements until strict release validation is enabled.
- Passing V1 release-gate assertions requires each customer turn to produce a governed run identity through the full **Customer Run API** Harness path, including authentication prompts, clarification prompts, refusals, handoff acknowledgements, and read-only status answers.
- V1 may collect **Customer Feedback Signal** values for internal observation, but feedback must not automatically update models, policies, retrieval indexes, or future answers.
- V1 **Customer Feedback Signal** storage may live in CustomerStore rather than the run artifact, but it must preserve conversation id, turn id, and run linkage; feedback does not rewrite Trace, Receipt, or the governed run outcome.
- V1 **Customer Feedback Signal** values must not create, update, rank, or admit **Case Memory**; feedback cannot become an implicit preference, fact, or follow-up instruction.
- Each customer-facing turn stores a **Customer Response Snapshot** linked to the RunStore `run_id` for audit replay and complaint investigation.
- V1 is released as a **Private Pilot Customer Service Bot**, not as a public internet production bot or full contact-center platform.
- V1 customer-facing execution may expose **Customer Run Progress State** values but does not stream unvalidated model tokens.
- V1 **Controlled ReAct Workflow** allows multiple governed ReAct Action Proposals, at most one governed tool call, and one final answer generation within a **ReAct Action Budget**.
- V1 **React Enterprise QA Template** uses **Evidence-First ReAct**: retrieval is the default first executable action, clarification is allowed for underspecified questions, and tool proposals are allowed only when policy permits.
- **React Enterprise QA Template V2** adds **Intent Resolution** before ReAct planning as a versioned template change, not as a runtime feature flag on earlier template versions.
- A **Controlled ReAct Workflow** cannot produce a direct final answer before evidence admission.
- A **Clarification Request** ends the current run with **Waiting For User Clarification** rather than refusal or approval waiting.
- A **Clarification Continuation Run** is a new governed run linked through the conversation timeline, not a durable checkpoint resume.
- **Intent Resolution** runs once per governed run; multi-turn intent understanding accumulates through **Controlled Conversation Context** across **Clarification Continuation Run** boundaries.
- A **Harness Invocation** is assembled before execution and then governed by the **Control Envelope**.
- An **Assisted QA Chat Frontend** submits questions through the **Run Execution API**.
- A **Run Execution API** starts a **Published Agent** by agent identifier, not by arbitrary manifest path supplied by the frontend.
- A **Run Execution API** starts Harness runs; Dashboard and receipt views remain read projections over run artifacts.
- A **Customer Service Chat Frontend** submits customer messages through the **Customer Run API**, not through the internal chat execution response shape.
- A **Customer Run API** starts governed Harness runs for a **Published Agent** while returning only **Customer-Safe Response Projection** values.
- Every **Customer Run API** turn must produce a non-empty RunStore `run_id` and a **Customer Response Snapshot** linked to that run, including authentication prompts, missing-field clarification prompts, safe refusals, and handoff-safe acknowledgements.
- A **Unified Chat Frontend** may share design, navigation rhythm, and message-composition flow across **Assisted QA Chat Frontend** and **Customer Service Chat Frontend** modes.
- A **Unified Chat Frontend** must not expose audit links, **Governance Detail Projection**, approval state, raw run identifiers, or receipt links in customer mode.
- A **Unified Chat Frontend** does not merge **Run Execution API** and **Customer Run API** response contracts; audience-specific projections remain separate.
- **Assisted QA Chat Frontend** mode may expose conversation management and internal audit affordances that **Customer Service Chat Frontend** mode must hide.
- **Published Agent Chat Access** exposes Published Agents to **Assisted QA Chat Frontend** through **Run Execution API** and to **Customer Service Chat Frontend** through **Customer Run API** only when the Agent is a **Customer-Facing Published Agent**.
- A **Customer-Facing Published Agent** is identified by the Agent Contract's top-level customer section, not by Agent id, workflow template, purpose wording, or frontend configuration.
- A **Published Agent Directory** may expose separate operator and customer projections, but both resolve through Published Agent state rather than Draft Agent configuration state.
- A **Published Agent Directory Entry** uses metadata snapshotted at publication time.
- A **Published Agent Directory Entry** must not expose manifest paths, source Draft Agent ids, validation run ids, or Contract Bundle contents to chat surfaces.
- **Direct Agent Chat Entry** uses the same stable Agent identity and audience checks as **Published Agent Directory**; it must not accept manifest paths or Draft Agent identifiers.
- **Direct Agent Chat Entry** prepares a new chat conversation for the requested **Published Agent** identity; existing conversation routes remain conversation-identity routes because the Agent binding already lives on the conversation.
- **Direct Agent Chat Entry** fails closed when the Agent identity is unknown or unavailable for the requested chat audience; it must not silently fall back to a default Agent.
- **Direct Agent Chat Entry** does not create an empty conversation on page load; the conversation is created only when the user submits the first message.
- A chat entry point without an Agent identity may preselect the only available **Published Agent** for that audience, but must present **Published Agent Directory** selection when multiple Agents are available.
- In customer chat, **Published Agent Chat Access** selects the Agent identity independently from customer session mode or customer identity; customer identity remains part of **Customer Authorization Context** and conversation creation.
- **Customer Run API** must reject non-customer-facing Agent identities at conversation creation, and customer-facing directory or error projections list only **Customer-Facing Published Agents**.
- **Agent Publication** may expose explicit chat entry actions for the newly published **Published Agent**, but publication itself does not automatically start or redirect to a chat conversation.
- An **Example Agent Template** must be imported into a **Draft Agent**, validated through an **Agent Validation Run**, and promoted through **Agent Publication** before any application-facing execution surface treats it as a **Published Agent**.
- **Run Execution API**, **Customer Run API**, **Published Agent Directory**, and **Direct Agent Chat Entry** must not expose **Example Agent Templates** directly.
- CLI demo, CLI run, CLI compare, and test fixtures may execute **Example Agent Templates** or manifest paths as local development and validation entry points; those entry points do not create **Published Agent Chat Access**.
- When no **Published Agent** exists for a chat audience, chat surfaces show an empty state that directs users back to import, validate, and publish through the **Agent Configuration Workspace**; they do not auto-import **Example Agent Templates**.
- Existing chat conversations remain bound to their original **Published Agent** identity; **Agent Publication** and **Agent Version Rollback** change the **Active Agent Version** resolved for that identity without moving conversations to a different Agent.
- The **Assisted QA Chat Frontend** resolves waiting approval through **Approval Checkpoint Resume**, not by starting a new follow-up run with an inline approval decision.
- The first framework boundary pass should make **Harness Invocation** and **Workflow Template** reusable while preserving **Enterprise QA Reference Agent** behavior.
- The **Enterprise QA Reference Agent** is built on the **Controlled Agent Harness Framework**.
- The V1 **Enterprise QA Reference Agent** operates in **Autonomous Customer Service Mode**.
- The V1 **Enterprise QA Reference Agent** includes a **Customer Service Chat Frontend** for direct end-customer use.
- V1 delivers **Customer Service Web Chat** before adding channel adapters for messaging apps, email, mobile SDKs, or contact-center platforms.
- V1 uses **Text-Only Customer Intake** and does not analyze customer-uploaded files or attachments.
- **Assisted Service Mode** remains a supported product direction but is no longer the V1 default target.
- An **Anonymous Customer Session** may ask generic policy questions but cannot access customer-specific tools, account facts, policy status, claim status, or personalized commitments.
- An **Authenticated Customer Session** is required before any customer-specific answer or tool call can proceed.
- **Customer Authorization Context** is admitted separately from **Controlled Conversation Context** and must enter the **Harness Invocation** or run state as Structured Control Context; it must not remain only as Customer Run API preflight state.
- **Customer Authorization Context** must not expose raw credentials to model prompts, trace, receipt, or tool parameters.
- V1 may use a **Mock Authenticated Customer Session** to prove the authentication and authorization boundary without integrating production OAuth, OIDC, IAM, or SSO.
- V1 requires at least two **Mock Customer Persona** fixtures so authorization isolation can be tested.
- A **Cross-Customer Access Attempt** must be refused before any customer-specific read tool executes and must create an internal **Customer Escalation Handoff** for monitoring.
- A **Customer Identity Adapter** is the future integration point for production identity providers.
- V1 **Autonomous Customer Service Mode** is **Read-Only Customer Service**.
- A **Customer-Specific Read Tool** requires an **Authenticated Customer Session** and **Customer Authorization Context**.
- V1 customer-specific read tools are limited to **Single-Resource Customer Read** behavior; bulk customer resource listing is future capability work.
- A **Policy-Authorized Read Tool** does not require human approval in V1 when PolicyEngine confirms it is authenticated, authorized, read-only, and parameter-bounded.
- A **Policy-Authorized Read Tool** must still execute inside a full **Harness Invocation** with PolicyEngine, Tool Gateway, Trace, Governance Receipt, and RunStore artifacts; Customer Run API preflight must not become a second tool execution path.
- **Tool Contract** and **Agent Contract** policy metadata are the authority for customer read-tool authorization conditions such as read-only classification, authenticated-customer requirements, ownership checks, risk level, and parameter bounds.
- PolicyEngine and Tool Gateway enforce customer read-tool authorization by comparing normalized tool arguments with **Customer Authorization Context** before execution; the ReAct Planner and Harness Review Subagent may propose or recommend, but cannot assert that authorization conditions are satisfied.
- A denied customer read-tool proposal records a **Customer Tool Authorization Denial** in Trace, Governance Receipt, and RunStore with deterministic denial reason and redacted argument/resource summaries.
- A **Customer Tool Authorization Denial** projects to customers only as a **Customer-Safe Response Projection** containing a safe refusal or **Clarification Request**; it must not expose policy rule names, authorization reasons, tool names, raw arguments, risk levels, internal resource identifiers, or Tool Gateway errors.
- A **Customer Tool Authorization Denial** that involves a **Cross-Customer Access Attempt** or suspected abuse/security risk must also create an internal **Customer Escalation Handoff** according to the **Handoff Trigger Policy**.
- An authorized customer read tool that fails during Tool Gateway, adapter, dependency, timeout, or runtime execution records a **Customer Tool Execution Failure** in Trace, Governance Receipt, and RunStore.
- A **Customer Tool Execution Failure** projects to customers as a customer-safe temporary failure or refusal and must not be relabeled as **Customer Tool Authorization Denial**, insufficient evidence, or an unsupported business answer.
- Customer-facing wording for **Customer Tool Execution Failure** may ask the customer to try again later as **Safe Conversational Text**, but must not promise system recovery, guarantee successful retry, claim human follow-up, or say the issue was escalated unless a **Customer Escalation Handoff** was actually created and projected with **Handoff-Safe Customer Wording**.
- A **Customer Tool Execution Failure** does not create a **Customer Escalation Handoff** by default; handoff occurs only when the **Handoff Trigger Policy** classifies that failure as an enterprise high-value failure, suspected abuse, or security-relevant condition.
- A customer retry after **Customer Tool Execution Failure** is a **Customer Tool Retry Run**: it starts a new governed run, links to the failed run, and repeats **Customer-Owned Resource Resolution**, PolicyEngine authorization, and Tool Gateway execution.
- A **Customer Tool Retry Run** must not reuse prior authorization, skip policy checks, or replay prior tool arguments directly; any prior failure context is admitted only as trace-safe conversation context.
- Consecutive **Customer Tool Execution Failure** events for the same conversation, customer-owned resource, and tool intent form a **Customer Tool Failure Series** recorded through linked run artifacts.
- A **Customer Tool Failure Series** does not automatically create a **Customer Escalation Handoff**; the **Handoff Trigger Policy** may configure enterprise high-value failure rules such as N consecutive failures for the same resource in one conversation.
- V1 customer-specific read scope includes **Policy Status Lookup Tool** and **Claim Status Lookup Tool**.
- A customer-specific read may proceed only after **Customer-Owned Resource Resolution** uniquely identifies the customer-owned policy, claim, or service record required by the proposed tool arguments.
- If the **Owned Resource Handle Index** contains exactly one matching resource for the customer's request, **Customer-Owned Resource Resolution** may identify that resource without a **Customer Resource Disambiguation Prompt**, allowing the planner to propose the corresponding single-resource lookup.
- Trace, Governance Receipt, and RunStore artifacts must record a **Customer Resource Resolution Basis** whenever V1 proceeds to single-resource lookup, including cases where disambiguation was skipped because exactly one owned resource matched.
- Customer-facing responses expose only **Customer-Safe Resource Handle** or **Customer-Safe Source Label** values for resolved resources; they must not expose **Customer Resource Resolution Basis** internals.
- In customer mode, a **LLM ReAct Planner** may propose **Policy Status Lookup Tool** or **Claim Status Lookup Tool** only as **ReAct Action Proposal** values when those tools are inside the run's **Tool Proposal Scope**.
- The customer-mode **Tool Proposal Scope** does not grant execution rights; PolicyEngine and Tool Gateway still authorize or deny the proposed read tool before execution.
- An **Authorized Tool Result** is distinct from **Accepted Evidence**, but final answer validation may use it to support a **Customer-Facing Business Claim** when it has a trace-safe source reference, redacted payload, tool authorization record, and matching Trace, Governance Receipt, and RunStore artifacts.
- A **Customer Response Snapshot** stores the exact customer-visible **Customer-Safe Source Label** values shown for **Authorized Tool Result** support, while internal run artifacts preserve the mapping from each label to the specific authorized tool result for audit replay.
- If an authenticated customer owns multiple matching resources and the request lacks a claim id, policy id, or other disambiguating input, V1 returns a **Customer Resource Disambiguation Prompt** with full run artifacts rather than silently selecting the most recent, most active, or highest-value resource.
- A **Customer Resource Disambiguation Prompt** may expose bounded option numbers and **Customer-Safe Resource Handle** values needed for selection, but must not expose claim status, policy status, coverage decisions, amounts, raw payload fields, internal customer ids, or internal authorization details.
- A **Customer Resource Disambiguation Prompt** may expose the count of matching owned resources, such as "you have 3 claims", only as disambiguation metadata from the **Owned Resource Handle Index**; the count must not imply claim status, policy status, amount, coverage, or eligibility.
- **Customer-Safe Resource Handle** values used in a **Customer Resource Disambiguation Prompt** must come from an **Owned Resource Handle Index** supplied by **Customer Authorization Context**, **Mock Customer Persona** fixtures, or a future **Customer Identity Adapter**.
- **Policy Status Lookup Tool** and **Claim Status Lookup Tool** must not be used to batch-read status results merely to construct disambiguation options; if no safe handle is available, V1 asks the customer to provide a claim id, policy id, or other stable identifier.
- A **Customer Disambiguation Option Mapping** is stored in **Controlled Conversation Context** and linked to the originating run and **Customer Response Snapshot**; it must not be stored as **Customer Authorization Context** or admitted as **Case Memory**.
- A **Clarification Continuation Run** may resolve replies such as "first", "the recent one", or "that second claim" when they unambiguously refer to a prior **Customer Resource Disambiguation Prompt** preserved in **Controlled Conversation Context** and the **Customer Disambiguation Option Mapping** identifies exactly one customer-owned resource.
- A **Customer Disambiguation Option Mapping** expires after successful single-resource resolution and lookup, a new disambiguation prompt, authenticated customer change, conversation reset, Published Agent change, or configured timeout.
- If a **Customer Disambiguation Option Mapping** is expired or absent, ambiguous replies such as "first" or "the recent one" produce a new **Clarification Request** rather than restoring the mapping from old transcripts, **Customer Response Snapshot** text, or **Case Memory**.
- A customer request to list all owned policies, claims, or claim statuses does not trigger a batch of **Policy-Authorized Read Tool** calls in V1; the response asks the customer to select one resource through a **Customer Resource Disambiguation Prompt** or safely explains the single-resource scope.
- A **Transactional Customer Action** is out of V1 scope and must produce a governed refusal, clarification, or internal handoff rather than execution.
- Ordinary unsupported or insufficient-evidence customer questions do not create a **Customer Escalation Handoff** by default; they return a customer-safe refusal with full run artifacts.
- A **Payment Or Coverage Guarantee Request** must return customer-safe refusal wording and create an internal **Customer Escalation Handoff** for review.
- A request for **Personalized Coverage Or Payment Decision** must be handled as a **Payment Or Coverage Guarantee Request** when the customer asks for a coverage, eligibility, payable amount, reimbursement, deadline, or payment commitment conclusion.
- V1 **Customer Escalation Handoff** triggers include **Cross-Customer Access Attempt**, **Transactional Customer Action**, **Payment Or Coverage Guarantee Request**, suspected abuse or security risk, and enterprise-configured high-value failure scenarios.
- V1 **Handoff Trigger Policy** has fixed baseline triggers and may allow Agent Contract or policy configuration to add enterprise high-value failure scenarios; frontend requests, user prompts, and arbitrary natural-language instructions cannot define handoff triggers.
- V1 records a **Customer Escalation Handoff** for internal follow-up monitoring instead of creating a ticket in a real CRM, helpdesk, or contact-center system.
- A **Customer Escalation Handoff** is an internal operational fact, not a customer-visible final outcome.
- Customer-visible responses for internal handoff cases use **Handoff-Safe Customer Wording**.
- A **Customer Escalation Handoff** is recorded through a **Customer Handoff Event** and exposed internally through a **Handoff Projection**, not through the final outcome enum.
- Each **Customer Handoff Event** uses a fixed **Handoff Reason** for trace, RunStore, Dashboard filtering, and acceptance tests.
- **Customer Handoff Event**, memory candidate, memory write, and memory admission facts must preserve **Run Artifact Consistency**: they are emitted before run finalization, or through a governed artifact append path that refreshes Receipt and RunStore projections together.
- The **Assisted QA Chat Frontend** uses **Controlled Conversation Context** for automatic multi-turn context injection.
- A **Conversation Store** preserves chat timelines while each turn remains linked to a governed run in RunStore.
- **Controlled Agent Memory** extends memory beyond per-run session state while remaining inside the **Control Envelope**.
- A **Hybrid Memory Framework** may use one or more **Memory Provider Adapter** implementations, but **Memory Admission** remains a Control Plane decision.
- The **Agent Configuration Workspace** exposes **Agent Memory Configuration** per Agent and does not treat memory as a reusable cross-Agent asset in the first implementation stage.
- Memory layers describe Proof Agent product semantics; **Memory Provider Adapter** implementations describe replaceable storage and retrieval engines.
- External memory engines may provide storage, retrieval, summarization, or ranking, but they must not decide **Memory Admission** or bypass the **Control Envelope**.
- **Case Memory** is generated from governed run facts and bounded, trace-safe facts or summaries derived from **Customer Response Snapshot** linkage, not from complete customer-visible message text, **Customer Feedback Signal**, raw transcripts, or unvalidated model text.
- **Case Memory Lifecycle Controls** must be proven before **Persistent User Memory** is enabled.
- The first **Persistent User Memory** implementation targets **Customer Persistent User Memory**, not operator or staff user profiles.
- The first **Customer Persistent User Memory** writes only a **Customer Memory Interest Profile**; it must not store report result values, policy status, claim status, raw tool payloads, raw evidence, sensitive customer facts, or model-inferred marketing personas.
- **Customer Persistent User Memory** may support intent understanding, preference-aware follow-up, and missing-field prompts after **Memory Admission**, but it is not **Accepted Evidence** and must not automatically trigger sensitive data retrieval.
- **Customer Memory Consent** gates Customer Persistent User Memory reads and writes.
- **Customer Memory Lifecycle Controls** operate at the customer reference boundary before single-memory editing is introduced.
- The first **Customer Persistent User Memory** implementation is isolated by Published Agent and customer reference; it must not cross Agent boundaries.
- A **Memory Subject Reference** identifies who **Persistent User Memory** is about without reusing **Case Memory** identifiers.
- **Case Memory** is generated from governed run facts, not from raw transcripts or unvalidated model text.
- **Case Focus** belongs to **Case Memory** and must not become a cross-session **Persistent User Memory** profile in the first implementation stage.
- **Case Memory** may support follow-up understanding after **Memory Admission**, but it is not **Accepted Evidence**.
- V1 uses a **Customer Conversation Retention Policy** for short-lived customer chat text and an **Audit Retention Boundary** for longer-lived trace-safe run facts.
- **RunStore** preserves governed run artifacts separately from the customer conversation timeline.
- V1 keeps the existing dashboard role as an **Internal Governance Dashboard** and does not deliver an **Agent Control Platform Console**.
- Agent configuration planning extends the **Dashboard Shell** with an **Agent Configuration Workspace** while preserving separate configuration, execution, and observability API boundaries.
- **Agent Configuration API** owns Draft Agent editing, reusable configuration assets, validation, publication, rollback, import, and export; it may trigger **Agent Validation Run** but not ordinary production execution.
- The first **Agent Configuration Store** implementation is a **Local Agent Configuration Store** aligned with RunStore and ConversationStore, while API and domain code depend on a replaceable store boundary.
- The Dashboard Shell should become **Agent-Centric**: global observability remains available, and each Agent detail view combines monitor, configure, validate/test, versions, and Contract View.
- The existing Dashboard `/knowledge` route becomes the global **Knowledge Source Workspace** for shared Knowledge Source administration; the product may label the navigation item "Knowledge" or "Knowledge Sources", but it does not add a parallel `/knowledge-sources` route.
- The **Knowledge Source Workspace** links each Source to **Knowledge Source Detail Workspace** at `/knowledge/:sourceId`. Its Overview, Documents, Versions, Provider, and Audit tabs centralize asset administration, while Agent Knowledge modules remain focused on binding selection, bounded overrides, resolved versions, and upgrade actions.
- The `/knowledge` **Knowledge Source Workspace List Projection** shows Source identity, description, tags, provider type, ACTIVE or ARCHIVED lifecycle, local index or remote verification availability, current published snapshot or configuration version, local READY and total document counts or remote target index or namespace, referencing Agent count, and warnings for unpublished changes, failed ingestion, or stale remote verification. Operators may filter by name, tag, provider, lifecycle, and warning state.
- **Knowledge Source Creation Wizard** starts from `/knowledge` and branches immediately into upload local documents for `local_index`, connect remote knowledge for `http_json` or another registered remote adapter, or register an existing `local_markdown` source. The wizard creates or updates a Source Draft only; verification and **Knowledge Source Publication** remain explicit follow-up actions.
- For a `local_index` source, **Knowledge Source Documents Tab** supports batch PDF and Markdown upload; filtering by name, tag, and state; pagination; and per-row document name, current READY revision, pending revision, state, update time, and current-published-snapshot membership. Single-document actions include replace, failed-revision retry, routing-metadata edit, archive, and revision history. Bulk actions include failed-revision retry, archive, and tag edit.
- **Knowledge Source Documents Tab** persistently shows a Candidate Knowledge Source Snapshot summary with included READY count, processing count, failed count, archived count, and explicit Publish Source action.
- **Remote Knowledge Source Provider Tab** uses a default form for adapter, endpoint, environment-variable credential references, index or namespace, timeout, and default `top_k`, plus an advanced section for supported protocol, request mapping, response JSON Pointer mapping, and Structured Remote Source Reference mapping. Typed remote adapters prefer descriptor-driven forms, while `http_json` exposes bounded mapping editors.
- **Remote Knowledge Source Connection Test** validates connectivity, authentication, target existence, and normalization shape. **Remote Knowledge Source Retrieval Preview** runs a bounded query and displays normalized candidates, citations, Provider-Native Relevance Scores, and Remote Knowledge Revision Observations. Neither action publishes a Source; a saved Draft still requires successful verification and explicit Knowledge Source Publication.
- **Local Index Provider Tab** uses a default form for ingestion model provider, model, environment-variable credential references, inherited routing model, and Knowledge Document Selection Budget defaulting to 8, plus an advanced section for explicit routing-model override, timeout, retry count, and worker concurrency. File and routing-metadata management remains in Knowledge Source Documents Tab.
- **Local Index Model Configuration Test** validates model settings and referenced credential availability without triggering a full rebuild. A change to ingestion configuration that could affect index artifacts sets **Local Index Reingestion Required**; published snapshots remain usable, but the replacement candidate snapshot cannot be published until required document revisions are reingested successfully.
- **Knowledge Ingestion Configuration Fingerprint** is calculated from the immutable **Knowledge Artifact Build Spec** and combines artifact-affecting ingestion configuration with each revision's content hash for compatible index-artifact reuse. A **Knowledge Revision Artifact Reference** preserves revision provenance separately from reusable artifact metadata. **Incremental Local Index Reingestion** queues only revisions in the current Candidate Knowledge Source Snapshot that lack compatible artifacts. Routing-model changes, Knowledge Document Selection Budget changes, and routing-metadata edits do not rebuild indexes.
- Dashboard shows the count of revisions requiring rebuild and exposes `Reingest required documents`. Current published snapshots continue serving while rebuilding, and a replacement candidate snapshot cannot publish until all required revisions are READY.
- **Knowledge Ingestion Worker Policy** uses one unified atomic store claim across quarantine-validation and artifact-build tasks, then applies a claim-time per-Source concurrency gate defaulting to 2 and configurable through `params.worker_concurrency` from 1 through 8. The gate counts non-expired `processing` tasks of both kinds, skips Sources already at their limit, and selects the oldest ready eligible task to avoid starvation without a peek-then-claim race. Worker concurrency affects scheduling only, not artifact fingerprinting. State transitions use claim-token ownership, renewable persisted leases, and bounded provider calls; at most 2 automatic retries per revision use backoff. Renewal failure immediately prevents the stale worker from starting further provider calls, publishing an artifact, or committing task state. An artifact already completed during an in-flight bounded call or atomic rename may remain reusable by the new owner. **Knowledge Ingestion Failure Classification** retries recoverable model timeout, transient rate limit, and temporary network failures, but fails unsupported format, scanned PDF, missing configuration, and missing credentials immediately. Exhausted revisions enter FAILED with stable Dashboard error code and short explanation and remain manually retryable.
- Worker restart resumes unfinished persisted queue tasks and checks compatible index artifacts before building, so recovery does not duplicate completed compatible work. **Atomic Knowledge Artifact Publication** adds artifact-key locking, double-checked cache validation, temporary-directory construction, atomic directory publication, and stale-temporary cleanup so concurrent workers never reuse partial artifacts or perform duplicate compatible builds.
- The upload API applies request-envelope protection only: it validates the target `local_index` Source, valid non-empty base64, and the 50 MB byte limit before storing bytes under a system-generated quarantine path. Staging atomically acquires a **Knowledge Source Document Capacity Reservation** under the queue lock so pending uploads cannot bypass the 500-document Source capacity. **Operator Knowledge Document Upload Validation** then asynchronously accepts only PDF and Markdown after MIME and content-signature consistency checks, limits one PDF to 500 pages and one batch to 50 files, and rejects zip archives, directories, nested attachments, encrypted PDFs, scanned PDFs, macro-bearing files, executable content, and unsupported files into **Rejected Knowledge Upload Retention**.
- **Atomic Knowledge Document Batch Upload** supports at most 50 files per batch. Its API reserves capacity for the full batch atomically before publishing quarantine records, fails staging as one batch if reservation or persistence fails, and then lets each successfully staged file proceed independently through asynchronous **Operator Knowledge Document Upload Validation**.
- Operator files first enter **Knowledge Document Upload Quarantine** under a system-generated storage path with sanitized display filename. A failed validation receives a stable error code and creates neither Knowledge Document Revision nor Knowledge Ingestion Job, so it cannot enter a candidate snapshot. Successful validation uses **Quarantined Knowledge Upload Promotion**, whose atomic commit marker gates ingestion-job visibility and whose deterministic identities make worker recovery idempotent.
- A validated Knowledge Document Revision retains its **Managed Knowledge Document Original** separately from generated index artifacts for reingestion, citation verification, and audit-safe inspection. An operator with `knowledge_source.view` may download it, and **Knowledge Document Original Download Audit** records that action.
- Archive and replacement retain Managed Knowledge Document Originals while snapshots, Published Agent Versions, or audit-retention rules reference them. **Unreferenced Knowledge Artifact Cleanup** may remove both originals and index artifacts only after those checks pass. **Rejected Knowledge Upload Retention** keeps rejected quarantine files for 24 hours for troubleshooting and then removes them automatically.
- Local index citations use **Local Knowledge Citation URI** with stable Source, document, revision, and PDF page or Markdown section identity without exposing storage paths. Run Detail and retrieval preview offer audited, permission-protected **Knowledge Citation Preview**, while original download remains a separate audited action.
- Customer responses use **Customer-Safe Knowledge Citation Projection** with safe source name plus page or section and omit internal revision ids and storage paths. A remote external citation URL is clickable only when **Remote Citation Link Allowlist** validates its protocol and domain; otherwise the UI renders non-clickable source text.
- Customer-facing answers cite evidence with **Customer Citation Markers** such as `[1]` and a **Customer Sources List**. The list shows safe source name, page or section, and safe document title, merges repeated references to the same safe source location, and omits confidence, provider, internal ids, revision ids, and remote mutable-external technical warnings.
- Mutable external replay limitations remain internal Knowledge Retrieval Runtime Facts in Receipt and Run Detail. If no Accepted Evidence exists, the final-answer model must not invent citations and must follow insufficient-evidence refusal behavior.
- **No Accepted Evidence Outcome** skips free-form final-answer generation or uses only a constrained refusal template without evidence context. Run Detail shows which retrieval phase eliminated evidence, and Receipt records zero Accepted Evidence, candidate count, refusal reason code, and whether provider failure contributed. Customer-safe wording does not include a Sources list.
- Routing empty selection produces **No Accepted Evidence Outcome** rather than implicit full-source fan-out.
- Advisory provider failure may still answer when remaining selected bindings produce Accepted Evidence. A selected required provider failure produces **No Accepted Evidence Outcome** and prevents an answer, even if other selected sources could have produced candidates.
- **Knowledge Source Publication Validation** is bound to one Source Draft version and becomes stale after relevant configuration changes. For `local_index`, **Local Index Source Publication Validation** requires at least one READY revision, no pending required reingestion, compatible artifacts for all included revisions, successful ingestion and routing model tests, and an editable smoke query proving routing, retrieval, and citation resolution.
- For remote Sources, **Remote Knowledge Source Publication Validation** requires adapter-supported health-check verification when available, authentication, target validation when declared, response normalization, and an editable smoke query proving normalized candidates plus citation or adequate Structured Remote Source Reference. Generic adapters such as `http_json` publish a mutable external `remote_config`; adapters that cannot prove retrieval normalization remain preview-only.
- **Knowledge Source Publication Confirmation** precedes Publish Source and shows current Source Draft, prior published snapshot or configuration version, local added, replaced, archived, and included READY counts or remote adapter, target index or namespace, pinned or mutable-external consistency mode, latest verification time, smoke-query result, and referencing Agent count. It requires a `change_note` recorded in version history and audit and explicitly states that existing Published Agent Versions do not change automatically.
- **Knowledge Source Versions Tab** lists published snapshots or configuration versions with publication time, actor, `change_note`, validation result, referencing Agent count, and version diff. Rolling back creates a **Knowledge Source Rollback Draft** from the selected historical version rather than mutating history or moving a production pointer.
- A Knowledge Source Rollback Draft requires fresh Source validation and explicit publication to create a new Source version. It never changes Published Agent Versions or Draft Agent bindings automatically; an Agent adopts the resulting Source version only through explicit binding upgrade, Agent validation, and Agent publication.
- Every Source supports audited **Knowledge Source Manifest Export** without credential values, originals, or index artifacts. A local index Source may additionally create an audited **Local Knowledge Source Offline Bundle** containing the manifest, validated originals, and content hashes while excluding secrets and excluding cached indexes by default.
- Import creates a **Knowledge Source Import Draft** rather than publishing implicitly. Remote imports require fresh connection test, validation, and publication. Local offline-bundle files pass upload validation again and reingest according to Knowledge Ingestion Configuration Fingerprint; externally supplied index artifacts are never trusted directly.
- **Knowledge Source Configuration API** owns `/api/config/knowledge-sources` list, create, and filter operations; `/api/config/knowledge-sources/:sourceId` detail, Draft update, archive, and restore; document operations; version list, diff, and rollback-Draft creation; validation; publication; remote connection test; retrieval preview; export; and import.
- **Agent Knowledge Binding Configuration API** stores Agent Draft `knowledge_bindings[]` and Agent-level blended-retrieval settings only. Knowledge Source provider parameters remain Source-owned, and Published Agent Versions capture a **Resolved Knowledge Binding Set** with resolved Source snapshot or configuration versions plus resolved binding settings.
- **Direct Knowledge Contract Migration** replaces inline Agent `knowledge.provider + params` with Source-owned provider configuration and Agent `knowledge_bindings[]` in one breaking change. Loader, Dashboard, examples, fixtures, and tests migrate together; the new loader rejects legacy inline knowledge configuration rather than carrying a dual-read path.
- **Agent Configuration MVP** prioritizes the vertical import-to-publication-to-monitoring loop before full Tool Source management, advanced Policy condition building, unbounded multi-source retrieval, full RBAC, deep visual diffs, or memory lifecycle UI.
- **Agent Configuration MVP** uses a **Workflow Stage Panel** for Workflow Template Stage Configuration before adding any visual workflow canvas.
- New Agent setup enters through an **Agent Creation Wizard** and then lands in the module-based **Agent Configuration Workspace** for ongoing edits.
- The **Agent Configuration Workspace** edits **Draft Agent** versions in the **Agent Configuration Store**; application-facing execution surfaces can call only immutable **Published Agent Version** snapshots after **Agent Publication**.
- A **Published Agent** resolves to an **Active Agent Version** by default, and **Agent Version Rollback** changes that pointer without mutating prior Published Agent Version snapshots.
- **Agent Contract** and **Agent Package** remain the reviewable execution artifacts even when drafts and publication metadata live in the **Agent Configuration Store**.
- **Agent Package Import** turns existing example or registry Agent Packages into Draft Agents without overwriting the original package files by default.
- **Agent Publication** requires a successful **Agent Validation Run** for the Draft Agent version being published.
- **Agent Validation Run** artifacts are stored in RunStore with **Run Purpose** metadata so validation evidence remains auditable without polluting default production run metrics.
- The first **Agent Configuration Workspace** may run as a single-user local experience, but it should still preserve **Agent Configuration Permission Model** roles and **Configuration Operation Audit** metadata for future RBAC.
- V1 includes an **Internal Handoff Monitor** for handoff visibility and run-detail drilldown, but not assignment, SLA, notification, or ticket workflow.
- The **Insurance Customer Service Agent** is the V1 customer-facing Published Agent for the **Insurance Service QA Domain**.
- The existing insurance service QA example remains a baseline and compatibility package rather than the V1 customer-facing Agent package.
- The V1 **Enterprise QA Reference Agent** targets the **Insurance Service QA Domain** before broader industry templates.
- Near-term delivery uses the **Enterprise QA Reference Agent** as the acceptance path while preserving framework-level boundaries.
- A **Knowledge Provider** returns zero or more **Candidate Evidence** chunks.
- A **Knowledge Source** owns its **Knowledge Provider** configuration, and the **Knowledge Provider Registry** resolves that source-owned provider before retrieval.
- **Knowledge Source Lifecycle State** separates reusable asset lifecycle from bindability and ingestion readiness. **Knowledge Source Archive** is the default delete-like action: it blocks new Agent binding and new Agent publication, leaves existing Draft Agent bindings visible as validation and publication blockers, and preserves existing Published Agent Version execution against pinned snapshots or configuration versions. Dashboard shows affected references through **Knowledge Source Reference Summary**.
- **Knowledge Source Restore** returns an archived source to ACTIVE without changing any Agent binding, Source Draft, publication, or resolved version automatically. **Knowledge Source Physical Deletion** is a separate danger-zone action allowed only for archived, unreferenced, empty Sources with no retained publications, snapshots, documents, uploads, jobs, or audit-retention blocker.
- **Knowledge Source Permission Model** separates `knowledge_source.view`, `knowledge_source.edit`, `knowledge_source.publish`, and `knowledge_source.archive`. Knowledge Source command requests do not carry actor fields; the API resolves Operator Identity Context server-side. Agent binding edits require `agent.edit`, and publishing a new Agent version requires `agent.publish`. V1 local single-user mode grants all by default while API checks, Dashboard actions, and Configuration Operation Audit preserve these boundaries for future RBAC.
- **Knowledge Configuration Operation Audit** records actor, time, affected Source or Agent, prior and resulting version identifiers, document intake and replacement, retry, document archive, Source publication, Source archive and restore, Physical Deletion eligibility and deletion decisions, remote verification, Agent binding changes, retrieval override changes, and explicit Source upgrades. Physical Deletion audit survives removal of the Source storage directory.
- **Knowledge Retrieval Runtime Facts** record resolved Source snapshot or configuration versions, routed Sources and local document revisions, provider call state, degraded retrieval, upstream revision observations, WRRF ordering, exact-dedup provenance, Evidence Admission Scores, citations, and Accepted Evidence Context Budget Truncation in Trace, Governance Receipt, and RunStore.
- **Knowledge Retrieval Plan Summary** records `binding_candidates[]` using **Knowledge Binding Candidate Summary**, `selected_bindings[]` using **Selected Knowledge Binding Summary**, local `document_candidates[]` and `selected_documents[]` when applicable, and **Knowledge Provider Call Summary** for each selected provider. Unselected bindings and documents record compact summary reasons only.
- RunStore and Dashboard Run Detail preserve the full Knowledge Retrieval Plan Summary. Governance Receipt keeps a compressed summary suitable for audit review without raw evidence content.
- Knowledge audit and retrieval facts do not store raw document content, credential values, or complete remote provider responses.
- An **Agent Knowledge Binding** may define a **Knowledge Binding Retrieval Override** for provider retrieval `top_k`, fusion weight, failure mode, and source-routing metadata hints. It cannot override provider endpoint, credentials, index or namespace, local index document-processing parameters, or admission scorer. Missing values inherit Knowledge Source defaults, and Published Agent Version snapshots capture resolved values.
- An unpinned Draft Agent binding uses **Draft Knowledge Binding Resolution** to follow the latest published Knowledge Source snapshot or configuration version and shows that resolved version in Dashboard. **Published Knowledge Binding Resolution** pins the source snapshot or configuration version and resolved binding settings inside each Published Agent Version, so later source publication never silently changes production behavior.
- When a Knowledge Source publishes a newer version, Dashboard exposes **Knowledge Binding Upgrade Available** for older Draft Agents and Published Agent Versions. An administrator applies an upgrade to a Draft Agent, runs validation, and publishes a new Agent version.
- V1 **Knowledge Provider Registry** contains trusted **Knowledge Provider Adapter Descriptors** rather than operator-uploaded executable code; each descriptor declares configuration schema, Dashboard form metadata, and **Knowledge Provider Capabilities**.
- V1 includes an **HTTP JSON Knowledge Provider** with a default versioned **Remote Retrieval Protocol** and validated declarative **Remote Retrieval Response Mapping** for non-standard remote APIs; specialized technology stacks may add trusted typed adapters through code installation.
- **Remote Retrieval Request Mapping** may project only whole-value placeholders `${query}`, `${top_k}`, and `${upstream_revision}` into query parameters and JSON body fields while preserving their source types; static JSON constants and nested structures remain allowed.
- Remote request endpoint and URL path are static published configuration values. Headers may be static non-sensitive values or environment-variable references with an optional static prefix. V1 request mapping does not support string interpolation, dynamic URL paths, loops, conditions, functions, network callbacks, or scripts.
- **Remote Retrieval Response Mapping** uses one JSON Pointer for the result array and relative JSON Pointer fields for each item; it may project normalized content, citation, **Structured Remote Source Reference** fields such as document id, page, and chunk id, id, Provider-Native Relevance Score, metadata, and revision observation fields.
- V1 response mapping does not support JSONPath wildcards, filters, recursive queries, functions, concatenation, calculations, scripts, raw-response LLM injection, or direct mapping into Evidence Admission Score.
- **Remote Retrieval Response Mapping Verification** runs during Remote Knowledge Source Verification and fails closed unless the result pointer resolves to an array and every normalized candidate shape provides content plus either citation or an adequate Structured Remote Source Reference.
- **Trusted Citation Formatting** converts an adequate Structured Remote Source Reference into citation using adapter-owned deterministic rules, for example `document://claims-guide#page-3`. Dashboard administrators cannot configure arbitrary citation templates. A candidate lacking both usable citation and adequate Structured Remote Source Reference remains visible in Trace and provider diagnostics but is inadmissible and excluded from **Accepted Evidence Context Assembly**.
- Evidence Admission Score may be supplied only through an approved calibrated adapter descriptor or approved admission scorer, not through an ordinary HTTP JSON response mapping.
- Published Remote Knowledge Source configuration versions capture the selected protocol version, request mapping, and response mapping so validation, audit, and rollback use the same remote retrieval contract.
- Dashboard configuration stores provider parameters and environment-variable credential references only; **Secret-Safe Knowledge Configuration Validation** recursively rejects raw secret-bearing fields before Source persistence and again before Knowledge Artifact Build Spec persistence. V1 does not execute arbitrary scripts uploaded through Dashboard.
- Every published Remote Knowledge Source captures an immutable **Remote Knowledge Source Configuration Version** managed by Proof Agent.
- A remote adapter with `snapshot_pin` capability publishes a **Pinned Remote Knowledge Source** with an upstream corpus revision; an adapter without that capability publishes a **Mutable External Knowledge Source** and Dashboard warns that exact historical replay is unavailable.
- Retrieval from a remote source records a **Remote Knowledge Revision Observation** in Trace, Governance Receipt, and RunStore when the adapter returns a revision or etag, otherwise it records the observation timestamp.
- Agent Validation Runs and Published Agent Versions preserve whether each bound remote source was pinned or mutable external.
- A remote adapter that declares `health_check` must pass **Remote Knowledge Source Verification** before its source may be published for production bindings; generic adapters without `health_check` must still pass smoke retrieval normalization and publish as mutable external `remote_config` resources.
- **Remote Knowledge Source Verification** validates connectivity, authentication, target index or namespace existence, and response normalization, then records verification time, adapter name, configuration version, and available upstream revision observation.
- Verification for a **Mutable External Knowledge Source** is valid for 24 hours by default; **Stale Remote Knowledge Source Verification** warns operators and blocks new Agent publication or rebinding until refreshed without immediately interrupting already-published Agent execution.
- An **Agent Contract** references one or more **Knowledge Sources** through an **Agent Knowledge Binding Set** without selecting providers.
- **Knowledge Binding Strategy** governs **Multi-Source Blended Retrieval** across the Agent's **Agent Knowledge Binding Set** and is executed by the Control Plane **Knowledge Retrieval Service**.
- Enterprise QA and Controlled ReAct workflows must call the same **Knowledge Retrieval Service** rather than directly invoking Knowledge Provider Adapters from runtime graph nodes.
- **Knowledge Source Routing** is deterministic by default: a single eligible binding is selected directly, explicit metadata matches select bounded sources, and ambiguous or empty deterministic selection returns no evidence unless optional model routing is explicitly configured.
- Optional **Knowledge Source Routing Model Configuration** may choose a bounded set of eligible bindings only after deterministic routing cannot make a clear selection; model routing failure does not fan out to every source.
- **Knowledge Source Selection Budget** defaults to 3 selected Knowledge Sources per query and is configurable from 1 through 8 at the Agent Knowledge Binding Set boundary; it is distinct from Knowledge Document Selection Budget and Agent Retrieval Strategy evidence `top_k`.
- If **Knowledge Source Routing** selects no sources, retrieval returns no evidence rather than silently querying every binding; uncertain selection may include more sources only within the configured Knowledge Source Selection Budget.
- Each selected **Knowledge Source** may use a different **Knowledge Provider Adapter**, but every adapter returns normalized **Candidate Evidence** through the same provider-neutral contract.
- **Cross-Source Evidence Fusion** combines normalized Candidate Evidence before Control Plane evidence admission; source routing and fusion cannot bypass Evidence Threshold or citation enforcement.
- V1 **Cross-Source Evidence Fusion** applies **Exact Cross-Source Evidence Deduplication** using a **Canonical Evidence Deduplication Key** made from canonical citation or trusted-formatted Structured Remote Source Reference plus normalized content hash. Merged candidates preserve every contributing Knowledge Source, Agent Knowledge Binding, and citation, and their WRRF contributions combine.
- **Candidate Evidence Identity** records evidence id, source id, source version id, binding id, provider name, optional document id, optional revision id, optional chunk id, citation, provider-native score, fusion rank, admission score, and trace-safe allowlisted metadata. Citation is mandatory before LLM context assembly.
- Deduplicated candidates preserve one **Candidate Evidence Contribution** per contributing source, including source and binding identifiers, provider, local document or remote chunk ids where available, provider-local rank, provider-native score, binding fusion weight, and citation.
- V1 does not deduplicate on content hash alone and does not perform semantic-similarity deduplication, because those shortcuts may collapse independently attributable evidence.
- **Merged Evidence Admission Evaluation** does not reward duplicate retrieval hits with a higher Evidence Admission Score. When configured, an approved admission scorer evaluates the merged normalized chunk once; otherwise the merged candidate uses the minimum available calibrated Evidence Admission Score from contributing sources. Contributors without calibrated admission scores remain visible in Trace but do not participate in score aggregation, and a merged candidate with no valid admission score remains inadmissible.
- V1 **Cross-Source Evidence Fusion** uses **Weighted Reciprocal Rank Fusion** because heterogeneous **Provider-Native Relevance Scores** are meaningful for provider-local ordering and Trace but are not assumed to be directly comparable across adapters.
- **Weighted Reciprocal Rank Fusion** uses a resolved **Knowledge Binding Fusion Weight** for each participating Agent Knowledge Binding; the default is 1.0, and the weight belongs to the binding rather than the shared Knowledge Source.
- Each selected binding applies its resolved **Knowledge Binding Failure Mode**: the default `required` mode fails the whole retrieval when its provider-specific call fails, while explicit `advisory` mode permits **Degraded Knowledge Retrieval** from the remaining selected bindings.
- **Degraded Knowledge Retrieval** records failed advisory binding summaries in Trace, Governance Receipt, and RunStore; remaining candidates still pass through normal Cross-Source Evidence Fusion, Evidence Threshold, and citation enforcement.
- **Cross-Source Fusion Rank** controls bounded candidate ordering before evidence admission; it does not itself create Accepted Evidence or bypass Evidence Threshold.
- The Control Envelope applies **Evidence Threshold** only to **Evidence Admission Score**, not to Provider-Native Relevance Score or Cross-Source Fusion Rank.
- A candidate without a reliable **Evidence Admission Score** remains traceable but inadmissible until an approved admission scorer supplies one.
- **Direct Evidence Score Contract Migration** removes overloaded `EvidenceChunk.score` in the same breaking implementation cutover as Direct Knowledge Contract Migration. Candidate Evidence uses optional `provider_native_score`, WRRF produces `fusion_rank`, and the Control Envelope evaluates optional `admission_score`. Validator, graph state, Trace, RunStore, Governance Receipt, providers, fixtures, and tests migrate together without a legacy alias.
- **Knowledge Source Implementation Sequence** starts with data contracts and loader changes for `knowledge_bindings[]`, Source-owned provider configuration, and split evidence scores; then implements Knowledge Source store/API; then `local_index` upload, worker, artifact cache, and snapshots; then multi-source runtime routing, provider calls, WRRF, deduplication, admission, and context assembly; then Dashboard `/knowledge`, Source detail tabs, Agent binding editor, and Run Detail; then fixtures and tests migration with legacy inline knowledge removed.
- **Accepted Evidence Context Assembly** sends only Accepted Evidence to the final-answer LLM after Control Plane evidence admission.
- **Accepted Evidence Context Assembly** iterates admitted, cited candidates in Cross-Source Fusion Rank order and stops when either **Accepted Evidence Context Chunk Budget** or **Accepted Evidence Context Token Budget** is exhausted. The defaults are 12 chunks and approximately 6000 tokens; Agent configuration may set 1 through 40 chunks and 500 through 20000 tokens.
- **Accepted Evidence Context Assembly** emits one **Accepted Evidence LLM Context Item** per included chunk with evidence id, source label, citation label, content, **Accepted Evidence Confidence Band**, source type, and context rank. It does not send Provider-Native Relevance Score, numeric Cross-Source Fusion Rank, internal source/version/revision ids, raw provider payload, or original file paths to the final-answer LLM.
- Final-answer context assembly does not reserve fixed per-source quotas. Trace records **Accepted Evidence Context Budget Truncation**, including how many already-admitted candidates remained outside LLM context.
- An **Evidence Chunk** may carry an **Evidence Citation** and **Evidence Metadata** separate from its content.
- **Control Envelope** evidence evaluation turns **Candidate Evidence** into **Accepted Evidence** or rejected evidence.
- **Authorized Tool Result** values are admitted through governed tool authorization and execution, not through evidence evaluation, even though they may support final-answer claim validation.
- Trace and Governance Receipt record **Evidence Summary** by default, not full evidence content.
- An **Agent Contract** must explicitly declare its **Retrieval Strategy**.
- An **Evidence Threshold** belongs to the **Retrieval Strategy**, not to a **Knowledge Provider**.
- A **Local Markdown Provider**, **Local Index Provider**, and remote adapters such as **HTTP JSON Knowledge Provider** are the target Knowledge Hub V1 provider families.
- The **Local Index Provider** is the production-directed knowledge integration for the **Insurance Service QA Domain**, replacing the deprecated **PageIndex Provider** per ADR-0015.
- V1 **Autonomous Customer Service Mode** keeps the **Local Markdown Provider** as the deterministic regression baseline and uses the **Local Index Provider** as the production-directed customer-service knowledge path.
- A **Local Index Provider** retrieves from an **Index-Backed Knowledge Source** created by **Knowledge Source Ingestion**; an Agent may bind that source only when its **Knowledge Source Index State** is READY.
- V1 **Local Index Snapshot Retrieval** applies **Knowledge Document Routing** within the resolved snapshot before document-level tree index search, merges normalized Candidate Evidence from the bounded selected set, applies the Agent Retrieval Strategy limit, and fails closed if any selected document search fails.
- Runtime retrieval uses **Local Index Runtime Load** against the published READY Knowledge Source Snapshot. LlamaIndex TreeIndex construction belongs to **Knowledge Source Ingestion** and must not happen on demand inside a governed Agent run.
- V1 **Knowledge Source Document Capacity** is up to 500 documents per source; this excludes unbounded per-query scans and requires explicit bounded **Knowledge Document Routing**.
- V1 **Knowledge Document Routing** first filters operator-managed metadata and then uses an LLM selector over filenames plus editable document descriptions to choose a bounded document set.
- **Knowledge Document Routing Metadata** includes title, description, tags, document type, and business category; ingestion may generate the description from LlamaIndex tree node summaries, and Dashboard operators may revise it.
- **Knowledge Document Selection Budget** defaults to 8 selected document revisions per query and is configurable from 1 through 20 at the Knowledge Source boundary; it is distinct from the Agent Retrieval Strategy evidence `top_k`.
- If **Knowledge Document Routing** selects no documents, retrieval returns no evidence rather than silently widening the search scope; uncertain selection may include more documents only within the configured **Knowledge Document Selection Budget**.
- The existing governed retrieval plan trace records an audit-safe **Knowledge Document Routing** summary, including selected document identifiers and selection basis without dumping document content.
- An **Index-Backed Knowledge Source** contains one or more **Knowledge Documents** and exposes an immutable READY **Knowledge Source Snapshot** to Agent Knowledge Bindings.
- Each **Knowledge Document** belongs to exactly one **Knowledge Source** and is indexed independently; a failed replacement build does not replace the last READY **Knowledge Source Snapshot**.
- A **Knowledge Document** keeps a stable document id while explicit file replacement creates an immutable **Knowledge Document Revision** with a new revision id. Uploading a same-named file never overwrites implicitly; Dashboard requires the operator to choose new document or replacement.
- **Knowledge Document Content Hash Reuse** makes repeated upload idempotent when content hash and ingestion configuration are compatible by reusing the existing index artifact rather than rebuilding it. Each READY revision stores a **Knowledge Revision Artifact Reference** rather than copying artifact bytes or injecting revision identity into reusable artifact metadata.
- Until a replacement Knowledge Document Revision reaches READY, its candidate snapshot continues to use the prior READY revision. After replacement becomes READY, only the unpublished candidate snapshot changes; the current published Knowledge Source Snapshot remains immutable until explicit Knowledge Source Publication.
- Each Knowledge Document revision progresses independently through **Knowledge Document Ingestion State** `QUEUED`, `PROCESSING`, `READY`, or `FAILED`. Dashboard permits retry, replacement, or archive for failed revisions without discarding unrelated READY revisions.
- A **Candidate Knowledge Source Snapshot** contains only READY Knowledge Document revisions. `QUEUED`, `PROCESSING`, `FAILED`, and archived revisions remain visible in Dashboard as explicit exclusions, and **Knowledge Source Publication** requires at least one READY revision.
- One failed or processing Draft document does not permanently block publication of unrelated READY revisions and does not change an existing bindable source away from **Knowledge Source Index State** `READY`; partial inclusion is explicit rather than silent.
- **Knowledge Document Archive** removes a document from future candidate snapshots without physically deleting revisions referenced by retained snapshots or Published Agent Versions.
- **Unreferenced Knowledge Artifact Cleanup** may physically delete only revisions and index artifacts with no retained snapshot or Published Agent Version references, and it must record configuration operation audit metadata.
- Upload, replacement, and removal of **Knowledge Documents** prepare candidate snapshots; only explicit **Knowledge Source Publication** promotes a candidate READY **Knowledge Source Snapshot** for Agent use.
- A Draft **Agent Knowledge Binding** may preview its source's latest published **Knowledge Source Snapshot**, but each **Published Agent Version** captures one **Resolved Knowledge Snapshot Binding** for every binding in its **Agent Knowledge Binding Set** so future Knowledge Source Publications do not silently change its retrieval corpus.
- **Agent Version Rollback** restores every **Resolved Knowledge Snapshot Binding** captured by the selected immutable **Published Agent Version**.
- V1 **Operator Knowledge Document Intake** accepts UTF-8 Markdown and text-based PDF files whose embedded font encodings or CMaps are extractable to meaningful Unicode text by the configured parser; scanned PDFs, OCR, images, office documents, HTML, and other formats fail closed as unsupported input.
- **Operator Knowledge Document Intake** is an internal design-time boundary and does not weaken **Text-Only Customer Intake** for customer chat.
- **Knowledge Source Ingestion** creates persisted **Knowledge Ingestion Jobs** that are claimed by a separate **Knowledge Ingestion Worker** rather than running inside Dashboard API request handling.
- The local **Knowledge Ingestion Worker** uses a file-backed recoverable queue boundary that future deployments may replace with a distributed queue without changing Knowledge Source semantics.
- An **Index-Backed Knowledge Source** owns **Knowledge Ingestion Model Configuration** independently from any Agent answer, planner, or review model configuration.
- **Knowledge Ingestion Model Configuration** stores model provider settings and credential environment-variable references, never raw credentials; promotion freezes its artifact-affecting declaration into a secret-safe **Knowledge Artifact Build Spec**, and missing credentials fail the job while preserving the last READY snapshot.
- An **Index-Backed Knowledge Source** owns **Knowledge Routing Model Configuration** independently from any Agent planner model configuration; it inherits the source's **Knowledge Ingestion Model Configuration** by default and may override provider, model, or environment-variable references.
- **Knowledge Document Routing** failure fails the retrieval closed and is recorded in Trace.
- Optional **Local Index Provider** ingestion cannot become a dependency of the deterministic no-network, no-credential demo or default CI gate.
- A **Remote Search Fixture Adapter** proves the Remote Search contract before production network integration.
- **Local Vector Provider** is historical and is not part of the Knowledge Hub V1 target architecture.
- **Knowledge First Stage** delivers executable single-step retrieval and reserves **Agentic RAG** as a governed future workflow.
- **Agentic RAG** in **Knowledge First Stage** fails with a **Retrieval Capability Error** rather than pretending to execute.
- **Agentic RAG** may orchestrate one or more **Knowledge Provider** retrievals.
- A **Retrieval Strategy** configures whether retrieval is single-step or **Agentic RAG**.
- A **Retrieval Strategy** chooses single-step or **Agentic RAG** within a business workflow template.
- A **Planner Model** may support **Agentic RAG**, but it is governed as a model call.
- **Agentic RAG** uses a **Retrieval Plan Gate** before planning and a **Retrieval Step Gate** before each retrieval step.
- A **Retrieval Step** is the workflow-level name for executing a Knowledge Provider retrieval attempt.
- **Agentic RAG** records **Retrieval Plan Event** and **Retrieval Step Event** trace facts before evidence evaluation.
- **Agentic RAG** fails closed unless **Single-Step Retrieval Fallback** is explicitly enabled.
- **Harness RAG** admits final answers only after policy and evidence checks.
- **Plain RAG** does not provide the Harness controls required by **Harness RAG**.

## Example dialogue

> **Dev:** "Should Agentic RAG be implemented as a new Knowledge Provider?"
> **Domain expert:** "No. A Knowledge Provider only returns Evidence Chunks; Agentic RAG is a controlled workflow that may call providers, but it must still stay inside the Control Envelope."

## Flagged ambiguities

- "Harness Agent framework" could mean the framework itself or an Agent built with it. Resolved: use **Controlled Agent Harness Framework** for the framework category.
- "V1 deliverable" could mean only the customer-service bot or the reusable Agent framework plus reference Agent. Resolved: V1 includes an **Agent Framework Deliverable** and the **Insurance Customer Service Agent**.
- "Workflow" could mean business flow, runtime graph mechanics, or a hard-coded orchestrator branch. Resolved: use **Workflow Template** for the governed flow shape, and keep runtime mechanics separate.
- "Workflow node editing" could mean configuring registered template stages, editing LangGraph nodes, or freely rewriting the runtime graph. Resolved: use **Workflow Template Stage Configuration** for editable stage settings that compile back to the Agent Contract without changing Harness semantics.
- "Legacy public stage compatibility" could preserve existing examples but keep node/stage ambiguity in the public Agent Contract. Resolved: use **Direct Workflow Stage Contract Migration**, migrate to `workflow.stages[]`, and do not dual-read legacy public stage aliases.
- "Internal node rename" could mean renaming every runtime graph node symbol or only public/domain Workflow Template configuration symbols. Resolved: follow **Stage Terminology Code Cutover Scope**; public/domain contracts become stages, while true Runtime Plane graph node terminology remains available.
- "`ReActWorkflowNodes` rename" could be bundled with the schema cutover or deferred to execution seam work. Resolved: defer `ReActWorkflowNodes` renaming or splitting until the Workflow Template Execution consumption slice.
- "Dashboard stage migration" could mean backend schema only or the full configuration surface. Resolved: **Dashboard Stage Configuration Surface Cutover** is part of Slice 1 and includes API payload fields, helpers, UI labels, fixtures, and tests.
- "Legacy contract migration tool" could mean providing a codemod for old generated local data or resetting local configuration state. Resolved: do not provide a legacy migration script; source-controlled fixtures are edited directly, and generated local Agent Configuration Store data is cleared with **Local Configuration Store Reset**.
- "`workflow.stages[]` item identity" could mean `id` or legacy aliases. Resolved: use **Workflow Stage Configuration Identifier** field `id` only, and reject aliases.
- "`workflow.stages[]` completeness" could mean listing every registered stage or only configured stages. Resolved: Agent Contract stores **Workflow Stage Configuration Override** entries only; omitted available stages use descriptor defaults in **Effective Workflow Stage Configuration**.
- "Effective stage config storage" could mean recomputing from overrides plus descriptor version or freezing the resolved result at publication. Resolved: Published Agent Versions store the **Published Effective Workflow Stage Configuration Snapshot** alongside overrides and descriptor version.
- "Complete stage prompt configuration" could mean exposing `system_prompt`, `developer_prompt`, or `raw_prompt`. Resolved: preserve the **Harness Prompt Authority Boundary**; stage prompt fields compile only into **Business Context Addendum**.
- "`role_guidance`" could mean a helpful business-role field or a disguised control prompt. Resolved: the first **Workflow Stage Prompt Field Set** does not include `role_guidance`; express role intent through `business_context` or `task_instructions[]`.
- "`workflow.stages[].context` shape" could mean a list of included context names or a boolean map. Resolved: use **Workflow Stage Context Option Configuration** as a descriptor-allowed boolean map with defaults and explicit false.
- "Context option false" could mean a valid explicit disable or a retained disabled-capability option. Resolved: explicit false is valid only inside the **Effective Workflow Stage Context Option Allowlist**; capability-unavailable context options are blockers even when false.
- "Stage terminology migration" could be bundled with execution behavior changes. Resolved: land the **Workflow Template Stage** cutover first, then deepen the **Workflow Template Execution** seam while preserving behavior.
- "Slice 2" could mean rewriting React stage logic, consuming Published snapshots as the only runtime input, or first establishing a typed execution boundary. Resolved: Slice 2 starts with the **React Enterprise QA Template Execution Boundary** and preserves React Enterprise QA behavior while LangGraph remains an internal scheduler.
- "Workflow Template Execution Result" could mean the final API/RunStore artifact shape or the governed facts returned by template execution. Resolved: it is the typed execution facts only; Delivery and Observability still own trace files, Governance Receipt rendering, RunStore persistence, and Dashboard projection.
- "Workflow Stage Result typing" could mean full per-stage union contracts immediately or a safer envelope first. Resolved: Slice 2 uses a **Workflow Stage Result Envelope** and records complete stage-specific union analysis as TODO.
- "Stage result summary" could mean an internal debug dump because Stage Results are inside execution. Resolved: **Workflow Stage Result Summary** is trace-safe by default and cannot carry raw Prompt/context/evidence/tool/provider/runtime state.
- "Stage handler return value" could mean keeping dict state deltas as the source of truth or returning Workflow Stage Result values directly. Resolved: React Enterprise QA stage handlers return **Workflow Stage Result Envelope** values, while a **Workflow Stage Result Runtime Adapter** handles LangGraph state delta conversion.
- "Continuation state" could mean leaking LangGraph state into execution facts. Resolved: use **Workflow Stage Continuation State** only as internal adapter input, separate from trace-safe summary and public execution results.
- "Approval pause" could mean the LangGraph interrupt payload or the governed approval state. Resolved: **Approval Pause** is the Workflow Template Execution fact; Runtime Plane interrupt mechanics are only one implementation of waiting.
- "Clarification waiting" could mean the same thing as operator approval waiting. Resolved: use **Clarification Need** for missing user information and **Approval Pause** for operator approval.
- "Workflow execution contracts" could live in the existing run contracts or ReAct-specific contracts. Resolved: use a separate **Workflow Execution Contract Module** and treat old `WorkflowState.current_node` as a follow-up convergence TODO rather than a Slice 2 blocker.
- "Workflow stage configuration contracts" could live inside Published Agent storage contracts, Workflow Template Execution contracts, or a neutral shared module. Resolved: use a separate **Workflow Stage Configuration Contract Module** shared by Agent Publication and Workflow Template Execution.
- "Published snapshot runtime consumption" could mean one execution input shape for every Agent path or separate semantics for Published and package-local runs. Resolved: the slice after React Enterprise QA Slice 2 makes **Published Effective Workflow Stage Configuration Runtime Input** the source of truth for Configuration Store Published Agent Version execution, while package-local or configured Agent execution uses **Package-Local Workflow Stage Configuration Runtime Input** from the latest supported Agent Contract structure.
- "Workflow Template Execution Input scope" could mean including every template-specific admission fact or only generic Workflow Template facts. Resolved: **Workflow Template Execution Input** remains template-generic; **Effective ReAct Action Set** is supplied to ReAct Enterprise QA Workflow Template Execution separately while still coming from **Resolved Workflow Stage Runtime Configuration**.
- "Stage Prompt/context runtime consumption" could mean only passing stage configuration through execution input or actually changing existing stage Prompt/context consumers. Resolved: React Enterprise QA stage Prompt and context consumers read Effective Workflow Stage Configuration from **Workflow Template Execution Input**.
- "Effective stage configuration type" could mean reusing the Published snapshot contract for every run or introducing a neutral value. Resolved: **Effective Workflow Stage Configuration** is the neutral value; **Published Effective Workflow Stage Configuration Snapshot** is the Published Agent Version capture of that value.
- "Effective stage configuration structure" could mean keeping loose per-stage mappings or defining typed stage entries. Resolved: **Effective Workflow Stage Configuration** contains typed **Effective Workflow Stage Configuration Stage** entries with stable top-level fields and bounded prompt/context payloads.
- "Effective stage configuration resolution owner" could mean Configuration Store publication code, Runtime Plane graph code, or a shared Control Plane operation. Resolved: Agent Publication and package-local Workflow Template Execution use the same Control Plane **Effective Workflow Stage Configuration** resolution semantics.
- "Effective stage configuration resolver output" could mean several independent helper return values or one aggregate runtime configuration fact. Resolved: use **Resolved Workflow Stage Runtime Configuration** as the single Control Plane resolver output for availability, effective config, source, trace summary, and template-specific planner action admission.
- "Effective stage configuration contents" could mean all descriptor stages with availability flags or only executable available stage configuration. Resolved: **Effective Workflow Stage Configuration** contains available stage configuration only, while **Workflow Stage Availability Set** explains unavailable stages.
- "Workflow Stage Availability Set representation" could mean documentation-only language or scattered booleans around routing code. Resolved: use a typed **Workflow Stage Availability Set** contract and have Runtime Adapters consume it without reinterpreting capabilities.
- "Workflow Stage Availability rule owner" could mean stage id conventions, Agent-owner switches, or backend template rules. Resolved: **Workflow Stage Availability Rule** belongs to the **Workflow Template Descriptor** and is resolved from Agent capability facts.
- "Effective ReAct Action Set ownership" could mean generic Workflow Template availability, prompt-only instruction, or ReAct-specific planner admission. Resolved: **Effective ReAct Action Set** is ReAct-specific, planner-facing, derived from Workflow Stage Availability and Tool Proposal Scope, and excludes unavailable actions before routing.
- "Availability and action-set guard authority" could mean LangGraph route functions, node helpers, or Workflow Template Execution stage handlers. Resolved: Control Plane Workflow Template Execution stage handlers perform admission; Runtime Adapters route only from already-admitted continuation facts.
- "Unavailable stage configuration handling" could mean rejecting Draft saves, silently dropping disabled stage overrides, or keeping inactive blockers. Resolved: Draft Agent save may retain unavailable stage configuration for repair, while Agent Validation and Agent Publication fail closed until restored or cleared.
- "Published stage availability storage" could mean embedding availability flags inside effective configuration or storing availability separately. Resolved: **Published Agent Version** stores **Workflow Stage Availability Set** separately from **Published Effective Workflow Stage Configuration Snapshot**.
- "Published Agent runtime fact handoff" could mean Workflow Template Execution reloading Published Agent Version state, Delivery passing arbitrary storage records, or Published Agent resolution carrying explicit execution facts. Resolved: use **Published Agent Runtime Facts** to hand off Workflow Stage Availability and Published Effective Workflow Stage Configuration Runtime Input without exposing them through Published Agent Directory projections.
- "Approval resume stage configuration" could mean rebuilding execution input when a tool approval resumes or restoring the run-start execution input. Resolved: a paused **Workflow Template Execution** resumes with the same **Workflow Template Execution Input** selected at run start.
- "Workflow Template Execution Input persistence" could mean ordinary trace/receipt storage, Dashboard-visible run detail, inline resume context, or Runtime Plane resume metadata. Resolved: full run-start input may be retained only behind **Workflow Template Execution Resume Metadata** as a protected reference with integrity validation; ordinary projections expose trace-safe summaries and references.
- "Workflow Stage Configuration trace summary" could mean full prompt/context capture, only per-stage applied context events, or one run-level source summary. Resolved: ordinary trace records a run-level **Workflow Stage Configuration Trace Summary** for the selected **Workflow Template Execution Input**, while full capture remains a separate validation/test-run concern.
- "Workflow Stage Trace Capture Mode placement" could mean Published Agent Version configuration, Workflow Template Execution Input, or validation/test observability request policy. Resolved: **Workflow Stage Trace Capture Mode** is a validation/test observability policy outside **Workflow Template Execution Input**; full-capture alignment to run-start input remains a separate trace-capture slice concern.
- "Published snapshot runtime consumption slice scope" could mean only adding snapshot fields, rewriting validation capture, replacing LangGraph, or consuming frozen stage facts at run start. Resolved: **Published Effective Workflow Stage Configuration Runtime Consumption Slice** consumes resolved stage availability/configuration facts at run start and defers full-capture realignment, historical descriptor registries, dynamic topology, complete stage result unions, second runtimes, and local-store compatibility migration.
- "Workflow Template Execution Input creation" could mean Delivery/API assembling per-surface inputs, Runtime Plane interpreting stage config, or a shared run entry point delegating to Control Plane resolution. Resolved: the common governed run entry point creates the run-scoped input after run id selection and delegates Effective Workflow Stage Configuration resolution to Control Plane logic.
- "Template descriptor version execution" could mean building a historical executable descriptor registry in this slice or only validating that the selected executable descriptor matches the Workflow Template Execution Input. Resolved: this slice fails closed on descriptor version mismatch and leaves versioned historical executable descriptors to a future slice.
- "Availability guard implementation" could mean dynamically generating LangGraph topology or keeping a static LangGraph adapter with runtime-neutral Control Plane guards. Resolved: this slice may keep static LangGraph topology, while availability routing and fail-closed decisions remain Workflow Template Execution semantics that future Runtime Adapters can consume.
- "LangGraph decoupling" could mean replacing LangGraph now, renaming every LangGraph-specific runtime class, or only removing Control Plane dependencies on LangGraph mechanics. Resolved: this slice removes direct Control Plane dependency on LangGraph interrupts/state/scheduler APIs while keeping LangGraph as the current **Workflow Runtime Adapter**.
- "React execution object naming" could mean a generic `ReActWorkflowExecution` or a concrete React Enterprise QA execution class. Resolved: use **ReAct Enterprise QA Workflow Execution** for the concrete class and reserve generic ReAct names for future shared abstractions.
- "ReAct framework" could mean an autonomous model-driven agent loop or a governed flow shape. Resolved: use **Controlled ReAct Workflow** for the governed Proof Agent version.
- "Multi-round user intent thinking" could mean exposing raw model thoughts or adding a governed understanding step. Resolved: use **Intent Resolution** as an audit-safe step before ReAct planning.
- "Intent Resolution rollout" could mean a mutable feature flag on the existing ReAct template or a new template version. Resolved: use **React Enterprise QA Template V2** so historical Published Agent Versions keep stable workflow semantics.
- "Intent summary" could mean reusing **Reasoning Summary** or creating a separate contract. Resolved: use **Intent Resolution Contract** because user-intent understanding and ReAct action rationale are different audit facts.
- "Multi-round Intent Resolution" could mean repeated hidden thinking inside one run or governed accumulation across user turns. Resolved: run Intent Resolution once per governed run and accumulate multi-turn understanding through **Controlled Conversation Context** and **Clarification Continuation Run**.
- "Intent Resolution next action" could mean directly executing retrieval or tools. Resolved: **Intent Resolution** may recommend an action category only; the **ReAct Planner** must still produce the governed **ReAct Action Proposal** before execution can be reviewed.
- "Intent Resolution review" could mean a new Auto Review enforcement point or deterministic validation only. Resolved: V2 uses deterministic **Intent Resolution Contract** validation and trace recording, while executable actions stay governed by existing ReAct review and `PolicyEngine` nodes.
- "Intent Resolution model config" could mean introducing a third Agent-owner model role or reusing planner configuration. Resolved: V2 reuses **ReAct Planner Config** but records Intent Resolution as a distinct model-call role and audit fact.
- "Intent Resolution visibility" could mean showing the understood intent to every user or treating it as governance detail. Resolved: expose it only through internal trace, receipt, Dashboard, or allowed operator **Governance Detail Projection**, never as ordinary customer-facing response text.
- "`enterprise_qa` with flags" could blur the deterministic baseline with ReAct behavior. Resolved: V1 adds **React Enterprise QA Template** instead of changing the existing template.
- "Customer service workflow" could mean the existing linear Enterprise QA path or the ReAct path. Resolved: V1 customer-facing automation uses **React Enterprise QA Template**; **Enterprise QA Template** remains the baseline path.
- "ReAct MVP" could mean requiring a remote LLM. Resolved: V1 requires a **Deterministic ReAct Demo**.
- "ReAct planner" could mean the final answer model or a separate planning role. Resolved: use **ReAct Planner** and configure it through **ReAct Planner Config**.
- "LLM planner" could mean replacing deterministic acceptance behavior or adding a second planner implementation. Resolved: use **LLM ReAct Planner** as an additional implementation.
- "V1 LLM support" could mean deterministic-only demo or unbounded model support. Resolved: V1 is real-LLM capable through the supported **Model Provider Registry** paths while deterministic planner, reviewer, and model behavior remain the release gate.
- "ReAct action" could mean arbitrary model output or a bounded action enum. Resolved: V1 uses a fixed **ReAct Action Set**.
- "Planner tool allowlist" could mean direct execution permission or the set of tool identifiers the planner may propose. Resolved: use **Tool Proposal Scope** for proposal eligibility only; execution still requires Harness policy and Tool Gateway authorization.
- "LLM automatic decision" could mean model self-approval, rule-based Harness review, or a Control Plane review subagent. Resolved: use **Harness Review Subagent** for the LLM-backed control component that runs only in **Auto Review Mode**.
- "LLM reviewer" could mean replacing deterministic review behavior or adding a provider-backed reviewer implementation. Resolved: use **LLM Harness Review Subagent** as an additional implementation.
- "Review model" could mean the final answer model or a separate control-plane reviewer. Resolved: **Review Subagent Config** is independent from final answer `model`.
- "AI core capability" could mean business answer generation, ReAct planning, or Harness review. Resolved: use **Business Agent AI Core** for business-facing AI and **Harness Decision Assistance** for control-facing AI.
- "Agent model configuration" could mean one shared model for every role or role-specific model settings. Resolved: use **Model Role Configuration**; UI may offer reuse shortcuts, but the Agent Contract stores distinct final, planner, and reviewer role settings.
- "Dashboard Models" could mean a provider model catalog, reusable connection assets, or Agent-only model fields. Resolved: use **Models Workspace** for administering live **Shared Model Connections**; Agent roles and Knowledge Sources may select a shared connection or use custom model configuration.
- "Shared model versioning" could mean pinning model connections into Published Agent Versions or resolving them live. Resolved per ADR-0020: **Shared Model Connections** are live references, and **Model Connection Impact Review**, configuration audit, **Model Connection Resolution Record**, and fail-closed resolution provide accountability instead of publication pinning.
- "Reviewer model parameters" could mean reviewer-specific top-level fields or the same role usage shape used by Answer and Planner. Resolved: use **Model Usage Parameters** under `review.subagent.params` for timeout, maximum output tokens, temperature, and similar model-call settings; migrate directly without dual-reading old top-level reviewer usage fields.
- "Separate model provider" could mean separate provider registries or separate configured instances. Resolved: **Business Agent AI Core** and **Harness Decision Assistance** share the **Model Provider Registry** but remain separate configured instances.
- "`ai_core` configuration" could mean a new top-level Agent Contract field or the existing role-specific model fields. Resolved: keep role-specific `model`, `react.planner`, and `review.subagent` fields.
- "Planner provider" or "review provider" could mean role-specific provider names. Resolved: provider names identify external model channels; role semantics come from the Agent Contract section.
- "LLM output" could mean raw provider text, provider-native tool calls, or a typed Harness contract. Resolved: V1 uses **Harness-Normalized Model Output** before any output affects control behavior.
- "JSON output" could mean strict JSON mode, JSON inside text, or natural-language field inference. Resolved: use **Model Output JSON Contract** with bounded extraction only.
- "Planner trace event" or "review trace event" could mean new role-specific model event names. Resolved: use shared model request and response events with **Model Call Role**.
- "Planner prompt" or "review prompt" could mean Agent-authored business instructions or Harness-maintained control instructions. Resolved: use **Harness Control Prompt** for V1 control-plane prompts.
- "Control context" could mean raw runtime state or a curated Harness input. Resolved: use **Structured Control Context** for planner and reviewer model calls.
- "Invalid model output" could mean guessing a safer action, asking clarification, or failing closed. Resolved: use **Model Output Normalization Failure** and trace the precise parse or validation reason.
- "Native tool calling" could mean provider-controlled tool execution or a payload normalization mechanism. Resolved: native tool calling is future **Native Tool Call Adapter** work and cannot bypass Harness governance.
- "Subagent decision" could mean a final policy decision or a typed suggestion. Resolved: a **Review Decision** is only advisory until `PolicyEngine` validates it.
- "Reviewer failure" could mean proceed optimistically or stop safely. Resolved: **Review Failure Policy** fails closed and records the reason.
- "Review every node" could include answer admission and final output validation. Resolved: V1 **Auto Review Scope** excludes deterministic answer admission as an authority boundary.
- "ReAct reasoning" could mean raw chain-of-thought or trace-safe planning facts. Resolved: record **Reasoning Summary** only.
- "Review trace" could mean final policy or reviewer suggestion. Resolved: **Review Decision Event** records the suggestion; `policy_decision` records the final governance decision.
- "Show planning" could mean trace recording or user-visible response projection. Resolved: **Governance Detail Projection** controls API/UI exposure, not trace completeness.
- "Full validation trace" could mean always storing raw prompt/context/debug payloads, a production diagnostic button, Published Agent configuration, ordinary trace content, or a controlled validation request switch. Resolved: default trace uses **Workflow Stage Configuration Trace Summary** and snapshot references; **Workflow Stage Trace Capture Mode** belongs to Agent Validation Run or explicit test-run requests and produces **Sensitive Validation Capture Artifact** output while preserving safety exclusions.
- "Full capture retention" could mean ordinary run trace retention or short-lived sensitive validation retention. Resolved: use **Sensitive Validation Capture Retention** with default 7-day TTL; ordinary summary trace, receipt facts, and validation outcomes remain under normal run artifact retention.
- "Response visibility flag" could mean an unrestricted frontend request. Resolved: **Response Detail Policy** caps what API responses can expose.
- "Policy configuration" could mean natural-language instructions, prompt rules, or executable governance rules. Resolved: use **Policy Rule Configuration** for structured rules; natural-language descriptions are non-executable unless compiled and validated.
- "Customer response" could mean the full internal run response or a customer-safe shape. Resolved: customer-facing surfaces use **Customer-Safe Response Projection** and internal operator/developer surfaces use governed audit projections.
- "Customer projection" could mean rewriting the run result without audit linkage. Resolved: projection is allowed for customer safety only when the exact customer-visible **Customer Response Snapshot** is linked to the governed run.
- "Customer-visible tool source" could mean exposing the tool name or internal run reference. Resolved: customer-facing responses use **Customer-Safe Source Label** values, and internal run artifacts map those labels to specific **Authorized Tool Result** records.
- "Product term explanation" could mean generic evidence-backed interpretation or a personalized coverage decision. Resolved: V1 supports **Insurance Product Term Interpretation** only when grounded in accepted evidence or authorized tool results and not framed as a guarantee or legal advice.
- "Insurance service process" could mean explaining how the process works or executing a service action. Resolved: V1 supports **Insurance Service Process Guidance** for evidence-backed process explanation and safe next-step options, not transactional action, SLA commitment, or claim outcome decision.
- "Anonymous insurance question" could mean generic product/process explanation or a personalized service request. Resolved: anonymous sessions may ask generic term and process questions, but **Personalized Insurance Service Request** handling requires authentication.
- "Am I covered" could mean explaining relevant coverage terms or making a personalized coverage/payment decision. Resolved: V1 may explain terms, process, and authorized status facts, but **Personalized Coverage Or Payment Decision** is out of autonomous scope and maps to **Payment Or Coverage Guarantee Request** when a conclusion is requested.
- "Improve approval odds" could mean a document checklist or **Outcome Optimization Advice**. Resolved: V1 may provide evidence-backed preparation steps and required materials, but must not predict, optimize, or imply improved claim, coverage, eligibility, approval, or payment outcomes.
- "Unsafe process wording" could mean refusing the whole request or safely reframing it. Resolved: V1 uses **Safe Process Guidance Reframe** when possible, and refuses or hands off only when the user insists on prediction, guarantee, personalized decision, or rule evasion.
- "Analysis" could mean evidence-bound explanation or unsupported reasoning beyond the source. Resolved: customer-facing analysis stays inside the evidence boundary and every business claim remains validated.
- "Friendly wording" could mean harmless conversational text or unsupported business advice. Resolved: **Safe Conversational Text** may be unaudited for evidence, but every **Customer-Facing Business Claim** requires **Accepted Evidence** or an **Authorized Tool Result**.
- "Multilingual customer service" could mean Chinese/English support or arbitrary language coverage. Resolved: V1 uses **Customer Response Language Policy** for Chinese and English only.
- "Translation" could mean a customer-safe projection or a new fact-generation layer. Resolved: V1 allows **Evidence-Bound Translation** only for claims already supported by **Accepted Evidence** or **Authorized Tool Result** values, with source references anchored to the original source.
- "V1 acceptance" could mean isolated demo questions or complete customer journeys. Resolved: V1 uses a **Customer Journey Acceptance Suite** covering anonymous, authenticated, refusal, clarification, internal handoff, retrieval failure, and bilingual paths.
- "Journey acceptance test" could mean a compatibility smoke test or a hard release blocker. Resolved: keep always-on smoke assertions for current customer-safe behavior, and use V1 release-gate assertions to expose unmet release requirements until strict validation is enabled.
- "Customer feedback" could mean an observation signal, run artifact fact, memory source, or online learning input. Resolved: V1 uses **Customer Feedback Signal** for observation only, keeps it linked to conversation turn and governed run, and does not create **Case Memory**, train, or update behavior.
- "Customer-visible answer history" could mean recomputing from trace, using the complete visible message as memory, or storing what the customer actually saw. Resolved: V1 stores the complete text as a **Customer Response Snapshot** linked to the governed run; **Case Memory** may only use bounded, trace-safe facts or summaries derived from that snapshot linkage.
- "V1 release" could mean private enterprise pilot or public internet production. Resolved: V1 is a **Private Pilot Customer Service Bot**; public-scale operations are future platform work.
- "Streaming" could mean customer-safe stage progress or raw model tokens. Resolved: V1 exposes **Customer Run Progress State** only; token streaming is future verified streaming work.
- "ReAct loop" could mean unlimited autonomous tool use or a bounded governed loop. Resolved: V1 uses a **ReAct Action Budget** and permits at most one governed tool call.
- "ReAct first action" could mean answer, tool call, retrieval, or clarification. Resolved: V1 uses **Evidence-First ReAct**.
- "Needs more user input" could mean refusal or approval. Resolved: use **Clarification Request** and **Waiting For User Clarification**.
- "Continue after clarification" could mean resuming the same runtime checkpoint or starting another governed run. Resolved: V1 uses a **Clarification Continuation Run** with **Controlled Conversation Context**.
- "Loaded manifest" could mean raw configuration or a ready-to-run execution object. Resolved: use **Harness Invocation** for the resolved run input assembled from contract and capabilities.
- "Chat API" could mean a raw model chat endpoint or a governed execution endpoint. Resolved: use **Run Execution API** for starting Harness runs from chat surfaces.
- "Customer chat API" could mean reusing the internal Chat API or adding a customer-safe endpoint. Resolved: V1 uses **Customer Run API** for customer-facing runs and keeps internal Chat API responses for operator/developer surfaces.
- "Configuration API" could mean extending Dashboard read routes, execution routes, or a separate boundary. Resolved: use **Agent Configuration API** for configuration lifecycle while keeping **Dashboard API**, **Run Execution API**, and **Customer Run API** separate.
- "Agent selection" could mean a user-provided manifest path or a configured Agent identity. Resolved: application surfaces call a **Published Agent** by stable agent identifier.
- "Agent discovery" could mean reading draft/version configuration state from the Dashboard or listing application-facing Agents. Resolved: use **Published Agent Directory** for chat discovery and keep **Agent Configuration API** focused on configuration lifecycle.
- "Chat Agent display name" could mean reading the latest Draft Agent metadata or the publication snapshot. Resolved: **Published Agent Directory Entry** uses metadata captured at publication time; unpublished draft edits do not rename already published chat entries.
- "Open chat by Agent id" could mean bypassing publication checks or using a direct chat route. Resolved: **Direct Agent Chat Entry** supports stable Agent identities while preserving the same audience checks as directory-based access.
- "Direct chat route" could mean changing existing conversation URLs or preparing a new Agent-bound conversation. Resolved: **Direct Agent Chat Entry** prepares a new conversation by Agent identity, while existing chat conversations remain addressed by conversation identity.
- "Invalid direct Agent id" could mean falling back to the default Agent, creating a draft preview, or showing an unavailable state. Resolved: **Direct Agent Chat Entry** fails closed with an unavailable/not-found state for the requested audience.
- "Open direct Agent chat" could mean immediately creating a stored empty conversation or preparing a new-message draft. Resolved: **Direct Agent Chat Entry** creates the stored conversation only when the first message is submitted.
- "Customer-visible Agent not found" could mean unknown Agent id only or unavailable for customer audience. Resolved: customer-facing discovery and errors expose only **Customer-Facing Published Agents**, and **Customer Run API** rejects non-customer-facing Agents at conversation creation.
- "Customer chat Agent selection" could mean selecting both an Agent and customer identity. Resolved: Agent selection and customer session mode are independent; customer identity is supplied through **Customer Authorization Context** during customer conversation creation.
- "Default chat Agent" could mean a hidden hardcoded example Agent or audience-aware selection. Resolved: if only one **Published Agent** is available for the audience it may be preselected; otherwise chat uses **Published Agent Directory** selection.
- "After publish, open chat" could mean automatic redirect or an explicit action. Resolved: **Agent Publication** may present chat entry actions, but does not automatically start or redirect to a chat conversation.
- "Static example Agent" could mean a built-in Published Agent or a reusable package template. Resolved: use **Example Agent Template** for static packages; only **Agent Publication** creates a formal **Published Agent** for application-facing execution.
- "Running an example Agent" could mean local CLI validation or application-facing execution. Resolved: CLI/demo/test entry points may run **Example Agent Templates** directly, but chat and run APIs require **Agent Publication** first.
- "No Agents in chat" could mean falling back to examples, auto-importing a template, or showing a setup state. Resolved: chat shows an empty state and points to the **Agent Configuration Workspace**; only explicit import, validation, and publication make an Agent chat-accessible.
- "Save Agent configuration" could mean creating a runnable Agent or persisting work in progress. Resolved: saving creates or updates a **Draft Agent**; only **Agent Publication** creates or updates a **Published Agent** for application-facing execution.
- "Rollback" could mean editing an old version, overwriting current production config, or changing the active pointer. Resolved: **Agent Version Rollback** selects an earlier immutable **Published Agent Version** as the **Active Agent Version**.
- "Configuration storage" could mean replacing Agent Contract files or storing editable product state. Resolved: the **Agent Configuration Store** owns draft/version metadata, while **Agent Contract** and **Agent Package** remain the reviewable execution artifacts.
- "Unified capability configuration" could mean an internal resolved profile over scattered YAML fields or a public Agent Contract YAML structure. Resolved: use top-level `capabilities:` as **Agent Contract Capability Configuration**, then resolve stage availability during Agent Publication.
- "Capability config migration" could mean dual-reading legacy top-level `tools` and `memory` or making one schema cutover. Resolved: use **Direct Capability Contract Migration** and reject legacy top-level capability fields.
- "Implementing the stage/capability contract" could mean one giant runtime and schema refactor or a staged migration. Resolved: follow **Agent Contract Stage Capability Implementation Sequence** so schema, publication snapshots, runtime consumption, and validation trace capture remain separately testable.
- "Schema cutover implementation order" could mean editing loader first or locking behavior with tests first. Resolved: Slice 1 starts with **Contract Schema Cutover Test Gate** before implementation.
- "`capabilities.knowledge`" could mean treating retrieval as an optional stage-availability capability. Resolved: keep `knowledge_bindings[]` as the separate Agent Knowledge Binding domain; React Enterprise QA retrieval stages remain available and fail through validation or retrieval when knowledge config is missing or invalid.
- "Enabled tools with an empty tool file" could mean an available Tool Stage Group with no proposals or an invalid capability. Resolved: **Enabled Capability Readiness** requires at least one valid **Tool Contract** when `capabilities.tools.enabled` is true.
- "Enabled memory with no scopes" could mean invalid configuration for all providers or valid session memory. Resolved: **Enabled Capability Readiness** requires a provider; provider-specific schema decides scope requirements, and scoped providers must enable at least one scope.
- "Disabled capability config" could mean a clean disabled declaration or a dormant configured capability. Resolved: published YAML permits clean `enabled: false` only; active fields under disabled capabilities are **Disabled Capability Configuration** blockers in Draft.
- "Missing capability config" could mean disabled-by-default or incomplete YAML. Resolved: use **Explicit Capability Enablement**; missing template-relevant capability domains or `enabled` fields fail schema or validation.
- "Configuration database" could mean requiring a production DB for the first implementation or defining a replaceable persistence boundary. Resolved: first use a **Local Agent Configuration Store** with a store adapter boundary.
- "Import Agent" could mean running an arbitrary manifest, overwriting example files, or creating an editable draft. Resolved: **Agent Package Import** creates a **Draft Agent** from a reviewable Agent Package and preserves advanced fields.
- "Configuration permissions" could mean full enterprise RBAC or no permission model at all. Resolved: first-stage configuration may be single-user, but the **Agent Configuration Permission Model** and **Configuration Operation Audit** fields are part of the domain model.
- "Test run" could mean a cosmetic frontend preview or a governed pre-publication execution. Resolved: use **Agent Validation Run** for required validation and test execution before **Agent Publication**.
- "Validation run storage" could mean a separate preview log or ordinary run history. Resolved: store validation artifacts in RunStore and distinguish them with **Run Purpose** metadata.
- "Workflow builder UI" could mean an ordered stage configuration panel or a drag-and-drop canvas. Resolved: first use a **Workflow Stage Panel**; any future canvas remains a presentation of Workflow Template Stage Configuration, not a new runtime graph source.
- "Two-layer workflow display" could mean two executable graphs or one governed workflow with a business-plan projection. Resolved: Dashboard uses **Workflow Control Layer Map** for the fixed Harness layer, **Workflow Business Plan Layer** for the Dynamic Insurance Business Subplan, and **Workflow Plan-to-Stage Mapping** to explain how business steps are handled without creating new topology.
- "YAML editor" could mean a second source of truth, an export pane, or a contract-level editor. Resolved: use **Contract View** as an advanced view over the same Draft Agent state, validated before save or publication.
- "Dashboard API" could mean read-only observability or execution. Resolved: Dashboard and receipt views remain read projections; **Run Execution API** owns run creation.
- "Management console" could mean internal run observability, Dashboard-hosted Agent configuration, or a full platform administration product. Resolved: V1 keeps an **Internal Governance Dashboard** for observability; Agent configuration belongs in an **Agent Configuration Workspace** hosted by the **Dashboard Shell** with separate configuration APIs; full **Agent Control Platform Console** work is future scope.
- "Agent builder" could mean a blank free-form graph editor or a guided Contract-first setup. Resolved: new Agents start in an **Agent Creation Wizard** and continue in the **Agent Configuration Workspace**.
- "Dashboard navigation" could mean a separate builder app, a settings page, or Agent-centered operations. Resolved: use an **Agent-Centric Dashboard Shell** with global observability and Agent detail views for monitoring and configuration.
- "Handoff monitoring" could mean a dashboard projection or a full ticket workflow. Resolved: V1 provides **Internal Handoff Monitor** only; assignment, SLA, notification, and ticket status workflows are future scope.
- "Approve and continue" could mean durable checkpoint resume or a new governed follow-up run. Resolved: use **Approval Checkpoint Resume** for approval decisions; do not start a new governed follow-up run merely to carry approval.
- "Enterprise QA intelligent customer service" could mean the whole product or the first Agent built with it. Resolved: use **Enterprise QA Reference Agent** for the first Agent and keep Proof Agent as the framework.
- "Insurance customer service Agent" could mean the existing insurance QA example or the V1 customer-facing Agent. Resolved: use **Insurance Customer Service Agent** for the V1 Published Agent and keep the existing insurance QA example as a baseline package.
- "Intelligent customer service" could mean direct customer-facing automation or staff assistance. Resolved: V1 delivery is **Autonomous Customer Service Mode**; **Assisted Service Mode** is a separate staff-assistance mode.
- "Chat frontend" could mean a customer-facing chatbot or a staff workbench. Resolved: V1 chat is a **Customer Service Chat Frontend**; **Assisted QA Chat Frontend** is the operator-facing surface.
- "Shared chat frontend" could mean one unrestricted UI or a shared shell with separate audience projections. Resolved: use **Unified Chat Frontend** for a shared design and interaction shell, with customer mode limited to **Customer-Safe Response Projection**.
- "Published Agent in chat" could mean every published Agent appears in every chat mode or a mode-specific access boundary. Resolved: **Published Agent Chat Access** exposes all Published Agents to operator chat, and exposes only **Customer-Facing Published Agents** to customer chat.
- "Customer-facing Agent" could mean an Agent id allowlist, workflow template, purpose text, or contract capability. Resolved: a **Customer-Facing Published Agent** is a Published Agent whose Agent Contract declares a top-level customer section.
- "Customer channel" could mean Web chat, messaging apps, email, mobile SDK, or contact-center integration. Resolved: V1 ships **Customer Service Web Chat**; other channels are future adapters.
- "Customer intake" could mean text questions or uploaded customer documents. Resolved: V1 uses **Text-Only Customer Intake**; attachment analysis is future work.
- "Customer-safe text" could mean no Harness run is needed for prompts or refusals. Resolved: Safe Conversational Text may not require Accepted Evidence, but every **Customer Run API** turn still needs a governed run and non-empty RunStore `run_id`.
- "Customer chat session" could mean anonymous policy browsing or authenticated account service. Resolved: use **Anonymous Customer Session** for generic-only access and **Authenticated Customer Session** for customer-specific service.
- "Customer context" could mean conversation history, identity, authorization, or raw credentials. Resolved: use **Controlled Conversation Context** for prior turns and **Customer Authorization Context** for verified customer scope; raw credentials never enter the Harness run context.
- "Customer authorization check" could mean API preflight or Harness-governed policy context. Resolved: Customer Run API may resolve mock identity, but **Customer Authorization Context** must be admitted into the Harness run so PolicyEngine, Tool Gateway, trace, receipt, and review paths can explain customer-specific access.
- "Customer resource selection" could mean choosing a default resource, presenting safe disambiguation options, or deterministically resolving one. Resolved: V1 requires **Customer-Owned Resource Resolution** to identify exactly one owned resource before a customer-specific read; otherwise it returns a **Customer Resource Disambiguation Prompt**.
- "Only one matching resource" could mean still asking for an id or proceeding with the unique resource. Resolved: when the **Owned Resource Handle Index** has exactly one matching customer-owned resource, V1 may proceed to single-resource lookup proposal without a disambiguation prompt.
- "Resolution audit" could mean customer-visible explanation or internal run basis. Resolved: **Customer Resource Resolution Basis** is an internal artifact fact recorded in Trace, Governance Receipt, and RunStore; customers see only safe handles or source labels.
- "Partial resource identifier" could mean a safe customer-facing handle or a raw backend identifier. Resolved: V1 disambiguation prompts may show **Customer-Safe Resource Handle** values such as fixture-provided ids, last-four identifiers, dates, or type labels, but not status, amounts, coverage, internal customer ids, raw payload fields, or authorization details.
- "Resource handle source" could mean authenticated owned-resource metadata or a hidden batch lookup. Resolved: **Customer-Safe Resource Handle** values come from an **Owned Resource Handle Index** supplied by auth context, mock personas, or a future identity adapter, not from running status lookup tools in bulk.
- "Resource count" could mean disambiguation metadata or a bulk account summary. Resolved: V1 may show matching resource counts from the **Owned Resource Handle Index** only to explain selection, not as status, amount, coverage, or eligibility information.
- "Disambiguation option state" could mean authorization, memory, or conversation context. Resolved: use **Customer Disambiguation Option Mapping** inside **Controlled Conversation Context**, linked to the originating run and **Customer Response Snapshot**, not **Customer Authorization Context** or **Case Memory**.
- "Disambiguation lifetime" could mean reusable conversation memory or a one-step clarification aid. Resolved: **Customer Disambiguation Option Mapping** is valid only for the current clarification sequence and expires on successful lookup, replacement prompt, identity change, conversation reset, Agent change, or timeout.
- "Expired disambiguation" could mean recovering stale option mappings from conversation history or asking again. Resolved: expired or absent **Customer Disambiguation Option Mapping** forces a new **Clarification Request**; old transcripts, snapshots, and **Case Memory** cannot restore it.
- "Customer authentication" could mean proving the Harness authorization boundary or integrating a production identity provider. Resolved: V1 uses **Mock Authenticated Customer Session** and reserves production OAuth/OIDC/IAM for **Customer Identity Adapter** work.
- "Mock customer" could mean a single demo identity or multiple authorization fixtures. Resolved: V1 uses at least two **Mock Customer Persona** fixtures and tests **Cross-Customer Access Attempt** behavior.
- "Cross-customer access" could mean a normal refusal or an internal security signal. Resolved: V1 returns customer-safe refusal wording and records an internal **Customer Escalation Handoff** for every **Cross-Customer Access Attempt**.
- "Customer service automation" could mean read-only answers or business-state changes. Resolved: V1 is **Read-Only Customer Service**; state-changing work is a **Transactional Customer Action** and is out of scope.
- "Institution insurance specialist workflow" could mean a short-term-insurance-only topology or a reusable staff-facing insurance workflow. Resolved: use **Institution Insurance Specialist** as the generic assisted-service user, and constrain short-term insurance deployments through **Insurance Business Line Scope** rather than a Harness-coded workflow fork.
- "Institution business system access" could mean read-only query support or direct business operations. Resolved: V1 **Read-Only Institution Assistance** may use **Institution Business Read Tool** bindings for reports, policies, claims, customers, agents, and configured business-line records; state-changing work is a **Transactional Insurance Operation** and is out of scope.
- "Insurance source truth" could mean knowledge documents, report data, business-system records, or the model's synthesized judgment. Resolved: use **Insurance Source Authority Order**; records answer current state, documents answer rules, reports answer metrics, and unresolved conflicts remain explicit instead of being reconciled by the model.
- "Missing institution authorization context" could mean refusing every request or allowing unrestricted tool lookup. Resolved: without sufficient **Institution Authorization Context**, the Agent may answer a **Public Insurance Knowledge Query** from approved knowledge sources, but must not use **Institution Business Read Tool** bindings for scoped reports, policy records, claim records, customer records, or agent records.
- "Institution specialist answer shape" could mean one final answer for every audience or separate operator and external-facing views. Resolved: use **Institution Specialist Response Projection** for the staff-facing answer and include an **External Wording Draft** only when the request source or use case is customer or agent communication.
- "Institution specialist intent routing" could mean a fixed business taxonomy only, unrestricted LLM-defined execution, or dynamic business planning inside a governed workflow. Resolved: use **Insurance Specialist Intent Taxonomy** as a baseline anchor, allow the **LLM ReAct Planner** to create a **Dynamic Insurance Business Subplan** for any insurance-related intent, and keep executable actions, tool scope, Workflow Template topology, and policy authority under the Control Envelope.
- "Institution specialist memory" could mean current-case follow-up context or a long-lived business fact store. Resolved: use **Institution Specialist Case Memory** for current task focus, clarified identifiers, scoped filters, and response-format preferences only; policy status, claim status, report values, tool payloads, and customer or agent identity facts remain live business records, not memory facts.
- "Payment guarantee" could mean an ordinary unsupported question or a high-risk service commitment request. Resolved: use **Payment Or Coverage Guarantee Request** and create an internal **Customer Escalation Handoff** while returning customer-safe refusal wording.
- "Handoff trigger configuration" could mean hard-coded only, business-configurable, or prompt-defined. Resolved: V1 keeps fixed baseline triggers and permits Agent Contract or policy configuration only for enterprise high-value failure scenarios; frontend and prompt-defined triggers are not trusted.
- "Customer lookup" could mean generic retrieval, authenticated account lookup, or a transaction. Resolved: use **Customer-Specific Read Tool** for authenticated read-only account facts.
- "Customer status lookup" could mean policy status, claim status, or a generic customer profile dump. Resolved: V1 exposes **Policy Status Lookup Tool** and **Claim Status Lookup Tool** only.
- "Missing claim id" could mean asking about all claims, guessing the newest claim, or asking the customer to clarify. Resolved: when multiple customer-owned claims match and no unique claim is resolved, V1 asks through a **Customer Resource Disambiguation Prompt** and does not propose a concrete lookup until a follow-up resolves exactly one resource.
- "The first one" could mean ordinary language understanding or unsafe default selection. Resolved: V1 may use ordinal or descriptive clarification replies only when they point to a prior **Customer Resource Disambiguation Prompt** option through **Customer Disambiguation Option Mapping** preserved in **Controlled Conversation Context**.
- "List all my claims" could mean a safe disambiguation aid or a bulk customer resource listing. Resolved: V1 read tools support **Single-Resource Customer Read** only; bounded disambiguation handles are allowed, but bulk status listing is future capability work.
- "Customer planner tool scope" could mean a generic customer lookup tool or the concrete V1 status lookup tools. Resolved: customer-mode **Tool Proposal Scope** includes **Policy Status Lookup Tool** and **Claim Status Lookup Tool** when declared by the Agent Contract and Tool Contracts; proposals remain non-executable until authorized.
- "Tool configuration" could mean a reusable connection, a governance contract, or an Agent-specific enablement rule. Resolved: use **Tool Source** for the connection/package, **Tool Contract** for governance, and **Agent Tool Binding** for per-Agent scope and approval settings.
- "Approval for customer lookup" could mean human approval or policy authorization. Resolved: V1 customer-facing read lookups are **Policy-Authorized Read Tool** calls; human approval is reserved for assisted or higher-risk flows.
- "Policy-authorized read" could mean direct Customer API preflight execution or a governed tool call that skips only human approval. Resolved: it skips human approval only; the read still runs inside the **Control Envelope** and writes full Harness run artifacts.
- "Tool authorization" could mean planner self-certification, reviewer advice, or deterministic contract enforcement. Resolved: **Tool Contract** and **Agent Contract** policy metadata define the conditions, while PolicyEngine and Tool Gateway enforce them against normalized arguments and **Customer Authorization Context**.
- "Read-tool authorization failure" could mean exposing access-control details to the customer or recording an internal denial. Resolved: V1 uses **Customer Tool Authorization Denial** internally and returns only customer-safe refusal or clarification text externally.
- "Tool Gateway failure" could mean authorization denial, insufficient evidence, or runtime failure. Resolved: after authorization, Tool Gateway, adapter, dependency, timeout, or runtime failures are **Customer Tool Execution Failure** events with customer-safe temporary failure wording and no default handoff.
- "Try again later" could mean safe temporary failure wording or a service commitment. Resolved: V1 may use it as **Safe Conversational Text** for **Customer Tool Execution Failure**, without promising recovery, successful retry, human follow-up, or escalation.
- "Retry customer lookup" could mean replaying the previous tool call or starting a governed retry. Resolved: V1 uses **Customer Tool Retry Run**, a new governed run linked to the failed run that repeats resolution, authorization, and execution.
- "Repeated tool failures" could mean automatic handoff or configurable high-value failure detection. Resolved: **Customer Tool Failure Series** records linked failures by conversation/resource/tool intent, and handoff occurs only when **Handoff Trigger Policy** configures that series as high-value or security-relevant.
- "Escalation" could mean a customer-visible outcome, an internal follow-up fact, or a real helpdesk ticket. Resolved: V1 creates an internal **Customer Escalation Handoff** for monitoring and returns only a **Customer-Safe Response Projection**; real ticket-system integration is future adapter work.
- "Insufficient evidence" could mean a normal customer-safe refusal or an internal handoff. Resolved: ordinary insufficient-evidence refusals do not create handoffs by default; handoff is reserved for operationally significant, security-relevant, or configured follow-up scenarios.
- "Handoff wording" could mean telling customers they were escalated to a human or giving a safe service acknowledgement. Resolved: V1 uses **Handoff-Safe Customer Wording** and hides internal handoff state from customers.
- "Handoff state" could mean a run outcome, a trace event, or a dashboard row. Resolved: V1 uses **Customer Handoff Event** plus **Handoff Projection**; final outcomes remain customer-service result semantics.
- "Handoff reason" could mean free-form notes or stable operational categories. Resolved: V1 uses fixed **Handoff Reason** codes.
- "Appending trace after a run" could mean a governed artifact update or a storage shortcut. Resolved: V1 requires **Run Artifact Consistency**; trace, Receipt, run metadata, and read projections must be updated as one coherent governed artifact set.
- "Multi-turn context" could mean raw transcript injection or governed context admission. Resolved: automatic context uses **Controlled Conversation Context** and must not replace per-turn evidence retrieval.
- "Conversation storage" could mean customer UX history, audit run storage, or persistent enterprise memory. Resolved: **Conversation Store** owns short-lived chat timelines, **RunStore** owns run artifacts, and persistent enterprise memory is a separate future capability.
- "Retention" could mean customer chat transcript retention or audit retention. Resolved: V1 separates **Customer Conversation Retention Policy** from the **Audit Retention Boundary**.
- "Enterprise QA" could mean a generic knowledge demo or a concrete first domain. Resolved: first-stage acceptance uses the **Insurance Service QA Domain** while keeping framework boundaries generic.
- "Production knowledge integration" could mean adding local vector indexing, using a remote retrieval service first, or building local tree indexes. Resolved per ADR-0015: first-stage production-directed integration uses the **Local Index Provider**, while **Local Markdown Provider** remains the deterministic baseline and **Local Vector Provider** is historical.
- "V1 knowledge source" could mean replacing local fixtures with remote retrieval or keeping only Markdown. Resolved: V1 uses **Local Markdown Provider** for deterministic regression and **Local Index Provider** for the production-directed customer-service path.
- "Knowledge base configuration" could mean a reusable data asset, a provider adapter, or an Agent-specific retrieval binding. Resolved: use **Knowledge Source** for the asset, **Knowledge Provider** for the adapter, and **Agent Knowledge Binding** for per-Agent use and retrieval settings.
- "Agent knowledge provider" could mean an Agent-selected retrieval adapter or the provider owned by a reusable Knowledge Source. Resolved: a **Knowledge Source** owns its **Knowledge Provider** configuration; an Agent uses **Agent Knowledge Binding** and does not select a provider.
- "Agent binding customization" could mean no per-Agent tuning, bounded retrieval overrides, or permission to mutate source-owned provider configuration. Resolved: **Knowledge Binding Retrieval Override** permits `top_k`, fusion weight, failure mode, and source-routing metadata hints only; endpoint, credentials, index or namespace, ingestion settings, and admission scorer remain Knowledge Source-owned.
- "Knowledge Source upgrade" could mean latest-at-runtime lookup for every Agent, immutable binding forever, or explicit Draft upgrade. Resolved: unpinned Draft bindings use **Draft Knowledge Binding Resolution** against the latest published source version, while **Published Knowledge Binding Resolution** remains immutable; Dashboard shows **Knowledge Binding Upgrade Available**, and production changes require Draft update, Agent Validation Run, and Agent Publication.
- "Archive a Knowledge Source" could mean disabling all current retrieval immediately, removing it only from future configuration, or physically deleting it. Resolved: **Knowledge Source Archive** moves the source to ARCHIVED, blocks new binding and new Agent publication, preserves existing Draft Agent bindings as explicit blockers, preserves execution of existing pinned Published Agent Versions, shows affected references through **Knowledge Source Reference Summary**, supports explicit restore without Agent mutation, and permits **Knowledge Source Physical Deletion** only for archived, unreferenced, empty Sources after strict eligibility checks.
- "Authorize knowledge configuration" could mean one broad administrator toggle, reusing Agent edit rights for every asset operation, or preserving distinct capabilities. Resolved: **Knowledge Source Permission Model** separates view, edit, publish, and archive; Knowledge Source API command requests resolve Operator Identity Context server-side instead of accepting request-body actor fields; Agent binding changes and Agent publication remain separate `agent.edit` and `agent.publish` capabilities. V1 single-user mode grants all while keeping API, Dashboard, and audit boundaries explicit.
- "Audit knowledge management and retrieval" could mean one mixed activity log, raw document retention, or separate trace-safe records. Resolved: **Knowledge Configuration Operation Audit** records administrative versioned changes and Source lifecycle decisions, including archive, restore, Physical Deletion eligibility, and Physical Deletion audit that survives Source directory removal; **Knowledge Retrieval Runtime Facts** record execution-time routing, provider, fusion, admission, citation, and truncation facts; neither stores raw documents, secrets, or complete remote responses.
- "Record retrieval planning" could mean only final evidence, every routing prompt and candidate, or a bounded plan summary. Resolved: **Knowledge Retrieval Plan Summary** records binding candidates, selected bindings, local document candidates and selections, provider call outcomes, compact unselected reasons, full RunStore/Dashboard detail, and compressed Governance Receipt summary without raw content.
- "Multiple knowledge bases" could mean priority-only fallback, querying all sources, or governed evidence blending. Resolved: an Agent has an **Agent Knowledge Binding Set** and uses bounded **Multi-Source Blended Retrieval** with **Knowledge Source Routing** before provider-specific retrieval.
- "Support multiple knowledge providers" could mean selecting one Agent-level adapter or allowing heterogeneous provider-backed Knowledge Sources in one retrieval plan. Resolved: each **Knowledge Source** owns one **Knowledge Provider Adapter**, and one Agent retrieval plan may select multiple sources backed by different adapters before **Cross-Source Evidence Fusion**.
- "Give retrieved information to the LLM" could mean passing through every provider result or assembling governed context. Resolved: providers return **Candidate Evidence**, the Control Plane admits **Accepted Evidence**, and **Accepted Evidence Context Assembly** sends only admitted evidence to the final-answer LLM.
- "Retrieval orchestration" could mean a runtime graph node calls `KnowledgeProvider.retrieve()` directly, each provider handles blending, or one Control Plane service governs the whole retrieval path. Resolved: Enterprise QA and Controlled ReAct workflows both use the **Knowledge Retrieval Service**; **Knowledge Provider Adapters** only retrieve one selected source and normalize Candidate Evidence.
- "Limit blended evidence sent to the LLM" could mean provider-specific quotas, chunk count only, token count only, or a bounded Agent-level assembly step. Resolved: **Accepted Evidence Context Assembly** walks Cross-Source Fusion Rank order without fixed per-source quotas and stops when either **Accepted Evidence Context Chunk Budget** or **Accepted Evidence Context Token Budget** is exhausted; Trace records budget truncation.
- "Format evidence for the final-answer LLM" could mean raw Candidate Evidence objects, ad hoc prompt concatenation, or a fixed safe projection. Resolved: **Accepted Evidence LLM Context Item** sends source label, citation label, content, confidence band, source type, and rank while excluding raw scores, internal ids, storage paths, and provider payloads.
- "Rank evidence from different providers" could mean sorting incompatible backend scores directly, requiring one universal scoring backend, or applying rank fusion. Resolved: V1 **Cross-Source Evidence Fusion** uses **Weighted Reciprocal Rank Fusion** over provider-local ranks and resolved source weights; **Provider-Native Relevance Scores** remain source-local and traceable.
- "Deduplicate evidence from different providers" could mean content-only collapse, semantic-similarity collapse, or deterministic exact identity. Resolved: V1 uses **Exact Cross-Source Evidence Deduplication** only when canonical citation or trusted-formatted Structured Remote Source Reference plus normalized content hash match exactly; merged candidates retain all provenance and combine WRRF contributions.
- "Identify retrieved evidence" could mean provider-native ids only, citation text only, or a governed normalized key set. Resolved: **Candidate Evidence Identity** carries Source, version, binding, provider, document/revision/chunk ids where available, citation, separated score fields, and trace-safe metadata, while **Candidate Evidence Contribution** preserves per-source provenance after exact deduplication.
- "Admit an exactly deduplicated candidate" could mean boosting confidence because multiple sources returned it, averaging scores, selecting the highest score, or applying conservative admission. Resolved: **Merged Evidence Admission Evaluation** keeps WRRF contribution aggregation separate from admission; an approved scorer evaluates the merged chunk once when configured, otherwise the minimum available calibrated contributor score applies, and candidates with no valid score remain inadmissible.
- "Evidence score" could mean a provider-native relevance value, a cross-source fusion result, or a Control Envelope admission value. Resolved: use **Provider-Native Relevance Score** for adapter-local ordering, **Cross-Source Fusion Rank** for WRRF candidate ordering, and **Evidence Admission Score** for Evidence Threshold evaluation. Missing admission scores fail closed.
- "Migrate overloaded EvidenceChunk.score" could mean retaining a single-provider alias or splitting score semantics directly. Resolved: because the contract is already undergoing a breaking cutover, use **Direct Evidence Score Contract Migration** and remove the old field while migrating validator, graph, observability projections, providers, fixtures, and tests together.
- "Implement Knowledge Sources" could mean building the Dashboard first, adding runtime fusion first, or migrating contracts first. Resolved: follow **Knowledge Source Implementation Sequence** so the contract and loader define the target shape before store/API, ingestion, runtime retrieval, Dashboard UI, and final fixture/test migration.
- "Knowledge source weight" could mean one global source priority or an Agent-specific fusion preference. Resolved: use **Knowledge Binding Fusion Weight** on each **Agent Knowledge Binding**, defaulting to 1.0, so different Agents may weight the same shared Knowledge Source differently.
- "Source routing limit" could mean Agent-level Knowledge Source fan-out, one Local Index source's document fan-out, or final evidence count. Resolved: use **Knowledge Source Selection Budget** for Agent-level source fan-out, defaulting to 3 and configurable from 1 through 8; **Knowledge Document Selection Budget** and Agent Retrieval Strategy `top_k` remain separate limits.
- "Choose Agent-bound knowledge sources" could mean query every binding, filter only metadata, or use an unbounded routing model. Resolved: **Knowledge Source Routing** is deterministic by default, uses optional **Knowledge Source Routing Model Configuration** only when explicitly configured, respects Knowledge Source Selection Budget, and returns no evidence rather than silently querying every source on empty or failed routing.
- "ReAct retrieval planning" could mean the ReAct Planner directly selects Knowledge Sources, providers, endpoints, or snapshots. Resolved: ReAct may propose a **Retrieval Intent** only; the Control Envelope performs **Knowledge Source Routing**, provider calls, fusion, citation enforcement, and evidence admission.
- "One selected provider failed" could mean fail every mixed retrieval, silently return partial evidence, or apply an explicit binding policy. Resolved: each **Agent Knowledge Binding** has a **Knowledge Binding Failure Mode**, defaulting to `required`; explicit `advisory` mode permits observable **Degraded Knowledge Retrieval** while preserving normal evidence admission.
- "Supported Knowledge Providers" could mean every provider currently present in code, every historical adapter, or the target Knowledge Hub capability set. Resolved: **Knowledge Hub V1 Provider Set** excludes PageIndex and Local Vector providers rather than keeping them as hidden compatibility entries.
- "Support third-party knowledge providers" could mean shipping only vendor-specific code, dynamically executing operator-uploaded scripts, or registering trusted adapters with a generic remote option. Resolved: V1 uses trusted **Knowledge Provider Adapter Descriptors**, includes an **HTTP JSON Knowledge Provider**, permits specialized adapters through code installation, and does not execute Dashboard-uploaded scripts.
- "Remote HTTP knowledge support" could mean every remote endpoint must implement one Proof Agent protocol or Dashboard can map any arbitrary API. Resolved: **HTTP JSON Knowledge Provider** has a preferred default **Remote Retrieval Protocol** and a constrained declarative mapping path for non-standard APIs; neither path permits executable transforms or evidence-admission bypass.
- "HTTP JSON adapter protocol" could mean one rigid response shape, arbitrary executable transforms, or a default protocol with bounded extension. Resolved: the **HTTP JSON Knowledge Provider** supports the versioned default **Remote Retrieval Protocol** plus validated declarative **Remote Retrieval Response Mapping** for non-standard remote responses; mappings normalize evidence fields and cannot execute code or bypass admission.
- "HTTP JSON request shape" could mean only `{query, top_k}`, unrestricted templates, or bounded declaration. Resolved: **Remote Retrieval Request Mapping** projects only whole-value placeholders `${query}`, `${top_k}`, and `${upstream_revision}` into query parameters and JSON body fields while preserving source types; endpoints and URL paths remain static, headers use static values or environment-variable references, and interpolation or expression features are excluded.
- "HTTP JSON response mapping language" could mean full JSONPath or JMESPath expressions, executable transforms, or bounded field projection. Resolved: **Remote Retrieval Response Mapping** uses JSON Pointer only: one result-array pointer plus relative item-field pointers. Health-check sample validation fails closed on missing normalized content or usable citation basis, and ordinary mappings cannot supply Evidence Admission Score.
- "Remote result citation" could mean requiring one upstream citation field, allowing Dashboard-authored citation templates, or accepting mapped structured source-reference fields. Resolved: a candidate must have either a mapped citation or an adequate mapped **Structured Remote Source Reference**; only **Trusted Citation Formatting** in adapter code may convert the latter into citation, and citation-free candidates never enter LLM context.
- "Version a remote knowledge source" could mean freezing only Proof Agent connection config, pretending every upstream corpus is immutable, or recording explicit consistency levels. Resolved: every remote source publishes a **Remote Knowledge Source Configuration Version**; adapters with `snapshot_pin` create a **Pinned Remote Knowledge Source**, while unsupported upstreams remain visible **Mutable External Knowledge Sources** with **Remote Knowledge Revision Observations** and no exact replay guarantee.
- "Verify a remote knowledge source" could mean testing only at runtime, permitting unchecked publication, or requiring a bounded pre-publication health check. Resolved: adapters with `health_check` must pass **Remote Knowledge Source Verification** before source publication; generic adapters such as `http_json` must pass smoke retrieval normalization and publish as mutable external `remote_config`; mutable external verification defaults to a 24-hour validity window, and **Stale Remote Knowledge Source Verification** blocks new publication or rebinding without immediately stopping existing Agent execution.
- "PageIndex provider" could mean keeping the remote HTTP integration, replacing it with a local engine, or supporting both. Resolved per ADR-0015: remove the remote `pageindex` provider from the target architecture, rename `local_pageindex` to `local_index` (**Local Index Provider**), use LlamaIndex TreeIndex as the underlying engine, and require migration of existing `pageindex` sources with forced re-publication of affected Published Agent Versions.
- "Retrieve from a multi-document local index source" could mean unbounded search, implicit file routing, or silent partial results. Resolved: V1 **Local Index Snapshot Retrieval** first applies bounded **Knowledge Document Routing** within the resolved snapshot, then searches selected revisions, merges normalized candidates, and fails closed if any selected document search fails.
- "Small local knowledge source" could mean capping a source at 20 documents or supporting a larger operator-managed collection. Resolved: V1 **Knowledge Source Document Capacity** targets up to 500 documents per source, so querying every document revision is not an acceptable retrieval path.
- "Document routing" could mean opaque model choice, metadata-only filtering, or a two-stage governed selection. Resolved: V1 filters **Knowledge Document Routing Metadata**, then uses an LLM selector over filenames and editable descriptions, and records an audit-safe routing summary in the retrieval plan trace.
- "Document selection limit" could mean final evidence `top_k`, source capacity, or routed search fan-out. Resolved: use **Knowledge Document Selection Budget** for routed document fan-out, with default 8 and configurable range 1 through 20; Agent Retrieval Strategy `top_k` remains the final evidence limit.
- "Upload PDF into RAG knowledge" could mean customer attachment analysis, direct Agent YAML mutation, or creating a reusable indexed asset. Resolved: Dashboard operator uploads create an **Index-Backed Knowledge Source** through **Knowledge Source Ingestion**; Agents bind only READY sources through **Agent Knowledge Binding**.
- "One knowledge base" could mean exactly one file or a reusable document collection. Resolved: an **Index-Backed Knowledge Source** contains one or more independently indexed **Knowledge Documents** and exposes the last promoted READY **Knowledge Source Snapshot**.
- "Partially failed batch ingestion" could mean blocking every source publication, silently dropping failed documents, or publishing an explicit READY subset. Resolved: every revision has an independent **Knowledge Document Ingestion State**; a **Candidate Knowledge Source Snapshot** includes only READY revisions, requires at least one, and Dashboard explicitly lists processing, failed, and archived exclusions while supporting retry, replacement, or archive.
- "Replace an uploaded document" could mean overwriting by filename, mutating the active index artifact, or creating an immutable revision. Resolved: a stable **Knowledge Document** id owns immutable **Knowledge Document Revisions**; Dashboard requires explicit new-document versus replacement intent, **Knowledge Document Content Hash Reuse** makes compatible repeated uploads idempotent, and replacement changes only a candidate snapshot until publication.
- "Adding one document" could mean mutating the active retrieval corpus immediately or preparing a replacement corpus. Resolved: document changes build a replacement **Knowledge Source Snapshot**; indexing failure preserves the currently active READY snapshot.
- "Delete a knowledge document" could mean removing it from future retrieval or physically purging historical artifacts. Resolved: use **Knowledge Document Archive** for reversible removal from candidate snapshots and permit **Unreferenced Knowledge Artifact Cleanup** only when no retained snapshot or Published Agent Version references the revision.
- "Indexed successfully" could mean immediately changing Agent retrieval behavior or making a candidate snapshot eligible for activation. Resolved: upload, replacement, and removal prepare a candidate READY **Knowledge Source Snapshot**, and **Knowledge Source Publication** is the required manual activation step.
- "Local index build" could mean building LlamaIndex artifacts during an Agent run or during Knowledge Hub administration. Resolved: **Knowledge Source Ingestion** builds local index artifacts before publication; runtime uses **Local Index Runtime Load** against a published READY snapshot only.
- "Agent binds a knowledge source" could mean following its latest published snapshot forever or freezing the validated corpus at Agent publication. Resolved: Draft Agents may preview the latest published snapshot, while each **Published Agent Version** records a **Resolved Knowledge Snapshot Binding** to the exact `snapshot_id`.
- "Rollback an Agent version" could mean restoring only its YAML or restoring its effective knowledge corpus too. Resolved: rollback selects the immutable **Published Agent Version** and therefore restores its captured **Resolved Knowledge Snapshot Binding**.
- "Dashboard PDF upload" could mean arbitrary attachment analysis or a constrained operator workflow. Resolved: V1 **Operator Knowledge Document Intake** accepts text-based PDF and Markdown Knowledge Documents only and fails closed on scanned PDFs or unsupported formats.
- "Operator upload" could imply enabling customer attachment uploads. Resolved: **Operator Knowledge Document Intake** is a design-time Dashboard capability and does not change **Text-Only Customer Intake**.
- "Background indexing" could mean keeping the upload HTTP request open, using an in-process callback, or queueing durable work. Resolved: **Knowledge Source Ingestion** persists a **Knowledge Ingestion Job** and a separate local **Knowledge Ingestion Worker** claims it asynchronously.
- "Local worker" could mean committing to one production queue technology. Resolved: V1 uses a file-backed recoverable queue behind the **Knowledge Ingestion Worker** boundary; future deployments may replace it with a distributed queue.
- "Local index model" could mean reusing an Agent answer model or configuring a design-time indexing model. Resolved: each **Index-Backed Knowledge Source** has independent **Knowledge Ingestion Model Configuration** with environment-variable credential references only.
- "Document routing model" could mean reusing an Agent planner, requiring a second source model, or inheriting the ingestion model. Resolved: **Knowledge Routing Model Configuration** belongs to the **Knowledge Source**, inherits **Knowledge Ingestion Model Configuration** by default, and may be overridden independently.
- "Local Index support" could mean requiring remote model credentials for every Proof Agent workflow. Resolved: local index ingestion is optional and does not change the deterministic no-network, no-credential demo or default CI gate.
- "Knowledge source routing" could mean choosing document revisions inside one source or choosing Agent-bound sources before provider calls. Resolved: use **Knowledge Source Routing** across an **Agent Knowledge Binding Set** and **Knowledge Document Routing** inside a selected Index-Backed Knowledge Source.
- "Agentic RAG" could mean either a provider or a workflow. Resolved: **Agentic RAG** is a controlled retrieval workflow, not a **Knowledge Provider**.
- "`knowledge.path`" could mean a universal knowledge field or a local-provider parameter. Resolved: provider-specific knowledge configuration belongs under the selected **Knowledge Provider** parameters.
- "`local`" could mean Markdown files, local vector indexes, or any local source. Resolved: target architecture uses **Local Markdown Provider** for deterministic/dev fixtures and **Local Index Provider** for production local knowledge; **Local Vector Provider** is historical.
- "Retrieval configuration" could mean provider setup or orchestration policy. Resolved: provider setup belongs to **Knowledge Provider** parameters; orchestration policy belongs to **Retrieval Strategy**.
- "Agentic RAG" could be modeled as a workflow template or a retrieval strategy. Resolved: it is a **Retrieval Strategy**, while workflow templates keep business-flow meaning.
- "Citation" could mean part of the evidence text or source metadata. Resolved: **Evidence Citation** is evidence metadata, not evidence content.
- "Accepted evidence" could mean evidence returned by retrieval or evidence admitted by governance. Resolved: only Control Plane evidence evaluation creates **Accepted Evidence**.
- "Tool result as evidence" could mean renaming tool output to **Accepted Evidence** or letting raw tool output support claims. Resolved: use **Authorized Tool Result** as a distinct claim-support source that requires tool authorization, redaction, source reference, and coherent run artifacts.
- "Tool source reference" could mean customer-safe basis disclosure or internal control-plane linkage. Resolved: customers see **Customer-Safe Source Label** values; Trace, Governance Receipt, and RunStore keep the internal mapping to tool authorization and redacted result details.
- "Audited evidence" could mean full content or safe summary. Resolved: default audit output records **Evidence Summary**, not raw evidence content.
- "Planner model" could mean another answer generator. Resolved: a **Planner Model** may only produce retrieval plans or query candidates.
- "Fallback" could mean silent best-effort behavior. Resolved: **Single-Step Retrieval Fallback** must be explicit in the Retrieval Strategy.
- "`KnowledgeProvider.retrieve`" could mean a workflow step or an implementation method. Resolved: **Retrieval Step** is the workflow concept; `retrieve` is an adapter method.
- "Local vector implementation" could mean querying an existing vector index or building a vector lifecycle. Resolved: **Local Vector Provider** is removed from the Knowledge Hub V1 target architecture; do not add a Vector Index Build lifecycle.
- "Dashboard sidebar" could mean a flat list, role-based sections, or monitoring/configuration separation. Resolved: the **Dashboard Shell** sidebar uses two **Sidebar Navigation Section** groups: MONITORING for observability and CONFIGURATION for design-time views.
- "Agent configuration sub-features" could mean grouped concerns, workflow stages, or contract artifacts. Resolved: the **Agent Configuration Workspace** uses **Agent Configuration Module** tabs (General, Workflow, Knowledge, Tools, Policy, Model, Memory, Response) organized by contract artifact.
- "Agent detail navigation" could mean horizontal tabs, vertical tabs, or a sectioned page. Resolved: the **Agent Configuration Workspace** uses vertical tabs in the main content area with CONFIGURE and LIFECYCLE sections.
- "Configuration editing" could mean forms only, visual builders, code only, or a hybrid. Resolved: each **Agent Configuration Module** uses a **Configuration Module Editor** with forms for common settings and YAML toggle for advanced editing.
- "Draft save behavior" could mean auto-save per field, save per module, or single draft save. Resolved: **Draft Agent** uses auto-save for all configuration changes with explicit publish in the Versions **Agent Lifecycle Tab**.
- "Validation interface" could mean a simple test runner, test suite, or validation dashboard. Resolved: the Validate & Test **Agent Lifecycle Tab** uses a **Validation Workspace** combining quick test, test suite, and validation history.
- "`Knowledge Hub`" could mean a new runtime, a retrieval engine, or the product-facing configuration surface for reusable knowledge. Resolved: **Knowledge Hub** names the Shared Asset Library capabilities for Knowledge Sources and Agent Knowledge Bindings, while retrieval still enters the Control Envelope through governed Knowledge Provider Adapters and evidence admission.
- "Reusable assets" could mean agent-scoped only, shared library, or hybrid. Resolved: **Knowledge Source**, **Tool Source**, and **Policy Rule Configuration** live in the **Shared Asset Library** and are bound to agents through Agent Knowledge Bindings and Agent Tool Bindings.
- "Agent Contract knowledge config" could mean storing full provider configuration inside every Agent or storing only reusable Source bindings. Resolved: Draft Agents store binding intent through **Agent Knowledge Binding Configuration API**, while Published Agent Versions execute with a **Resolved Knowledge Binding Set** pinned to Source snapshot or configuration versions.
- "Knowledge Source workspace route" could mean adding `/knowledge-sources`, keeping the existing `/knowledge`, or embedding all file management under one Agent. Resolved: evolve the existing `/knowledge` page into the global **Knowledge Source Workspace** and do not add `/knowledge-sources`.
- "Knowledge Source detail route" could mean a modal, an Agent-embedded document manager, or a reusable-asset detail page. Resolved: use **Knowledge Source Detail Workspace** at `/knowledge/:sourceId` with Overview, Documents, Versions, Provider, and Audit tabs; Agent pages link to it without embedding full file management.
- "Knowledge Source list" could mean a thin link list, raw Agent YAML excerpts, or an operational reusable-asset inventory. Resolved: **Knowledge Source Workspace List Projection** shows identity, metadata, provider, lifecycle, availability, published version, local document counts or remote target, Agent reference count, and warning indicators, with filters for name, tag, provider, lifecycle, and warning state.
- "Create a Knowledge Source" could mean one provider-specific form, remote-only setup, or an intake wizard with explicit publication. Resolved: **Knowledge Source Creation Wizard** branches into local index upload, registered remote adapter connection, or existing local-source registration; it saves a Source Draft and never publishes implicitly.
- "Operate a 500-document local source" could mean a raw upload list, one-file-at-a-time management, or a paginated document workspace. Resolved: **Knowledge Source Documents Tab** provides batch upload, state filters, pagination, revision visibility, per-document and bulk actions, routing metadata edits, and a persistent candidate-snapshot publication summary.
- "Configure a remote Knowledge Source" could mean raw JSON only, a fixed adapter-specific form, or layered descriptor-driven configuration. Resolved: **Remote Knowledge Source Provider Tab** uses common fields by default, bounded advanced mappings when supported, typed forms for registered remote adapters, and mapping editors for `http_json`; connection testing and retrieval preview never publish implicitly.
- "Configure local index" could mean mixing files and model settings, exposing every setting at once, or using a layered provider form. Resolved: **Local Index Provider Tab** keeps file management in Documents, exposes common model and routing defaults first, folds timeout, retry, concurrency, and routing-model override into advanced settings, offers a non-ingesting model-configuration test, and marks artifact-affecting ingestion changes as **Local Index Reingestion Required**.
- "Reingest after local index configuration change" could mean rebuilding every document, silently reusing incompatible artifacts, or rebuilding only missing compatible artifacts. Resolved: **Knowledge Ingestion Configuration Fingerprint** plus content hash identifies reusable artifacts, and **Incremental Local Index Reingestion** queues only candidate-snapshot revisions lacking compatible artifacts; routing-only changes do not rebuild indexes.
- "Retry local ingestion" could mean retrying everything forever, requiring manual retry for every transient failure, or bounded classified recovery. Resolved: **Knowledge Ingestion Worker Policy** uses Source-level concurrency default 2 configurable 1 through 8, at most 2 automatic backoff retries for recoverable errors, immediate failure for non-recoverable intake or configuration errors, stable Dashboard error classification, manual retry after FAILED, and persisted-queue restart recovery without duplicate compatible builds.
- "Accept Dashboard document uploads" could mean trusting browser validation, allowing archives, or enforcing server-side quarantine. Resolved: **Operator Knowledge Document Upload Validation** checks type, signature, size, page count, and batch count, rejects unsafe or unsupported inputs, and **Knowledge Document Upload Quarantine** prevents revision creation or ingestion queueing until validation passes.
- "Retain uploaded originals" could mean discarding files after indexing, keeping every upload forever, or managing validated originals separately from quarantine. Resolved: each validated revision retains a **Managed Knowledge Document Original** for reingestion and citation verification, authorized downloads are audited, archive and replacement preserve referenced originals, cleanup obeys reference and retention checks, and rejected quarantine files use **Rejected Knowledge Upload Retention** of 24 hours only.
- "Open a knowledge citation" could mean exposing storage paths, using mutable document links, or resolving a governed source reference. Resolved: local evidence uses stable **Local Knowledge Citation URI**, Dashboard opens audited permission-protected **Knowledge Citation Preview** at PDF page or Markdown section, customer output uses **Customer-Safe Knowledge Citation Projection**, remote clickable URLs require **Remote Citation Link Allowlist**, and citation preview audit remains distinct from original-download audit.
- "Show citations to customers" could mean exposing internal source ids, inline full URLs, or numbered safe references. Resolved: customer answers use **Customer Citation Marker** and **Customer Sources List**, merge duplicate safe locations, omit internal ids and confidence, keep mutable-external replay warnings internal, and never invent citations when no Accepted Evidence exists.
- "Answer with no Accepted Evidence" could mean best-effort generation, a blank citation list, or governed refusal. Resolved: **No Accepted Evidence Outcome** uses insufficient-evidence/refusal behavior, avoids free-form evidence claims and Sources list, records the failing retrieval phase and candidate counts, and distinguishes advisory failures with remaining evidence from required provider failure.
- "Mixed retrieval failure" could mean answering from remaining sources, retrying every source, or refusing. Resolved: empty routing and selected required binding failure produce **No Accepted Evidence Outcome**; selected advisory binding failure may continue only when remaining selected bindings produce Accepted Evidence.
- "Validate before Source publication" could mean upload completion, one permanent check, or Draft-version-bound verification. Resolved: **Knowledge Source Publication Validation** invalidates after relevant Draft changes; local index Sources require READY compatible artifacts, model tests, and routing-retrieval-citation smoke query, while remote Sources require adapter-supported health checks when available, auth, declared target validation, response normalization, citation basis, and smoke query. Generic `http_json` publishes a mutable external `remote_config`; adapters that cannot prove retrieval normalization remain preview-only.
- "Confirm Source publication" could mean one-click activation, an Agent-impacting deployment, or an explicit reviewed promotion. Resolved: **Knowledge Source Publication Confirmation** shows the version delta, local or remote summary, smoke validation, Agent reference count, requires audited `change_note`, and explains that existing Published Agent Versions remain pinned while Draft Agents gain an upgrade option.
- "Rollback a Knowledge Source" could mean mutating history, rewinding a shared production pointer, or preparing a reviewed replacement. Resolved: **Knowledge Source Versions Tab** creates a **Knowledge Source Rollback Draft** from a historical version, requires fresh validation and publication for a new version, and never automatically changes Published Agent Versions or Draft Agent bindings.
- "Export or import a Knowledge Source" could mean exporting secrets and cached indexes, exporting only configuration, or supporting an explicit local offline bundle. Resolved: every Source supports audited secret-free **Knowledge Source Manifest Export**; local index may additionally export **Local Knowledge Source Offline Bundle** with originals and hashes; import always creates **Knowledge Source Import Draft**, revalidates remote connections or local files, reingests local artifacts by fingerprint, and never trusts imported indexes directly.
- "Knowledge Source API" could mean keeping provider settings inside Agent YAML, adding UI-only state, or exposing shared Source resources. Resolved: **Knowledge Source Configuration API** owns Source CRUD, lifecycle, document, version, validation, publication, preview, and import-export resources, while **Agent Knowledge Binding Configuration API** stores Agent `knowledge_bindings[]` and blended-retrieval settings without provider parameters.
- "Migrate inline Agent knowledge configuration" could mean long-lived dual-read compatibility, auto-wrapping old manifests at runtime, or a breaking direct cutover. Resolved: because Agents are not yet deployed, use **Direct Knowledge Contract Migration**: migrate loader, Dashboard, examples, fixtures, and tests together, accept only `knowledge_bindings[]` in the new Agent contract, and reject inline `knowledge.provider + params`.
- "Agent-specific monitoring" could mean a separate tab, split view, or lifecycle integration. Resolved: the Monitor **Agent Lifecycle Tab** appears under LIFECYCLE alongside Validate & Test, Versions, and Contract View.
- "Workflow editing" could mean a linear list, visual diagram, accordion, or tabbed editor. Resolved: the Workflow **Agent Configuration Module** uses an expandable accordion showing all nodes with inline configuration fields.
- "Agent creation" could mean inline form, modal wizard, or template selection. Resolved: the **Agent Creation Wizard** starts with template selection (Enterprise QA, Customer Service, Blank) before collecting agent details.
- "Unsupported retrieval" could mean invalid configuration or unavailable capability. Resolved: a recognized but unavailable strategy is a **Retrieval Capability Error**.
- "Agentic retrieval" could mean a single provider call, unbounded multi-round search, or governed iterative planning. Resolved: `retrieval.strategy: agentic` activates the **RetrievalPlanner** which drives a multi-round loop with `planner_model` for query analysis and `evaluator_model` for evidence sufficiency assessment, outputs structured **RetrievalAction** decisions, respects `max_rounds` hard limit, and fails closed on errors returning accumulated evidence.
- "Agentic retrieval inside ReAct" could mean one shared loop, a recursive autonomous Agent, or a governed nested retrieval loop. Resolved: **Nested ReAct Retrieval Loop** is allowed only when a Controlled ReAct retrieval action invokes the shared governed retrieval service; `react.max_actions` limits the outer ReAct loop and `retrieval.max_rounds` limits the inner RetrievalPlanner loop.
- "Tree index retrieval" could mean calling the external PageIndex API, using LlamaIndex's built-in retrievers, or implementing custom tree traversal. Resolved: **Local Index Provider** uses LlamaIndex `TreeSelectLeafRetriever` for single-document tree traversal, routes all LLM calls through **ProofAgentLLM** bridge to Proof Agent's ModelProvider protocol, and supports structured interfaces (`list_structure`, `retrieve_at_scope`) declared via **RetrievalCapabilities**.
- "Planner error handling" could mean retry, partial results, or complete failure. Resolved: **RetrievalPlanner** uses fail-closed semantics — LLM failure, Action Plan parse failure, or provider timeout terminates the loop and returns accumulated evidence from prior rounds; all failures are recorded in trace with stable error codes.
- "Multi-round trace" could mean one summary event, per-round detail, or full LLM conversation. Resolved: each round emits `retrieval_step`, `model_request`, `model_response` events with `round_id` correlation, and a final `agentic_retrieval_completed` summary event records total rounds, candidates, accepted count, final action, and per-round history.
- "Planner-Provider boundary" could mean Planner sees merged results, per-source results, or both. Resolved: V1 **RetrievalPlanner** operates above **BlendedKnowledgeProvider** and sees only merged evidence; V2 will evolve to per-source awareness for `narrow_scope` and `try_different_source` actions, accepting the architectural rework cost.
- "Planner LLM calls" could mean bypassing governance, sharing the final-answer model, or using dedicated governed roles. Resolved per ADR-0005 amendment: **ModelCallRole.RETRIEVAL_PLANNER** and **ModelCallRole.RETRIEVAL_EVALUATOR** are separate LLM roles with independent trace identity, and **ModelCallRole.INGESTION** and **ModelCallRole.ROUTING** govern index-build and tree-traversal LLM calls respectively.
