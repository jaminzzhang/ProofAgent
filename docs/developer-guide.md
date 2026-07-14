# Proof Agent Developer Guide

## 1. Setup

Requirements: Python 3.12+, `uv`, Node.js and npm.

```bash
uv sync --extra dev --extra dashboard
npm install
```

Run the canonical Agent offline:

```bash
uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "住院理赔需要准备哪些材料？"
```

The package uses deterministic planner, reviewer and answer providers. It requires no API key.

## 2. Supported package

`examples/agent_management_insurance_specialist/` is the only public package. Its main files are:

```text
agent.yaml          V3 Agent Contract
policy.yaml         deterministic policy rules
knowledge/          package-local development knowledge
skills/             governed Business Flow Skill Packs
```

The only workflow is:

```yaml
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3

react:
  max_plan_rounds: 4
  max_tool_calls: 0
```

Do not add `workflow.runtime`, `workflow.checkpointer`, `react.max_steps`, legacy template IDs, package-local Python handlers or stdio tools. The canonical package has `capabilities.tools.enabled: false`.

## 3. Local services

```bash
uv run --extra dev --extra dashboard proof-agent dev
```

Frontend development:

```bash
npm run dev -w proof-agent-dashboard
npm run dev -w proof-agent-chat
```

Open Dashboard on `http://127.0.0.1:5173` and Operator Chat on `http://127.0.0.1:5174/operator`.

For a restartable integrated local session:

```bash
uv run --extra dev --extra dashboard proof-agent verify-remote
```

The gateway is local-only at `http://127.0.0.1:18080`. It does not create a public tunnel.

## 4. Authoring rules

- Contracts are strict and provider-neutral.
- Configuration may name environment variables but must not contain secret values.
- Workflow stage prompts are Business Context Addenda, not control instructions.
- Business Flow Skill Packs may narrow routing; they never grant tool or data authority.
- Memory is context, never Accepted Evidence.
- Model output is untrusted until deterministic validators admit it.
- Trace stores safe summaries, never raw chain-of-thought, credentials or unrestricted payloads.

When adding a model or knowledge adapter, keep SDK objects inside `capabilities/` and return Proof Agent contracts. When adding an execution entry, route it through the same bootstrap, Control Plane, policy, validators, trace and receipt path.

## 5. Tools and future sandbox

The initial production baseline has no approval workflow and no state-changing tools. A production read-only tool must have a frozen contract, bounded parameters, server-resolved permission context, schema-validated/redacted output and an allowlisted HTTPS destination.

Do not execute arbitrary scripts or commands in API, Executor, Knowledge Worker or Agent processes. The planned sandbox must be separately isolated with resource limits, read-only inputs, bounded writable workspace, default-deny network, timeouts, output quotas, immutable job definition and complete audit. Until that design is approved and implemented, script/command execution is out of scope.

## 6. Production adapter boundary

S0 uses local development stores. Do not describe them as production-safe. Production implementation must add:

- PostgreSQL repositories and migrations;
- OIDC-only seven-day sessions and permission mapping;
- CSRF, secret handles and default-deny egress;
- S3-compatible immutable artifacts and verified materialization;
- bounded PostgreSQL queue, same-image Run Executor and coarse SSE progress;
- hardened Compose/Blue-Green deployment and recovery procedures.

S3-first finalization intentionally accepts losing uncommitted partial progress: write and verify S3 objects/manifest first, then make them visible in one PostgreSQL transaction.

## 7. Hybrid Knowledge release evidence

Hybrid Knowledge publication is fail closed. A Published Agent Version with a Hybrid binding must reference a registered `KnowledgeReleaseRecord` that binds the exact Contract Bundle and Resolved Hybrid Knowledge Bindings to four distinct immutable artifacts: live Shadow, Capacity, Sealed Acceptance and Recovery. Registration also requires an independently configured Release Evidence Authority.

Production evaluation and operations adapters use the `private-http` entry point over an allowlisted HTTPS origin and pinned private-network resolution. Configure the driver selectors and verifier separately:

```bash
export PA_KNOWLEDGE_SHADOW_DRIVER=private-http
export PA_KNOWLEDGE_CAPACITY_DRIVER=private-http
export PA_KNOWLEDGE_RECOVERY_DRIVER=private-http
export PA_KNOWLEDGE_ACCEPTANCE_DRIVER=private-http
export PA_KNOWLEDGE_ACCEPTANCE_VERIFIER=hmac-sha256
export PA_KNOWLEDGE_OPERATIONS_PROVIDER=private-http
export PA_KNOWLEDGE_RELEASE_AUTHORITY=private-http
```

Do not place observations or active-pointer snapshots in Shadow suite files. The trusted driver executes both pinned bindings live. Sealed Acceptance accepts only independently attested aggregate facts bound to the exact candidate, suite and Gate Profile.

## 8. Release verification

Run the full local suite:

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

Release manifests are checked with:

```bash
proof-agent release verify \
  --manifest /path/to/release-gate-manifest.json \
  --evidence-root /path/to/immutable/evidence \
  --at 2026-07-12T10:00:00Z
```

Exit codes: 0 GO, 1 valid NO-GO, 2 invalid input. Never hand-edit a result to GO; regenerate evidence for the exact candidate.

## 9. Documentation discipline

Update README, PRD, technical design, developer guide and progress when active behavior changes. Keep ADRs and dated specs historical. Label proposed production behavior as planned until executable tests prove it.
