# Proof Agent

Proof Agent is a Controlled Agent Harness Framework for enterprise Agent delivery. Its domain language centers on governed execution, evidence-backed answers, tool approval, and auditability.

> **Domain split migration**: Routed domain contexts start at [CONTEXT-MAP.md](CONTEXT-MAP.md). This file keeps product-wide terms only. Add new terms to the relevant `docs/domain/*/CONTEXT.md` file, and put resolved ambiguity or relationship history in the matching `docs/domain/*/decisions.md` file when it is worth preserving.

## Language

This root glossary now carries only product-wide terms. Use [CONTEXT-MAP.md](CONTEXT-MAP.md) to route to focused domain glossaries before reading task-specific language.

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

**Agent Package**:
A reviewable delivery artifact containing an Agent Contract plus its policy, tools, knowledge references, fixtures, and domain adapters.
_Avoid_: Database-only Agent, uploaded manifest path, loose config bundle

**Public Example Agent Package**:
A source-controlled Agent Package under `examples/` used as a stable runnable reference for users, docs, local configuration seeding, tests, and Dashboard creation flows.
_Avoid_: Workflow Template, template registry entry, generated local Draft Agent data

**Harness RAG**:
An evidence-backed RAG flow governed by the Control Envelope.
_Avoid_: Plain RAG, uncontrolled RAG

**Plain RAG**:
A retrieve-then-generate flow without Harness policy gates or evidence admission.
_Avoid_: Harness RAG

**Proof Agent**:
The product and codebase for building governed, auditable enterprise Agents inside a Controlled Agent Harness Framework.
_Avoid_: Generic chatbot, one-off RAG demo

**Harness Engineering**:
The discipline of designing Agent delivery through explicit contracts, governed capabilities, evidence checks, audit output, and controlled execution boundaries.
_Avoid_: Prompt engineering only, RAG tuning

**Workflow Template**:
A registered governed flow shape selected by an Agent Contract for a run.
_Avoid_: Runtime graph mechanics, arbitrary LangGraph topology

**PolicyEngine**:
The Control Plane authority that evaluates policy rules and returns governed decisions without being bypassed by runtime or capability adapters.
_Avoid_: Prompt instruction, UI-only policy

**Tool Gateway**:
The governed boundary through which tool proposals are authorized, approved when needed, executed, summarized, and audited.
_Avoid_: Direct tool executor, plugin shortcut

**Trace & Audit**:
The audit side channel that records trace-safe facts about execution without becoming a second workflow path or leaking raw sensitive payloads.
_Avoid_: Debug dump, hidden execution state

**Governance Receipt**:
The human-readable audit artifact summarizing the governed outcome, evidence, policy, tool approval, model use, and relevant run facts.
_Avoid_: Raw trace, model transcript

**Production Transactional State Store**:
The authoritative production boundary for mutable structured configuration, run, conversation, approval, evaluation, audit-metadata, and coordination state across Proof Agent.
_Avoid_: Local JSON authority, filesystem lock, read projection as execution state, transient cache as source of truth

**Production Artifact Store**:
The authoritative production object-storage boundary for immutable Trace, Governance Receipt, Knowledge, validation, evaluation, and export artifacts referenced from Production Transactional State Store metadata.
_Avoid_: Local runs directory, mutable latest path, database blob as artifact authority, unverified object reference

**Initial Production Topology**:
The first supported deployment shape for the internal single-tenant private pilot: one hardened Linux host running the browser gateway, API, Run Executor, Knowledge Worker, and static application surfaces through production Docker Compose, with external production state, artifact, identity, and secret services.
_Avoid_: Development Compose, Kubernetes cluster, multi-host high availability, public quick tunnel

**Production Deployment Slot**:
One of the fixed Blue or Green application stacks that can be standby, routed, draining, soaking, or retained for rollback while the stable Gateway remains outside both slots.
_Avoid_: Percentage canary pool, in-place container replacement, independently routed frontend, mutable release directory

**Production Role Activation Lease**:
The PostgreSQL ownership record and fencing epoch that permits exactly one Production Deployment Slot to claim new Run Executor and Knowledge Worker tasks.
_Avoid_: Process-local leader flag, simultaneous active slots, Gateway route as worker ownership, unfenced heartbeat

