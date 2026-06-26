# Workflow Control

Workflow Control contains the language for governed execution: Workflow Templates, Controlled ReAct orchestration, approvals, clarifications, observations, and finalization.

## Language

**Workflow Template Execution**:
The governed execution of one selected Workflow Template during a run, including Control Envelope stage semantics without owning Runtime Plane mechanics.
_Avoid_: Runtime graph execution, template-specific node class, orchestrator branch

**Workflow Template Execution Result**:
The typed governed facts produced by one Workflow Template Execution, including completion, terminal outcome, approval pause, clarification need, evidence basis, and safe response facts.
_Avoid_: Runtime state dict, LangGraph final state, Dashboard projection

**Workflow Template Execution Result Run Handoff**:
The process-local RunResult field that returns the Workflow Template Execution Result from a Workflow Runtime Adapter to Delivery for validation artifact construction and other governed post-processing.
_Avoid_: RunStore detail field, Dashboard projection, trace file payload, runtime state passthrough

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

**ReAct Enterprise QA Stage Behavior**:
The internal Control Plane behavior service that performs React Enterprise QA stage work and returns scheduler-neutral state deltas for wrapping by ReAct Enterprise QA Workflow Execution.
_Avoid_: Workflow Template Stage API, LangGraph node handler, Workflow Stage Result owner, runtime graph scheduler

**ReAct Stage Behavior Consolidation Slice**:
The Workflow improvement slice that makes ReAct Enterprise QA Workflow Execution the only public stage execution surface, moves shared stage work into ReAct Enterprise QA Stage Behavior, and removes duplicated tool/approval behavior.
_Avoid_: Runtime graph rewrite, complete stage-specific result union, descriptor-derived dynamic topology, LangGraph node rename campaign

**Workflow Refactor Closure Program**:
The bounded cleanup program that closes remaining Workflow terminology and execution-boundary debt after the Agent Contract stage/capability refactor.
_Avoid_: New workflow feature roadmap, dynamic topology rewrite, second runtime program

**Workflow Stage Result Union Decision**:
The closure decision that Workflow Stage Result remains a trace-safe envelope rather than becoming a complete per-stage result union.
_Avoid_: Immediate per-stage union implementation, raw runtime state contract, validation capture schema rewrite

**Stage-Specific Result Projection**:
A purpose-bound typed projection of one Workflow Template Stage fact for a named consumer such as approval handling, clarification handling, or validation capture.
_Avoid_: Complete per-stage result union, raw stage payload, Workflow Stage Continuation State

**Workflow Legacy Contract Convergence**:
The cleanup of older Workflow-facing contracts and templates so legacy names and execution shapes no longer conflict with Workflow Template Stage and Workflow Template Execution language.
_Avoid_: ReAct Stage Behavior Consolidation, dynamic topology, new template capability

**Legacy WorkflowState Retirement**:
The Workflow Legacy Contract Convergence decision that removed the older WorkflowState snapshot contract instead of renaming its `current_node` field into new stage terminology.
_Avoid_: current_stage alias, long-term compatibility shim, Runtime Plane state contract

**Enterprise QA Baseline Reset**:
The deliberate replacement of the old deterministic Enterprise QA baseline when preserving it would block clean Workflow Template Execution boundaries.
_Avoid_: Incidental regression break, ReAct template rename, hidden compatibility migration

**Workflow Stage Result**:
The typed Control Envelope facts produced by one Workflow Template Stage for use inside a Workflow Template Execution.
_Avoid_: Arbitrary state fragment, public runtime graph node output, loose dict mutation

**Workflow Stage Result Envelope**:
The typed envelope for Workflow Stage Result values, carrying stage id, stage status, optional terminal outcome, trace-safe summary, and produced governed fact references without requiring a complete per-stage result union.
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

**Workflow Stage Result Verification Projection**:
The full-capture representation of an intermediate Workflow Stage Result as stage id, status, outcome, safe summary, and produced fact references, excluding Workflow Stage Continuation State.
_Avoid_: Continuation state, scheduler state, raw stage result dump, runtime state dict

**Workflow Stage Failure Diagnostic Projection**:
The validation-safe explanation of why a Workflow Template Stage stopped because of an exceptional or repairable diagnostic condition, carried as an independent execution fact rather than inside Workflow Stage Result Summary, and limited to stable error codes, role names, bounded lengths, stage status, trace event references, and bounded contract-field diagnostics without free-form diagnostic messages.
_Avoid_: Governed refusal, approval pause, clarification need, provider response body, raw failed output, rejected field value, free-form exception message, stack trace, runtime state, chain-of-thought

**ReAct Self-Loop Iteration Count**:
The number of ReAct reasoning cycles executed inside a single model-bearing Workflow Stage during one run, derived by counting `reasoning_summary` trace events linked to that stage, and rendered on the Run Flow Diagram as a self-loop badge on the stage node. Refusal paths that skip reasoning render with count zero and no self-loop, surfacing as a visually distinct Refusal terminal node rather than a missing loop.
_Avoid_: Workflow Stage visit count, outer pipeline step count, action_proposal count, tool call count, loop budget, max_rounds

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
_Avoid_: LangGraph node, arbitrary runtime step, node-labeled workflow configuration

