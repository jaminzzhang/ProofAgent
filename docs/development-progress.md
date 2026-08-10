# Development Progress

Updated: 2026-08-10

## Current decision

[KNOWN | HIGH] The Hybrid Knowledge happy path is code-complete and deployment-executable from PDF upload through controlled production Agent publication. S6 foundations now include compatibility binding, image/Compose definitions, deep API/Worker readiness, PostgreSQL-fenced Worker role leases, an explicit locked expand-only migration job, provider-neutral Blue/Green choreography, atomic multi-surface nginx switching, a first built-in `docker-compose-v1` operations driver, and a finalized Release Registry with authenticated exact bundle downloads. Formal production release remains **NO-GO**: no immutable candidate image has been built or scanned here, the driver has not run against disposable or real Docker/nginx infrastructure, no real release bundle has been finalized/downloaded, the workspace has no real private parser/embedding/reranker/answer-model/evaluator execution, S6 operational evidence is incomplete, and none of the 13 candidate-bound release Gates has a formal passing Evidence result.

[FRAME | HIGH] ADR 0153 formally defers runtime Case Memory from the initial private pilot. The production Agent remains memory-disabled and PostgreSQL conversation context remains non-evidence. Existing Case Memory contracts, schema and repositories are dormant infrastructure, not an advertised release capability.

## 2026-08-10 AI-assisted metadata review

- [KNOWN | HIGH] Hybrid parser output may now include one Profile-shaped AI Document Default alongside exact Rule Unit proposals. The parser pipeline binds the suggestion to server-owned document lineage and Review V2 collapses Rule Units whose proposals match the default, leaving only genuine differences or incomplete values as override work.
- [KNOWN | HIGH] A replacement revision now supersedes prior current Review Sets and Review rows for the same stable document in the same PostgreSQL transaction that stores the new Review Set. Prior review payloads and decisions remain retained history but no longer inflate current Dashboard counts or publication blockers.
- [KNOWN | HIGH] The Documents workspace now exposes the existing governed replacement-revision command for each completed candidate document, using a bounded PDF file chooser, exact Source revision, idempotency and durable operation polling. This gives operators an explicit way to rerun changed parsing/review behavior without creating a duplicate stable document.
- [KNOWN | HIGH] Dashboard labels the immutable parser baseline as an AI suggestion, announces the number of suggestions ready for confirmation, and requires the existing reasoned `Confirm & approve` action. The AI path does not gain review permission, approve metadata, or bypass exact review identity and Source revision checks.
- [KNOWN | HIGH] The production-local model plane exercises the contract with a reference-Profile-valid default, while a missing or malformed private-service proposal remains governed `needs_input`/review-required work rather than automatic authority. Real production metadata quality still depends on the separately deployed private model adapter and an authorized non-reference Profile.

## 2026-08-08 Metadata Review and Workbook V2 core implementation

- [KNOWN | HIGH] Hybrid build completion now atomically materializes one Profile-bound Metadata Review V2 set covering the Document Default and complete canonical Rule Unit inventory. Missing parser metadata becomes operator-owned `needs_input` work instead of a technical build failure; Save, Approve and Reject use exact review identity/version CAS.
- [KNOWN | HIGH] Metadata Workbook V2 is a server-generated, five-sheet, one-use asynchronous workflow: Generate Export → Download → upload edited XLSX → safe Preview → reasoned Apply. The returned Workbook is checked for package ambiguity/traversal, expansion limits, forbidden members, formulas, defined names, sheet/column/identity drift, locked-field changes, registered validation ranges and Profile values before a bounded report or three-way merge is persisted.
- [KNOWN | HIGH] PostgreSQL migrations `0020_metadata_review_v2` and `0021_metadata_workbook_v2` add the Review/Profile and Workbook Export/Preview/Apply authorities plus fenced jobs. Generate and Preview admission do not mutate Source revision; Apply commits the exact Preview and Review Set atomically, advances Source revision once, and invalidates unconsumed prepared publications and preparation jobs in the same transaction.
- [KNOWN | HIGH] The provider-neutral API and Dashboard switched directly to V2. The old metadata-import endpoint and production V1 Workbook Worker composition are absent. Reviews remain the primary structured workflow; the optional Workbook panel exposes Generate, Download, Return, safe validation/conflict Preview and Apply only when exact identity, readiness and reason are present.
- [COMPUTED | HIGH] Local verification on 2026-08-08: the complete backend suite with real test PostgreSQL passed **3151** tests with **1** environment-dependent skip and **13** opt-in tests deselected; the changed Workbook/Review/Pipeline slice passed **113/113** after type-boundary cleanup. Dashboard passed **219/219** and its production build. Ruff passed for `proof_agent` and `tests`; mypy passed over **425** product sources; domain-context checks and `git diff --check` passed. A generated Workbook was imported, inspected and rendered through the bundled spreadsheet artifact runtime: all five sheets rendered, no formulas were present, and the formula-error scan matched zero cells.
- [KNOWN | HIGH] This is implementation and local integration evidence, not a production cutover or formal GO. LibreOffice round-trip evidence, explicit V1 lineage/data migration rehearsal with verified backup restoration, real production Profile provisioning, retained-object expiry execution, private-service execution and the maintenance-window acceptance/forward-repair runbook remain release work.

