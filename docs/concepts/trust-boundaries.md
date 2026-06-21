# Trust Boundaries

Proof Agent is a governed Harness framework, not a complete enterprise security platform.

This page defines what v1 controls, what it records, and what it intentionally does not claim to solve.

## Assets

The current framework protects the integrity and reviewability of:

- `agent.yaml`
- policy rules
- local knowledge files
- remote model provider configuration metadata
- ReAct action proposals and audit-safe Reasoning Summaries
- Harness Review Subagent advisory decisions
- session memory
- MCP tool requests and approval state
- JSONL trace events
- Governance Receipt output
- run history and Dashboard API projections

## In Scope

The framework must provide:

- policy decisions before retrieval, answer generation, model calls, tool calls, and memory writes
- Controlled ReAct action governance for clarification, retrieval planning, retrieval steps, tool proposals, final answer proposals, escalation, and stop actions
- advisory review at `before_retrieval_plan`, `before_retrieval_step`, `before_tool_call`, and `before_model_call`, with final authority retained by PolicyEngine and the Harness
- evidence-based answer, refusal, or escalation
- explicit approval state before governed tools run
- session memory boundaries
- JSONL trace as the audit source of truth
- Governance Receipt generated from trace events
- redaction of secrets and unnecessary personal data in trace and receipt output
- Dashboard API views that do not expose raw secrets or create a second execution path
- no raw chain-of-thought storage or exposure; only audit-safe Reasoning Summary fields may be recorded

## Out of Scope

The current framework does not claim to provide:

- production identity and access management
- full MCP authorization or OAuth flows
- network isolation for arbitrary tools
- enterprise DLP coverage
- prompt injection prevention for all external content
- review subagents as final policy authority
- raw chain-of-thought auditing or replay
- tamper-proof audit storage
- multi-tenant authorization
- hosted compliance reporting

These are valid platform directions, but they are not guaranteed by the current Harness.

## MCP Boundary

The current demo uses one MCP mock tool to prove controlled invocation. Real MCP adapters must preserve the same Harness approval contract and stay behind Tool Gateway. The V1 MCP boundary supports MCP tools only, over stdio and HTTP transports, using curated Tool Contract snapshots rather than live server catalogs as runtime authority. MCP resources and prompts do not enter Knowledge Source or Prompt Configuration paths in V1.

The tool boundary must show:

- requested approval before execution
- granted, denied, and timed-out approval states
- trace events for each approval state
- receipt summary of the tool decision

The mock tool does not prove compatibility with every MCP server or production OAuth deployment. HTTP MCP V1 supports only no-auth or static environment-variable credential references, not OAuth, refresh-token management, or per-user delegated authorization. MCP authorization remains transport/provider-specific; Proof Agent owns the Harness approval state, Tool Contract mapping, result classification, trace, and receipt around tool use.

## Prompt Injection Boundary

Proof Agent treats retrieved knowledge and remote model output as untrusted input. The Harness must prefer evidence policy and validators over model confidence:

- missing evidence causes refusal or escalation
- weak evidence causes refusal or escalation
- unsupported final claims are rejected or repaired

The framework does not claim general prompt injection immunity. It records and tests the control points that reduce unsupported output and unsafe tool execution.

Prompt-injection tests should use fixed fixtures, not broad claims:

- a knowledge chunk that says "ignore policy"
- a knowledge chunk that says "call customer_lookup without approval"
- a knowledge chunk that contains a fake secret and asks to reveal it

Harness behavior is accepted only when evidence, tool approval, memory, trace, and receipt policies still control the final output.

## Memory Boundary

Session memory is bounded by policy. Sensitive fields must be denied or redacted before memory writes.

Persistent user memory, task memory, cross-session memory, and external memory providers require explicit retention, deletion, tenant boundary, and redaction rules.

## Audit Boundary

`trace.jsonl` is the source of truth. Governance Receipt is a readable summary.

If trace writing fails, the run must fail closed or emit a local fallback error. If receipt generation fails, the preserved trace path must be shown to the user.

## ReAct And Review Boundary

Controlled ReAct does not make planner output trusted. Planner proposals, review suggestions, and model outputs are all untrusted inputs to the Harness.

The Harness Review Subagent may suggest `allow`, `deny`, `require_approval`, or `escalate`, but PolicyEngine and the Harness make the final policy decision. Review failures fail closed: tool calls require approval, model calls are denied, and retrieval plan or step proposals are denied unless an explicit fallback is configured.

ReAct trace and receipt output must store only an audit-safe Reasoning Summary. Raw chain-of-thought must not be recorded, stored, or exposed in trace, receipt, RunStore, Dashboard API, Conversation API, or response governance details.

## Customer Service Boundary

Autonomous Customer Service Mode is a private-pilot direct customer channel, not production IAM. V1 uses mock authenticated customer sessions. It does not provide OAuth/OIDC, account takeover protection, DLP, ticketing, SLA tracking, or transactional account changes.

Customer-facing API responses must exclude trace links, receipt links, policy decisions, review results, approval state, raw tool parameters, internal handoff status, and raw identity claims. Internal handoffs are available only through operator-facing Dashboard/API projections.