**React Enterprise QA Stage Set**:
The governed Workflow Template Stages for React Enterprise QA: plan, clarification, retrieval_review, retrieval, model_answer, tool_review, tool, memory, and response; V2 adds intent_resolution before plan.
_Avoid_: LangGraph node list, every policy check, every helper function

**Tool Stage Group**:
The paired tool_review and tool Workflow Template Stages that are enabled together only when the Agent Contract exposes governed tool capability.
_Avoid_: Tool stage without review, review stage without tool, provider-native tool execution

**Workflow Template Descriptor**:
The backend-owned, read-only description of a registered Workflow Template's stages, stage availability rules, branch relationships, governed handoff points, editable Prompt fields, and allowed context options used by Dashboard to render the Workflow Relationship Map and Stage Inspector.
_Avoid_: Frontend-hardcoded workflow graph, Agent-authored node registry, runtime graph source of truth

**Dynamic Workflow Template Catalog**:
The live list of registered Workflow Templates served by `GET /api/config/workflow-templates` and consumed by Dashboard via `fetchWorkflowTemplates()` / `useWorkflowTemplates` to populate the Template selector dynamically. The frontend static template option list is a fallback only, used when the catalog cannot be loaded; it is no longer the source of truth for the template inventory.
_Avoid_: Hardcoded template dropdown, frontend-only template registry, per-Agent template enumeration

**Template Selector Fallback**:
The static Workflow Template name list kept in the Dashboard module config as a last-resort option set, shown only when the Dynamic Workflow Template Catalog fails to load (network/permission/availability). It guarantees the selector is never empty but is maintained for degradation, not as the primary inventory.
_Avoid_: Primary template list, canonical template registry, always-visible static options

**Workflow Template Descriptor Version**:
The immutable version identifier for the Workflow Template Descriptor used to validate, render, publish, and later explain a Published Agent Version's Workflow Stage Prompt Configuration.
_Avoid_: Latest template lookup for historical runs, mutable Dashboard graph version, frontend descriptor version

**Workflow Template Stage Configuration**:
The editable `workflow.stages[]` per-stage settings exposed by a registered Workflow Template while preserving the template's governed stage types, ordering constraints, and Control Envelope semantics.
_Avoid_: Free-form runtime graph editing, arbitrary node creation, prompt-defined workflow

**Workflow Stage Configuration Runtime Source**:
The trace-safe category that identifies whether a run's Effective Workflow Stage Configuration came from a Published Agent Version snapshot or from package-local latest Agent Contract resolution.
_Avoid_: Raw manifest path, Dashboard tab state, storage lookup mechanism

**Workflow Stage Configuration Identifier**:
The required `id` field on each `workflow.stages[]` item that references one registered Workflow Template Stage.
_Avoid_: legacy id aliases, display label, runtime graph node id

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
A Workflow Template where a model proposes reasoning steps and action proposals, while the Control Envelope governs whether each step may execute. Per ADR-0032, the product baseline is the real **Controlled ReAct Loop** (observe-then-replan), not the earlier single-pass wiring.
_Avoid_: Autonomous ReAct agent, direct model executor, single-pass DAG mislabeled as a loop

**Controlled ReAct Orchestrator**:
The run-scoped Control Plane execution authority for the React Enterprise QA V3 product path. Its public execution interface starts or resumes a governed run; Intent Resolution, planning, review, observation actions, approval suspension and resume, convergence, and terminal outcome selection are internal orchestration steps.
_Avoid_: LangGraph topology, legacy workflow compatibility layer, autonomous agent runtime, public per-stage executor

**Controlled ReAct Intent Resolution Placement**:
The V3 rule that Intent Resolution is an Orchestrator-owned pre-loop control stage that records intent and Business Flow admission facts before the first plan round. It is not a Delivery preprocessor and does not count against the Controlled ReAct Loop `max_plan_rounds` budget.
_Avoid_: delivery-owned intent routing, plan round zero, descriptor-owned pre-node, prompt-only context injection

**Controlled ReAct Stage Projection**:
The trace-safe projection that names an internal Controlled ReAct Orchestrator step as a Workflow Template Stage for trace, Governance Receipt, Dashboard, and validation capture. It is an observability and explanation fact, not an execution interface or internal module seam.
_Avoid_: Public stage method, runtime graph node, Orchestrator module boundary, stage-owned execution

**Controlled ReAct Stage Projection Authority**:
The V3 target-state rule that Workflow Stage projection facts are produced by the Controlled ReAct Orchestrator from real internal transition facts before Delivery writes trace, receipt, RunStore, or validation capture artifacts. Delivery-side stage projection may exist only as a temporary migration shim and must not become the semantic source of stage sequencing.
_Avoid_: delivery-owned stage sequencing, synthetic full-chain trace, projection-as-execution, artifact writer as workflow authority

**Controlled ReAct Review Stage Execution**:
The V3 rule that `retrieval_review` and `tool_review` projections must come from real Orchestrator review, policy, and action-constraining facts before an observation action executes. They are not UI filler stages and must not be emitted merely to make a run appear to have traversed the full Workflow Template.
_Avoid_: synthetic review stage, trace-only review, post-hoc review projection, review-as-display

