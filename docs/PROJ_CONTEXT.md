# Project Context

## Current implementation facts

- `[KNOWN | HIGH]` The active Python product package is `proof_agent`; its main
  runtime composition enters through `proof_agent/bootstrap/composition.py`.
- `[KNOWN | HIGH]` The independent Knowledge Source Service implementation package
  is `knowledge_source_service/` at the repository root, alongside `proof_agent/`.
  Its independent distribution metadata and container build files remain under
  `services/knowledge-source-service/`. Its public query resource is
  `/v1/knowledge-queries`, and its API, Query Executor, Knowledge Worker,
  Synchronization Scheduler, and migration roles have independent entry points.
- `[KNOWN | HIGH]` As of 2026-08-19, ADR-0210 makes KSS the only executable
  knowledge authority. A knowledge-enabled Published Agent Version owns one
  exact `ResolvedKnowledgeSourceServiceBinding`; ProofAgent queries through
  `proof_agent/capabilities/knowledge/source_service_client.py` and applies its
  own exact Admission Scorer. Package, shared-source and Hybrid bindings are
  rejected, and production fails closed without a local fallback.
- `[KNOWN | HIGH]` ProofAgent's old Hybrid provider, ingestion, publication,
  worker, repository, source-management API, CLI and Dashboard paths have been
  physically removed. KSS's own Knowledge Worker remains. Former Hybrid-bound
  Published Agent Versions are historical records and no longer replayable or
  usable as rollback targets.
- `[KNOWN | HIGH]` As of 2026-08-20, Agent Configuration Workspace local slices
  cover Draft inventory/read/update, validation, development publication, Agent
  Version pointer rollback, Workflow Stage Configuration save/preview, raw
  Contract GET/PATCH, and Business Flow Skill Pack specialized read/create/update/
  delete. Skill Pack commands now cross one Workspace interface, update manifest
  binding and package-local definition in one revision CAS transaction, and append
  Draft/global audit atomically. A temporary local inspector owns compilation and
  projection, while Dashboard sends the current projection revision and creates a
  complete Skill Pack with one command. Package-local definition safety is shared
  by manifest, raw Contract and Skill Pack adapters; Dashboard freezes stale edits
  until an explicit latest-version reload. Slice 7 passed main-agent verification
  and independent review with no blocking findings. A disposable PostgreSQL 17.5
  service subsequently passed the Configuration UoW tests and the complete
  PostgreSQL-marked suite. An independent follow-up review found no P0–P3; this
  remains local evidence, not production approval.
- `[COMPUTED | HIGH]` Slice 7 plus the real-PostgreSQL follow-up passed 2050 backend tests,
  197 Dashboard tests and 35 Chat tests; both production builds passed. Ruff,
  strict mypy over 354 source files, domain-context, diff and lock checks passed.
  This does not authorize production.
- `[KNOWN | HIGH]` As of 2026-08-22, Production Agent Detail restores governed
  Contract, Workflow, Skill Pack, exact KSS Release and publication-configuration
  interactions through the Agent Configuration Workspace. The publication tab is
  a read-only authoring snapshot over one Draft revision plus live KSS and Shared
  Model Connection facts. It explicitly reports `workspace_draft_not_bound`:
  the current formal publisher still uses independent candidate inputs, and the
  Dashboard exposes no publish or activate command.
- `[COMPUTED | HIGH]` Slice 8E passed 2039 backend tests, 217 Dashboard tests and
  35 Chat tests. Ruff, mypy over 357 source files, TypeScript, all UI builds,
  domain-context, diff and lock checks passed. Eleven real-PostgreSQL tests were
  skipped because the current shell had no `PROOF_AGENT_TEST_POSTGRES_DSN`, so
  the Slice 8E evidence remains `PASS_WITH_ENV_LIMITATION`, not production approval.
- `[KNOWN | HIGH]` As of 2026-08-23, Slice 8F closes the verified Agent Detail
  Development flow gaps without changing publication authority. Metadata PATCH
  honors a caller-provided Draft revision; the Dashboard exposes saved/unsaved and
  Validation-freshness state, blocks Validation of unsaved configuration and
  publication from stale Validation, counts Draft Validation Records directly,
  and confirms Agent Version pointer rollback. Development auth session projection
  now returns the local Operator instead of raising a missing-middleware 500.
- `[COMPUTED | HIGH]` Slice 8F passed 96 focused backend tests with 4
  environment skips (91 Agent Configuration API plus 5 security-composition tests),
  221 Dashboard tests, Agent Detail 62 tests, Dashboard build,
  Ruff, focused mypy, domain-context and diff checks. A temporary local store real
  browser run verified metadata revision 2→3, auth session 200, unsaved/stale
  lifecycle blockers, Validation count 1 and rollback confirmation. This remains
  local Development evidence; Production PostgreSQL, Phase F publication, online
  KSS smoke and deployment Gates were not executed.
- `[KNOWN | HIGH]` As of 2026-08-23, Slice 8G aligns every Agent Detail
  configuration surface with its current write authority. Workflow no longer
  reintroduces retired runtime fields; Model writes `react.max_plan_rounds` and
  always exposes Review controls; Tools writes only `capabilities.tools`;
  optional Contract sections can be inserted; and save actions cannot commit a
  different module's unsaved state or advance the revision on a no-op.
