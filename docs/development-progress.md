# Development Progress

Updated: 2026-08-29

## Current decision

[KNOWN | HIGH] ADR-0210 makes KSS the only executable knowledge authority. A
knowledge-enabled Published Agent Version owns one exact KSS binding and ProofAgent
keeps only the KSS client, exact Admission Scorer client and Control Plane Admission.
The former Hybrid provider, source-management API, ingestion/publication worker,
repositories, CLI and Dashboard paths are deleted. Old Hybrid-bound Agent Versions
cannot replay or roll back. Formal production release remains **NO-GO** until an
approved scorer revision, exact grant and versioned secret, real dependency readiness,
shadow/pilot/recovery evidence and all Product Release Authority Gates pass.

[FRAME | HIGH] ADR 0153 formally defers runtime Case Memory from the initial private pilot. The production Agent remains memory-disabled and PostgreSQL conversation context remains non-evidence. Existing Case Memory contracts, schema and repositories are dormant infrastructure, not an advertised release capability.

## 2026-08-29 controlled Release Preparation cancellation BFF (TDD-04F)

- [KNOWN | HIGH] KSS and ProofAgent now expose a no-body `POST :cancel` command for
  one exact queued/running Preparation. Both require `Idempotency-Key`; the BFF also
  requires `knowledge_source.edit`. The guarded client revalidates exact identity,
  cancelled state and same-resource `Location`; KSS checks path Scope before using
  the existing database-time, operator-scoped cancellation transaction.
- [KNOWN | HIGH] Exact replay returns the original cancelled result with one success
  audit. Rebinding the key to another Preparation returns idempotency conflict; a new
  command against a terminal state is not cancellable. Body input, Scope drift and
  upstream identity/state/Location drift fail closed without exposing private input.
  A real BFF → KSS → PostgreSQL vertical proved queued → cancelled and no additional
  queryable Release, Worker, lease, fence, artifact or secret authority.
- [COMPUTED | HIGH] Focused local and PostgreSQL affected suites passed 238 tests.
  The final full backend passed 2471 tests with 24 existing declared skips and 2
  deselected; 2 explicit Hybrid integrations passed separately. Mypy over 454 product
  files, full Ruff, 9-file formatting, `git diff --check`, TypeScript, Dashboard 225,
  Chat 35 and all frontend builds passed. Canonical KSS OpenAPI is bound to
  `ce34e8b4fbcd16c90201890cb8e466980132aedbbfc0dce35dedec155749ce3a`;
  migration head and dependency locks are unchanged.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-04F, while the feature remains
  `PARTIAL_VERIFICATION`. No expiry BFF, Dashboard command, continuous process role,
  artifact cleanup, ready quarantine, Agent formal publication, deployment,
  production configuration or Production GO was added.

## 2026-08-29 controlled Release Preparation publication BFF (TDD-04E)

- [KNOWN | HIGH] KSS and ProofAgent now expose a no-body `POST :publish` command for
  one exact Preparation. The BFF requires `knowledge_source.edit`; the guarded client
  revalidates exact identity, consumed state and same-resource `Location`; KSS checks
  path Scope before delegating to the existing one-use PostgreSQL publication CAS.
- [KNOWN | HIGH] The command adds no Idempotency-Key or second receipt authority.
  Uncertain response, replay or expiry is recovered by reading the exact Preparation.
  A real BFF → KSS → PostgreSQL vertical proved queued → ready → consumed, an empty
  catalog before publication and exactly one queryable Release afterwards, with no
  Worker, lease, fence, artifact, secret or raw failure field in the browser projection.
- [COMPUTED | HIGH] The fail-if-missing KSS plus ProofAgent KSS/BFF impact set passed
  480 tests with zero skips. The full backend passed 2461 tests with 24 existing
  declared skips and 2 deselected; 2 explicit Hybrid integrations passed separately.
  Mypy over 454 product files, full Ruff, 9-file formatting, domain/diff, root/KSS lock
  checks, TypeScript, Dashboard 225, Chat 35 and all frontend builds passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-04E, while the feature remains
  `PARTIAL_VERIFICATION`. No cancel/expiry BFF, Dashboard command, continuous process
  role, Agent formal publication, deployment, production configuration or Production
  GO was added.

## 2026-08-29 KSS one-shot Release Preparation execution runtime (TDD-04D)

- [KNOWN | HIGH] KSS runtime composition now optionally accepts a distinct
  `BasePreparationExecutionConfiguration` with Worker identity, lease duration and
  candidate TTL. The resulting `base_preparation_executor.run_once()` processes at
  most one durable queued or recoverable running Preparation through the existing
  frozen-plan builder and fenced `ready/failed` transaction. The default API runtime
  leaves this handle disabled, so management requests do not execute background work.
- [KNOWN | HIGH] A real BFF → KSS → PostgreSQL tracer created a queued Preparation
  through the default API runtime, rebuilt a separate execution runtime against the
  same durable authority, and reached ready without creating a queryable Release.
  The BFF current-state projection still omitted Worker, lease/fence and artifact
  fields. Separate core contracts confirmed one call advances at most one queued
  resource and rejects invalid candidate TTL before claim.
