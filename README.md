# Proof Agent

Proof Agent is a Controlled Agent Harness Framework for governed, evidence-backed and auditable enterprise Agent execution.

## Current baseline

The active product baseline is intentionally narrow:

- one workflow: `react_enterprise_qa_v3`;
- one public Agent package: `examples/agent_management_insurance_specialist/`;
- two browser surfaces: Dashboard and Operator Chat (`/operator`);
- no customer Chat, handoff monitor or approval workflow;
- no local account/password/user-management system;
- production identity target: OIDC-only, with a seven-day login session and server-side permissions;
- no package-local Python tool handlers, MCP stdio tools or state-changing tools in the initial release;
- future script/command execution belongs in a separately designed sandbox, not in the current Agent runtime.

The deterministic provider remains available for offline development and regression. It is not evidence that the production deployment, identity, PostgreSQL, S3, queue, recovery or real-model gates are complete.

## Quick start

```bash
uv sync --extra dev --extra dashboard
uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "住院理赔需要准备哪些材料？"
```

Start the local API and development services:

```bash
uv run --extra dev --extra dashboard proof-agent dev
```

Start the restartable local verification gateway:

```bash
uv run --extra dev --extra dashboard proof-agent verify-remote
```

Open:

- Dashboard: `http://127.0.0.1:5173`
- Operator Chat: `http://127.0.0.1:5174/operator`
- Local verification gateway: `http://127.0.0.1:18080`

`verify-remote` is local-only. It does not start an unauthenticated public tunnel.

## Architecture

```text
CLI / API / Dashboard / Operator Chat
                 |
                 v
       Bootstrap + composition
                 |
                 v
 Controlled ReAct V3 Control Plane
 workflow -> policy -> retrieval/tool ports -> validators
                 |
                 v
 models / knowledge / memory / read-only MCP adapters
                 |
                 v
 trace -> receipt -> RunStore -> read projections
```

Key boundaries:

- `proof_agent/contracts/`: frozen provider-neutral contracts;
- `proof_agent/bootstrap/`: manifest loading and dependency composition;
- `proof_agent/control/`: V3 orchestration, policy, evidence admission and validators;
- `proof_agent/capabilities/`: model, knowledge, memory and governed tool adapters;
- `proof_agent/delivery/`: CLI and application APIs;
- `proof_agent/observability/`: trace, receipt, RunStore and read APIs;
- `proof_agent/release/`: immutable release contracts and fail-closed release verifier.

There is no active `proof_agent/runtime/` compatibility package. LangGraph and LangChain are not production dependencies.

## Initial-production closure

S0 establishes the strict V3-only source baseline and release-gate contracts. Formal release still requires the dependent slices below:

1. S1 — focused store ports, migrations and PostgreSQL authority;
2. S2 — OIDC-only sessions, Dashboard permission mapping, CSRF, secret handles and default-deny egress;
3. S3 — S3-compatible artifact storage, S3-first finalization, verified materialization, retention and recovery;
4. S4 — bounded PostgreSQL async queue inside Proof Agent, same-image Run Executor, cancellation and coarse SSE progress;
5. S5 — production publication of the sole Agent with production knowledge, memory and optional validated read-only HTTPS tools;
6. S6 — hardened image/Compose topology, Blue/Green deployment, readiness, runbooks, release registry and pilot gates.

The authoritative closure design is `docs/superpowers/specs/2026-07-11-proofagent-initial-production-release-closure-design.md`. The current readiness report is under `reports/`.

## Verification

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

Some HTTP transport and gateway tests open loopback sockets. In a filesystem-only sandbox they can fail with `PermissionError`; run them in CI or a host environment that permits local socket binding before a release Gate is signed.

## Documentation

Start with `docs/README.md`. Active product truth lives in README, PRD, technical design, developer guide and development progress. ADRs and dated specifications are historical decision records and may describe removed or deferred surfaces.
