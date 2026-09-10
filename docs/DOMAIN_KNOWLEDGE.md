# Domain Knowledge Index

This file routes implementation work to the authoritative domain records. It is
not a second glossary.

## Primary maps

- `docs/adr/0254-preserve-model-contract-failure-diagnostics.md` and
  `docs/features/agent-kernel-quality/tdd-stage-capture-failures.md` — failed intent
  capture, safe contract diagnostics and answer-failure outcome semantics.
- `docs/adr/0253-configure-agent-clarification-level.md` and
  `docs/features/agent-kernel-quality/tdd-clarification-policy.md` — Agent clarification
  levels, bounded missing-field classification, non-evidence scope assumptions and local acceptance.

- `docs/features/agent-kernel-quality/scope-p1-p2.md` and `tdd-p1-p2.md` — bounded task state, read-only tool completion, local business-action fencing, Skill runtime narrowing and measurement; ADR-0245 through ADR-0248 define their authority boundaries.

- `CONTEXT-MAP.md` — bounded contexts and ownership boundaries.
- `docs/domain/knowledge-evidence/CONTEXT.md` — Knowledge & Evidence language,
  invariants, and ownership.
- `docs/domain/knowledge-evidence/decisions.md` — decision index for this domain.
- `docs/domain/workflow-control/CONTEXT.md` — workflow and Control Plane
  authority.
- `docs/adr/0241-gate-final-answers-on-required-retrieval-evidence.md` — frozen
  required queries, bound retrieval proofs, finalization and recovery constraints;
  P0-2 acceptance is in `docs/features/agent-kernel-quality/tdd-p0-2.md`.
- `docs/domain/tools-models-memory/CONTEXT.md` — external capability boundaries.
- `docs/domain/evaluation/CONTEXT.md` and `docs/domain/evaluation/decisions.md` — evaluation targets,
  governed resolution, verified quality and release evidence boundaries;
  `docs/adr/0240-separate-verified-quality-from-governed-resolution.md` records P0-1B.

## Active external Knowledge boundary

- `docs/adr/0244-validate-bounded-answer-facts-before-admission.md` defines
  cited-evidence numeric/explicit-assertion consistency and the existing one-repair boundary.
  P0-4 scope and limits: `docs/features/agent-kernel-quality/scope-p0-4.md`;
  acceptance: `docs/features/agent-kernel-quality/tdd-p0-4.md`.

- `docs/adr/0243-preserve-typed-external-evidence-through-answer-input.md` defines
  typed records, explicit Dify content format, source identity and answer projection.
  P0-3 acceptance: `docs/features/agent-kernel-quality/tdd-p0-3.md`.

- `docs/adr/0242-replace-kss-runtime-coupling-with-external-knowledge.md` supersedes
  the KSS-only execution and default deployment assumptions below.
- `docs/features/external-knowledge/configuration.md` describes Dify and Agentset configuration,
  candidate admission, mutable observations and production limits.
- `docs/features/external-knowledge/scope-plan.md` and `verification.md` route acceptance.

## Historical Knowledge Source Service design authority

The following KSS records explain historical contracts and evidence. They do not
require or authorize KSS in the current runtime; ADR-0242 takes precedence.


- `docs/superpowers/specs/2026-08-11-knowledge-source-service-design.md` — accepted
  target design.
- `docs/superpowers/plans/2026-08-11-knowledge-source-service.md` — delivery
  sequence, not implementation status.
- `docs/adr/0192-separate-knowledge-source-service-from-agent-evidence-admission.md`
  through `docs/adr/0207-deploy-one-knowledge-service-with-isolated-process-roles.md`
  — accepted service boundary and runtime decisions.
- `docs/adr/0210-make-kss-the-only-executable-knowledge-authority.md` — historical
  execution authority. It supersedes executable Hybrid, package-local and shared
  knowledge binding paths in ProofAgent.
- `docs/adr/0234-revalidate-exact-kss-release-before-agent-version-rollback.md` —
  historical Agent Version rollback Release-state preflight and failure boundary.
- `docs/adr/0235-bind-agent-version-rollback-to-the-confirmed-active-pointer.md` —
  caller-confirmed Active pointer and rollback concurrency boundary.
- `docs/adr/0236-gate-production-agent-version-rollback-at-composition.md` —
  default-closed Production rollback HTTP and capability admission boundary.
- `docs/adr/0237-rehearse-production-agent-rollback-with-isolated-real-dependencies.md` —
  isolated real KSS/PostgreSQL rollback rehearsal and Production boundary.
- `docs/adr/0238-probe-the-deployed-production-agent-rollback-gate-while-closed.md` —
  production-local TLS/OIDC/CSRF gate-closed probe and credential boundary.
- `docs/adr/0239-extract-kss-into-an-independently-released-project.md` — physical
  project, source/build ownership and external-artifact integration boundary.

## High-risk implementation scenes

- `[FRAME | HIGH]` A Knowledge Query is bound to exactly one Knowledge Space and
  one immutable Knowledge Base Release; runtime `latest` resolution is invalid.
- `[FRAME | HIGH]` One Knowledge Space may serve multiple Agents, but V1 never
  crosses organization or Space boundaries during a query.
- `[FRAME | HIGH]` Candidate Evidence is retrieval output, not admitted evidence
  and not a truth decision.
- `[FRAME | HIGH]` Structured results retain typed semantics and do not enter
  relevance-rank fusion.
- `[FRAME | HIGH]` Agentic retrieval is explicit and bounded; it cannot call
  external tools, expand access, admit evidence, or answer for ProofAgent.
- `[FRAME | HIGH]` Base Versions are immutable and Knowledge Base Releases become
  visible atomically.
- `[FRAME | HIGH]` A knowledge-enabled Published Agent Version has exactly one
  exact KSS binding; unavailable KSS, grant, secret or Admission Scorer fails
  closed, with no local provider fallback.
- `[FRAME | HIGH]` Old Hybrid-bound Published Agent Versions are historical
  records only and are not valid replay or rollback targets after ADR-0210.

When implementation exposes an unrecorded domain decision, update the owning
context or add an ADR before encoding the choice in code.

- `docs/adr/0249-support-provider-specific-external-knowledge-bindings.md` and
  `docs/features/external-knowledge/agentset-verification.md` cover mixed provider contracts and local acceptance.