- [COMPUTED | HIGH] Preparation core, PostgreSQL lease/fence/recovery and runtime
  composition passed 160 tests. The KSS plus ProofAgent KSS/BFF impact set passed
  460 tests with zero skips. The full backend passed 2449 tests with 24 existing
  declared skips and 2 deselected; 2 explicit Hybrid integrations passed separately.
  Mypy over 454 product files, full Ruff, affected formatting, domain/diff, root/KSS
  lock checks, TypeScript, Dashboard 225, Chat 35 and all frontend builds passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-04D, while the feature remains
  `PARTIAL_VERIFICATION`. No CLI, continuous Preparation process role, batch loop,
  automatic retry, publish/cancel/expiry BFF, Dashboard, deployment, production
  configuration or Production GO was added.

## 2026-08-29 KSS Base Draft → Release Preparation BFF (TDD-04C)

- [KNOWN | HIGH] ProofAgent now exposes same-origin Base Draft save and exact
  revision read, plus exact Draft revision Preparation start and exact current
  status read. Space/Base identity belongs to the path; browser bodies contain only
  `expected_revision + members` or `draft_revision`. Reads require
  `knowledge_source.view`, mutations require `knowledge_source.edit`, and writes
  preserve the exact KSS `Idempotency-Key`. KSS returns `202` for both first start
  and exact replay of the immutable queued admission receipt.
- [KNOWN | HIGH] Browser projections contain exact Draft, Base Version and
  Preparation identity, digests, members, state, safe terminal fields and a
  same-origin link. They exclude KSS credentials, Worker identity, fencing token,
  lease deadline, artifact capability/reference and raw failure detail. The guarded
  client rejects malformed states, unknown fields, Scope/revision/Preparation drift
  and foreign or missing Location. Fixed non-echoing `422` behavior covers invalid
  request input.
- [COMPUTED | HIGH] Focused BFF/client tests passed 36 checks. The focused affected
  set passed 115 checks, including the complete PostgreSQL Preparation contract. A
  real ProofAgent BFF → guarded client → KSS HTTP → PostgreSQL contract saved and
  read exact Draft history, started/replayed/read a queued Preparation and confirmed
  that no Release was created. The complete backend passed 2445 tests with 24
  declared skips and 2 deselected; 2 explicit Hybrid integrations passed separately.
  Ruff, format, Mypy over 454 product files, root/KSS lock checks, domain/diff,
  TypeScript, Dashboard 225, Chat 35 and all frontend builds passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-04C, while the feature remains
  `PARTIAL_VERIFICATION`. There is no Preparation execution process,
  publish/cancel/expiry BFF, Dashboard page, verified terminal-operator delegation,
  deployment or Production GO. A queued Preparation therefore remains visible but
  cannot become a queryable Release through the product chain yet.

## 2026-08-29 KSS Connection Profile → Synchronization BFF (TDD-04B)

- [KNOWN | HIGH] ProofAgent now exposes same-origin Connection Profile create,
  current/exact revision read, revision-CAS revise, validate and publish, plus
  exact-profile synchronization submit and status read. Reads require
  `knowledge_source.view`; mutations require `knowledge_source.edit`. Browser
  commands preserve the exact KSS `Idempotency-Key`; a new synchronization returns
  `202` and an exact replay returns `200`.
- [KNOWN | HIGH] The BFF accepts only strict HTTPS profile configuration and
  versioned Secret Handle references. Profile responses omit endpoint, Handle,
  egress/trust references and KSS credentials. Synchronization responses include
  only exact Scope/task/Profile identities, state, timestamps, materialized Source
  Version, same-origin link and stable failure codes; raw problem detail and trace
  are removed. Invalid request structure returns a fixed safe `422` without input
  echo. The guarded client rejects unknown fields, identity drift, redirects and
  malformed task state.
- [COMPUTED | HIGH] The two focused BFF/client files passed 22 tests. A real
  ProofAgent BFF → guarded client → KSS HTTP → PostgreSQL contract passed. The
  KSS plus ProofAgent affected set passed 440 tests; the complete backend passed
  2429 tests with 24 existing declared skips and 2 deselected, and the 2 explicit
  Hybrid integrations passed separately. Ruff, Mypy over 454 product files,
  affected formatting, root/KSS lock checks, TypeScript, Dashboard 225 tests,
  Chat 35 tests and all frontend builds passed. KSS OpenAPI and migration
  fingerprints remain unchanged.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-04B, while the feature remains
  `PARTIAL_VERIFICATION`. There is no Dashboard Profile page, real Vault/egress/TLS
  reader, managed-profile process cutover, Base Draft/Preparation BFF, deployment
  or Production GO. KSS audit currently records the configured ProofAgent service
  operator; verified terminal-operator delegation/audit correlation remains a P1
  production gap.

## 2026-08-29 KSS lifecycle/reference-summary BFF read (TDD-04A)

- [KNOWN | HIGH] KSS now exposes one authenticated exact
  `GET .../releases/{knowledge_base_release_id}/deletion-eligibility` resource.
  ProofAgent exposes the corresponding same-origin
  `/api/config/knowledge-service/.../deletion-eligibility` BFF resource. Both read
  paths require `knowledge_source.view`; identities without that permission receive
  `403` before KSS assessment is invoked.
- [KNOWN | HIGH] The BFF projection includes exact Release identity, lifecycle
  state, stable blockers, active/deregistered Reference counts, lifecycle times and
  artifact-retention state. It omits the KSS operator credential and endpoint,
  external-resource identity, artifact authority/assessment identity and raw
  upstream problem. The guarded client rejects exact-identity drift and unknown
  secret-bearing fields.