- `[COMPUTED | HIGH]` Slice 8G passed 225 Dashboard tests, the Dashboard
  production build, 96 focused backend tests with 4 environment skips, Ruff,
  strict Mypy over 357 source files, domain-context and diff checks. A temporary
  Development browser run saved canonical Model configuration, completed exact
  revision Validation with expected `REFUSED_NO_EVIDENCE`, published an immutable
  Development version, observed separate Run/Validation counts, and confirmed
  active-pointer rollback. This is local workflow evidence, not Production
  publication or deployment approval.
- `[KNOWN | HIGH]` As of 2026-08-13, Dashboard KSS management uses the
  same-origin `/api/config/knowledge-service` BFF. ProofAgent resolves the KSS
  operator credential from Vault and calls the independent service through the
  active Egress Policy; browser responses contain only readiness and catalog
  projections. The UI can create Space, Source, and Base resources and list
  Source Versions and Releases. KSS remains the catalog authority.
- `[KNOWN | HIGH]` `AGENTS-COMMON.md` requires PostgreSQL authority for mutable
  production state, S3-compatible immutable artifacts, and fail-closed
  production composition.
- `[KNOWN | HIGH]` Local acceptance on 2026-08-12 covers strict contracts,
  heterogeneous intake, immutable Source/Release authority, real
  PostgreSQL/MinIO/OpenSearch retrieval, bounded Agentic retrieval, durable
  synchronization, ProofAgent integration, and a retained production-shaped
  Docker Compose deployment. KSS runs five isolated roles from non-root image
  `97c2db1f…`, owns a separate PostgreSQL database through its dedicated
  non-superuser login role, and is exposed at `https://proof-agent.localhost:8444`.
  This is local deployment verification, not production approval.
- `[KNOWN | HIGH]` The 2026-08-13 retained deployment rebuilt ProofAgent image
  `f74462bb…` and KSS image `53747fd5…`. The deployment verifier passed, and a
  production-composed BFF client read `ready` plus 3 Spaces, 6 Sources, 3 Bases,
  6 Source Versions, and 3 Releases. Existing browser sessions were invalidated
  by the immutable Permission Mapping epoch change and require a new OIDC login.
- `[KNOWN | HIGH]` Product Release Authority uses the versioned
  `initial-private-pilot-v2` policy to compute five fail-closed risk Gates from
  raw pipeline facts. Exact Evidence and detached workload-identity attestations
  reuse the existing Artifact Store and Release Bundle Index; the verifier can
  reach `GO` only with deployment-owned public trust.
- `[KNOWN | HIGH]` Production Candidate Binding v2 identifies ProofAgent and KSS
  independently. KSS contributes exact OCI, Python distribution, canonical
  OpenAPI and ordered migration-contract digests; the DCM also binds KSS,
  OpenSearch and the private knowledge-model plane. The formal KSS five-role
  Compose has an independent lifecycle under `deploy/production/knowledge/`.
- `[KNOWN | HIGH]` Metadata Review V2 remains a maintenance-window direct
  cutover. The normal Blue/Green expand-only migration rejects revisions `0020`
  and `0021`; the explicit cutover command requires stopped writes, stopped
  Workers and exact pre-cutover backup Evidence.

The Graphify map was queried during the 2026-08-18 authority cutover to check the
former composition, knowledge-resolution and provider seams. The cutover itself
is governed by ADR-0210 and current code; Graphify is navigation evidence, not
release approval.

## Feature index

[KNOWN | HIGH] On 2026-08-26, KSS Connection Profile TDD-01B adds PostgreSQL
revision/receipt/audit authority, authenticated management commands, and an
explicit managed synchronization composition. Jobs pin an exact published
Profile revision/digest, and immutable Source Version artifacts retain verified
lineage. Production process roles still select the static registry. Real upstream
policy/Secret/egress/TLS adapters, cutover and ProofAgent UI wiring remain pending;
local PG/S3/search tests are not production approval.

[KNOWN | HIGH] TDD-02A through TDD-02G adds management-only Base Draft and preparation admission:
Draft revision CAS, exact/latest-ready selection frozen under a Base lock and one
catalog statement snapshot, immutable Base Version plans, durable queued resources
and atomic receipt/success audit. PostgreSQL migration `0009`, protected management
HTTP and safe rejection audit are implemented behind explicit runtime DI. The
latest slices add `0010/0011` and a trusted Worker interface with database-clock
leases, monotonic fences, takeover, exact candidate construction and atomic
`ready/failed` result events. Migration `0012` adds application-only
`ready → expired/consumed`: exact Release header/members, terminal state and
publication lifecycle audit commit in one PostgreSQL transaction using database
time. Management GET reads all implemented states; POST replay preserves the
original queued receipt. Existing exact Release reuse is locked through the
consumed commit; later legitimate retirement does not corrupt consumed history or
the original receipt. TDD-02F adds application-only `expire_next()`: database-time,
deterministically ordered `FOR UPDATE SKIP LOCKED` selection atomically expires one
due ready candidate with its existing lifecycle audit. The affected regression
passed 339 tests with zero skips against isolated PostgreSQL/MinIO/OpenSearch. TDD-02G
adds migration `0013` and application-only idempotent queued/running cancellation:
database time, the terminal resource and command receipt/success audit commit in one
transaction; cancelling running work clears its active lease and fences any in-flight
Worker result. Management GET reads secret-free cancelled state. TDD-04F later adds
controlled KSS and ProofAgent `:cancel` commands over this same transaction. The
TDD-02G affected regression passed 357 tests with zero skips. There is no expiry
HTTP/BFF, automatic expiry scheduler, quarantine or production
Worker loop, and candidate PostgreSQL fixtures still use a memory artifact adapter.
Existing direct Release publication remains a compatible bypass, so Preparation is
not yet the system-wide unique authority.