**Controlled ReAct Shadow Verification**:
The temporary migration safety check that runs new Controlled ReAct Orchestrator behavior against representative historical V3 inputs and compares governed outcomes, stage projections, trace facts, and known semantic corrections before deleting legacy execution paths. It is not a compatibility mode and does not preserve old executors after cutover.
_Avoid_: Dual runtime support, long-lived compatibility adapter, feature flag rollout, legacy behavior contract

**Controlled ReAct Run State**:
The typed internal state of one Controlled ReAct Orchestrator execution, carrying run references, intent facts, admitted Business Flow Skill Pack facts, action history, Observation Records, approval pause, evidence basis references, blockers, and terminal outcome. It is an internal Control Plane value, not a Runtime Plane state dictionary or trace payload.
_Avoid_: LangGraph state, continuation dict, raw stage delta, trace-as-state

**Controlled ReAct Run State Snapshot**:
The protected resumable capture of Controlled ReAct Run State written when the Controlled ReAct Orchestrator suspends for approval. Approval resume loads this snapshot, validates the original Workflow Template Execution Input integrity, applies the approval decision as loop state, and continues orchestration.
_Avoid_: LangGraph checkpoint as authority, trace replay, mutable latest Agent Contract reload, ad hoc resume payload

**Controlled ReAct Run State Snapshot Store**:
The execution-state port that persists and loads Controlled ReAct Run State Snapshots for approval resume. The Controlled ReAct Orchestrator owns writes and reads; Trace, Governance Receipt, RunStore, and Dashboard may carry only trace-safe snapshot references or approval projections and must not deserialize snapshots or drive resume semantics from them.
_Avoid_: RunStore detail field, trace event payload as state, Dashboard resume source, LangGraph checkpoint store

**Controlled ReAct Approval Resume Loopback**:
The V3 rule that approval resume writes an Observation Record and returns to plan whether the operator approved or denied the pending tool action. `WAITING_FOR_APPROVAL` is a governed waiting state, not a terminal outcome, and approval denial must not bypass replan.
_Avoid_: approval denial as terminal branch, approval result as final answer, resume-to-response shortcut, pending approval as workflow failure

**Controlled ReAct Transition Commit**:
The single-run atomic commit boundary for one Controlled ReAct Orchestrator transition. It updates run state or snapshot, emits trace-safe stage and approval projections, and records idempotency keys for action and observation outputs under one transition lock.
_Avoid_: Parallel resume, split state/trace writes, duplicate Observation Record append, tool retry as new action, final-only stage assembly

**Controlled ReAct Outcome Taxonomy**:
The mutually exclusive result classes for a Controlled ReAct Orchestrator transition: governed waiting, governed terminal outcome, or exceptional diagnostic stop. Approval pauses and clarification needs are waiting states, normal refusals and evidence-insufficient answers are governed terminal outcomes, and provider, adapter, normalization, or readiness failures are diagnostic stops with Workflow Stage Failure Diagnostic Projection.
_Avoid_: Approval as failure, diagnostic stop as ordinary stage summary, provider exception as customer answer, HTTP status as workflow semantics

**Controlled ReAct State Machine Core**:
The typed transition kernel inside the Controlled ReAct Orchestrator. It advances Controlled ReAct Run State through explicit commands and effect results while depending on LLM, retrieval, tool, policy, trace projection, and snapshot persistence through ports.
_Avoid_: capability-owned state mutation, runtime graph state, dict transition payload, direct adapter call inside state update

**Controlled ReAct Action Authority**:
The Orchestrator-owned decision boundary that turns planner proposals, eligible action sets, review facts, policy facts, and observation history into the next governed action or terminal/waiting outcome. Planner, Review, Policy, Tool Gateway, retrieval, and tool adapters provide proposals or effect facts; they do not jump orchestration state or produce final answers.
_Avoid_: planner as router, review as executor, policy as flow controller, tool gateway final response

**Controlled ReAct Final Answer Gate**:
The Orchestrator-owned terminal gate inside `model_answer` that validates final answer schema, safety, citation binding, and answer adequacy before an answered outcome may be returned. Delivery may project this result but must not repair or override an Orchestrator-produced terminal outcome after the fact.
_Avoid_: delivery-side answer correction, citation-only success, raw evidence answer, post-hoc terminal rewrite

**Controlled ReAct Memory Write Placement**:
The V3 rule that memory write is an Orchestrator-owned post-terminal governed side effect projected as the `memory` Workflow Template Stage before `response`. By default, memory write failure records a blocked or skipped memory projection but does not change the already-governed terminal answer outcome unless policy explicitly requires fail-closed behavior.
_Avoid_: memory-owned answer change, delivery-side memory write, memory write inside plan round, hidden terminal rewrite

**Controlled ReAct Memory Read Placement**:
The V3 rule that memory read is an Orchestrator-owned pre-loop context step after Intent Resolution and before the first plan round. Memory read may influence planning, retrieval query formation, and clarification selection, but it is not accepted evidence and must not become a citation basis for the final answer.
_Avoid_: memory as evidence, memory citation, retrieval-afterthought memory read, delivery-side context injection

