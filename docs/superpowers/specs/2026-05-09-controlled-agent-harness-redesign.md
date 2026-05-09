# Proof Agent Controlled Agent Harness Redesign

Status: APPROVED FOR PLANNING  
Date: 2026-05-09  
Primary reference: `docs/Proof Agent - Controlled Agent Harness Framework.md`

## 1. Design Decision

Proof Agent should be redesigned around a **platform vision with a narrow MVP**.

The long-term product vision is an enterprise **Agent Control Platform**: a system for designing, running, approving, validating, observing, and auditing controlled AI Agent workflows.

The v1 delivery remains deliberately narrow: a local-first, CLI-first **Controlled Agent Harness Framework** that proves the platform direction through one enterprise knowledge Q&A reference template.

This keeps the project ambitious without turning v1 into a broad platform build.

## 2. New Positioning

Proof Agent is a **Controlled Agent Harness Framework** for building enterprise Agents that are workflow-governed, policy-enforced, tool-gated, memory-bounded, validated, and auditable.

The previous "Enterprise Agent Delivery Kit" framing remains useful, but it becomes the delivery shape rather than the core identity:

- **Proof Agent** is the framework.
- **Enterprise Agent Delivery Kit** is the packaged experience built on top of the framework.
- **Enterprise QA Template** is the first reference template and acceptance scenario.

The public story should move from:

```text
An out-of-the-box enterprise knowledge Q&A Agent.
```

to:

```text
A framework for building controlled enterprise Agents with Harness Engineering.
v1 proves the framework through a runnable enterprise knowledge Q&A template.
```

## 3. Product Definition

Proof Agent uses Harness Engineering to put Agent intelligence inside a deterministic control system.

The core product rule is:

```text
LLM is not the controller.
Workflow is the controller.

Agent proposes.
Harness disposes.

Tools execute.
Validators verify.
Humans approve.
Trace proves.
```

This means:

- LLM nodes may classify, summarize, plan, reason, and write.
- Workflow decides state transitions.
- Policy decides whether important actions may continue.
- Tool Gateway decides whether a tool request is allowed, denied, or paused for approval.
- Validators decide whether structured outputs, evidence, tool results, and safety constraints pass.
- Audit records every meaningful decision.

## 4. v1 Scope

v1 should be named:

```text
Proof Agent v1: Local-first Controlled Agent Harness MVP
```

v1 is not a complete platform and not a single-purpose RAG demo. It is a minimal local framework whose first template proves the Harness lifecycle end to end.

### Required v1 Modules

| Module | v1 responsibility |
| --- | --- |
| Agent Contract | Use `agent.yaml` to declare workflow, policy, tools, memory, knowledge, model, and audit settings. |
| Workflow Orchestrator | Execute an explicit state machine. LangGraph can be the implementation, but not the public identity. |
| Policy Engine | Produce typed decisions at enforcement points: `allow`, `deny`, `require_approval`, `escalate`. |
| Tool Gateway | Centralize tool allowlist, risk level, parameter guard, approval state, and audit. v1 uses one MCP mock tool. |
| Knowledge Provider | Provide local knowledge retrieval for the reference template. |
| Memory Boundary | Support session memory only; every write must pass policy. |
| Validator / Evaluator | Provide minimal schema, evidence, tool result, safety, and deterministic quality checks. |
| Audit & Receipt | Write JSONL trace as the v1 source of truth and generate Governance Receipt from trace events. |

### v1 Non-Goals

- GUI or Admin Console
- hosted control plane
- multi-tenant auth, RBAC, or OAuth
- production MCP Gateway
- multi-Agent collaboration
- public multi-runtime support
- multiple industry templates
- long-term memory system
- cloud observability platform

## 5. Reference Template Role

The enterprise Q&A template is a **reference template**, not the product boundary.

It must prove that Proof Agent can run this controlled lifecycle:

```text
Load Agent Contract
  -> execute Workflow
  -> enforce Policy
  -> retrieve Knowledge
  -> evaluate Evidence
  -> answer / refuse / escalate
  -> route Tool calls through Gateway
  -> pause for Approval when required
  -> bound Memory writes
  -> write Trace
  -> generate Governance Receipt
```

