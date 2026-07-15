# Development Progress

Updated: 2026-07-15

## Current decision

[KNOWN | HIGH] The Hybrid Knowledge happy path is now deployment-executable from PDF upload through exact Phase F evidence registration and Agent publication. Formal production release remains **NO-GO** until the real private-model/evaluator environment executes Phase F successfully and the remaining platform-wide S1–S6 work and all 13 release Gates are complete.

## 2026-07-15 Hybrid Knowledge closed loop

- [KNOWN | HIGH] API/worker production composition now connects quarantined PDF ingestion to private Docling/Paddle parsing and versioned S3 artifacts.
- [KNOWN | HIGH] Candidate assembly requires ready documents and approved metadata, freezes the business-approved visibility scope, and publishes through PostgreSQL fencing, exact S3 manifests, real Embedding, OpenSearch read-back/smoke retrieval and an immutable projection attestation.
- [KNOWN | HIGH] Published Agent execution reconstructs its frozen historical Source publication from PostgreSQL and exact S3 versions, verifies generation/index UUID/manifest/attestation authority, then executes governed BM25+dense+RRF+reranker retrieval and citation-bound answering.
- [KNOWN | HIGH] Phase F commands produce Shadow, Capacity, Acceptance and Recovery results; the sealing command uploads four distinct exact S3 references, and release registration independently verifies those references before Agent publication.
- [KNOWN | HIGH] Production schema installation is explicit through `proof-agent hybrid-migrate`; the idempotent DDL upgrades the historical schema, including durable publication smoke queries.
- [KNOWN | HIGH] The deployment procedure is documented in `docs/deployment/hybrid-knowledge-closed-loop.md`.

[COMPUTED | HIGH] Current branch verification: Ruff passed; mypy passed over 256 source files; the default backend suite passed 2768 tests with 1 skipped and 10 opt-in tests deselected; the disposable PostgreSQL/MinIO/OpenSearch suite passed 8 publication, historical-DDL, generation-rebuild, frozen-binding and 1000+ restoration tests; the Phase F capacity/recovery suite passed 2 tests covering five runs and four injected fault classes.

[KNOWN | HIGH] No real private Docling/Paddle/Embedding/Reranker or independent evaluator endpoints and credentials were supplied in this workspace, so their deployment-specific execution evidence has not been fabricated. They remain mandatory before a formal GO decision.

## Completed S0 work

- fixed root frontend build/typecheck contracts;
- added strict candidate, evidence and Gate contracts plus fail-closed verifier/CLI;
- moved retained V3 helpers into the Controlled ReAct Control Plane;
- made `react_enterprise_qa_v3` the only active workflow template;
- removed the legacy `proof_agent/runtime/` package and LangGraph/LangChain dependencies;
- removed customer and approval product routes/pages;
- removed legacy examples and retained only `agent_management_insurance_specialist`;
- disabled package-local executable tools in the canonical Agent;
- removed the public quick-tunnel path from local verification;
- migrated stage context and Business Flow Skill Pack routing to V3.

## Integrated Hybrid Knowledge work

- Live Shadow v2 executes legacy and candidate bindings through trusted drivers and rejects suite-carried observations or pointer snapshots.
- Sealed Acceptance verifies independently produced aggregate attestations, evaluator and key identity, signature, and exact candidate/suite/Gate Profile binding.
- `KnowledgeReleaseRecord` freezes the exact Contract Bundle, Resolved Hybrid Knowledge Bindings, and distinct Shadow, Capacity, Acceptance and Recovery artifact references into a Published Agent Version.
- Release registration fails closed without an independent Release Evidence Authority; production evaluation and operations use pinned private-network adapters.
- The external asset manifest enforces a 300-case tuning suite, 200-case tuner-hidden acceptance suite, 30/50/20 query mix and a separate 100-to-200-case parser benchmark.
- [KNOWN | HIGH] Before integration with `main`, the Hybrid track passed 2662 backend tests with 1 skipped and 8 opt-in tests deselected, plus Ruff and mypy over 257 source files. The current verification supersedes these historical counts.

This work does not change the formal production **NO-GO** decision: the S1-S6 platform and 13 candidate-bound release Gates remain required.

## Verification evidence

On 2026-07-12:

- backend: 1615 passed, 1 skipped, 8 socket-bound tests deselected, 2 Pydantic serializer warnings;
- Dashboard: 204/204 tests passed and production build succeeded;
- Operator Chat: 39/39 tests passed and production build succeeded;
- Ruff passed;
- initial production inventory guards: 8/8 passed.

The eight deselected tests require loopback socket binding, which the current execution sandbox denies. They remain mandatory in CI/host verification. Dashboard tests also emit two React `act(...)` warnings; Chat build reports a 597.73 kB minified chunk warning.

## Remaining dependency-ordered work

| Slice | Status | Depends on | Exit condition |
| --- | --- | --- | --- |
| S1 PostgreSQL authority | partial: Hybrid authority complete | S0 | complete the remaining platform-wide migrations, repositories, concurrency and real-PG tests |
| S2 OIDC/permissions/secrets/egress | not started | S1 | OIDC-only seven-day session, CSRF, permission negatives, recovery group, secret handles, default-deny egress |
| S3 S3 artifacts/recovery | partial: Hybrid exact artifacts and recovery complete | S1 | complete platform-wide S3-first visibility, GC/TTL/materialization/restore operations |
| S4 queue/Executor/SSE | not started | S2 + S3 | 5/50 bounds, idempotency, lease/fencing, cancellation and reconnect tests |
| S5 sole production Agent | partial: frozen Hybrid runtime path complete | S3 + S4 | bind the sole production candidate and pass deterministic and real-LLM evaluation |
| S6 deployment/operations | not started | S2–S5 | hardened image, Blue/Green, readiness, recovery, runbooks, release registry and pilot |

Do not start the formal release Gate until S6 is complete. The fail-closed verifier must return GO against one immutable candidate binding; green local tests alone are insufficient.