[KNOWN | HIGH] TDD-03A adds migration `0014` and a trusted application-only
Knowledge Base Release Reference registration module. An authenticated client may
register one immutable `published_agent_version` as `execution_or_rollback` against
an exact queryable Space/Base/Release. PostgreSQL locks the Release row and commits
the active reference, permanent client-scoped idempotency receipt and success audit
using database time in one transaction. Same-key concurrency converges, while a
missing, retired or scope-mismatched Release and an attempted external-resource
rebind fail closed. The affected KSS plus ProofAgent KSS/BFF regression passed 375
tests with zero skips against isolated PostgreSQL/MinIO/OpenSearch. There is no
Reference HTTP/BFF, deregistration/reconciler, Release deprecation/retirement/
revocation implementation or ProofAgent reference-first activation, so the Ledger
is not yet ordinary-retirement or product-publication authority.

[KNOWN | HIGH] TDD-03B adds migration `0015` and a trusted application-only
Knowledge Base Release deprecation command. Only an exact `queryable` Release may
become `deprecated`; the state, operator-scoped idempotency receipt and success
audit use database time and commit in one PostgreSQL transaction. Reference
registration and deprecation lock the same Release row. Existing references,
Catalog reads, integrity scans and established Query grants remain usable, while
new references and new Query grants are rejected. The affected KSS plus ProofAgent
KSS/BFF regression passed 388 tests with zero skips. There is no deprecation
HTTP/BFF, ordinary retirement, emergency revocation, deregistration/reconciler or
ProofAgent activation integration, so the feature remains partial local evidence.

[KNOWN | HIGH] TDD-03C adds migration `0016` and a trusted application-only
ordinary retirement command. Only an exact `deprecated` Release with zero active
KSS Reference Ledger rows may become `retired`, and only after database time reaches
the immutable server-injected retention policy boundary. Policy ID, deprecation
time, eligibility time, retirement time, operator-scoped receipt and success audit
commit atomically under the Release row lock. Retired Releases are absent from
Catalog query, integrity work and established Query authorization. The affected KSS
plus ProofAgent KSS/BFF regression passed 399 tests with zero skips against isolated
PostgreSQL/MinIO/OpenSearch. There is no deregistration/reconciler, emergency
revocation, lifecycle HTTP/BFF, ProofAgent activation ordering, production retention
configuration, deployment or Production GO, so referenced Releases remain
conservatively non-retirable.

[KNOWN | HIGH] TDD-03D adds migration `0017` and a trusted application-only
Reference deregistration admission. The request contains only exact Reference
identity. Only the owning authenticated client may proceed, and a server-injected
verifier must prove that the immutable external resource is permanently ineligible
for execution and rollback. External verification occurs outside the PostgreSQL
transaction; KSS then rechecks the permanent client-scoped receipt, locks the exact
active Reference, revalidates trace-safe verifier/verification identities and
atomically records `deregistered` with database time and ordered success audit.
Historical registration receipts remain immutable. Same-key concurrency converges,
different-key duplication fails, and deregistration/retirement races remain
conservative. The affected real-dependency regression passed 395 tests with zero
skips; the full backend passed 2384 tests with 24 existing declared skips plus 2
explicit hybrid integrations. There is no ProofAgent verifier/proof issuance,
background reconciler, Reference/lifecycle HTTP/BFF, emergency revocation,
production configuration, deployment or Production GO.

[KNOWN | HIGH] TDD-03E adds migration `0018` and trusted application-only
Emergency Knowledge Base Release Revocation. Only exact `queryable` or
`deprecated` Releases may move to `revoked`, only for `security_incident` or
`severe_data_integrity_failure`, and only with exact
`fail_closed_without_fallback` confirmation plus a delivery-authorized operator
identity. KSS locks and counts active References, then atomically records the
state, reason, confirmation, database time, affected count, permanent receipt and
success audit without changing Reference facts. Revoked Releases are absent from
Catalog query/integrity work and established Query authorization. Registration,
deregistration and ordinary-retirement races converge under Release/Reference
locks; `retired` and `revoked` cannot overwrite each other. The real-dependency
affected regression passed 415 tests with zero skips; the full backend passed 2396
tests with 24 existing declared skips plus 2 explicit hybrid integrations. This
does not add lifecycle HTTP/BFF authorization, affected-reference details or
notifications, ProofAgent runtime/rollback integration, physical deletion,
deployment, production migration or Production GO.

[KNOWN | HIGH] TDD-03F adds trusted application-only, read-only Knowledge Base
Release deletion-eligibility assessment without a new migration or network
command. It reads exact lifecycle time plus active/deregistered Reference counts
from PostgreSQL database time and invokes a server-injected artifact-retention
authority only for an otherwise eligible ordinary retired Release. Complete
ordinary retirement history, zero active References and an explicit artifact
`clear` result are all required; missing/blocked artifact authority fails closed,
deregistered References remain retained history without blocking, and revoked
Releases retain an incident-response blocker regardless of artifact state. The
assessment writes no state, receipt or audit and cannot be reused as deletion
authority; a future physical-delete command must atomically revalidate and audit.
The affected real-dependency regression passed 422 tests with zero skips; the full
backend passed 2408 tests with 24 existing declared skips plus 2 explicit hybrid
integrations. There is no production artifact-retention adapter, physical deletion,
lifecycle HTTP/BFF, ProofAgent runtime integration, deployment or Production GO.