## 2026-08-05 Dashboard Knowledge operation outcome visibility

- [KNOWN | HIGH] Dashboard publication preparation, publication commit and metadata-workbook import now require the polled durable operation to end in `succeeded` before showing success or loading success-only projections. Failed and cancelled terminal outcomes retain their stable `outcome_code` plus safe `outcome_detail` in the operator-visible error banner.
- [KNOWN | HIGH] Knowledge workspace load errors and mutation errors now have separate state, so a Source reload or tab-projection refresh cannot erase a terminal operation failure after briefly rendering it. Starting a new mutation also clears any stale success notice.
- [COMPUTED | HIGH] The regression reproduces the real reload race and passed with all 215 Dashboard tests; workspace typecheck and Dashboard/Operator Chat production builds passed. The retained local production stack was rebuilt on image `a2c2053b0fda`, and browser verification kept `publication_metadata_review_required: Publication preparation could not be completed.` visible after the worker advanced `ks_insurance` to revision 16.

## 2026-07-28 Hybrid document rejection visibility

- [KNOWN | HIGH] Expected `PA_HYBRID_INTAKE_*` PDF preflight rejections are now returned by the Knowledge Source API as sanitized HTTP 422 Problem Details instead of falling through to a generic HTTP 500. The public problem code is normalized to the existing lowercase API schema while Dashboard presents the stable uppercase intake code to operators.
- [KNOWN | HIGH] Dashboard document intake now renders each rejected file's safe reason and reports a failed batch as failure rather than showing the previous unconditional success banner. Temporary paths, exception internals, private-service endpoints and remediation text are not exposed.
- [KNOWN | HIGH] Hybrid preflight no longer charges embedded font programs against the 2 MiB per-page decoded drawing/content budget. Distinct font streams now share a bounded 32 MiB document-level decoded budget and remain guarded by a 64x expansion limit with 256 KiB slack; shared fonts are charged once. This admits ordinary multi-megabyte Chinese font resources without permitting the existing page-content or high-expansion font bomb fixtures.
- [COMPUTED | HIGH] The related backend slice passed 91 tests, Dashboard passed 213 tests, the focused eight-test Source detail suite and Dashboard production build passed, and Ruff passed for the changed Python slice. After the font-budget correction, the retained `production-local` application roles were rolled to image `4918cdc16ea96cf715e389bcf20e09bac2db294edf4a933ef5088c91143407ac`; runtime verification passed TLS Gateway, Dashboard, OIDC, six private-model compatibility routes, OpenSearch, PostgreSQL schema/security state and S3 versioning. API `/readyz` remains HTTP 503 solely because `published_agent` is intentionally not ready.
- [COMPUTED | HIGH] The large-font regression was red before the budget separation and green afterwards; the complete Hybrid intake, worker and multipart API slice passed 128 tests, including retained page-content and font-expansion bomb negatives. Ruff and mypy passed for the changed intake slice.
- [KNOWN | HIGH] The original rejected PDF bytes were removed by the pre-persistence cleanup path and no durable operation, ingestion job or S3 object was created. Its surfaced code and detail prove that the old combined decoded-resource budget was exhausted, but only another upload can distinguish a now-admitted embedded-font case from a page whose actual drawing/content stream still exceeds the unchanged 2 MiB safety limit.

## 2026-07-27 unified Hybrid Knowledge Source V1

