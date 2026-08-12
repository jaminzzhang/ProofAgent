# Project Context

## Current implementation facts

- `[KNOWN | HIGH]` The active Python product package is `proof_agent`; its main
  runtime composition enters through `proof_agent/bootstrap/composition.py`.
- `[KNOWN | HIGH]` The independent Knowledge Source Service lives under
  `services/knowledge-source-service/`; its public query resource is
  `/v1/knowledge-queries`, and its API, Query Executor, Knowledge Worker,
  Synchronization Scheduler, and migration roles have independent entry points.
- `[KNOWN | HIGH]` ProofAgent integrates through the provider-neutral
  `KnowledgeCandidateService` port and
  `proof_agent/capabilities/knowledge/source_service_client.py`. The production
  path fails closed and does not use the local Hybrid provider as an exception
  fallback.
- `[KNOWN | HIGH]` `AGENTS-COMMON.md` requires PostgreSQL authority for mutable
  production state, S3-compatible immutable artifacts, and fail-closed
  production composition.
- `[KNOWN | HIGH]` Local acceptance on 2026-08-12 covers strict contracts,
  heterogeneous intake, immutable Source/Release authority, real
  PostgreSQL/MinIO/OpenSearch retrieval, bounded Agentic retrieval, durable
  synchronization, ProofAgent integration, and an independently built non-root
  OCI image. This is local verification, not production approval.

The existing Graphify map was queried on 2026-08-11 to locate the composition,
knowledge-resolution, provider, retrieval, and local-index seams. It was not
rebuilt, so code remains the authority for implementation decisions.

## Feature index

| Feature ID | Status | Evidence directory | Governing design |
| --- | --- | --- | --- |
| `knowledge-source-service` | `VERIFIED_LOCAL` | `docs/features/knowledge-source-service/` | `docs/superpowers/specs/2026-08-11-knowledge-source-service-design.md` |
| `production-agent-lifecycle` | `PARTIAL_VERIFICATION` | `docs/features/production-agent-lifecycle/` | ADR-0124 and `docs/superpowers/plans/2026-07-11-proofagent-s5-sole-agent-migration-plan.md` |

## Status vocabulary

- `SCOPING`: behavior or authority remains undecided.
- `TDD_INPUT_READY`: scope and acceptance evidence are sufficient to start RED.
- `IMPLEMENTING`: at least one TDD slice is active, but feature acceptance is not
  complete.
- `PARTIAL_VERIFICATION`: implementation and default local checks pass, but one or
  more named P1 environment-backed checks remain unexecuted; this is not production
  approval.
- `VERIFIED_LOCAL`: recorded local acceptance checks pass; this is not deployment
  evidence.
- `BLOCKED`: a named dependency or decision prevents meaningful progress.