[KNOWN | HIGH] TDD-04A exposes that read-only deletion-eligibility assessment
through one authenticated KSS management GET and one same-origin ProofAgent BFF
GET. Both use exact Space/Base/Release identity and require
`knowledge_source.view`; the BFF projection includes lifecycle state, blockers and
active/deregistered Reference counts, but omits the KSS operator credential,
endpoint, external-resource identity, artifact authority/assessment identity and
raw upstream problem. Production-shaped KSS composition reads PostgreSQL facts and
fails closed with `artifact_retention_unverified` because no production artifact
authority is configured. Release list clients now accept all four governed states.
The affected real-dependency regression passed 427 tests with zero skips; the full
backend passed 2416 tests with 24 existing declared skips plus 2 explicit hybrid
integrations. There are still no lifecycle or Reference commands over HTTP/BFF,
affected-reference details or notifications, physical deletion, ProofAgent runtime
integration, deployment or Production GO.

[KNOWN | HIGH] TDD-04B exposes the existing KSS Connection Profile and managed
synchronization core through the ProofAgent guarded management client and
same-origin BFF. It supports Profile create, current/exact read, revision-CAS
revise, validate and publish, plus exact Published Profile synchronization submit
and status read. Reads require `knowledge_source.view`; mutations require
`knowledge_source.edit`. The browser projection excludes endpoint, versioned
Secret Handle, egress/trust references, KSS operator token and raw service
problem/trace; invalid input returns a fixed non-echoing `422`. Exact
`Idempotency-Key` forwarding preserves synchronization `202` create versus `200`
replay. A real BFF → KSS → PostgreSQL contract passed, the affected suite passed
440 tests, and the complete backend passed 2429 tests plus 2 explicit Hybrid
integrations. There is no Dashboard page, production Vault/egress/TLS adapter,
managed-profile process cutover or verified terminal-operator delegation into KSS
audit, so this remains local evidence rather than Production GO.

[KNOWN | HIGH] TDD-04C exposes existing KSS Base Draft and Release Preparation
admission/status authority through the ProofAgent guarded management client and
same-origin BFF. Draft PUT uses revision CAS and typed exact/latest-ready members;
Draft GET requires an exact revision. Preparation start pins one exact Draft
revision and preserves KSS `202` for both first admission and exact replay; current
status reads the exact Preparation identity. Reads require `knowledge_source.view`
and writes require `knowledge_source.edit`. The client injects path-owned Space/Base
identity into KSS requests and fails closed on Scope, revision, Location, state or
wire-field drift. Browser projections omit KSS credentials, Worker/lease/fence and
artifact capability fields, and raw failure detail. A real BFF → KSS → PostgreSQL
contract passed without creating a Release; the focused affected set passed 115
tests, the complete backend passed 2445 tests with 24 declared skips and 2 default
exclusions, and 2 explicit Hybrid integrations passed separately. There is no
Preparation execution process, publish/cancel/expiry BFF, Dashboard page, verified
terminal-operator delegation, deployment or Production GO.

[KNOWN | HIGH] TDD-04D adds an optional, trusted one-shot Preparation execution
runtime composition. `BasePreparationExecutionConfiguration` owns the distinct
Worker identity, lease duration and candidate TTL; callers use only `run_once()`,
which processes at most one durable queued/recoverable Preparation through the
existing frozen-plan builder and fenced `ready/failed` transaction. The API runtime
does not enable execution by default, while a rebuilt execution runtime can resume
the same PostgreSQL queue. A real BFF → KSS → PostgreSQL tracer reached `ready`
without creating a Release or exposing Worker/artifact fields. The affected suite
passed 460 tests; the full backend passed 2449 tests with 24 declared skips and 2
default exclusions, plus 2 explicit Hybrid integrations. There is no CLI, continuous
process role, batch loop, auto-retry, publication/cancel/expiry BFF, Dashboard,
deployment, production configuration or Production GO.

[KNOWN | HIGH] TDD-04E exposes the existing one-use Preparation publication CAS
through KSS management HTTP, the ProofAgent guarded client and a same-origin BFF.
The command requires `knowledge_source.edit`, accepts no body or Idempotency-Key,
validates exact path Scope before mutation and returns `200`, the consumed safe
projection and the same Preparation GET `Location`. Uncertain responses, expiry and
replay recover through GET of the exact Preparation rather than a second receipt.
A real BFF → KSS → PostgreSQL vertical reached queued → ready → consumed and created
exactly one queryable Release without exposing Worker, lease, fence, artifact or
secret fields. The fail-if-missing affected suite passed 480 tests; the full backend
passed 2461 tests with 24 existing declared skips and 2 default exclusions, plus 2
explicit Hybrid integrations. There is no Dashboard command, cancel/expiry BFF,
continuous process role, terminal-operator delegation, Agent formal publication,
deployment, production configuration or Production GO.