- [KNOWN | HIGH] Production-shaped KSS composition uses
  `PostgresReleaseLifecycleRepository`. No artifact-retention authority was added;
  therefore an otherwise ordinary retired Release returns
  `artifact_retention_unverified` and remains ineligible. Release catalog clients
  and Dashboard types now recognize `queryable`, `deprecated`, `retired` and
  `revoked` without enabling lifecycle commands.
- [COMPUTED | HIGH] Four focused files passed 32 tests. The final KSS plus
  ProofAgent KSS/BFF affected regression passed 427 tests with zero skips against
  isolated PostgreSQL/MinIO/OpenSearch. The full backend passed 2416 tests with 24
  existing declared skips and 2 deselected; the two explicit Hybrid integrations
  passed separately. Ruff, Mypy over 454 product files, affected format, domain,
  diff and both lock checks passed. Dashboard 225 and Chat 35 tests, TypeScript and
  all frontend builds passed. Canonical KSS OpenAPI changed to
  `e75e6d8e677017f22397d91d8d71bcc89b4888ad3f18b5246b997c35bc94b4c5`;
  the migration contract remains unchanged.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. There is no lifecycle or
  Reference command over HTTP/BFF, affected-reference detail or notification,
  Dashboard lifecycle page, production artifact-retention adapter, physical
  deletion, ProofAgent verifier/reconciler/runtime integration, deployment,
  production migration or Production GO.

## 2026-08-29 KSS Release deletion eligibility (TDD-03F)

- [KNOWN | HIGH] `KnowledgeBaseReleaseLifecycleApplication.assess_deletion_eligibility()`
  reads one exact Release identity and returns a secret-free eligibility projection;
  it accepts no operator, idempotency key, caller time, Reference count, retention
  verdict or delete reason.
- [KNOWN | HIGH] Only an ordinary `retired` Release with complete `retired_at`, zero
  active KSS References and an explicit `clear` result from the server-injected
  artifact-retention authority is eligible. Deregistered References remain counted
  history without blocking. Queryable/deprecated Releases remain ordinary lifecycle
  blockers; revoked Releases retain an incident-response blocker and do not call the
  artifact authority.
- [KNOWN | HIGH] PostgreSQL returns state, lifecycle time, active/deregistered counts
  and database `assessed_at` in one read. The assessment writes no state, receipt or
  audit and is not deletion authority; a future physical-delete command must recheck
  atomically and audit independently. No migration or OpenAPI change was made.
- [COMPUTED | HIGH] Memory contracts passed 28 tests and Release PostgreSQL contracts
  passed 34. The KSS plus ProofAgent KSS/BFF affected regression passed 422 tests with
  zero skips against isolated PostgreSQL/MinIO/OpenSearch. The corrected full backend
  run passed 2408 tests with 24 existing declared skips and 2 deselected; the two
  explicit hybrid integrations passed separately. Ruff, Mypy over 454 product files,
  affected formatting, domain-context, diff and both lock checks passed. Dashboard
  225 and Chat 35 tests, typecheck and all frontend builds passed.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. There is no production
  artifact-retention adapter, physical deletion command, incident clearance,
  lifecycle HTTP/BFF/Dashboard, ProofAgent verifier/reconciler/runtime integration,
  deployment, production migration or Production GO.

## 2026-08-29 KSS emergency Release revocation (TDD-03E)

- [KNOWN | HIGH] `KnowledgeBaseReleaseLifecycleApplication.revoke()` accepts one
  exact Release tuple, a bounded `security_incident` or
  `severe_data_integrity_failure` reason, exact
  `fail_closed_without_fallback` confirmation, trusted operator identity and an
  operator-scoped idempotency key. Only `queryable` or `deprecated` may become
  `revoked`; ordinary `retired` and existing `revoked` are terminal.
- [KNOWN | HIGH] Migration `0018` stores database `revoked_at`, bounded reason and
  a permanent revocation command/audit row on the shared lifecycle sequence. The
  transaction locks the Release and active Reference rows, computes the affected
  active count itself, and commits state/result/receipt/audit atomically. Existing
  active or deregistered Reference facts are preserved. Revoked Releases fail
  Catalog query, integrity enumeration, existing Query Grant authorization and new
  Reference registration without fallback.
- [COMPUTED | HIGH] Memory/PostgreSQL/Catalog/Access/distribution focused contracts
  passed 69 tests. The final real-dependency affected set passed 415 tests with zero
  skips against isolated PostgreSQL/MinIO/OpenSearch. The full backend passed 2396
  tests with 24 existing declared skips and 2 deselected; the 2 explicitly selected
  PostgreSQL/S3 integrations passed. Mypy passed 454 product sources; Ruff,
  affected formatting, domain-context, diff and root/KSS lock checks passed.
  Dashboard 225 tests, Chat 35 tests, TypeScript and all three production builds
  passed. OpenAPI and migration fingerprints are recorded in the feature report.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. There is no lifecycle
  HTTP/BFF authorization, affected-reference detail projection or notification,
  ProofAgent runtime/rollback fail-closed integration, physical deletion,
  production migration, deployment or Production GO. The application-only
  operator identity is a trusted delivery seam, not evidence that production role
  wiring exists.

## 2026-08-28 KSS Release Reference deregistration admission (TDD-03D)

- [KNOWN | HIGH] `KnowledgeBaseReleaseReferenceApplication.deregister()` now
  accepts only an exact Reference ID plus trusted authenticated client identity and
  client-scoped idempotency key. Only the Reference owner may proceed. A
  server-injected `ReleaseReferenceDeregistrationVerifier` must prove permanent
  loss of both execution and rollback eligibility; callers cannot report this fact,
  time, counts or TTL themselves.