**Controlled ReAct Response Projection Ownership**:
The V3 rule that `response` is an Orchestrator-owned governed response projection stage that shapes the caller-visible message, refusal wording, citation presentation, and disclosure semantics from the terminal outcome. Delivery finalizes artifacts such as trace, receipt, and RunStore records, but must not own workflow response semantics.
_Avoid_: delivery-owned response wording, artifact finalization as workflow stage, ungoverned final output wrapper, receipt-driven response

**Controlled ReAct Effect Port Set**:
The minimum side-effect interface set consumed by the Controlled ReAct Orchestrator: intent resolver, planner, review, policy, knowledge observation, tool observation, observation truth store, answer synthesis, stage projection, snapshot store, and transition lock. Concrete runtime, delivery, provider, store, and adapter classes plug in behind these ports.
_Avoid_: direct RunStore dependency, direct LangGraph dependency, direct provider client dependency, broad service locator

**Controlled ReAct Port Protocol Module**:
The internal `proof_agent/control/workflow/controlled_react/ports.py` module that declares Orchestrator effect port protocols. These protocols are Control Plane dependency-inversion seams, while only persisted or serialized DTOs belong in `proof_agent/contracts/`.
_Avoid_: global contracts for private ports, delivery-owned port protocols, runtime-owned port protocols, service locator module

**Controlled ReAct Contract Module**:
The `proof_agent/contracts/controlled_react.py` module for persisted, resumable, or audit-replayable Controlled ReAct DTOs such as Controlled ReAct Run State, Controlled ReAct Run State Snapshot, Observation Record, Observation Truth Artifact variants, and Answer Evidence Context. Observation Effect, Observation Identity, Observation Commit Result, Observation Summary Builder, transition commands, and state-machine step types remain in `proof_agent/control/workflow/controlled_react/`.
_Avoid_: internal command contract, port protocol contract, runtime state contract, trace-only DTO

**Controlled ReAct Public Execution Result**:
The Orchestrator external return boundary: `WorkflowTemplateExecutionResult` only. Controlled ReAct Run State, run-state snapshots, transition commands, and effect results remain internal implementation or resume artifacts and must not be returned to Delivery as public execution facts.
_Avoid_: RunState API response, snapshot handoff result, transition debug payload, internal state leak

**Controlled ReAct Delivery Entry Point**:
The Delivery-to-Control handoff for the V3 product path: Delivery resolves the Published Agent, run id, request facts, and artifact finalization context, then calls `ControlledReActOrchestrator.start` or `ControlledReActOrchestrator.resume`. Delivery must not call LangGraph runners or React runtime graphs for V3 orchestration semantics.
_Avoid_: delivery-owned workflow branch, direct runtime runner call, approval registry as execution authority, Delivery state machine

**Controlled ReAct Legacy Runtime Deletion Gate**:
The cutover condition that removes legacy V3 execution entrypoints and their authority from production code, tests, and current architecture documentation. `run_with_langgraph`, `resume_langgraph_approval`, `LangGraphApprovalResumeRegistry`, React runtime graphs, and LangGraph checkpoint resume must not remain as V3 execution paths after Orchestrator cutover.
_Avoid_: hidden legacy test authority, CLI fallback runner, documentation-defined old path, optional compatibility branch

**Controlled ReAct Template-Bound Execution**:
The V3 execution binding where `workflow.template: react_enterprise_qa_v3` selects the Controlled ReAct Orchestrator product path. `workflow.runtime` no longer chooses the execution engine for V3 Published Agents, and LangGraph checkpointer fields do not define approval resume semantics.
_Avoid_: YAML-selected runtime engine, runtime feature flag, checkpointer-owned resume, template/runtime split authority

**Controlled ReAct Stage Descriptor Projection**:
The V3 interpretation of Workflow Template Descriptor stages and `workflow.stages[]`: they configure and explain stage projections for Dashboard, Governance Receipt, RunStore, and validation capture. They do not define execution nodes, edges, branches, ordering, loops, or Orchestrator state transitions.
_Avoid_: YAML workflow graph, descriptor-owned execution order, configurable branch edge, stage list as runtime plan

**Controlled ReAct Workflow Completeness**:
The V3 completeness standard that requires the Orchestrator to execute the real Controlled ReAct Loop, enforce the relevant governance gates, and emit complete Workflow Stage projections for trace, receipt, Dashboard, and validation capture. Completeness is not descriptor-order execution and must not move execution authority out of the Orchestrator.
_Avoid_: running every descriptor stage in order, projection-only success, trace event checklist, descriptor-driven orchestration

**Controlled ReAct Orchestrator Test Authority**:
The V3 correctness test boundary centered on the Controlled ReAct Orchestrator: pure state-machine tests, fake-port integration tests, and Delivery smoke tests through `WorkflowTemplateExecutionResult`. Legacy runtime-runner tests may survive only when rewritten to assert current V3 Orchestrator semantics.
_Avoid_: LangGraph runner test authority, checkpoint resume golden path, old trace parity test, hidden legacy fixture

**Controlled ReAct Workflow Completeness Acceptance Suite**:
The first V3 full-chain acceptance matrix: single retrieval with memory read/write and response projection; no-evidence governed refusal; tool approval waiting with snapshot and approval projection; approved approval resume returning to plan; denied approval resume returning to plan; and bad final answer rejection through schema, citation, safety, and adequacy gates.
_Avoid_: single happy-path validation, trace-only coverage, model-answer-only test, approval terminal shortcut