The template should demonstrate:

- supported question: answer with citations
- unsupported question: refuse or escalate
- partially supported question: answer only supported claims or escalate
- tool-required question: wait for approval before MCP mock execution
- prompt-injection fixture: fail to bypass policy, citations, approval, or memory rules
- Plain RAG vs Harness RAG comparison: ordinary RAG may answer loosely, Harness RAG must obey policy

## 6. Target Architecture

The long-term architecture should be expressed as five layers.

```text
User / CLI / API
      |
      v
Agent Control Layer
  - Intent Router
  - Workflow Orchestrator
  - Plan Controller
  - Policy Engine
  - Approval Engine
      |
      v
Agent Runtime Layer
  - LLM Node
  - Planner Skill
  - Research Skill
  - Writer Skill
  - Critic / Validator Skill
      |
      v
Gateway & Context Layer
  - Tool Gateway
  - MCP Adapter
  - Knowledge Provider
  - Memory Provider
      |
      v
Verification & Governance Layer
  - Schema Validator
  - Evidence Evaluator
  - Tool Result Validator
  - Safety Validator
  - Quality Evaluator
  - JSONL Trace
  - Governance Receipt
      |
      v
Templates & Examples
  - Enterprise QA Template
  - Plain RAG vs Harness RAG comparison
```

The v1 implementation is the narrow version:

```text
CLI
 |
 agent.yaml
 |
 Workflow Orchestrator
 |
 Policy Engine + Validator
 |
 Local Knowledge + MCP Mock Tool + Session Memory
 |
 Trace + Governance Receipt
 |
 Enterprise QA Template
```

## 7. Key Architecture Changes

### Harness is the main abstraction

LangGraph should remain an implementation detail. The public mental model should be Workflow + Policy + Gateway + Validator + Audit.

### Tool Gateway is a first-class module

Even with one MCP mock tool, v1 should use Gateway semantics: tool allowlist, risk level, parameter validation, approval state, result normalization, and trace events.

### Validator / Evaluator is core

Validation is not auxiliary. Proof Agent controls Agents by checking structure, evidence, tool results, safety, and quality before producing final outputs or writing memory.

### Plan Controller is part of the platform roadmap

Plan Controller is important for requirement analysis, operational analysis, code execution, and other long-running Agents. It should be documented in the long-term architecture but kept out of the enterprise QA v1 critical path unless needed.

### Templates validate the framework

Templates should be treated as acceptance scenarios for the Harness framework. Enterprise QA proves the first scenario. Future templates can cover insurance, finance, operations, software delivery, and customer service.

## 8. Recommended Documentation Structure

The current docs can evolve toward this structure:

```text
docs/
  vision/
    controlled-agent-harness-framework.md
    platform-roadmap.md
  architecture/
    system-architecture.md
    workflow-orchestrator.md
    tool-gateway.md
    validator-evaluator.md
    memory-knowledge.md
    observability-governance.md
  concepts/
    control-envelope.md
    agent-contract.md
    policy-engine.md
    approval-state-contract.md
    trace-event-contract.md
    governance-receipt-contract.md
    trust-boundaries.md
  examples/
    enterprise-qa.md
    launch-script.md
    governance-receipt.md
  planning/
    prd-v1.md
    technical-plan-v1.md
    test-plan-v1.md
```

The repo does not need to move every document immediately. The first step is to align README, PRD, Technical Plan, and Framework Design around the new positioning.

## 9. Delivery Roadmap

### Phase 0: Documentation and Contract Freeze

Goal: unify project narrative before implementation.

Deliverables:

- Controlled Agent Harness Framework positioning
- v1 PRD with platform vision and narrow MVP
- system architecture document
- Agent Contract, Workflow, Policy, Tool Gateway, Validator, Trace, and Receipt contracts
- Enterprise QA reference template definition

Acceptance:

- README explains Proof Agent in three minutes
- terminology is consistent across docs
- enterprise QA is described as the first template, not the whole product

