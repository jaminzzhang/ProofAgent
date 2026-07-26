# Development Progress

Updated: 2026-07-26

## Current decision

[KNOWN | HIGH] The Hybrid Knowledge happy path is now code-complete and deployment-executable from PDF upload through controlled production Agent publication. Formal production release remains **NO-GO**: the workspace has no real private parser/embedding/reranker/answer-model/evaluator execution, S5 still lacks PostgreSQL Case Memory integration, S6 deployment/operations is incomplete, and none of the 13 candidate-bound release Gates has a formal passing Evidence result.

## 2026-07-15 Hybrid Knowledge closed loop

- [KNOWN | HIGH] API/worker production composition now connects quarantined PDF ingestion to private Docling/Paddle parsing and versioned S3 artifacts.
- [KNOWN | HIGH] Candidate assembly requires ready documents and approved metadata, freezes the business-approved visibility scope, and publishes through PostgreSQL fencing, exact S3 manifests, real Embedding, OpenSearch read-back/smoke retrieval and an immutable projection attestation.
- [KNOWN | HIGH] Published Agent execution reconstructs its frozen historical Source publication from PostgreSQL and exact S3 versions, verifies generation/index UUID/manifest/attestation authority, then executes governed BM25+dense+RRF+reranker retrieval and citation-bound answering.
- [KNOWN | HIGH] Phase F commands produce Shadow, Capacity, Acceptance and Recovery results; the sealing command uploads four distinct exact S3 references, and release registration independently verifies those references before Agent publication.
- [KNOWN | HIGH] `production-publish-agent` independently verifies the Phase F record, runs the exact online Hybrid path, retains trace/receipt as exact S3 versions, requires a cited answer, and activates the immutable Agent Version with an active-pointer CAS. Concurrent stale candidates cannot overwrite the winner.
- [KNOWN | HIGH] `deploy/production/agent_management_insurance_specialist/` is a separately validated production candidate package: one required shared Hybrid binding, three roles referencing `model_production_primary`, no inline model credentials, no package-local Knowledge, no local tools and no non-authoritative runtime memory. The production Model Connection stores its API key as authenticated PostgreSQL ciphertext under a separately mounted versioned keyring. The deterministic `examples/` package remains development-only.
- [KNOWN | HIGH] Production schema installation is explicit through `proof-agent hybrid-migrate`; the idempotent DDL upgrades the historical schema, including durable publication smoke queries.
- [KNOWN | HIGH] The deployment procedure is documented in `docs/deployment/hybrid-knowledge-closed-loop.md`.

[COMPUTED | HIGH] Current branch verification on 2026-07-15: Ruff passed for `proof_agent` and `tests`; mypy passed over 363 source files; the final default backend suite passed 2936 tests with 1 skipped and 74 external-integration tests deselected; 41 real PostgreSQL/S3 tests passed; all 11 disposable PostgreSQL/MinIO/OpenSearch Hybrid tests passed, including repeat-run-safe publication, historical DDL, generation rebuild, frozen binding, 1000+ restoration, capacity and four-class recovery injection; frontend production builds passed and Dashboard/Chat passed 218/35 tests.

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

This work does not change the formal production **NO-GO** decision: implemented code and local integration tests are prerequisites, not candidate-bound Gate Evidence.

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
| S1 PostgreSQL authority | implementation complete; candidate evidence pending | S0 | run exact-version production compatibility and migration evidence against the bound candidate |
| S2 OIDC/permissions/secrets/egress | core implementation complete; reference-service exercises pending | S1 | real OIDC/Vault, Recovery Group, revoke/rotate and negative browser evidence |
| S3 S3 artifacts/recovery | core implementation complete; timed combined restore pending | S1 | candidate S3 compatibility, PITR + exact-version restore, RPO/RTO exercise |
| S4 queue/Executor/SSE | core implementation complete; load/deployment evidence pending | S2 + S3 | bound 5/50 load, coarse reconnect and N/N-1 deployment execution |
| S5 sole production Agent | partial | S3 + S4 | wire PostgreSQL Case Memory or formally narrow the contract; run real-LLM/Phase F and publish the candidate |
| S6 deployment/operations | not complete | S2–S5 | hardened image, stable Gateway, Blue/Green jobs, security bootstrap, Release Registry/download, alerts, runbooks and pilot |

## Formal 13-Gate inventory

[KNOWN | HIGH] The immutable profile and fail-closed verifier exist and are heavily unit-tested, but Gate producers, candidate binding, immutable image evidence and operational rehearsals are not complete. Therefore every formal Gate remains `not_run`, not `passed`.

| Gate | Formal status | Principal missing Evidence |
| --- | --- | --- |
| backend_frontend_quality | not_run | clean candidate install, coverage ≥90%, domain check and bound build/test result |
| distribution_image | not_run | wheel/sdist clean install and immutable hardened image readiness smoke |
| supply_chain_runtime_security | not_run | SBOM/provenance/scans with zero High/Critical findings |
| identity_authorization | not_run | real OIDC, freshness/revocation, permission negatives and Recovery Group exercise |
| secrets_egress | not_run | real Vault rotate/revoke plus exact-origin/DNS/redirect denial evidence |
| deterministic_evaluation | not_run | exact production Agent deterministic suite with zero required skips |
| real_llm_evaluation | not_run | exact candidate real-model success/refusal/clarification/failure/budget suite |
| dependency_compatibility | not_run | completed Deployment Compatibility Manifest for every concrete dependency |
| capacity_responsiveness | not_run | 20/5/50 envelope, 30-minute load and four-hour soak |
| queue_progress | not_run | candidate queue/cancel/lease/reconnect evidence from deployment topology |
| resilience_recovery | not_run | fault matrix, timed combined PG/S3 restore and RPO/RTO proof |
| deployment | not_run | expand-contract, standby, drain, atomic switch, smoke and rollback |
| browser_operations | not_run | OIDC browser flow, accessibility, audit export, alerts/runbooks and one-day pilot |

Do not compute a formal release decision until S6/S7A/S8A are frozen. The fail-closed verifier must return `GO` against one immutable candidate binding; green local tests alone are insufficient.