**Intent Resolution**:
The governed understanding step that turns a user turn and admitted conversation context into an audit-safe summary of user goal, domain intent, known facts, missing fields, ambiguities, risk flags, and the recommended next action before ReAct planning.
_Avoid_: Raw chain-of-thought, hidden thinking, unstructured intent guess

**Intent Resolution Contract**:
The structured output contract for Intent Resolution, distinct from Reasoning Summary because it describes user intent and ambiguity rather than the rationale for a selected ReAct action.
_Avoid_: Reused Reasoning Summary, planner scratchpad, free-form intent notes

**Retrieval Query Set**:
A bounded, non-executing set of candidate Knowledge retrieval queries emitted with Intent Resolution to express the search angles needed for the user's intent before the governed Retrieval stages choose and execute queries.
_Avoid_: Executable retrieval plan, provider call list, ReAct planner query rewrite, untrusted web search rewrite

**Knowledge Query Expansion**:
The public Intent Resolution behavior for knowledge-retrieval intents where the model expands one user question into a bounded Retrieval Query Set with complementary search angles. It is domain-neutral: query items express angles such as original wording, synonym or business terminology, time/entity/metric qualifiers, and bilingual alternatives when useful, without creating a new domain-specific query type.
_Avoid_: Business-specific query subtype, one-query synonym rewrite, source filter, executable retrieval plan

**Parallel Query Set Retrieval**:
The bounded execution behavior where independent Retrieval Query Items from one reviewed Retrieval Query Set may retrieve concurrently when the provider explicitly declares parallel retrieval support. It preserves one governed retrieval action, required-item fail-closed semantics, optional-item timeout degradation, and deterministic evidence aggregation by query-set order.
_Avoid_: Parallel ReAct planning, unbounded provider fan-out, implicit provider thread-safety, optional query blocking after timeout

**Retrieval Query Item**:
One candidate query in a Retrieval Query Set, carrying query text plus audit-safe intent angle, required flag, and reason without naming Knowledge Sources, providers, filters, or execution parameters.
_Avoid_: Provider route, source filter, scoped retrieval command, top_k override

**React Enterprise QA Template**:
The V1 Controlled ReAct Workflow Template for enterprise question answering.
_Avoid_: Replacing Enterprise QA Template, generic autonomous agent template

**React Enterprise QA Template V2**:
The versioned Controlled ReAct Workflow Template that adds Intent Resolution before ReAct planning while preserving historical interpretation of earlier Published Agent Versions.
_Avoid_: Runtime feature flag for v1, mutable latest template behavior

**React Enterprise QA Template V3**:
The product-baseline Controlled ReAct Workflow Template that combines Intent Resolution, Business Flow Skill Pack admission, and the real Controlled ReAct Loop. Earlier Enterprise QA and React Enterprise QA V1/V2 execution paths are retired rather than kept as compatibility paths.
_Avoid_: Compatibility template, feature flag, parallel legacy workflow

**Deterministic ReAct Demo**:
A no-API-key acceptance path for the React Enterprise QA Template using deterministic planner and review providers.
_Avoid_: Remote-only ReAct demo, provider-dependent MVP

**Deterministic ReAct Baseline**:
The deterministic regression baseline for Proof Agent's primary React Enterprise QA Workflow Template, using deterministic planner, reviewer, model, retrieval, and tool implementations.
_Avoid_: Legacy linear Enterprise QA baseline, remote-model release gate, separate workflow world

**Controlled ReAct Loop**:
The real Think→Act→Observe→Replan loop shape for React Enterprise QA Template V3, in which each `plan` round emits one governed ReAct Action Proposal, executes one observation action, writes an Observation Record, and returns to plan until plan emits a terminal action. Distinct from the retired single-pass ReAct wiring where retrieval and tool were terminal branches.
_Avoid_: Single-pass ReAct DAG, classification pipeline mislabeled as ReAct, plan-and-execute batch

**Plan Round**:
One invocation of the `plan` stage in the Controlled ReAct Loop. The unit counted by the `max_plan_rounds` budget. Replaces the older `max_steps` concept; `react.max_steps` is read as a backward-compatible alias for `max_plan_rounds`.
_Avoid_: Graph node, retrieval step, tool call

**Observation Action**:
A Controlled ReAct Loop action that gathers information and then returns control to `plan`: `PLAN_RETRIEVAL` and `PROPOSE_TOOL_CALL`. Its only execution result is an Observation Record; it must not create final output or select a terminal outcome.
_Avoid_: Terminal action, one-shot branch, tool-generated final answer, retrieval-generated final answer

**Observation Effect**:
The internal effect result returned by a Knowledge Observation Port or Tool Observation Port after executing an Observation Action, carrying a proposed Observation Record envelope, a typed Observation Truth Artifact, and a trace-safe projection. It is not committed state until the Orchestrator validates and atomically writes the truth artifact and record.
_Avoid_: Committed Observation Record, adapter-owned state append, trace event as effect