- [KNOWN | HIGH] Migration `0017` adds durable `active → deregistered` current
  state, trace-safe verifier/verification identities and database `deregistered_at`.
  Registration and deregistration share one client-scoped command ledger and audit
  order. Historical registration receipts remain immutable. External verification
  runs outside the database transaction; the transaction rechecks replay, locks the
  exact Reference, validates owner/proof identity, and commits state, receipt and
  success audit atomically.
- [KNOWN | HIGH] Focused memory/PostgreSQL/Access/distribution contracts passed 58
  tests. KSS plus ProofAgent KSS/BFF affected regression passed 395 tests with zero
  skips against isolated PostgreSQL/MinIO/OpenSearch. Full backend passed 2384 main
  tests with 24 existing declared skips and 2 deselected; 2 explicitly selected
  hybrid integrations also passed. Mypy passed 454 product source files and Ruff
  passed. OpenAPI remained unchanged; migration head is
  `0017_release_reference_deregistration`.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. The injected verifier is a
  seam, not a ProofAgent implementation. There is no ProofAgent proof issuance,
  background reconciler, Reference/lifecycle HTTP/BFF/Dashboard command, emergency
  revocation, physical deletion, production configuration, deployment, production
  migration or Production GO.

## 2026-08-28 KSS ordinary Release retirement admission (TDD-03C)

- [KNOWN | HIGH] `KnowledgeBaseReleaseLifecycleApplication.retire()` now performs
  the application-only `deprecated → retired` transition for an exact
  Space/Base/Release. A trusted immutable `ReleaseRetentionPolicy` is injected by
  server composition; callers cannot report reference counts, time or eligibility.
- [KNOWN | HIGH] Migration `0016` preserves deprecation history and adds database
  `retired_at` plus a permanent retirement receipt/success audit. Retirement holds
  the Release row lock, rejects active KSS references and pre-boundary database
  time, and commits state, policy identity, eligibility time, retirement time and
  audit atomically. Retired Releases are non-queryable in Catalog, integrity work
  and established Query authorization.
- [KNOWN | HIGH] Focused retirement contracts passed 48 tests. KSS plus ProofAgent
  KSS/BFF affected regression passed 399 tests with zero skips. Full backend passed
  2374 main tests plus 2 explicit hybrid tests; Mypy passed 454 product source files,
  and Ruff, targeted format, domain-context, diff and both lock checks passed.
  OpenAPI remained unchanged; migration head is `0016_release_retirement`.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. There is no
  deregistration/reconciler, emergency revocation, physical deletion, lifecycle
  HTTP/BFF/Dashboard command, ProofAgent reference-first activation, production
  retention configuration, deployment, production migration or Production GO.

## 2026-08-28 KSS Release deprecation core (TDD-03B)

- [KNOWN | HIGH] `KnowledgeBaseReleaseLifecycleApplication.deprecate()` now
  performs the one-way application-only `queryable → deprecated` transition for
  an exact Space/Base/Release. It uses a trusted operator identity and
  operator-scoped idempotency key; exact replay returns the original result.
- [KNOWN | HIGH] Migration `0015` adds the `deprecated` state, database-owned
  `deprecated_at`, and a permanent lifecycle command receipt/success audit.
  Registration and deprecation use the same Release row lock. Existing active
  references, Catalog reads, integrity scans and established Query grants remain
  valid; new Reference registration and new Query grants fail closed.
- [KNOWN | HIGH] Tests cover memory contracts, database time and rebuild, eight-way
  replay convergence, registration/deprecation competition, non-deprecatable
  states, audit rollback and `0014 → 0015` migration replay. KSS plus ProofAgent
  KSS/BFF affected regression passed 388 tests with zero skips. Full backend
  regression passed 2363 main tests plus 2 explicit hybrid tests; Mypy passed 454
  source files, Ruff and frontend typecheck/tests/build passed.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. There is no lifecycle
  HTTP/BFF/Dashboard command, ordinary retirement, emergency revocation,
  deregistration/reconciler, ProofAgent reference-first activation, deployment,
  production migration or Production GO.

## 2026-08-28 KSS exact Release Reference registration (TDD-03A)

- [KNOWN | HIGH] `KnowledgeBaseReleaseReferenceApplication.register()` now
  records a trusted authenticated client's immutable `published_agent_version`
  reference to one exact queryable Space/Base/Release. The V1 purpose is
  `execution_or_rollback`; registration itself does not activate the external
  Agent Version.
- [KNOWN | HIGH] Migration `0014` stores the active reference and permanent
  client-scoped command receipt/success audit. PostgreSQL locks the Release row,
  obtains database time and commits all three facts in one transaction. Exact
  same-key replay returns the original reference; a different fingerprint,
  missing/retired/scope-mismatched Release or immutable-resource rebind fails
  closed.
- [KNOWN | HIGH] Tests cover in-memory contracts, database rebuild, eight-way
  same-key concurrency, retired rejection, audit failure rollback and `0013 →
  0014` upgrade/replay. The full KSS plus ProofAgent KSS/BFF affected suite passed
  375 tests with zero skips. The post-slice backend regression passed 2356 main
  tests plus 2 explicitly selected hybrid integration tests; Mypy passed 454
  source files, and Ruff, domain-context, diff and both lock checks passed.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. There is no reference
  HTTP/BFF, deregistration/reconciler, Release deprecation/retirement/revocation,
  ProofAgent reference-first publication/activation, deployment, production
  migration or Production GO.

