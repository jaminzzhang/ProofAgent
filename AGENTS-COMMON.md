# Proof Agent Coding-Agent Guide

Read this file before repository-specific entry points such as `AGENTS.md`.

## Reasoning and claims

Act as a senior engineer, security reviewer and product skeptic. Do not agree merely because a user proposes a solution. Check repository evidence, identify tradeoffs and say when a requested design would weaken the Control Envelope.

For substantive architecture, security, readiness and status claims, prefix the claim with one source tag and one confidence tag:

- source: `KNOWN` (direct repository/runtime evidence), `COMPUTED` (derived from evidence), `INFERRED` (reasoned but not directly proved), `COMMON` (stable engineering knowledge), `FRAME` (approved design/decision), `GUESS` (weak hypothesis);
- confidence: `HIGH`, `MED`, `LOW`.

Example: `[KNOWN | HIGH] The active workflow registry exposes only react_enterprise_qa_v3.`

State uncertainty and missing evidence. Cite repository paths, commands, tests, commits or dated design records close to the claim. Never present a plan as implemented or a green local test suite as production release proof.

## Active product boundary

- only `react_enterprise_qa_v3` is active;
- only `examples/agent_management_insurance_specialist/` is public;
- only Dashboard and Operator Chat (`/operator`) are active browser surfaces;
- no customer Chat/handoff product and no approval workflow;
- no local accounts, passwords, user directory or user-management page;
- production identity target is OIDC-only with a seven-day backend session and server-side permissions;
- no active `proof_agent/runtime/` compatibility package;
- no package-local Python handlers, MCP stdio tools or state-changing production tools;
- arbitrary scripts/commands belong only in a future separately isolated sandbox.

Historical ADRs and dated specs may describe removed capabilities. Active truth is README, `docs/prd.md`, `docs/technical-design.md`, `docs/developer-guide.md` and `docs/development-progress.md`.

## Architecture invariants

- Control Plane owns workflow, policy, evidence admission, validation and outcome mapping.
- Models, knowledge, memory and tools are capabilities behind provider-neutral ports.
- The model proposes; it never grants itself permission or executes a capability directly.
- Memory and conversation context are not Accepted Evidence.
- Tools enter only through Tool Gateway; initial-production tools are read-only, published, schema-bounded and server-authorized.
- Trace is the execution fact log; Governance Receipt is a projection.
- Audit/read models do not become execution authority.
- Third-party SDK objects and secrets do not leak into public contracts or trace.
- Raw chain-of-thought is never stored or returned.
- Configuration may reference environment variable names or secret handles, never secret values.

## Production boundary

S0 local files are development adapters. Production requires:

- PostgreSQL authority for mutable state and queue/coordination;
- OIDC-only sessions, CSRF and permission mappings;
- secret handles and default-deny egress;
- S3-compatible immutable artifacts with S3-first verification and one PostgreSQL visibility transaction;
- a bounded PostgreSQL queue and same-image Run Executor role;
- coarse SSE progress with durable current-state reconnect;
- hardened Compose/Blue-Green deployment and all 13 release Gates.

Do not add filesystem or local-identity fallbacks in production mode. Dependency failure must fail closed.

## Repository layout

```text
proof_agent/contracts/       provider-neutral contracts
proof_agent/bootstrap/       config and composition
proof_agent/control/         workflow, policy, knowledge and validators
proof_agent/capabilities/    concrete adapters
proof_agent/delivery/        CLI and APIs
proof_agent/observability/   trace, receipt, stores and read APIs
proof_agent/release/         release contracts and verifier
dashboard/                   operator configuration/observation UI
chat/                        Operator Chat UI
examples/agent_management_insurance_specialist/
tests/                       backend tests
docs/                        active docs plus historical records
```

## Commands

Install:

```bash
uv sync --extra dev --extra dashboard
npm install
```

Canonical smoke run:

```bash
uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "住院理赔需要准备哪些材料？"
```

Local services:

```bash
uv run --extra dev --extra dashboard proof-agent dev
uv run --extra dev --extra dashboard proof-agent verify-remote
```

`verify-remote` is local-only. Dashboard defaults to port 5173, Operator Chat to 5174, API to 8000 and the integrated gateway to 18080.

Full verification:

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

Run the smallest relevant test first while developing, then the full affected suite. Socket-bound HTTP tests must run in an environment that permits loopback binding before release evidence is signed.

## Change rules

- Use test-first changes for behavior and regressions.
- Preserve user changes and unrelated dirty-worktree content.
- Use `rg` for repository searches.
- Update active documentation in the same change as behavior.
- Do not silently retain deprecated config fields; strict contracts should reject them.
- Do not create alternate execution paths in API, frontend, evaluation or observability code.
- Do not weaken deterministic gates because an LLM or human judge is favorable.
- New trace fields require redaction and audience review.
- New storage requires ownership, transaction, concurrency, retention and recovery semantics.
- New network integrations require an explicit allowlist and secret-handle boundary.
- New script/command execution requires the separate sandbox design; never smuggle it through tools or workers.

## Review priorities

Prioritize:

1. authority or trust-boundary bypass;
2. loss of fail-closed behavior;
3. secret, identity, tenant or artifact leakage;
4. concurrency/idempotency/fencing errors;
5. evidence/citation correctness;
6. release binding or freshness errors;
7. product-surface regression and documentation drift.

Report findings with concrete file/line evidence and severity. Distinguish defects from intentional scope decisions and from future work.
