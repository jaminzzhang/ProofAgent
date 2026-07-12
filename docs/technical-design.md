# Proof Agent Technical Design

> Active architecture authority. Historical ADRs and dated specifications preserve earlier decisions but do not override this baseline.

## 1. Product boundary

Proof Agent is a Controlled Agent Harness Framework. The initial private pilot has one internal operator Agent, one workflow implementation and no approval or customer product surface.

```text
Workflow decides.
Policy permits or denies.
Evidence supports.
Validators admit or block.
Memory stays bounded.
Trace records.
Receipt proves.
```

The initial release does not execute arbitrary scripts, local Python handlers, MCP stdio tools or state-changing tools. A future sandbox is a separate security boundary and is not part of this design.

## 2. Active architecture

```text
Dashboard / Operator Chat / CLI
              |
              v
      Delivery APIs and CLI
              |
              v
 Bootstrap / composition / registries
              |
              v
+--------------------------------------+
| Controlled ReAct V3 Control Plane    |
| intent -> plan -> observe -> answer  |
| policy -> evidence -> validators     |
+--------------------------------------+
              |
              v
 model / knowledge / memory / tool ports
              |
              v
 trace -> receipt -> stores -> projections
```

The only workflow identity is `react_enterprise_qa_v3`. The template identity selects the orchestrator directly. Public manifest fields `workflow.runtime`, `workflow.checkpointer` and `react.max_steps` are rejected. There is no active `proof_agent/runtime/` compatibility package and no LangGraph/LangChain production dependency.

## 3. Module ownership

| Module | Owns |
| --- | --- |
| `contracts/` | strict provider-neutral DTOs and enums |
| `bootstrap/` | config parsing, path validation, secret-looking field rejection, composition |
| `control/workflow/controlled_react/` | V3 run state, action constraints, observations and terminal outcomes |
| `control/policy/` | deterministic enforcement decisions |
| `control/knowledge/` | routing, provider coordination, fusion and evidence admission |
| `control/validators/` | schema, evidence, citation, safety and tool-result admission |
| `capabilities/` | concrete model, knowledge, memory and governed tool adapters |
| `delivery/` | CLI, configuration, execution and conversation APIs |
| `observability/` | trace, receipt, RunStore and read projections |
| `release/` | candidate binding, Gate profile, digest and fail-closed release decision |

SDK objects and raw provider payloads must not leak across these boundaries.

## 4. Controlled ReAct V3

The planner proposes only:

```text
ASK_CLARIFICATION
PLAN_RETRIEVAL
PROPOSE_TOOL_CALL
GENERATE_FINAL_ANSWER
REFUSE
```

The Control Plane validates and executes proposals. Retrieval or a permitted tool produces a committed `ObservationRecord`, after which the planner may replan. Terminal output is admitted only after evidence, policy and validators pass.

`react.max_plan_rounds` bounds planning. `react.max_tool_calls` bounds tool proposals; the canonical Agent sets it to zero and disables tools. Raw chain-of-thought is never stored; only trace-safe reasoning summaries may be recorded.

Business Flow Skill Packs and editable stage prompts can narrow context or improve wording. They cannot change topology, grant permissions, create tools, bypass evidence or override policy.

## 5. Current application surfaces

- Dashboard configures Agents, knowledge, models, tool sources and permission mappings, and reads governed run/evaluation projections.
- Operator Chat at `/operator` starts runs by published Agent ID and uses bounded conversation context.
- Customer routes, customer Chat, handoff routes, approval queue and approve/deny commands are absent.
- `verify-remote` provides a local single-entry verification gateway only.

No browser request may supply trusted actor identity, permission, manifest path, workflow authority or secret value.

## 6. Identity and permissions target

Production authentication is OIDC-only. Proof Agent does not create local accounts, store local passwords or expose user-management pages. A successful OIDC login creates a backend-managed same-origin session valid for seven days.

Authorization maps OIDC group/claim context to fine-grained permissions. The Dashboard directly edits mapping configuration; there is no approval workflow. A deployment-controlled recovery OIDC group retains access to permission-mapping and audit recovery operations. Session, CSRF, freshness/revocation and permission checks are server authority.

This target belongs to S2 and is not yet implemented by the S0 local stores.

## 7. Production state and artifacts

PostgreSQL is the authority for mutable production configuration, sessions, permission mappings, runs, conversations, queue state, memory metadata, audit metadata and coordination. Local JSON/filesystem stores remain development adapters only.

An S3-compatible object store is the authority for immutable trace, receipt, knowledge, validation, evaluation and release artifacts. Finalization is S3-first:

1. write objects under unique immutable keys;
2. verify exact version, length and digest;
3. write and verify a complete artifact manifest;
4. use one PostgreSQL transaction to bind the manifest and make the result visible.

If step 4 is lost, uncommitted objects are orphans and may be collected later. Proof Agent does not implement a recovery Saga for partial progress and never reports a successful governed result without a verified manifest.

## 8. Async execution and SSE

The Run Executor is not a separate product microservice. It is a same-image Proof Agent process role that claims a bounded PostgreSQL queue.

Initial capacity is five active attempts and 50 queued requests. Duplicate submissions use idempotency keys. Leases, attempt numbers, claim tokens and fencing prevent stale workers from committing results. The hard attempt deadline is 120 seconds.

The API responds immediately after admission. Coarse lifecycle progress is delivered through Server-Sent Events (SSE), a one-way HTTP stream from server to browser. Durable current state supports reconnect; fine-grained progress may be best-effort. Browser disconnect does not cancel a run.

This target belongs to S4 and depends on S2 and S3.

## 9. Knowledge, models, tools and memory

- Deterministic and OpenAI-compatible model adapters share provider-neutral contracts.
- Package Markdown supports offline regression. Production knowledge must resolve published, verified S3-backed snapshots.
- Read-only HTTP/MCP tools may be introduced only through frozen contracts, publication validation, server-side authorization, redaction, schema validation and default-deny egress.
- MCP stdio, local handler imports and state-changing tools are not production-admissible.
- Case Memory may provide continuity but is not evidence. Production memory state requires PostgreSQL and retention/deletion controls.

## 10. Audit and release authority

Trace is the execution fact log. Governance Receipt is a human projection. Production completion requires both to be members of a verified artifact manifest.

The immutable release candidate binding pins source commit, clean tree, product version, OCI digest, Python distribution, frontend assets, migrations, sole Agent bundle, evaluation contract, configuration snapshot, Gate profile and dependency compatibility manifest.

The `initial-private-pilot-v1` profile requires 13 Gates. `proof-agent release verify` recomputes digests, binding, freshness, thresholds and status. Missing, stale, mismatched, unknown or non-passed required evidence returns NO-GO.

## 11. Deployment target

Initial production is one hardened Linux host with a stable gateway and Blue/Green application slots. Gateway, API, Run Executor, Knowledge Worker, Dashboard and Operator Chat are separate Compose roles; API and Executor use the same product image.

External PostgreSQL, S3-compatible storage, OIDC, secret provider and model endpoints are deployment bindings. `/readyz` must verify their concrete compatibility, not merely process liveness. Migrations are explicit and backward-compatible across the rollback window.

## 12. Verification policy

Local quality gates:

```bash
uv lock --check
uv run --extra dev python -m pytest tests/ -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
npm run typecheck
npm test
npm run build
python3 scripts/check-domain-contexts.py
git diff --check
```

Formal release additionally requires real PostgreSQL and S3 integration, OIDC/secret-provider contract services, real-model evaluation, capacity/latency, failure injection, restore, Blue/Green, authenticated browser and operator-pilot evidence bound to the same candidate.