## 2026-08-28 KSS cooperative Preparation cancellation (TDD-02G)

- [KNOWN | HIGH] `KnowledgeBasePreparationApplication.cancel()` now accepts one
  exact Preparation identity, trusted operator identity and operator-scoped
  idempotency key. Migration `0013` adds durable `cancelled_at`, extends the
  Preparation state constraint and records cancellation through the existing
  command receipt/success-audit authority.
- [KNOWN | HIGH] Only queued/running resources may become cancelled. PostgreSQL
  locks the resource, uses database time and commits terminal state plus receipt
  atomically. Running cancellation clears lease owner/deadline while retaining the
  fence; an in-flight Builder may finish external work but its stale claim cannot
  submit ready or failed. No partial artifact becomes Release authority.
- [KNOWN | HIGH] Tests cover exact replay, fingerprint conflict, terminal-state
  rejection, invalid input, eight concurrent cancellations, queued claim/cancel
  competition, in-flight build fencing, audit failure rollback, secret-free GET
  with absent HTTP cancel command, and `0012 → 0013` active-running upgrade.
  Preparation/PostgreSQL/distribution passed 170 tests; the full affected KSS and
  ProofAgent KSS/BFF suite passed 357 tests with zero skips against isolated
  PostgreSQL/MinIO/OpenSearch. The post-slice repository regression passed 2346
  main backend tests plus 2 explicitly selected hybrid integration tests, 225
  Dashboard tests and 35 Chat tests. Mypy passed 448 source files; Ruff, locks,
  typecheck and all frontend builds passed.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. There is no cancellation
  HTTP/BFF/CLI, deployment wiring, production migration, automatic Worker/reaper,
  artifact cleanup or Production GO. Ready candidate corruption is not cancellable;
  quarantine requires a separately approved authority and recovery contract.

## 2026-08-28 KSS one-shot active Preparation expiry (TDD-02F)

- [KNOWN | HIGH] `KnowledgeBasePreparationApplication.expire_next()` now expires
  at most one due ready candidate per trusted server-side call. PostgreSQL uses
  database time, deterministic expiry/identity ordering and
  `FOR UPDATE SKIP LOCKED LIMIT 1`; state and the existing publication lifecycle audit commit in one
  transaction. Management GET remains read-only.
- [KNOWN | HIGH] The new contracts cover an unexpired no-op, the exact in-memory
  expiry boundary, invalid actor input, eight concurrent callers, a locked earliest
  row, audit-write rollback, corrupted candidate failure and a race with publish.
  Active and publish-triggered expiry share one adapter-internal terminal transition.
  No path creates a Release.
- [KNOWN | HIGH] Preparation memory/PostgreSQL tests passed 133 checks. The full
  affected KSS and ProofAgent KSS/BFF suite passed 339 tests with zero skips against
  isolated PostgreSQL/MinIO/OpenSearch. KSS mypy passed over 91 source files; Ruff
  and formatting checks passed.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. `expire_next()` is a one-shot
  application Interface, not an automatic reaper or health probe. `None` may mean
  no due item or temporary lock contention. There is no scheduler/process wiring,
  HTTP/BFF, object cleanup, production migration or Production GO. TDD-02G later
  added application-only queued/running cancellation, but not a network command.

## 2026-08-28 KSS one-use core Release publication (TDD-02E)

- [KNOWN | HIGH] `KnowledgeBasePreparationApplication.publish()` now consumes one
  unexpired ready candidate. Migration `0012` adds durable `expired/consumed`, an
  exact same-Space Release foreign key and one lifecycle event per Preparation.
  PostgreSQL time decides the exact expiry boundary; expired state and audit commit
  before the application returns `base_preparation_expired`.
- [KNOWN | HIGH] Successful publication writes the exact Release header, ordered
  members, consumed Preparation and audit in one caller-owned transaction. Eight
  concurrent callers produce one success; transaction-failure and pre-commit
  visibility tests prove no partial catalog/state visibility. An existing Release
  is reused only when queryable and fully equal, with its lifecycle row locked
  through consumed commit; retired, partial or conflicting rows fail closed without
  repair or revival. Later legitimate retirement preserves consumed history and the
  original queued receipt.
- [KNOWN | HIGH] Preparation core/PostgreSQL/distribution tests passed 145 checks.
  The full affected KSS and ProofAgent KSS/BFF suite passed 332 tests with zero
  skips against isolated PostgreSQL/MinIO/OpenSearch. KSS mypy passed over 91
  source files; Ruff passed. Exact OpenAPI and migration fingerprints are recorded
  in feature TDD report section 16.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. Publication is a trusted
  application Interface only: no `:publish` HTTP route, BFF/Dashboard, role wiring,
  active expiry reaper, cancellation, production process or migration was added.
  Existing direct Release publication remains compatible, so the one-use path is
  not yet the unique system-wide authority and is not Production GO.

## 2026-08-27 KSS fenced candidate result (TDD-02D)

- [KNOWN | HIGH] User separately approved local SQL, build interface, repository
  and management-state work. `KnowledgeReleaseApplication.prepare()` and
  `KnowledgeReleaseCandidateBuilder` build an exact immutable candidate without
  writing it to the Release catalog. Existing direct `publish()` behavior remains
  compatible and separate.