**Observation Identity Allocation**:
The Orchestrator-owned deterministic assignment of `observation_id`, `truth_ref`, and commit key before an Observation Action executes. Observation adapters must use the allocated identity in their Observation Effect and must not mint observation ids or truth refs.
_Avoid_: Adapter-generated observation id, random truth ref, retry-dependent identity, provider-owned commit key

**Observation Summary Builder**:
The deterministic Control Plane builder that derives the planner-visible Observation Record `summary` from Observation Truth Artifact metadata, evidence admission facts, Tool Contract `summary_fields`, and redaction policy. Observation adapters do not author free-form planner-visible summaries.
_Avoid_: Adapter-authored summary, raw evidence summary, raw tool payload summary, model-written observation summary

**Terminal Action**:
A Controlled ReAct Loop action that ends the loop: `GENERATE_FINAL_ANSWER`, `ASK_CLARIFICATION`, `REFUSE`. Terminal actions are the only loop exit.
_Avoid_: Observation action, mid-loop stop

**Observation Record**:
The structured control-state envelope written into state after each observation action, carrying a deterministic no-LLM summary, convergence fields, safe source/citation references, and a `truth_ref` to the Observation Truth Artifact. Observation Records are the sole loop-visible result carrier for Observation Actions; they are control state, not logs, and `plan` reads summaries while `model_answer` resolves `truth_ref` for full content.
_Avoid_: Discarded tool output, trace-only observation, unstructured planner scratchpad, direct final response, raw evidence summary

**Observation Truth Artifact**:
The typed payload artifact referenced by an Observation Record `truth_ref`, modeled as a discriminated union for retrieval truth and tool truth. It contains full admitted retrieval evidence or authorized tool result plus redaction and admission metadata for final-answer synthesis, audit replay, and receipt basis, and it must not be embedded in Observation Record `summary`.
_Avoid_: Summary payload, planner scratchpad, trace payload, evidence stuffed into summary

**Retrieval Observation Truth**:
The Observation Truth Artifact variant for governed retrieval, carrying accepted evidence chunks, rejected-evidence summary, admission metadata, and citation references. It is the only full retrieval payload that final-answer synthesis may use after a retrieval Observation Record.
_Avoid_: Evidence in summary, citation-only record, raw provider response

**Tool Observation Truth**:
The Observation Truth Artifact variant for governed tool execution, carrying the authorized redacted tool result, tool identity, result schema reference, approval reference when available, and redaction metadata. It is distinct from Tool Observation Record summary, which contains only planner-visible fields.
_Avoid_: Tool summary as truth, raw tool payload, approval trace as result

**Observation Truth Store**:
The Control Plane storage boundary for Observation Truth Artifacts, written atomically with Observation Record commit and resolved by `truth_ref` for final-answer synthesis, audit replay, and receipt basis. Controlled ReAct Run State and snapshots store only `truth_ref`, never the full truth payload.
_Avoid_: Snapshot payload store, trace store, RunStore projection, summary-backed truth

**Observation Truth Projection**:
The trace-safe observability projection emitted from Observation Commit for Trace, Governance Receipt, RunStore, and Dashboard. It carries ids, counts, status, source/citation references, redaction facts, and bounded summaries only; it does not expose full Observation Truth Artifact payloads.
_Avoid_: Truth artifact read, raw evidence projection, raw tool result projection, Dashboard truth payload

**Observation Audit Replay**:
The permissioned audit path that resolves Observation Truth Artifacts by `truth_ref` for replay, investigation, or validation use cases. It is separate from ordinary Trace, Governance Receipt, RunStore, and Dashboard projections.
_Avoid_: Ordinary run detail, receipt rendering, trace replay shortcut, customer-visible source view

**Observation Commit**:
The Orchestrator-owned atomic transition that validates an Observation Effect, writes the Observation Truth Artifact, appends the Observation Record envelope, and emits trace-safe projections under one transition boundary. Observation adapters may propose effects but cannot mutate Control Plane state directly.
_Avoid_: Adapter append, split truth/record write, trace-first commit, best-effort observation persistence

**Observation Commit Failure**:
The fail-closed result when Observation Commit cannot validate or persist the complete observation unit, including truth artifact validation, truth store write, summary build, record append, or trace-safe projection construction. A failed commit must not append an Observation Record or create a state where `truth_ref` cannot resolve.
_Avoid_: Partial observation, record without truth, truth without record, fake trace success, silent degraded commit

**Eligible Action Set**:
The runtime-computed subset of ReAct actions that `plan` is permitted to choose in a given round, narrowed by the Convergence Check. Enforced structurally by `_constrain_action`, not by prompt wording.
_Avoid_: Prompt suggestion, advisory action list, LLM self-policed constraint

**Planner Eligible Action Contract**:
The planner-facing structured input contract that exposes the current Eligible Action Set as the only allowed actions for a Plan Round. Prompt context may explain why the set was narrowed, but it must not broaden the structured `allowed_actions` list.
_Avoid_: Static planner allowlist, prompt-only constraint, all-actions planner schema

**Answer-Ready Convergence Signal**:
The Convergence Check signal that fires when Accepted Evidence exists and the latest Observation Record declares no unresolved subgoals. It activates the Answer-Ready Finalization Gate: the loop should proceed to `GENERATE_FINAL_ANSWER` unless an explicit blocker is present.
_Avoid_: Repeat retrieval by default, evidence-saturation-only convergence, planner-owned stop decision, terminal two-choice ambiguity

