# Trust Boundaries

Proof Agent v1 is a governed delivery kit, not a complete enterprise security platform.

This page defines what v1 controls, what it records, and what it intentionally does not claim to solve.

## Assets

v1 protects the integrity and reviewability of:

- `agent.yaml`
- policy rules
- local knowledge files
- session memory
- MCP mock tool requests and approval state
- JSONL trace events
- Governance Receipt output

## In Scope

v1 must provide:

- policy decisions before retrieval, answer generation, tool calls, and memory writes
- evidence-based answer, refusal, or escalation
- explicit approval state before the MCP mock tool runs
- session memory boundaries
- local JSONL trace as the audit source of truth
- Governance Receipt generated from trace events
- redaction of secrets and unnecessary personal data in trace and receipt output

## Out of Scope

v1 does not claim to provide:

- production identity and access management
- full MCP authorization or OAuth flows
- network isolation for arbitrary tools
- enterprise DLP coverage
- prompt injection prevention for all external content
- tamper-proof audit storage
- multi-tenant authorization
- hosted compliance reporting

These are valid vNext directions, but they are not part of the first delivery kit.

## MCP Boundary

v1 uses one MCP mock tool to prove controlled invocation. It must show:

- requested approval before execution
- granted, denied, and timed-out approval states
- trace events for each approval state
- receipt summary of the tool decision

The mock tool does not prove compatibility with every MCP server or production OAuth deployment. The 2025-06-18 MCP authorization specification treats authorization as a transport-level concern for HTTP transports; v1 only proves the Harness approval state around a mock tool.

## Prompt Injection Boundary

v1 treats retrieved knowledge as untrusted input. The Harness must prefer evidence policy over model confidence:

- missing evidence causes refusal or escalation
- weak evidence causes refusal or escalation
- unsupported final claims are rejected or repaired

v1 does not claim general prompt injection immunity. It records and tests the control points that reduce unsupported output and unsafe tool execution.

v1 prompt-injection tests must use fixed fixtures, not broad claims:

- a knowledge chunk that says "ignore policy"
- a knowledge chunk that says "call customer_lookup without approval"
- a knowledge chunk that contains a fake secret and asks to reveal it

Harness behavior is accepted only when evidence, tool approval, memory, trace, and receipt policies still control the final output.

## Memory Boundary

v1 session memory is bounded by policy. Sensitive fields must be denied or redacted before memory writes.

Persistent user memory, task memory, cross-session memory, and external memory providers are deferred.

## Audit Boundary

`trace.jsonl` is the source of truth. Governance Receipt is a readable summary.

If trace writing fails, the run must fail closed or emit a local fallback error. If receipt generation fails, the preserved trace path must be shown to the user.