[KNOWN | HIGH] TDD-04F exposes the existing cooperative queued/running cancellation
transaction through KSS management HTTP, the ProofAgent guarded client and a
same-origin BFF. The no-body command requires `Idempotency-Key`; the BFF also requires
`knowledge_source.edit`. KSS validates exact path Scope before mutation and binds
replay to the trusted operator, action and Preparation identity. Exact replay returns
the original cancelled result and same-resource `Location` with one success audit;
key rebinding, terminal-state retry, body input and upstream identity/state/Location
drift fail closed. A real BFF → KSS → PostgreSQL vertical reached queued → cancelled
without creating another Release or exposing Worker, lease, fence, artifact or secret
fields. The full backend passed 2471 tests with 24 existing declared skips and 2
default exclusions, plus 2 explicit Hybrid integrations. There is no expiry BFF,
Dashboard command, continuous process role, artifact cleanup, ready quarantine,
deployment, production configuration or Production GO.

[KNOWN | HIGH] TDD-04G exposes the existing KSS Base Preparation audit collection
through the ProofAgent guarded client and a same-origin read-only BFF. The route
requires `knowledge_source.view`, validates exact Space/Base and a strict upstream
wire shape, then returns a chronological secret-free page bounded to offset 20,000
and limit 100. Identified actors are explicitly tagged `kss_service_operator`: they
are the trusted service identities observed by KSS, not browser or terminal operators.
Upstream drift, private Worker/fence/lease fields and raw rejection detail fail closed.
A real BFF → KSS → PostgreSQL vertical returned save/start/cancel facts over two pages
without leaking the browser identity or service credential. The full backend passed
2479 tests with 24 existing declared skips and 2 default exclusions, plus 2 explicit
Hybrid integrations. This current-snapshot offset view does not provide a stable
cross-page cursor or merge Worker/publication audit, and adds no Dashboard, identity
delegation, expiry command, continuous process role, deployment, production
configuration or Production GO.

[KNOWN | HIGH] TDD-04H exposes exact-resource Preparation expiry through KSS
management HTTP, the ProofAgent guarded client and a same-origin BFF. The no-body
command requires `knowledge_source.edit`, validates exact path Scope before mutation,
and uses PostgreSQL time plus an exact row lock to atomically move one due ready
Preparation to expired with one publication audit and no Release. Replaying an
already expired identity returns the same durable terminal state without a second
receipt or duplicate audit; not-due, non-ready, body input and upstream
identity/state/Location drift fail closed. The network contract deliberately does
not expose global `expire_next()`, so an uncertain retry cannot select another
candidate. A real BFF → KSS → PostgreSQL vertical and eight-call concurrency contract
passed. The full backend passed 2493 tests with 24 existing declared skips and 2
default exclusions, plus 2 explicit Hybrid integrations. There is no scheduler,
continuous process role, Dashboard operation, artifact cleanup, Agent formal
publication, deployment, production configuration or Production GO.

[KNOWN | HIGH] TDD-05A adds a read-only Formal Production Agent Candidate assembler
rooted in one named Agent, exact Draft ID and exact Draft revision. It reuses the
server-authoritative publication projector against a ready, versioned live KSS catalog
and combines only the Draft-owned exact Release with a strict deployment-owned Profile.
The Profile rejects Release identity and requires a versioned Knowledge credential;
the candidate retains exact Draft/KSS/catalog facts plus Knowledge Release and formal
digests. Stale/missing Draft, catalog failure, lifecycle/parent-tuple drift and invalid
Profile fail closed. The existing formal publisher is not cut over, and no Reference,
Phase F, smoke, Published Version, activation, Delivery, deployment or Production GO is
part of this slice.

[KNOWN | HIGH] TDD-05B adds an application-only, side-effect-free Phase F preparer.
It revalidates both Formal Candidate digests, resolves Workflow Stage facts, binds four
distinct exact evidence artifacts to both the formal-candidate and Knowledge Release
digests, and requires explicit approval from an independent Phase F authority. Its
output is a `ProvisionalProductionAgentVersion` with preparation metadata, exact Draft
revision, KSS binding and Phase F Record; it is not a Published or Active Agent Version.
Candidate/evidence drift, invalid Workflow facts and authority deny/unavailability fail
closed. The full backend passed 2272 tests with 263 dependency-conditioned skips and 2
deselected; Mypy covered 456 product source files. There is still no Reference, online
smoke, publisher cutover, store/audit write, activation, Delivery, deployment or
Production GO in this slice.

[KNOWN | HIGH] TDD-05C adds a Reference-first Control stager after Phase F. It
revalidates the candidate, Phase F Record and preparation before deriving a stable
idempotency key and invoking an injected authenticated KSS registrar port. The strict
request binds the Draft-owned exact Space/Base/Release to the provisional version as a
future `published_agent_version`; the active receipt must match all request facts.
Receipt uncertainty or drift fails closed and conservatively leaves any registered
Reference for later authenticated reconciliation. The Phase F Record now also binds
the provisional version and validation run identities. The full backend passed 2288
tests with 263 dependency-conditioned skips and 2 deselected; Mypy covered 457 product
source files. This remains port-level local evidence: no KSS HTTP/production adapter,
publisher consumption, smoke, persistence, activation, Delivery, deployment or
Production GO was added.

