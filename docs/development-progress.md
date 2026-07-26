# Development Progress

Updated: 2026-07-26

## Current decision

[KNOWN | HIGH] The Hybrid Knowledge happy path is code-complete and deployment-executable from PDF upload through controlled production Agent publication. S6 foundations now include compatibility binding, image/Compose definitions, deep API/Worker readiness, PostgreSQL-fenced Worker role leases, an explicit locked expand-only migration job, provider-neutral Blue/Green choreography, atomic multi-surface nginx switching and a first built-in `docker-compose-v1` operations driver. Formal production release remains **NO-GO**: no immutable candidate image has been built or scanned here, the driver has not run against disposable or real Docker/nginx infrastructure, the workspace has no real private parser/embedding/reranker/answer-model/evaluator execution, S6 operational evidence is incomplete, and none of the 13 candidate-bound release Gates has a formal passing Evidence result.

[FRAME | HIGH] ADR 0153 formally defers runtime Case Memory from the initial private pilot. The production Agent remains memory-disabled and PostgreSQL conversation context remains non-evidence. Existing Case Memory contracts, schema and repositories are dormant infrastructure, not an advertised release capability.

## 2026-07-26 production Model Connection management

- [KNOWN | HIGH] Production now exposes an independent `/api/config/model-connections` delivery slice instead of falling through to Dashboard `StaticFiles`. OIDC named permissions, CSRF middleware, PostgreSQL optimistic revisions, same-transaction audit, Secret Provider protocol checks and trace-safe projections remain mandatory.
- [KNOWN | HIGH] Production create/update accepts only opaque `ProductionSecretHandle` values with purpose `model_credential`; the existing development path continues to use environment-variable references. Runtime model resolution now carries the handle into the guarded OpenAI-compatible provider path without resolving or tracing secret material.
- [KNOWN | HIGH] PostgreSQL reference projection counts exact shared-model occurrences in Draft Agents and Knowledge Sources plus immutable Published Agent Version references. High-impact changes require explicit review when references exist; physical deletion remains blocked by retained audit.
- [KNOWN | HIGH] Dashboard Models list and detail surfaces select Env versus Secret Handle inputs from API capability/response shape and send current production revisions for update, archive and restore.
- [COMPUTED | HIGH] Local verification on 2026-07-26: the complete backend suite with the test-only PostgreSQL DSN passed 3126 tests with 1 skip and 13 opt-in Hybrid tests deselected; Dashboard passed 224 tests and its production build; mypy passed over 382 product sources; the changed Python slice passed Ruff.
- [KNOWN | HIGH] The currently running `production-local` Docker stack is sourced from another worktree and was not rebuilt from these changes. No real Vault lifecycle or provider request was executed, so browser/runtime deployment proof and release Gate evidence remain pending.

## 2026-07-25 initial S6 implementation

- [KNOWN | HIGH] The strict Deployment Compatibility Manifest now requires exact PostgreSQL, S3, OIDC, Secret Provider, Gateway and model identities, immutable revisions, a credential-free native PostgreSQL authority or exact HTTPS origins, component capability evidence and at most 72-hour-old content-addressed evidence. `proof-agent deployment validate-compatibility` emits machine JSON and a canonical manifest digest.
- [KNOWN | HIGH] `deploy/production/Dockerfile` builds frontend assets and wheel/sdist in separate stages, installs the production extra non-editably, and runs as UID/GID 10001 without copying the source tree into the runtime stage. `mcp[cli]` moved out of base runtime dependencies into the development extra.
- [KNOWN | HIGH] The checked-in slot topology defines five same-image roles with read-only filesystems, all Linux capabilities dropped, no public slot ports, bounded tmpfs/resources and per-slot external networks. The stable Gateway attaches to blue and green, routes API/OIDC callback/SSE/Dashboard/Operator Chat as one routing generation, and enforces TLS and request limits.
- [KNOWN | HIGH] Production `/readyz` now reports release ID, image digest, slot, role, activation state, schema revision/compatible range and DCM digest without exposing dependency exceptions or secrets. `STANDBY` is a healthy deployment state.
- [KNOWN | HIGH] API `/readyz` now binds candidate identity and verifies exact PostgreSQL schema, OIDC discovery/JWKS, a dedicated Vault probe handle, versioned S3 and a background exact write-read success no older than 60 seconds, active egress policy, sole Published Agent and queue authority. Provider errors are reduced to sanitized component states.
- [KNOWN | HIGH] `run-executor` and the production Knowledge Worker use PostgreSQL-fenced role activation epochs and renewable leases. `STANDBY`/`DRAINING` do not claim new work; lease loss fails Worker readiness, prevents new claims and fences final commits. Both roles expose loopback `/livez` and `/readyz` for Compose health checks.
- [KNOWN | HIGH] `deploy/production/slot/compose.yaml` includes a non-restarting `migration` profile that invokes the candidate image with `database upgrade --locked --expand-only --target <exact-head>`. Production CLI use requires all three acknowledgements; application startup remains migration-free.
- [KNOWN | HIGH] The Blue/Green choreography now records every step against one candidate-binding digest, enforces the 150-second pre-switch drain abort, requires explicit admission pause when N/N-1 queue compatibility fails, promotes only with a higher epoch, runs the fixed 30-minute soak, and performs route-first rollback with candidate drain/fencing and explicit lost-Attempt failure.
- [KNOWN | HIGH] Gateway switching renders all three upstream groups and public slot/generation markers together, validates a same-directory candidate through containerized `nginx -t`, atomically replaces and reloads it, verifies Dashboard/Operator Chat/API/OIDC callback/SSE on one generation, and restores/reloads the old include on mixed observations.
- [KNOWN | HIGH] `scripts/deployment/blue_green.py` is an external shell-free command boundary with bounded subprocess output, Docker-based nginx control and an atomic mode-0600 result journal. Its built-in `docker-compose-v1` driver validates both immutable slots, runs migration/standby/readiness/N/N-1 checks, atomically controls Run admission, drains and promotes PostgreSQL-fenced Workers, executes stable-origin OIDC/submission/SSE/terminal/S3 smoke, soaks and performs route-first rollback. Other environments can still supply one trusted entry point. No real deployment rehearsal is claimed.
- [COMPUTED | HIGH] Local verification on 2026-07-25: 3032 backend tests passed with 64 skipped and 13 opt-in tests deselected; the focused changed deployment/Worker slice passed 33 tests with 3 real-PostgreSQL tests skipped. Dashboard/Operator Chat passed 218/35 tests and both production builds; both production Compose files passed `docker compose config`; Ruff passed, mypy passed over 376 product sources and separately over all 3 deployment scripts, the lock file was current, domain checks passed and `git diff --check` passed. The three Worker-role PostgreSQL concurrency tests are among the skips because no real test DSN was configured. Operator Chat still reports a 600.22 kB minified chunk warning. Dockerfile/Nginx container checks and a real driver rehearsal were not executed; Docker/nginx command ordering, atomic restoration and rollback were verified through fakes, not a running container.

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
| S5 sole production Agent | contract narrowed; external evidence pending | S3 + S4 | run real-LLM/Phase F against private services and publish the exact candidate |
| S6 deployment/operations | partial: Tasks 1–5 plus Task 6 choreography, atomic Gateway and first Compose driver; real execution evidence missing | S2–S5 | build/scan exact image; review and rehearse Blue/Green driver, security bootstrap, Release Registry/download, alerts, runbooks and pilot |

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
