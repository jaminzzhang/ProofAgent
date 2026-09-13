# Proof Agent Documentation

## Active sources of truth

Read in this order:

1. `../README.md` — current product boundary and commands;
2. `prd.md` — initial-release requirements and non-goals;
3. `technical-design.md` — active architecture and production target;
4. `developer-guide.md` — authoring, local operation and verification;
5. `operations-deployment-development-guide.zh-CN.md` — Chinese newcomer runbook for local operation, deployment boundaries, development and incident triage;
6. `development-progress.md` — implemented versus remaining work;
7. `features/external-knowledge/configuration.md` — active Dify/Agentset bindings and production limitations;
8. `deployment/local-production-docker.md` — local production-shaped Docker stack and verification;
9. `../CONTEXT-MAP.md` — domain vocabulary routing.

The sole example guide is `examples/agent-management-insurance-specialist.md`.

## Business-task verification

- [业务任务验证用例模板](testing/business-task-verification-template.zh-CN.md) — 从真实业务问题设计验收、正反例、多轮场景与结果证据；用于后续业务任务验证。
- [项目核心目标与设计验收](../AGENTS-COMMON.md#product-goals-and-design-acceptance) — 设计、开发与评审的共享目标来源。

## Initial-production planning

- `superpowers/specs/2026-07-11-proofagent-initial-production-release-closure-design.md` — approved closure design;
- `superpowers/plans/2026-07-11-proofagent-s0-v3-baseline-plan.md` — S0 implementation plan;
- `../reports/proofagent-release-readiness-2026-07-12.html` — current readiness and dependency-ordered Todo report.

## Architecture maintenance

- [2026-09-08 architecture review and cleanup](features/architecture-simplification/verification.md) — dependency direction, retired Customer code and local verification.
- [2026-09-08 test applicability cleanup](features/architecture-simplification/test-cleanup.md) — retired tests, integration markers, CI smoke and remaining coverage gaps.

## Historical records

Files under `adr/`, `superpowers/specs/`, `superpowers/plans/` and older concept/example documents are historical records. They may describe customer service, approval workflows, LangGraph compatibility, old Agents or other removed/deferred capabilities. Do not treat them as active product support unless an active source above explicitly says so.

When behavior changes, update the active sources in the same change. Do not rewrite accepted ADR history merely to make it look current.