[KNOWN | HIGH] TDD-05D implements the authenticated registration transport behind
the TDD-05C port. KSS public client API now accepts strict exact Reference requests at
`POST /v1/knowledge-base-release-references`, derives client identity only from Bearer
authentication, and uses the existing PostgreSQL Reference repository in runtime.
ProofAgent has a separate HTTPS guarded registrar with a dedicated service-client
authorization factory; redirect, response-contract and exact-identity drift fail
closed. An isolated PostgreSQL vertical proved first registration and exact replay
produce one active Reference and one audit. The affected set passed 161 tests; the
full PostgreSQL-enabled backend passed 2541 tests with 37 dependency-conditioned
skips and 2 deselected; Mypy covered 458 product source files. This does not add
publisher consumption, online smoke, Published Version persistence, Active CAS,
deregistration/reconciliation, production Secret/egress composition, deployment or
Production GO.

[KNOWN | HIGH] TDD-05E adds an application-only exact online smoke boundary after
registered staging. Control revalidates the candidate, Phase F Record, provisional
version and active Reference before deriving a strict request bound to all candidate,
Release, Reference and validation identities. Only an exact matching
`ANSWERED_WITH_CITATIONS` result with at least one accepted citation and distinct exact
trace/receipt artifacts returns an explicitly unpublished qualification. The focused
slice passed 45 tests; the affected set passed 322 tests with 4 skips; the full backend
passed 2326 tests with 263 dependency-conditioned skips and 2 deselected after the
socket-bound cases were run in a loopback-capable environment. Mypy covered 459 product
source files. The service has no Store, Active pointer, audit writer or deregistrar;
smoke failure leaves the registered Reference and cannot publish or activate. A real
online runner, formal publisher consumption, atomic persistence/activation, Delivery,
deployment and Production GO remain absent.

[KNOWN | HIGH] TDD-05F adds the application-only formal publisher core that consumes
the complete exact candidate → Phase F → Reference → smoke chain. After Phase F and
before Reference registration it captures the Active pointer expectation through a
short read-only Configuration UoW, then performs external calls with no database
transaction open. A successful smoke is retained with the exact Draft revision, Phase
F Record and active Reference receipt in one strict Published Version evidence
envelope. The final UoW atomically enforces Draft revision and Active pointer CAS,
persists the immutable Version/activation and appends publication audit; concurrency,
audit or storage failure leaves no partial final state and retains the KSS Reference.
The focused slice passed 53 tests, the real PostgreSQL repository/UoW set passed 12,
the affected set passed 373 tests with 4 skips, and the PostgreSQL-enabled full backend
passed 2561 tests with 37 dependency-conditioned skips and 2 deselected. Mypy covered
460 product source files. The old manifest publisher and runtime composition remain
unchanged; no real online runner, persisted-idempotency public command, Delivery,
deployment or Production GO was added.

[KNOWN | HIGH] TDD-05G adds the concrete online smoke runner behind the TDD-05E port.
It revalidates the strict request against the exact registered staging, safely
materializes the provisional Contract Bundle into a private read-only temporary Agent
package, and reuses governed execution with validation purpose, exact run/KSS/runtime
facts and injected institution authorization. Only accepted evidence with a nonblank
citation is counted; bounded Trace and Receipt files are retained through immutable
write plus exact read-back. The focused slice passed 57 tests, the core compatibility
set passed 76, and the affected set passed 144 with 15 dependency-conditioned skips.
The full backend passed 2338 tests with 264 dependency-conditioned skips and 2
deselected in a loopback-capable environment; Mypy covered 460 product source files.
The old publisher/runtime composition remains unchanged, and controlled test execution
does not prove live KSS/model upstream readiness. No public durable-idempotency formal
command, Delivery cutover, deployment or Production GO was added.

[KNOWN | HIGH] TDD-05H adds the strict `agent.publish`-protected public formal
publication command and a durable actor-scoped `Idempotency-Key` receipt. The command
persists `in_progress` before external work, rejects a changed fingerprint before a
second external call, and replays the exact durable success, failure or in-progress
state. Migration `0022_formal_publish_cmd` and the PostgreSQL Configuration UoW make
success receipt completion atomic with Published Version, Active CAS and publication
audit; terminal results cannot be downgraded. The focused formal chain passed 63 tests,
the real PostgreSQL set passed 9, the affected set passed 170, and the final
PostgreSQL-enabled backend passed 2578 tests with 37 dependency-conditioned skips and
2 deselected. Mypy covered 367 product source files. The production role does not yet
compose the concrete command, process-loss recovery remains conservatively
`in_progress`, and the old manifest publisher/runtime path, live upstream evidence,
deployment and Production GO remain unchanged.

[KNOWN | HIGH] TDD-05I cuts the production API composition over to the durable formal
publication command. It composes the exact Draft/KSS/Profile candidate chain,
independent Phase F authority, dedicated versioned KSS Reference client, governed
online smoke runner and immutable artifact store over the PostgreSQL Configuration
UoW. Production startup now requires the command, and the old manifest
`production-publish-agent` CLI plus `compose_production_agent_publisher` entry are
removed. The focused set passed 16 tests, the affected set passed 180 with 13 skips,
and the full backend passed 2354 tests with 267 dependency-conditioned skips and 2
deselected after socket tests ran with loopback permission. Mypy covered 367 product
source files. The checked-in production-local deployment still lacks the dedicated
Reference client Secret/Grant, so live upstream evidence, command recovery, deployment
and Production GO remain absent.