- [KNOWN | HIGH] Migration `0011` adds durable `ready/failed` result state,
  candidate data and terminal-time constraints without rewriting `0009/0010`.
  Final submission holds one short row transaction and checks the current owner,
  database-clock lease, fencing token and complete frozen admission. A stale Worker
  cannot overwrite the newer attempt; a commit failure rolls back result and audit.
- [KNOWN | HIGH] Management GET exposes safe `ready/failed` resources without
  candidate JSON, artifact references or lease capabilities. Build exceptions become
  stable failure codes without raw details; POST replay still returns the original
  `queued` receipt. Twelve new behavior contracts were added. The full affected suite
  passed 316 tests with zero skips against isolated PG/MinIO/OpenSearch; mypy passed
  over 91 source files and Ruff passed.
- [FRAME | HIGH] This remains `PARTIAL_VERIFICATION`. No constant Worker loop,
  production composition, `ready → expired`, one-use publication, `consumed`
  transition, orphan-artifact collection, ProofAgent BFF/Dashboard wiring or
  production migration was implemented. See feature TDD report section 15.

## 2026-08-27 KSS preparation Worker lease coordination (TDD-02C)

- [KNOWN | HIGH] User separately approved local migration, repository and state
  contract work. Migration `0010` adds lease owner/fence/deadline and atomic
  coordination audit without rewriting `0009`. Worker claim/renew uses PostgreSQL
  time and row locks; expired work can be taken over, stale claims cannot renew,
  and the same Worker ID cannot reuse an older fence.
- [KNOWN | HIGH] Management GET exposes queued/running without private claim
  fields. Original POST receipts remain queued after state changes; exact admission
  identity and integrity checks remain enforced. No new role, Worker HTTP route,
  CLI, process loop or production configuration was added.
- [KNOWN | HIGH] New coverage is 17 PG/HTTP and 9 core/input contracts. The full
  affected suite passed 304 tests, zero skips, in 22.79 seconds against isolated
  PG/MinIO/OpenSearch with fail-if-missing. Focused preparation/distribution tests
  passed 118; KSS mypy (90 files), Ruff, format and lock checks passed. Upgrade from
  queued `0009` data is tested, but not production migration or recovery.
- [FRAME | HIGH] Build execution and final-result/artifact fencing remain pending,
  as do cancellation, ready/failed, candidate expiry and one-use publication. A
  successful lease check is not permission to publish later outside its transaction.
  Existing direct Release behavior is unchanged. Feature remains
  `PARTIAL_VERIFICATION`; see the feature TDD report section 14.

## 2026-08-26 KSS durable preparation admission and management API (TDD-02B)

- [KNOWN | HIGH] User separately approved local SQL/repository/API work. Migration
  `0009` persists Draft history, exact Base Versions, queued Preparations and
  operator-scoped receipts/success audit atomically. Base row locks protect Draft
  CAS; one catalog statement freezes all selected Sources. Stored Drafts, plans
  and receipts are checked for integrity on reads.
- [KNOWN | HIGH] Protected management routes save/read Drafts, start/read queued
  Preparations and expose safe audit. Server-side `knowledge_source.view/edit`
  gates and durable rejection audit do not introduce per-Space ACL or local roles.
  Explicit runtime DI requires an operator authenticator and identity factory;
  production process composition remains unchanged.
- [KNOWN | HIGH] The affected KSS and ProofAgent boundary suite passed 278 tests,
  zero skips, in 20.17 seconds with real isolated PostgreSQL/MinIO/OpenSearch and
  fail-if-missing enabled. This includes 22 new PG/HTTP tests and the existing 51
  core contracts. KSS Ruff, mypy (89 files), 11-file format check and lock check
  passed. New preparation fixtures use memory artifacts; no new Worker is tested.
- [FRAME | HIGH] Preparation execution, lease/fencing, cancellation/expiry,
  ready/consumed and one-use publication remain pending. The existing direct
  Release path is not replaced; no production SQL, deployment or Git commit was
  performed. Feature remains `PARTIAL_VERIFICATION`. See section 13 of
  `docs/features/kss-configuration-publication-loop/tdd-report.md` and
  `base-preparation-local-guide.md` in the same directory.

## 2026-08-26 KSS Base Draft and preparation admission core (TDD-02A)

- [KNOWN | HIGH] `KnowledgeBasePreparationApplication` adds revisioned Drafts,
  strict exact/latest-ready member selection, an immutable exact Base Version plan,
  and a non-queryable `queued` Preparation. Draft CAS, catalog resolution, resource,
  idempotency receipt and success audit share a serializable test transaction.
- [KNOWN | HIGH] Core verification passed 51 tests. The affected KSS/ProofAgent
  boundary suite passed 212 tests with 44 skips because this turn did not configure
  isolated PG/S3/search dependencies. KSS Ruff and mypy over 88 files passed.
  These results do not replace the separate TDD-01B real-dependency evidence below.
- [KNOWN | HIGH] This is an application interface with test-only in-memory
  storage, not durable async execution. No HTTP or runtime composition enables it.
  PostgreSQL, authorization/rejection audit, Worker fencing, readiness/expiry and
  one-use publication remain pending. No SQL, deployment or dependency changed.
  Feature status remains `PARTIAL_VERIFICATION`; see section 12 of
  `docs/features/kss-configuration-publication-loop/tdd-report.md`.

## 2026-08-26 KSS Connection Profile persistence and wiring (TDD-01A/01B)

