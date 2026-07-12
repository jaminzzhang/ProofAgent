# Proof Agent PRD

## Product

Proof Agent is a Controlled Agent Harness Framework. It keeps model output, evidence, tools, memory, policy and audit inside a provider-neutral Control Envelope.

The initial private pilot is an internal operator product, not a customer-service product. Its sole Agent is `agent_management_insurance_specialist`, executed only by Controlled ReAct V3.

## Users

- internal insurance operations specialists using Operator Chat;
- Agent owners configuring and publishing the sole Agent through Dashboard;
- security, compliance and operations staff reviewing permissions, traces, receipts and release evidence.

## Initial-release scope

| Area | Requirement |
| --- | --- |
| Identity | OIDC-only; no local accounts or passwords; seven-day login session |
| Authorization | server-resolved permissions; Dashboard configuration; no approval workflow |
| Agent | only `agent_management_insurance_specialist` |
| Workflow | only `react_enterprise_qa_v3`; no legacy runtime selector/checkpointer |
| Surfaces | Dashboard and `/operator`; customer and approval routes absent |
| Knowledge | governed published snapshots; production artifacts backed by S3-compatible storage |
| Tools | optional validated read-only HTTPS/MCP tools; no local handler, stdio or state-changing tool |
| Execution | persistent bounded queue inside Proof Agent; same product image runs the Run Executor role |
| Progress | immediate admission response and coarse SSE progress; reconnect restores durable current state |
| State | PostgreSQL is production transactional authority |
| Artifacts | S3-first write/verify, then one PostgreSQL visibility transaction; partial progress may be discarded |
| Audit | trace, Governance Receipt, immutable artifact manifest and release evidence |
| Deployment | hardened single-host production Compose with stable gateway and Blue/Green slots |

## Explicit non-goals

- local username/password, user directory or user-management page;
- customer Chat, customer identity, handoff monitoring or customer memory;
- approval queues, approve/deny commands or an approval workflow;
- Kubernetes, multi-host HA or a separate Run Worker microservice;
- arbitrary scripts or shell commands in the Agent process;
- state-changing tools in the initial release;
- a public quick tunnel;
- multi-Agent catalog or legacy workflow compatibility.

A future sandbox may safely execute scripts and commands, but it requires a separate threat model, isolation boundary, resource limits, filesystem/network policy, artifact exchange contract and audit design before implementation.

## Release success criteria

Release is GO only when the immutable `initial-private-pilot-v1` profile has all 13 required Gates passed and bound to the same candidate. At minimum this includes code quality, distribution, supply chain, identity/authorization, secrets/egress, deterministic and real-LLM evaluation, dependency compatibility, capacity/latency, queue/progress, resilience/recovery, deployment and browser/operations evidence.

The target operating envelope is 20 online operators, five active runs and 50 queued requests. Admission is subsecond, first progress and free-slot dispatch target one second, ordinary governed answers target 60-second P95, and the hard attempt deadline is 120 seconds.

## Delivery sequence

S0 V3-only baseline → S1 PostgreSQL → S2 OIDC/permissions/secrets/egress and S3 S3 artifacts → S4 queue/Executor/SSE → S5 sole production Agent → S6 deployment, recovery and pilot Gate.