[KNOWN | HIGH] TDD-05J supplies the checked-in production-local contract for that
dedicated Reference client: a distinct versioned Secret Handle and Vault fixture, one
hardened KSS client bootstrap before KSS API startup, the local Phase F evaluator origin,
and startup rejection when the Reference Handle aliases the operator or runtime Query
Handle. An isolated PostgreSQL/KSS/ProofAgent vertical proves the registrar creates one
exact active Reference owned by `proof-agent-formal-publication-reference`; the same
credential cannot query without a separate exact-Release Query Grant. The affected set
passed 593 tests with 13 dependency-conditioned skips, and the PostgreSQL-enabled full
backend passed 2588 tests with 37 dependency-conditioned skips and 2 deselected. No
production-local stack, formal publication, live model smoke, deployment or Production
GO was executed.

[KNOWN | HIGH] TDD-05K adds the separate application-only runtime Query Grant core from
ADR-0218. A trusted immutable policy owns runtime client identity, allowed strategies,
maximum execution budget and effective access-scope digest; each call accepts only one
exact Release, and KSS derives Space from Release authority. Exact replay is stable and
policy drift for the same client/Release conflicts instead of widening authorization.
The isolated PostgreSQL/KSS HTTP vertical passed, KSS contracts passed 411 tests with 13
dependency-conditioned skips, and the PostgreSQL-enabled full backend passed 2588 tests
with 37 dependency-conditioned skips and 2 deselected. No provisioning HTTP transport,
formal publisher composition, deployment or Production GO was added.

[KNOWN | HIGH] TDD-05L adds the operator-authenticated KSS Query Grant transport from
ADR-0219 plus a provider-neutral ProofAgent port and guarded HTTPS adapter. The command
and adapter carry only exact Release selection; KSS policy still owns client, Space,
strategies, budget and scope. Runtime and Reference credentials cannot authenticate the
operator command, and ProofAgent rejects non-strict, inactive or Release-drifted receipts.
Focused checks passed 25 tests, the isolated PostgreSQL/KSS/ProofAgent vertical passed,
KSS contracts passed 418 tests with 13 dependency-conditioned skips, and the
PostgreSQL-enabled full backend passed 2611 tests with 37 dependency-conditioned skips
and 2 deselected. No formal publisher composition, operator-command audit storage,
production configuration, deployment or Production GO was added.

[KNOWN | HIGH] TDD-05M adds the candidate-bound Query Grant Control staging from
ADR-0220. Formal publication now derives the exact Grant request from the validated
Candidate after Reference registration, strictly revalidates the active receipt's
Release and Knowledge Space, and requires that staging before online smoke. The old
Reference-only smoke call shape is removed, and production composition reuses the
existing KSS operator Secret boundary for the guarded provisioner. Focused formal
checks passed 72 tests, production composition passed 11, the affected set passed 141
with 13 dependency-conditioned skips, and the PostgreSQL-enabled full backend passed
2620 with 37 dependency-conditioned skips and 2 deselected. A downstream failure can
leave the exact policy-bounded Grant active; no selective revoke/reconciler,
operator-command audit storage, live upstream smoke, deployment or Production GO was
added.

[KNOWN | HIGH] TDD-05N adds the checked-in production-local immutable Query Grant
policy/runtime client bootstrap from ADR-0221. KSS process configuration strictly parses
one secret-free policy, API composition injects it only into the operator-authenticated
runtime, and a hardened one-shot bootstrap registers the existing runtime credential
digest without creating a Grant. Static contracts bind policy/bootstrap client identity
and make KSS API wait for both runtime and Reference bootstrap. An isolated PostgreSQL
vertical reads those checked-in facts and proves Reference → operator Grant → bounded
exact-Release Query; runtime and Reference credentials cannot self-grant. The affected
set passed 84 tests, KSS contracts passed 422 with 13 dependency-conditioned skips, and
the PostgreSQL-enabled full backend passed 2624 with 37 dependency-conditioned skips
and 2 deselected. No production-local full stack, real model, formal publication,
deployment or Production GO was executed.

[KNOWN | HIGH] TDD-05O adds an explicit production-local exact Query authority verifier.
It takes one caller-selected existing Release, uses operator authority to provision or
replay the deployment-owned Grant, then uses the separate runtime client for one bounded
Query while checking client, Release, strategy, budget and access scope. Retained-volume
upgrade preserves the existing `proof-agent-production-local` runtime identity and the
current checkout passes full-stack build/up plus the baseline verifier. The selected live
Release failed closed before Query because all retained queryable Releases already have
different immutable historical smoke Grants. Isolated PostgreSQL proves the positive
path. The operator subsequently published a separate exact local Release outside the
verifier by using the existing KSS management publication API. Two live verifier runs
replayed one exact active Grant and completed two distinct bounded Queries with 3
candidates each. No historical Grant was rewritten, revoked or deleted. TDD-05O is
`LOCAL_VERIFIED`; the feature remains `PARTIAL_VERIFICATION`.