- [KNOWN | HIGH] Dashboard and API now use one provider-neutral `/api/config/knowledge-sources` V1 contract. PostgreSQL is Source authority, versioned S3 holds exact artifacts, OpenSearch is a rebuildable projection, and the separately deployed Private Knowledge Model Serving Plane supplies scheduler/Docling/PaddleOCR/embedding/reranker capabilities. Browser payloads contain no private-service endpoints, credentials, model digests or S3 authority.
- [KNOWN | HIGH] Configuration, Ingestion, Operations, Workspace/Review, Publication Preparation and Publication Commit are focused application services behind the one router. Source reads are cursor bounded with server aggregates; mutations require named permissions, exact revisions or review identities, durable idempotency and safe Problem Details. `knowledge_source.review` is independent from publish permission.
- [KNOWN | HIGH] PDF and exact-revision workbook intake stream multipart bytes into bounded durable operations. Knowledge Worker claims persist attempt history, cancellation/retry and replay state. Publication preparation performs private-model, S3 and OpenSearch work asynchronously; the final Source publication path performs only freshness/idempotency/permission checks and a short PostgreSQL CAS.
- [KNOWN | HIGH] Dashboard exposes the accepted seven-tab Source workspace—Overview, Documents, Reviews, Versions & Publish, Operations, Provider & Health and Audit—using server action capabilities rather than provider-name inference. The closed-loop UI test covers exact review CAS and Prepare → poll → Publish, and asserts the flow stops before Agent activation.
- [KNOWN | HIGH] Dashboard Agent Knowledge configuration recognizes published `hybrid_index` Sources, optionally pins `retrieval_profile_revision_id` through the existing strict binding contract, and shows the resolved provider/profile facts on bound-Source cards. Leaving the field empty preserves server-side default resolution during Agent validation; Dashboard still does not accept private service endpoints, credentials, OpenSearch settings or Agent activation authority.
- [KNOWN | HIGH] The deployable file-backed Knowledge Hub fallback, mode-specific Knowledge routes/DTOs, JSON/Base64 document/workbook and batch endpoints, the old production Knowledge router, Dashboard legacy clients/panels and compatibility tests have been deleted. Package-local Markdown remains an Agent Package capability and is independent of the shared Source authority.
- [KNOWN | HIGH] A one-shot Development Hub migrator verifies an operator backup byte-for-byte before reading it, dry-runs without target mutation, re-admits validated PDF originals through V1 intake, never imports cached indexes, preserves safe remote configuration only as unpublished/unverified state, rejects literal secrets and emits atomic JSON/TXT manifests. This disposable environment had no legacy Source tree, so the operator dry-run was explicitly not applicable; seven focused migration tests cover its behavior.
- [KNOWN | HIGH] The Alembic graph now preserves the released `0011_model_credential` identity and adopts its existing credential table before advancing through the current expand-only head. The local production migration job uses the same locked, explicit-target contract as the production slot definition; a real retained PostgreSQL authority advanced from historical `0011_model_credential` through `0019_ingestion_operation_link` without stamping or rollback.
- [COMPUTED | HIGH] Local verification on 2026-07-27: the default backend suite passed **3113** tests with **1** unrelated skip and **13** opt-in Hybrid tests deselected while PostgreSQL tests were configured fail-on-missing. The real disposable PostgreSQL 17/MinIO/OpenSearch 3.1 Hybrid suite passed **13/13** in 142.44 seconds. Dashboard passed **212/212**, Operator Chat **35/35**, workspace typecheck and both production builds passed; Ruff passed and mypy passed over **416** product sources. A real PG/S3 e2e exposed and fixed FrozenDict evidence serialization at the PostgreSQL JSON boundary; its focused repository regression and isolated Run Queue e2e are green.
- [COMPUTED | HIGH] The retained `production-local` stack was rebuilt and cut over to image `871f13546e8506b5ea0bafa51046a29abe0474c6609e2e870b8f1594a0623857`. API/Dashboard and model-plane are healthy; Knowledge Worker and Run Executor are running on the same image; TLS Gateway, Dashboard SPA, OIDC, six private-model compatibility routes, OpenSearch, PostgreSQL/security state and S3 versioning passed the runtime verifier. `/readyz` remains HTTP 503 solely because the sole production Agent has not been published, which is the intended fail-closed state. The generated `Local Harness` compatibility fixture is startup-test input only and is not formal release Evidence.
- [KNOWN | HIGH] This is local implementation and disposable-data-plane evidence, not a production GO. No inactive blue-green candidate slot was deployed, no real private Docling/PaddleOCR/embedding/reranker service or production OIDC/Vault environment was exercised, and no candidate-bound Gate Evidence was produced.

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
- [KNOWN | HIGH] `0013_release_registry` adds an immutable two-state Release Registry. A conditional transaction binds one candidate and exact Release Gate Manifest, then finalizes exactly once with the Bundle Index, detached attestation and trust identity. The `audit.export`-guarded endpoint verifies Ed25519-bound Index bytes and exact PostgreSQL/S3 object versions into a read-only cache before serving only Index-authorized members with byte-range, attachment, no-store and audit behavior. Dashboard `/releases` exposes no S3 location. No real candidate finalization or download evidence is claimed.
- [COMPUTED | HIGH] Local verification on 2026-07-25: a disposable PostgreSQL 17.5 service was started on loopback and the fail-on-missing `PROOF_AGENT_TEST_POSTGRES_DSN` configuration was enabled. All 65 PostgreSQL-only integration tests passed instead of skipping; this exposed and corrected stale Run Executor test setup so deployment-role and Attempt leases are exercised independently. The complete backend suite with that DSN passed 3115 tests with 1 remaining skip and 13 opt-in Hybrid tests deselected. Dashboard/Operator Chat passed 221/35 tests and both production builds; both production Compose files passed `docker compose config`; Ruff passed, mypy passed over 381 product sources, the lock file was current, domain checks passed and `git diff --check` passed. Operator Chat still reports a 600.22 kB minified chunk warning. No real versioned S3 bundle was finalized or downloaded, and Dockerfile/Nginx container checks plus a real driver rehearsal were not executed; signature/digest authorization, Docker/nginx command ordering, atomic restoration and rollback were verified through local tests and fakes rather than production infrastructure.

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
| S6 deployment/operations | partial: Tasks 1–7 implemented, including Blue/Green driver and Release Registry/download; real execution evidence missing | S2–S5 | build/scan exact image; rehearse Blue/Green and security bootstrap; finalize/download a real bundle; add alerts, runbooks and pilot |

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
