# Proof Agent Documentation

## Active sources of truth

Read in this order:

1. `../README.md` — current product boundary and commands;
2. `prd.md` — initial-release requirements and non-goals;
3. `technical-design.md` — active architecture and production target;
4. `developer-guide.md` — authoring, local operation and verification;
5. `development-progress.md` — implemented versus remaining work;
6. `../CONTEXT-MAP.md` — domain vocabulary routing.

The sole example guide is `examples/agent-management-insurance-specialist.md`.

## Initial-production planning

- `superpowers/specs/2026-07-11-proofagent-initial-production-release-closure-design.md` — approved closure design;
- `superpowers/plans/2026-07-11-proofagent-s0-v3-baseline-plan.md` — S0 implementation plan;
- `../reports/proofagent-release-readiness-2026-07-12.html` — current readiness and dependency-ordered Todo report.

## Historical records

Files under `adr/`, `superpowers/specs/`, `superpowers/plans/` and older concept/example documents are historical records. They may describe customer service, approval workflows, LangGraph compatibility, old Agents or other removed/deferred capabilities. Do not treat them as active product support unless an active source above explicitly says so.

When behavior changes, update the active sources in the same change. Do not rewrite accepted ADR history merely to make it look current.