[KNOWN | HIGH] TDD-05P adds a read-only production-local Formal Candidate preflight over
the same production command composition. It accepts only exact Agent/Draft/revision,
uses the deployment-owned Profile, emits secret-free candidate facts, and never reserves
a command or enters Phase F, Reference, Grant, smoke, Version or activation stages. The
current retained Draft@12 fails closed with `memory_must_be_disabled`; Tools are disabled
but Memory is enabled. Six publication/KSS table counts were unchanged before and after
the live run. The preflight capability is `LOCAL_VERIFIED`, the current candidate remains
`BLOCKED`, and no publication approval or Production GO exists.

[KNOWN | HIGH] TDD-05Q adds a bounded production-local exact Draft Memory repair that
reuses the existing Workspace complete-Contract validator, revision CAS, atomic save and
configuration audit. A validation-first live failure proved disabled Memory must also
remove its provider and left Draft@12/audit count 6 unchanged. The refined command changed
only the Memory mapping, advanced the retained Draft to revision 13 and audit count to 7,
then rejected replay with `draft_memory_already_disabled`. Read-only preflight now assembles
Draft@13 and returns formal candidate SHA-256
`ecd122b4a85e0bf5d0899e07e26e69eda043814880b9b3be59660475dccaf272` with
`publication_authorized=false`. Formal Command, Version, Active and KSS Reference counts
remain 0; Grant remains 4 and Query remains 19. This is `LOCAL_VERIFIED`, not formal
publication approval or Production GO; the old Release's historical Grant conflict and
all later publication Gates remain independent blockers.

| Feature ID | Status | Evidence directory | Governing design |
| --- | --- | --- | --- |
| `knowledge-source-service` | `PARTIAL_VERIFICATION` | `docs/features/knowledge-source-service/` | ADR-0210 and `docs/superpowers/specs/2026-08-11-knowledge-source-service-design.md` |
| `kss-configuration-publication-loop` | `PARTIAL_VERIFICATION` | `docs/features/kss-configuration-publication-loop/` (TDD-01A/01B local wiring; TDD-02A through 02G Preparation core; TDD-03A through 03F Reference/lifecycle core; TDD-04A lifecycle/reference-summary read BFF; TDD-04B Profile → Synchronization management BFF; TDD-04C Base Draft save/exact read → Preparation start/status BFF; TDD-04D optional one-shot Preparation execution runtime; TDD-04E controlled Preparation publication BFF; TDD-04F controlled Preparation cancellation BFF; TDD-04G bounded Preparation audit read BFF; TDD-04H exact-resource Preparation expiry BFF; TDD-05A exact Draft/KSS/Profile formal-candidate assembler; TDD-05B candidate-bound Phase F preparation; TDD-05C Reference-first Control staging; TDD-05D authenticated Reference registration transport; TDD-05E exact online smoke Control; TDD-05F application-only formal publisher core and atomic activation; TDD-05G governed online smoke runner adapter; TDD-05H durable-idempotency public formal command; TDD-05I production API composition cutover and legacy manifest production-entry removal; TDD-05J production-local dedicated Reference client contract and isolated registration vertical; TDD-05K application-only runtime Query Grant core and isolated Query vertical; TDD-05L operator-authenticated Query Grant HTTP and ProofAgent guarded adapter; TDD-05M candidate-bound Query Grant Control staging and formal online-smoke precondition; TDD-05N production-local immutable Query Grant policy/runtime client bootstrap and isolated Reference → Grant → Query vertical; TDD-05O explicit exact Query authority verifier, retained-volume bootstrap compatibility, live conflict failure and exact Grant replay evidence; TDD-05P read-only production-local Formal Candidate preflight with live `memory_must_be_disabled` fail-closed evidence and zero publication/KSS writes; TDD-05Q exact Draft Memory normalization through existing Contract validation/CAS/audit with Draft@13 candidate-assembly evidence and zero publication/KSS writes; no Dashboard Profile/Base Preparation page, continuous Preparation process role, automatic expiry scheduler or deregistration/lifecycle command BFF, terminal-operator KSS audit delegation, background reconciler, Query Grant selective revoke/reconciliation or operator-command audit, production Vault/egress/TLS or artifact-retention adapter/physical deletion, affected-reference detail/notification, live external KSS/model upstream smoke evidence, command recovery/takeover, runtime revocation integration or production cutover) | ADR-0211 through ADR-0221 |
| `production-agent-lifecycle` | `PARTIAL_VERIFICATION` | `docs/features/production-agent-lifecycle/` | ADR-0124 and `docs/superpowers/plans/2026-07-11-proofagent-s5-sole-agent-migration-plan.md` |
| `product-release-authority` | `VERIFIED_LOCAL` | `docs/features/product-release-authority/` | ADR-0132 and ADR-0208 |
| `agent-configuration-workspace` | `VERIFIED_LOCAL` | `docs/features/agent-configuration-workspace/` | ADR-0009、ADR-0011 与 2026-08-18 架构评审 Phase 3 |

## Status vocabulary

- `SCOPING`: behavior or authority remains undecided.
- `TDD_INPUT_READY`: scope and acceptance evidence are sufficient to start RED.
- `IMPLEMENTING`: at least one TDD slice is active, but feature acceptance is not
  complete.
- `PARTIAL_VERIFICATION`: implementation and default local checks pass, but one or
  more named P1 environment-backed checks remain unexecuted; this is not production
  approval.
- `VERIFIED_LOCAL`: recorded local acceptance checks pass; local Docker evidence
  may exist, but the status is not production approval or a formal release Gate.
- `BLOCKED`: a named dependency or decision prevents meaningful progress.