- [KNOWN | HIGH] `ConnectionProfileApplication` now provides an HTTP snapshot
  Profile lifecycle, exact revision resolution, immutable historical publication,
  safe management views, and operator-scoped idempotency with atomic state/audit
  records in PostgreSQL. Source/Space foreign keys, concurrent command replay,
  state-version CAS and protected rejection audit are covered locally.
- [KNOWN | HIGH] Management HTTP enforces server-authenticated global
  `knowledge_source.view/edit` permissions. Explicit managed composition accepts
  only v2 exact-profile jobs; Worker revalidates the pinned revision/digest and
  persists verified Profile lineage in immutable Source Version artifacts.
- [COMPUTED | HIGH] Final KSS plus ProofAgent KSS/BFF boundary verification passed
  205 tests (175 KSS contracts and 30 ProofAgent boundary tests) with real isolated
  PostgreSQL, MinIO and OpenSearch and no skips. KSS/ProofAgent mypy, KSS Ruff,
  domain-context, diff and lock checks passed. Evidence is in the feature report.
- [KNOWN | HIGH] Production process composition still selects the static registry.
  Real policy/Secret/egress/TLS adapters, process cutover and ProofAgent BFF/UI role
  bundles remain pending. SQL migrations were applied only to random isolated
  test schemas; no deployment or production configuration changed. This is `PARTIAL_VERIFICATION`,
  not completion of TDD-01 or Production GO. See
  `docs/features/kss-configuration-publication-loop/tdd-report.md`.

## 2026-08-18 KSS authority cutover

- [KNOWN | HIGH] `ResolvedKnowledgeBindingSet` now accepts only an exact
  `ResolvedKnowledgeSourceServiceBinding`; package/shared bindings are rejected and
  published manifests contribute no knowledge authority.
- [KNOWN | HIGH] Production runtime resolves the versioned KSS client secret lazily,
  submits an exact-Space/exact-Release query and applies an exact ProofAgent-owned
  scorer. Identity, revision, candidate-set or score drift fails closed.
- [KNOWN | HIGH] ProofAgent Hybrid runtime, source API, worker, persistence and UI
  surfaces were physically removed. KSS's service-owned worker remains.
- [COMPUTED | HIGH] Final local verification on 2026-08-19 passed 1837 backend tests
  with 120 environment-dependent skips and two explicit deselections. Dashboard passed
  all 195 tests across 32 files and its production build. Ruff passed for `proof_agent`
  and `tests`; strict mypy passed over 346 product source files; domain-context and
  `git diff --check` checks passed.
- [LIMIT | HIGH] These are local checks, not live cutover evidence. No image was built
  or deployed in this increment, and no real production KSS, grant, secret, scorer,
  shadow, pilot, recovery or Product Release Gate was exercised.

## 2026-08-13 Product Release Authority

- [KNOWN | HIGH] ADR 0208 activates `initial-private-pilot-v2` with five top-level risk Gates while retaining all 13 required check families and their thresholds, binding rules, and freshness windows. The canonical profile is now the sole policy source used by both Gate production and independent verification.
- [KNOWN | HIGH] The provider-neutral release CLI now binds build inventory, evaluates raw facts without accepting producer status, closes partial manifests with explicit `not_run` results, and verifies detached Ed25519 Evidence attestations against deployment-owned issuer, subject, key ID, and public key trust. Evidence and attestations reuse the existing exact-version Artifact Store and Bundle Index contracts; no second pipeline, service, approval workflow, or PostgreSQL ledger was added.
- [COMPUTED | HIGH] The Product Release Authority, Release verifier/registry/download, and S3 Artifact Store slice passed 225 tests with 1 environment-dependent skip. The complete default backend suite passed 3197 tests with 134 environment-dependent skips and 13 opt-in tests deselected. Ruff passed for `proof_agent` and `tests`, and mypy passed over 435 product sources. These are local implementation checks, not formal release Evidence.
- [KNOWN | HIGH] Production remains `NO-GO` until the existing pipeline supplies one clean immutable candidate plus real signed Evidence for every required check, the exact artifacts and attestations are finalized in the Release Bundle, and offline verification returns `GO` inside the evidence and deployment windows.

## 2026-08-12 production Agent Draft lifecycle repair

- [KNOWN | HIGH] Production now registers a focused `/api/config/agents` list/create/read/update/contract/version slice instead of sending Create Agent to the development-only manifest import route and then the generic API 404. Creation accepts only display name and purpose plus `Idempotency-Key`; the server loads the sole packaged `agent_management_insurance_specialist` V3 template. Browser-supplied manifest paths, Agent IDs and Workflow authority are rejected.
- [KNOWN | HIGH] Draft initialization and General metadata updates use the PostgreSQL Agent repository through one Configuration UoW with trace-safe audit metadata. Creation is singleton and fingerprint-idempotent; updates require revision CAS. The slice remains behind production OIDC Session, named Agent permissions and same-origin CSRF, and it does not register validation, publication, rollback or activation mutations.
- [KNOWN | HIGH] Dashboard Agents and Agent Detail now render server capability projections. Production hides manifest import, unsupported configuration modules, validation, publication and rollback; development retains explicit package import and also exposes the server-owned create contract.
- [COMPUTED | HIGH] The focused backend slice passed 91 tests with 7 PostgreSQL tests skipped. One default backend run passed 3182 tests; the final run passed 3179 tests before four unrelated `test_remote_verify_gateway*` loopback requests timed out, and those four remained timing-sensitive on isolated rerun. Dashboard passed 227 tests and its production build. Workspace Ruff and mypy over 431 product sources passed. The result is `PARTIAL_VERIFICATION`: no isolated PostgreSQL DSN was available for the new query/transaction path, the final backend suite was not wholly green, and the production-local image/browser flow was not rebuilt or exercised.
- [KNOWN | HIGH] This repair initializes an editable Draft only. It does not satisfy Published Agent readiness, Phase F Evidence or any formal release Gate, and it does not change the current production **NO-GO** decision.

