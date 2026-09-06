# Proof Agent Developer Guide

> [KNOWN | HIGH] 2026-09-06：ADR-0242 覆盖本文历史 KSS-only 运行与默认部署描述。
> 当前知识库采用外部 provider 绑定，首接 Dify，继续由 ProofAgent 执行证据准入与任务完成校验。
> 配置、能力限制与验收见 [外部知识库配置](features/external-knowledge/configuration.md)。
> KSS 专属正式发布证据不复用；外部知识库生产发布 profile 尚待独立验证。


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

Run the offline kernel quality baseline separately from the formal evaluation campaign:

```bash
uv run --extra dev python scripts/check-agent-kernel-baseline.py \
  --output-dir /tmp/proofagent-kernel-baseline
```

[KNOWN | HIGH] This command drives the existing Control Plane with fixed synthetic
model and Dify HTTP boundaries. It checks numeric validation, compound retrieval coverage,
intent rewrites, admitted structured facts in answer input, and 30-turn constraint
retention. It reads no environment files and needs no service credentials. Exit `0`
means all five local probes passed; `1` means a capability gap, invalid observation or
source change was detected; `2` means the measurement infrastructure failed. Inspect
`kernel_baseline.md` and `kernel_baseline.json` in the output directory. The report is
diagnostic evidence, not answer accuracy, formal campaign readiness or Production GO.
Current results and slice acceptance are in
`docs/features/agent-kernel-quality/tdd-p0-4.md`; the original measurement record is
`docs/features/agent-kernel-quality/tdd-report.md`.

[KNOWN | HIGH] Final-answer validation includes bounded numeric and explicit-assertion
consistency against cited Accepted Evidence. Keep source subjects, conditions, negations
and units; for typed fields use `record_id field is value unit`, one fact per sentence.
Only standalone quantity tokens are normalized; typed non-numeric values are literal.
Correct free paraphrases may be conservatively rejected; unrecognized language is
counted as unassessed. One policy-governed repair rechecks every validator; remaining
failure refuses delivery. Scope and limits: ADR-0244 and
`docs/features/agent-kernel-quality/scope-p0-4.md`.

[KNOWN | HIGH] Controlled ReAct now freezes the first validated intent and gates
finalization on its `required=true` retrieval queries. Query identity trims only
outer whitespace and deduplicates exact matches. Completion needs same-run,
digest-bound retrieval truth with the actual executed query and Accepted Evidence
whose nonblank source/citation references are available in the answer context.
Counts, model completion claims and tool success cannot satisfy this gate.

Premature final or duplicate/unrelated retrieval proposals advance to an unattempted
required query through the existing Review, Policy and KSS binding path. Failed
queries stay incomplete while other requirements continue; no remaining progress
or an exhausted observation budget produces a stable refusal. If the last allowed
observation completes the required set, final answer generation is permitted.
Explicit refusal/clarification and unresolved business/retrieval subgoals still
block finalization. A denied tool is never executed; governed alternative retrieval
may still answer. Resume validates original proof before any new observation,
without changing snapshot fields or re-running Intent Resolution.

Applicable runs emit `task_completion_evaluated` with `stage_id=plan` and
`retrieval-task-completion.v1` payloads. The final plan stage includes the same
coverage projection for answers, refusals, clarification and policy/scope denial.
Payloads contain stable reasons, requirement hashes, counts and bound truth refs;
they contain no new raw query or answer content. Calls without required queries
retain the original event sequence and report `not_applicable`. Approval-wait
snapshots retain their existing format; pre-pause progress is in plan events.
Coverage is necessary for finalization, not semantic answer or business-task
verification. ADR-0241 and `tdd-p0-2.md` define the exact local acceptance boundary.

[KNOWN | HIGH] The existing Evaluation Analyzer now also writes
`evaluation_quality.json` (`evaluation-quality-report.v1`), with typed metrics
(`evaluation-quality.v1`), case/scenario quality reasons and explicit cohort
membership. The same results appear in `evaluation_report.md`,
`evaluation_analysis_receipt.md`, and existing case JSONL rows. An optional
`quality_target` on a suite case accepts `answer_correctness`,
`refusal_appropriateness`, or `task_completion`. Task classification is explicit;
legacy answer/refusal labels must have consistent expected resolution/outcome.
Unknown case or expected-assertion fields and contradictory explicit labels fail
validation. Correct misspellings instead of relying on ignored configuration.

