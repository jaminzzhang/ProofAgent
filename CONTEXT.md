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
