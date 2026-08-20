# Domain Knowledge Index

This file routes implementation work to the authoritative domain records. It is
not a second glossary.

## Primary maps

- `CONTEXT-MAP.md` — bounded contexts and ownership boundaries.
- `docs/domain/knowledge-evidence/CONTEXT.md` — Knowledge & Evidence language,
  invariants, and ownership.
- `docs/domain/knowledge-evidence/decisions.md` — decision index for this domain.
- `docs/domain/workflow-control/CONTEXT.md` — workflow and Control Plane
  authority.
- `docs/domain/tools-models-memory/CONTEXT.md` — external capability boundaries.

## Knowledge Source Service design authority

- `docs/superpowers/specs/2026-08-11-knowledge-source-service-design.md` — accepted
  target design.
- `docs/superpowers/plans/2026-08-11-knowledge-source-service.md` — delivery
  sequence, not implementation status.
- `docs/adr/0192-separate-knowledge-source-service-from-agent-evidence-admission.md`
  through `docs/adr/0207-deploy-one-knowledge-service-with-isolated-process-roles.md`
  — accepted service boundary and runtime decisions.
- `docs/adr/0210-make-kss-the-only-executable-knowledge-authority.md` — current
  execution authority. It supersedes executable Hybrid, package-local and shared
  knowledge binding paths in ProofAgent.

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