**Deployment Drain**:
The pre-switch state in which the active slot stops new task claims while completing already claimed Attempts within the bounded release drain interval.
_Avoid_: Immediate worker kill, cross-release attempt transfer, queue admission shutdown, silent duplicate execution

**Release Rollback Window**:
The post-switch period through which the immediately previous immutable slot, compatible schema, and tested reversal procedure remain available for application rollback without a database down migration.
_Avoid_: Destructive migration window, indefinite old production traffic, source-tree rollback, best-effort image reconstruction

**Production Deployment Compatibility Manifest**:
The production-candidate-bound inventory and verification evidence for the concrete external database, object store, identity provider, secret provider, gateway, and model-provider combination used by one deployment.
_Avoid_: Generic compatibility claim, reference-stack-only proof, unversioned provider list, deployment note detached from candidate

**Initial Production Agent**:
The sole first-release production Agent identity, `agent_management_insurance_specialist`, migrated to the V3 Controlled ReAct path and bound only to production-admissible Knowledge, Case Memory, model, and read-only tool capabilities.
_Avoid_: Production Agent catalog, V2 example Agent, customer-facing example Agent

**Initial Production Availability SLO**:
The internal, non-contractual objective that the initial production service is available for 99.0% of each calendar month, excluding no more than four hours of pre-announced maintenance.
_Avoid_: External SLA, high-availability guarantee, process-only health percentage

**Initial Production Capacity Envelope**:
The first-release operating boundary of 20 simultaneously online operators, five active governed runs, and 50 queued run requests, with explicit overload rejection beyond that boundary.
_Avoid_: Unlimited concurrency, request-thread capacity assumption, silent overload timeout

**Initial Production Responsiveness SLO**:
The first-release latency objective covering subsecond run acceptance and feedback, subsecond dispatch when capacity is available, a 60-second P95 governed answer for standard supported cases, and a 120-second hard run deadline.
_Avoid_: Acknowledgement-only latency, hidden queue time, unbounded run duration

**Initial Production Support Window**:
The internal private-pilot support boundary of business days from 09:00 through 18:00 in `Asia/Shanghai`, with 30-minute P0 and four-hour P1 acknowledgement targets during that window.
_Avoid_: 24-by-7 on-call commitment, external support SLA, availability measurement window

**Production Run Queue**:
The Proof Agent-owned persistent admission boundary for accepted governed run requests awaiting bounded execution or carrying recoverable execution state.
_Avoid_: API memory queue, external message broker, unbounded background task list

**Run Executor**:
The same-release Proof Agent process role that leases and executes work from Production Run Queue without becoming a public microservice or arbitrary-code sandbox.
_Avoid_: Run Worker microservice, request-thread executor, Sandbox Execution Service

**Production Run Execution Snapshot**:
The immutable execution-contract version and set of published Agent, Knowledge, model connection, egress-policy, and secret-handle version references resolved when a Production Run Queue request begins execution.
_Avoid_: Live mutable configuration lookup, browser-selected runtime version, raw secret snapshot

**S3-First Artifact Finalization**:
The initial-production commit boundary that verifies unique immutable artifact objects and their Production Artifact Manifest in the Production Artifact Store before one Production Transactional State Store transaction makes them visible with their owner outcome.
_Avoid_: PostgreSQL-first success, recoverable per-object upload Saga, success before artifact verification, mutable object overwrite

**Production Artifact Manifest**:
The immutable inventory of exact object versions, roles, lengths, and digests that defines one complete multi-object production artifact result.
_Avoid_: S3 prefix listing as completeness proof, mutable latest manifest, database blob copy, unverified file set

**Uncommitted Artifact Orphan**:
An immutable object written during S3-First Artifact Finalization that has no authoritative Production Transactional State Store reference because its producer did not complete the visibility transaction.
_Avoid_: Published artifact, recoverable terminal result, immediately deletable unknown object

**Run Progress Stream**:
The trace-safe operator projection that durably exposes current coarse Run lifecycle and terminal state while fine-grained intermediate details remain best-effort; reconnect resumes from the current durable state rather than guaranteeing replay of every missed detail.
_Avoid_: Raw model token stream, complete durable progress-event log, browser-disconnect cancellation, polling-only completion response
