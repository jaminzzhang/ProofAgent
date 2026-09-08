# Proof Agent Technical Design

> [KNOWN | HIGH] 2026-09-06：ADR-0242 覆盖本文历史 KSS-only 运行与默认部署描述。
> 当前知识库采用外部 provider 绑定，首接 Dify，继续由 ProofAgent 执行证据准入与任务完成校验。
> 配置、能力限制与验收见 [外部知识库配置](features/external-knowledge/configuration.md)。
> KSS 专属正式发布证据不复用；外部知识库生产发布 profile 尚待独立验证。


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

[KNOWN | HIGH] `contracts/published_agent.py` owns the resolved `PublishedAgent`
data object shared by Control and Delivery. Registry lookup, materialization and
HTTP projections remain in Delivery. Control and Contracts must not import Delivery;
`tests/test_dependency_layout.py` enforces this direction with an AST import check.
Architecture analysis and cleanup evidence: [2026-09-08 review](features/architecture-simplification/verification.md).

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

No browser request may supply trusted actor identity, permission, manifest path, or
workflow authority. The one secret-input exception is an OIDC/CSRF-protected Model
Connection create/replace command: its API Key is write-only, encrypted before the
transaction commits, and never returned to the browser.

## 6. Identity and permissions target

Production authentication is OIDC-only. Proof Agent does not create local accounts, store local passwords or expose user-management pages. A successful OIDC login creates a backend-managed same-origin session valid for seven days.

Authorization maps OIDC group/claim context to fine-grained permissions. The Dashboard directly edits mapping configuration; there is no approval workflow. A deployment-controlled recovery OIDC group retains access to permission-mapping and audit recovery operations. Session, CSRF, freshness/revocation and permission checks are server authority.

This target belongs to S2 and is not yet implemented by the S0 local stores.

## 7. Production state and artifacts

PostgreSQL is the authority for mutable production configuration, sessions, permission mappings, runs, conversations, queue state, memory metadata, audit metadata and coordination. Local JSON/filesystem stores remain development adapters only.

Production model API keys are stored outside configuration JSON in
`model_connection_credentials` as AES-256-GCM ciphertext bound to connection id and
key version. The deployment mounts the versioned keyring from
`PROOF_AGENT_MODEL_CREDENTIAL_KEYRING_FILE`; the keyring is never stored in
PostgreSQL. Connection, credential envelope and configuration audit mutations share
one transaction. API, Dashboard, trace and audit expose only a configured marker.

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

- Deterministic and OpenAI-compatible model adapters share provider-neutral
  contracts. Production model credentials resolve through `ModelCredentialResolver`
  only at provider-client construction; development environment references do not
  widen that production boundary.
- [KNOWN | HIGH] Dify and Agentset provide read-only Candidate Evidence through
  frozen external bindings and guarded transport. Remote content remains mutable;
  observation hashes bind the evidence actually used. Offline fixtures are regression
  inputs. External Knowledge production publication remains closed pending its own
  profile and verification (ADR-0242, ADR-0249).
- Read-only HTTP/MCP tools may be introduced only through frozen contracts, publication validation, server-side authorization, redaction, schema validation and default-deny egress.
- MCP stdio, local handler imports and state-changing tools are not production-admissible.
- The initial private pilot keeps runtime Case Memory disabled. PostgreSQL conversation context may provide bounded continuity but is not evidence.
- A later Case Memory release must use PostgreSQL authority and define admission, deletion, expiry, audit, sensitive-data and evaluation controls before enabling runtime reads or writes.

## 10. Audit and release authority

Trace is the execution fact log. Governance Receipt is a human projection. Production completion requires both to be members of a verified artifact manifest.

The immutable release candidate binding pins source commit, clean tree, product version, OCI digest, Python distribution, frontend assets, migrations, sole Agent bundle, evaluation contract, configuration snapshot, Gate profile and dependency compatibility manifest.

The `initial-private-pilot-v2` profile requires five top-level risk Gates covering 13 required check families. `proof-agent release verify` recomputes digests, binding, freshness, thresholds and status. Missing, stale, mismatched, unknown or non-passed required evidence returns NO-GO.

### 10.1 External Knowledge boundary

[KNOWN | HIGH] Agent manifests bind provider identity, exact remote Dataset or
Namespace/Tenant, endpoint, versioned credential reference and retrieval settings.
`bootstrap/external_knowledge.py` composes Dify and Agentset adapters behind the
same provider-neutral port. The model cannot select another Dataset or credential.

ProofAgent owns Evidence Admission, required-query completion, conflict handling
and final-answer validation. Provider ranking never grants evidence authority.
Unavailable required retrieval or invalid provenance fails closed; conversation
memory is not Accepted Evidence. See [configuration and limits](features/external-knowledge/configuration.md).

[KNOWN | HIGH] KSS-only publication, release and evaluation contracts are historical
(ADR-0242 supersedes their runtime assumptions). Retained readers and rejection gates
must not reactivate old bindings. Default API, Executor and readiness do not require
KSS; external production publication needs independent profile and verification.
Earlier KSS protocols remain documented in the dated ADRs and cutover records.

## 11. Deployment target

Initial production is one hardened Linux host with a stable gateway and Blue/Green application slots. Gateway, API, Run Executor, Dashboard and Operator Chat are separate ProofAgent Compose roles; API and Executor use the same product image. External Knowledge providers are independently operated dependencies, not ProofAgent process roles.

External PostgreSQL, S3-compatible storage, OIDC, secret provider and model endpoints are deployment bindings. `/readyz` must verify their concrete compatibility, not merely process liveness. Migrations are explicit and backward-compatible across the rollback window.

The readiness projection reports release ID, image digest, deployment slot, process role, activation state, schema revision/compatible range and Deployment Compatibility Manifest digest together with sanitized component status. The API verifies exact PostgreSQL schema compatibility, OIDC discovery/JWKS, a dedicated Secret Provider probe handle, versioned S3 plus a background exact write-read success no older than 60 seconds, active egress policy, the sole Published Agent under the admitted production profile, and the durable run queue. The Run Executor owns a PostgreSQL-fenced role lease with a monotonically increasing activation epoch, background heartbeat, explicit drain/release transitions and loopback `/livez`/`/readyz`; `STANDBY` and `DRAINING` do not claim new work, while in-flight work is fenced from committing after role ownership loss. KSS role readiness and fencing remain service-owned.

Production migration is an explicit, non-restarting Compose profile. The candidate command must acknowledge the advisory lock and expand-only policy and bind the exact packaged schema head; API and worker composition never invokes migration code. Every shipped Alembic revision must be present in the code-owned reviewed expand-only allowlist, while downgrade/contract operations remain unavailable during the rollback window.

The provider-neutral Blue/Green controller records each action against one candidate-binding digest. It validates and migrates before candidate standby, runs bidirectional queue compatibility, drains old claims for at most 150 seconds, switches all Gateway surfaces as one routing generation, then promotes only at a higher Worker activation epoch. Pre-switch failures restore the old epoch without activating the candidate; post-switch failures route back to the ready old API before candidate drain/fencing and higher-epoch old-Worker activation. Nginx configuration is tested as a temporary complete candidate, atomically renamed and reloaded, then verified through both browser surfaces, API, OIDC callback and SSE. Environment-specific Compose, authentication and provider operations remain behind an external deployment-driver entry point and are not part of the Agent runtime image.

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