**Answer-Ready Finalization Gate**:
The Control Plane rule that treats answer-ready state as a final-answer obligation, not a peer choice between answer and refusal. When no explicit blocker exists, the next Plan Round's Eligible Action Set is `GENERATE_FINAL_ANSWER` only. A `REFUSE` terminal action remains valid only when the state carries a specific blocker such as unresolved subgoals, a policy denial, no Accepted Evidence, evidence relevance failure, or citation-binding impossibility.
_Avoid_: Refusal from model caution alone, refusal because past turns failed, refusal without a blocker, answer-ready as terminal coin flip, answer-ready terminal two-choice set

**Answer-Ready Planner Context Isolation**:
The model-bearing context projection rule for Plan Rounds after the Answer-Ready Convergence Signal fires. Current Observation Records and explicit blockers govern the terminal decision; prior refusal or failed-attempt summaries must be omitted from free-text planner context or projected only as bounded non-blocking metadata that cannot justify refusal.
_Avoid_: Historical refusal as current evidence, prior failed attempts as a blocker, free-text failure summaries in answer-ready planner context

**Answer-Ready Action Constraint**:
The deterministic eligibility enforcement rule that rewrites any non-`GENERATE_FINAL_ANSWER` proposal to `GENERATE_FINAL_ANSWER` when answer-ready state has no explicit blocker. If a blocker exists, the blocker determines whether `REFUSE`, `ASK_CLARIFICATION`, or another governed terminal path is eligible.
_Avoid_: Accepting planner-selected refusal without blocker, relying on provider function-calling alone, hidden answer-ready rewrite

**Answer-Ready Synthetic Finalization**:
The plan-stage Control Plane behavior that emits a synthetic `GENERATE_FINAL_ANSWER` action without invoking the planner model when the Answer-Ready Finalization Gate has no blockers. It preserves the Controlled ReAct Loop topology because the exit action is still produced by the `plan` stage, but removes unnecessary model latency and historical-context influence from a deterministic finalization decision.
_Avoid_: Calling planner just to confirm finalization, model-owned finalization when blockers are empty, skipping the plan stage entirely

**Answer-Ready Blocker**:
A first-class Control Plane state item that explains why answer-ready state cannot proceed directly to `GENERATE_FINAL_ANSWER`. Each blocker has a stable `code`, bounded `reason`, and optional source reference. Common codes include `no_accepted_evidence`, `unresolved_subgoal`, `policy_denied`, `evidence_relevance_failed`, `citation_binding_impossible`, and `variant_conflict`.
_Avoid_: Inferring blockers from scattered state at decision time, raw model rationale as blocker, unstructured refusal reason

**Answer-Ready Evidence Projection**:
The evidence projection rule after the Answer-Ready Finalization Gate admits `GENERATE_FINAL_ANSWER`. The planner reads only Observation Record summaries and blockers, while `model_answer` must receive the full Accepted Evidence truth layer plus Observation Record `citation_refs` and `source_refs` so it can synthesize and bind cited claims.
_Avoid_: Final answer from planner summary only, citation refs without evidence content, moving refusal from planner to model_answer by starving evidence

**Answer Evidence Context**:
The Orchestrator-built final-answer input that resolves required Observation Record `truth_ref` values through the Observation Truth Store and packages typed retrieval/tool truth, citation refs, source refs, and validation precheck facts for AnswerSynthesisPort. AnswerSynthesisPort consumes this resolved context and does not receive a Truth Store handle.
_Avoid_: Answer adapter store read, summary-derived evidence, planner summary as answer evidence, store handle in model_answer

**Product Variant Ambiguity**:
A product-clause ambiguity where the user names a product family or short product name that could map to multiple variants. It does not block Answer-Ready Finalization when Accepted Evidence clearly identifies one product variant; the final answer must state the cited variant scope. It becomes a blocker only when Accepted Evidence contains conflicting variants or cannot establish which variant the answer would cover.
_Avoid_: Refusal from ambiguity alone, unstated product-scope answer, merging multiple variants without saying so

**Unresolved Subgoal**:
A planner-visible item in an Observation Record summary that names a still-unanswered part of a compound request and justifies another Observation Action after Accepted Evidence exists.
_Avoid_: Hidden TODO, model hunch, chain-of-thought proxy

**Final Answer Citation Binding Gate**:
The fail-closed validation gate that binds customer-visible factual claims to Observation Record `citation_refs` or `source_refs`. If Accepted Evidence exists and the final answer lacks supported citation references for factual claims, the answer is rejected rather than projected as governed output.
_Avoid_: Citation-looking text, source list without Observation Record support, best-effort unsupported answer

**Convergence Check**:
The deterministic, plan-precondition Control Plane enforcement point that inspects control state (Plan Round count, Evidence Trajectory, Action History) and narrows the Eligible Action Set to force the loop to converge. It never emits a terminal outcome directly; it only constrains what `plan` may choose.
_Avoid_: LLM-driven convergence, heuristic hint, soft prompt guidance