## 2026-08-12 independent Knowledge Source Service local-production deployment

- [KNOWN | HIGH] `docker-compose.production-local.yml` now runs the independent Knowledge Source Service as five isolated roles from one image: API, Query Executor, Knowledge Worker, Sync Scheduler and one-shot Migration. The four long-running roles use UID/GID `10001:10001`, a read-only root filesystem, no Linux capabilities and `no-new-privileges`.
- [KNOWN | HIGH] KSS owns the `knowledge_source_service` PostgreSQL database and `proof-agent-knowledge-local` versioned bucket. It shares only the physical PostgreSQL, MinIO and OpenSearch containers with ProofAgent. The first deployment correctly failed when KSS was pointed at ProofAgent's `proof` database; the final topology adds an idempotent database initialization Job, a dedicated random database credential, and the non-superuser `knowledge_source_service` login role. The KSS database, `public` schema and all 13 current tables are owned by that role; the `proof` database remains owned by `proof`.
- [KNOWN | HIGH] The external KSS origin is `https://proof-agent.localhost:8444`. KSS accesses OpenSearch, the projection encoder, the bounded Agentic controller and OCR through the internal TLS gateway with an explicit private CA. The local compatibility model plane requires a dedicated Bearer credential for all three KSS model protocols.
- [COMPUTED | HIGH] The retained stack is running KSS image `97c2db1f468f52029e59813d4d8a4d559848df93c66e17deff855bfb007986f5` and Agent image `cc4f80141cea15598aad3638c15044daeadb5cd506dcf63b1237e887ee37daee`. Markdown and typed CSV intake produced exact Release `release-a4b70851cb914862000e15c3`; single-pass returned 3 candidates, structured query returned 2 records and Agentic retrieval returned 3 candidates. A one-shot ProofAgent run crossed the guarded HTTPS boundary and returned `ANSWERED_WITH_CITATIONS` with the admitted answer facts 4 hours, CNY 300 and 30 days. The repeatable deployment verifier includes the KSS database ownership boundary; the KSS real PostgreSQL/MinIO/OpenSearch contract suite passed 105 tests.
- [KNOWN | HIGH] This is local production-shaped deployment evidence, not a production GO. The local model plane and explicit compatibility Admission Scorer are test authorities only. The long-running ProofAgent API remains HTTP 503 at `/readyz` solely because no sole Published Agent has been selected and published; automatically publishing a demo Agent would bypass the intended release authority.

## 2026-08-11 Metadata Review candidate repair

- [KNOWN | HIGH] The explicit Metadata Review V2 migration now materializes missing Review Sets for completed current candidates from their exact canonical and insurance-metadata artifacts. It never approves a Review, advances the Source Draft only when coverage is restored, and is repeatable after success. The production-local reference bootstrap waits for versioned S3 readiness before applying this fixture-only repair.
- [KNOWN | HIGH] The maintenance CLI can withdraw one duplicate current candidate only when the operator supplies both exact document/revision identities, a Source revision CAS, actor, reason and `--apply`, and both completed builds have the same original SHA-256. The transaction preserves ingestion jobs, artifacts and decisions, marks the duplicate Review Set historical, retains the selected candidate, advances the Source Draft and appends a trace-safe audit event. Different content or stale candidate authority fails closed.
- [KNOWN | HIGH] Knowledge Source summary and next-action projection now count only revisions represented by current candidate authority: the completed candidate plus any in-flight pending replacement. Historical completed, failed or review-required ingestion jobs remain visible as retained history but no longer inflate current document counts or block publication preparation.
- [KNOWN | HIGH] First publication preparation for a unified Hybrid Source now creates and locks its publication authority before inserting the foreign-keyed index generation in the same transaction. This removes the fresh-Source `hybrid_knowledge_generation_source_id_fkey` failure while preserving the live-attempt fence and generation identity checks.
- [KNOWN | HIGH] Strict private-model embedding and reranker response contracts now accept canonical JSON arrays at the transport boundary and normalize them to immutable tuples before domain use. Shape, batch, dimension, exact model revision, candidate order and finite-number validation remain fail closed.
- [KNOWN | HIGH] OpenSearch projection now canonicalizes embedding values to the backend's IEEE-754 float32 `knn_vector` precision before both storage and digest construction, then re-normalizes the backend's shorter JSON number representation during exact readback. Embedding and immutable-projection integrity remain recomputable without dropping or weakening vector tamper detection.
- [COMPUTED | HIGH] The affected publication, OpenSearch and private-model slice passed **210** tests with **1** environment-dependent skip; the PostgreSQL publication/ingestion and adjacent CLI/bootstrap slice passed **36** tests. Ruff, focused mypy, Compose validation and `git diff --check` passed. The production-local application roles were rebuilt on image `078ab01c2f62662c8bd045ccafb6faa2a07da2d3db1e5c06c6fd21f5cd6122b4`; infrastructure verification passed and a real Dashboard preparation advanced `ks_insurance` to revision 60 with prepared authority fence 12. Final Source publication was intentionally not committed.

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