### Phase 1: Framework Skeleton

Goal: build the main local framework path without real LLM dependency.

Deliverables:

- `proof-agent demo`
- `proof-agent run <agent.yaml>`
- `agent.yaml` loader and schema validation
- workflow runner skeleton
- policy decision model
- trace writer
- receipt generator shell
- deterministic provider

Acceptance:

- no API key required
- deterministic scenario runs through real contracts
- every run writes trace and receipt
- config errors fail fast with actionable error codes

### Phase 2: Harness RAG Reference Template

Goal: prove Proof Agent is not plain RAG.

Deliverables:

- `examples/enterprise_qa/agent.yaml`
- `policy.yaml`
- local Markdown knowledge provider
- evidence evaluator
- citation mapper
- Plain RAG vs Harness RAG comparison
- supported, unsupported, and partial evidence scenarios

Acceptance:

- supported question answers with citations
- unsupported question refuses or escalates
- Plain RAG and Harness RAG visibly diverge
- evidence threshold is policy-controlled

### Phase 3: Tool Gateway and Approval State

Goal: prove tools cannot be used outside Harness control.

Deliverables:

- `tools.yaml`
- MCP mock tool
- Tool Gateway routing
- risk level and allowlist
- `require_approval` state
- approval granted, denied, and timed-out trace events

Acceptance:

- tool calls pass through `before_tool_call`
- unapproved tools do not execute
- denied and timed-out approvals return safe responses
- Receipt explains why the tool did or did not run

### Phase 4: Memory Boundary and Validators

Goal: prove context and outputs are controlled too.

Deliverables:

- session memory
- `before_memory_write`
- sensitive field redaction
- schema validator
- evidence validator
- tool result validator
- safety validator
- deterministic quality checks

Acceptance:

- memory writes are allowed, denied, and audited through policy
- sensitive fields do not enter trace or receipt
- weak evidence, abnormal tool results, and invalid output formats are blocked
- prompt-injection fixtures cannot bypass policy

### Phase 5: Release Readiness

Goal: make the open-source project evaluable.

Deliverables:

- Docker Compose
- `proof-agent doctor`
- `proof-agent inspect`
- README 3-minute launch path
- Trust Boundaries
- CI smoke tests
- release checklist

Acceptance:

- new user can run full evaluation in 30 minutes
- `proof-agent demo` completes in under two minutes without API key
- `proof-agent run examples/enterprise_qa/agent.yaml` completes end to end
- every run writes `runs/latest/trace.jsonl` and `runs/latest/governance_receipt.md`

## 10. v1 Acceptance Statement

v1 is accepted when Proof Agent can run a local enterprise QA reference template through a controlled Harness lifecycle:

```text
contract loading
workflow execution
policy decisions
evidence validation
tool approval
memory boundary
JSONL trace
Governance Receipt
```

The project should not claim production governance, full security, or complete platform coverage in v1. It should claim a working local framework that demonstrates the control model clearly enough for enterprise Agent owners to evaluate and extend.

## 11. Open Questions for Implementation Planning

1. Should v1 expose `workflow.yaml` as a public DSL, or keep workflow selection inside `agent.yaml` and the reference template?
2. Should policy support only YAML rules in v1, or allow Python hooks behind an internal interface?
3. Should Tool Gateway expose generic high-level tool verbs in v1, or keep the public surface limited to named MCP mock tools?
4. How strict should deterministic quality checks be before introducing optional LLM-as-judge evaluation?
5. Should the first implementation plan reorganize docs into the proposed directory structure, or keep filenames stable until code exists?

## 12. Spec Self-Review

- Placeholder scan: no TBD or TODO placeholders remain.
- Consistency check: positioning, v1 scope, architecture, roadmap, and acceptance all use the same framework-first, template-validated framing.
- Scope check: the spec is broad enough to reset the project direction but keeps v1 implementation local, CLI-first, and template-verified.
- Ambiguity check: enterprise QA is explicitly a reference template; platform features are documented as roadmap, not v1 commitments.