**Action Constraint**:
The deterministic rewrite performed when a plan proposal falls outside the Eligible Action Set: the action is replaced by a default (`GENERATE_FINAL_ANSWER` in convergence contexts, `REFUSE` in divergence contexts) and an `action_constrained` trace event records the original, the constrained value, and the reason. Permanent provider-neutral backstop even after function-calling enforcement lands.
_Avoid_: Silent rewrite, retry-the-LLM, prompt re-negotiation

**Evidence Trajectory**:
The per-round sequence of accepted-evidence counts used by the Convergence Check to detect evidence saturation. Control state, not a log.
_Avoid_: Final evidence list, retrieval debug log

**Action History**:
The per-round sequence of selected action types and parameter hashes used by the Convergence Check to detect action repetition and oscillation. Control state, not a log.
_Avoid_: Trace event stream, audit-only history

**Observation Action Deduplication Gate**:
The pre-execution Control Plane gate that rejects an Observation Action when the same `action_type` and `parameter_hash` already ran in the same governed run and no Observation Record declares a new unresolved subgoal requiring that repeat. It narrows the next decision to terminal actions instead of spending another retrieval or tool call.
_Avoid_: Retrieval cache, post-hoc saturation signal, planner-owned duplicate suppression

**Tiered Loop Models**:
The Controlled ReAct Loop model assignment policy where `intent_resolution` and `plan` use a smaller, faster model and `model_answer` uses a larger model, so that loop cost and latency stay bounded as plan rounds grow.
_Avoid_: Single model for all stages, unbounded per-round cost

**Deterministic Plan Short-Circuit**:
A bounded, audited rule path that selects the first plan action without calling the planner model when the request is unambiguous, so that simple requests are not forced through multiple plan rounds.
_Avoid_: Hidden second planner, unaudited fast path, silent behavioral drift from the LLM planner

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

**Effective Tool Proposal Scope**:
The planner-visible, run-time subset of Tool Proposal Scope after intent admission, Workflow Template stage context, caller audience, policy prechecks, and tool budget constraints are applied.
_Avoid_: Full Agent tool catalog, full MCP tool catalog, complete parameter schema dump

**Workflow Stage Configuration Trace Summary**:
The default trace-safe record of a run's Workflow Stage configuration source and per-stage configuration summary: source, reference when available, descriptor version, stage ids, configured prompt field names, bounded lengths and counts, context option names, and redaction status.
_Avoid_: Full prompt text, full context payload, raw validation dump

**Workflow Stage Trace Capture Mode**:
The validation/test-run request switch that controls whether run trace stores only Workflow Stage Configuration Trace Summary or additionally captures full stage Prompt, selected context values, and intermediate Workflow Stage Result details for verification.
_Avoid_: Always-on verbose trace, production raw prompt archive, chain-of-thought capture

**Workflow Stage Prompt Value Capture**:
The full-capture record of run-start effective Workflow Stage Prompt Field Set values, including allowed Agent-authored business prompt text after secret redaction, field lengths, redaction flags, and source metadata.
_Avoid_: system_prompt, developer_prompt, raw_prompt, provider request body, complete model context

**Workflow Stage Context Verification Projection**:
The full-capture representation of applied Workflow Stage context as option names, safe summaries, counts, identifiers, and references observed during execution, without storing raw business content.
_Avoid_: Raw context dump, full model context snapshot, raw transcript, raw evidence content

**Workflow Stage Context Application Fact**:
The runtime-neutral, trace-safe execution fact emitted when a Workflow Template Stage applies its selected context, carrying the same safe summary used by Workflow Stage Context Verification Projection.
_Avoid_: Trace-file-only event, raw context payload, runtime adapter state, model request dump

**Workflow Stage Context Configuration Capture**:
The full-capture record of selected Workflow Stage context option keys from the run-start Workflow Template Execution Input for available stages, independent of whether those stages executed.
_Avoid_: Applied context event, raw context value, latest descriptor replay

**Workflow Template Execution Resume Metadata**:
The Runtime Plane metadata retained for resuming a paused Workflow Template Execution, including a protected reference to the run-start Workflow Template Execution Input needed for checkpoint resume without exposing full Prompt or context values through ordinary trace, receipt, RunStore detail, or Dashboard projection.
_Avoid_: Ordinary trace content, Governance Receipt section, Dashboard run detail payload

**Clarification Requested Event**:
A trace event that records a Clarification Request and the missing information categories.
_Avoid_: Approval event, refusal event

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

**Approval Checkpoint Resume**:
The governed continuation of the original run after an external approval decision resolves a PendingApproval, resuming the stored runtime checkpoint and appending the terminal approval event to the original run trace.
_Avoid_: Approval Continuation Run, new follow-up run, silent retry

**Pending Approval Operation Source**:
The `PendingApproval` projection used by Approval Console actions to identify an unresolved approval request. Approval Console may display `ApprovalState`, but approve and deny actions must target `PendingApproval.approval_id`, not trace event ids or status-only approval projections.
_Avoid_: ApprovalState as command target, trace event id as approval id, inferred approval action

**Approval Resolution Actor**:
The operator identity resolved from Operator Identity Context for an approve or deny command and persisted on terminal approval trace events.
_Avoid_: Anonymous approval, customer-supplied approval authority, trace event without resolver identity