Only required standalone cases enter the three quality denominators. Missing or
unverified artifacts remain `not_evaluated`; unclassified required cases have a
separate count. `verified_success_rate` is passed / total and
`assessment_coverage_rate` is (passed + failed) / total; empty rates are null.
When unmeasured cases exist, this is not an accuracy estimate. In this version,
answer semantics and task completion have no positive verifier. Refusal success
only means the curated refusal decision matched, with verified complete artifacts,
passing required Gates and no pending semantic assertions. GRR, Gate Profiles,
Release Decision and `judge_mode=none` retain their governance meaning.

Artifact parsing and observed hashes share one byte snapshot. Missing or malformed
per-case artifacts fail that governance case while the rest of the analysis
continues; raw read errors are not copied to reports. Historical results without
quality fields stay unmeasured. Reproducible inputs and the complete acceptance
record are in `docs/features/agent-kernel-quality/tdd-p0-1b.md`.

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
- Configuration may name environment variables or carry a configured encrypted model
  credential marker, but must not contain secret values. Production model API keys
  are authenticated ciphertext in a separate PostgreSQL table whose keyring is
  deployment-owned and external to PostgreSQL.
- Workflow stage prompts are Business Context Addenda, not control instructions.
- Business Flow Skill Packs may narrow routing; they never grant tool or data authority.
- Memory is context, never Accepted Evidence.
- Runtime Case Memory is disabled for the initial private pilot; do not enable it in the production Agent manifest without a separately approved, candidate-bound memory release slice.
- Model output is untrusted until deterministic validators admit it.
- Trace stores safe summaries, never raw chain-of-thought, credentials or unrestricted payloads.

When adding a model or knowledge adapter, keep SDK objects inside `capabilities/` and return Proof Agent contracts. When adding an execution entry, route it through the same bootstrap, Control Plane, policy, validators, trace and receipt path.

## 5. Tools and future sandbox

The initial production baseline has no approval workflow and no state-changing tools. A production read-only tool must have a frozen contract, bounded parameters, server-resolved permission context, schema-validated/redacted output and an allowlisted HTTPS destination.

Do not execute arbitrary scripts or commands in API, Executor, Knowledge Worker or Agent processes. The planned sandbox must be separately isolated with resource limits, read-only inputs, bounded writable workspace, default-deny network, timeouts, output quotas, immutable job definition and complete audit. Until that design is approved and implemented, script/command execution is out of scope.

## 6. Production adapter boundary

S0 uses local development stores. Do not describe them as production-safe. The production code now includes:

- PostgreSQL repositories and migrations;
- OIDC-only seven-day sessions and permission mapping;
- CSRF, encrypted PostgreSQL model credentials with an external keyring, Secret
  Handles for other credentials, and default-deny egress;
- S3-compatible immutable artifacts and verified materialization;
- bounded PostgreSQL queue, same-image Run Executor and coarse SSE progress;
- PostgreSQL conversation context; runtime Case Memory remains deliberately disabled for the initial pilot;
- strict Deployment Compatibility Manifest validation;
- a non-editable multi-stage image definition, immutable static server, stable Gateway and hardened Blue/Green slot definitions;
- candidate identity and sanitized dependency status in `/readyz`.

The definitions are not a completed release. PostgreSQL schema, OIDC discovery/JWKS, Secret Provider and recent S3 write-read API probes plus a locked expand-only migration job are implemented. Worker roles use PostgreSQL activation epochs, renewable ownership leases, explicit drain/release, claim fencing and loopback readiness endpoints; `STANDBY`/`DRAINING` do not claim new work. Candidate image build and scan, Blue/Green controller choreography, recovery exercises, Release Registry/download, telemetry, alerts, runbooks and all candidate-bound Gates remain required.

S3-first finalization intentionally accepts losing uncommitted partial progress: write and verify S3 objects/manifest first, then make them visible in one PostgreSQL transaction.

## 7. KSS-only knowledge authority

A knowledge-enabled Published Agent Version freezes exactly one KSS binding: exact
Space, exact Release, client identity, versioned secret reference and ProofAgent
Admission Scorer identity/revision. Package-local, shared-source and Hybrid bindings
are rejected. KSS returns Candidate Evidence; ProofAgent alone performs Admission and
answer governance. Missing KSS, grant, secret or scorer fails closed with no local
fallback.

The former ProofAgent Hybrid provider, source API, ingestion/publication worker,
repository and CLI paths have been removed. KSS's independent Knowledge Worker is
unchanged. Old Hybrid-bound Agent Versions are not replay or rollback targets; see
`docs/deployment/kss-authority-cutover.md`.

[KNOWN | HIGH] KSS implementation, migrations, distribution, internal tests and image
build are owned by a separate project. This repository must not import or package KSS.
For production-local integration, build/review KSS in its own project and pass the exact
external `name@sha256` reference as `KSS_IMAGE`; missing or mutable input is a start
failure, not a reason to restore an embedded implementation.

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
