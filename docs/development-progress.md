# Development Progress

Updated: 2026-09-03

## Current decision

[KNOWN | HIGH] ADR-0210 makes KSS the only executable knowledge authority. A
knowledge-enabled Published Agent Version owns one exact KSS binding and ProofAgent
keeps only the KSS client, exact Admission Scorer client and Control Plane Admission.
The former Hybrid provider, source-management API, ingestion/publication worker,
repositories, CLI and Dashboard paths are deleted. Old Hybrid-bound Agent Versions
cannot replay or roll back. Formal production release remains **NO-GO** until an
approved scorer revision, exact grant and versioned secret, real dependency readiness,
shadow/pilot/recovery evidence and all Product Release Authority Gates pass.

[KNOWN | HIGH] ADR-0239 now separates physical product ownership as well: KSS source,
migrations, distribution, internal contract tests and formal five-role Compose were
extracted to the independent local project `/Users/jamin/Dev/mz-projects/KSS` and removed
from ProofAgent. ProofAgent production-local Compose consumes only an explicit external
immutable `KSS_IMAGE`; guarded clients, Candidate Binding, Admission and final answer
authority remain here. This is a local repository migration, not a production data
migration, deployment, release or cutover.

[FRAME | HIGH] ADR 0153 formally defers runtime Case Memory from the initial private pilot. The production Agent remains memory-disabled and PostgreSQL conversation context remains non-evidence. Existing Case Memory contracts, schema and repositories are dormant infrastructure, not an advertised release capability.

## 2026-09-02 Deployed rollback gate-closed probe (TDD-06I)

- [KNOWN | HIGH] ADR-0238 adds one explicit production-local host entry. It accepts
  only a private `0600` session JSON file path, rejects symlinks and group/other
  permissions, reuses the bounded TLS client, follows a rotated session cookie, and
  never prints the cookie or current CSRF token.
- [COMPUTED | HIGH] One fixed fictional rollback request now covers the deployed
  admission contract in three states: unauthenticated `401`, authenticated without
  same-origin CSRF `403`, and authenticated with `agent.publish` plus current CSRF
  returning the exact `503 production_agent_rollback_unavailable`. Seven focused tests
  and 109 affected tests passed with one existing Authlib warning.
- [COMPUTED | HIGH] The restricted full-backend run passed 2520 tests, skipped 277
  dependency-conditioned tests, deselected 2, and reported 8 socket-permission failures.
  All 45 tests in the four loopback-dependent files then passed outside the restricted
  sandbox. Ruff, Mypy over 474 sources, lock, domain-context, shell syntax and diff
  checks passed.
- [COMPUTED | HIGH] The current production-local image built successfully. The baseline
  passed TLS API/KSS, Dashboard, OIDC, model-plane, OpenSearch, both migration ledgers,
  KSS PostgreSQL authority isolation and both versioned buckets. Readiness returned the
  expected fail-closed `503` only because `published_agent=not_ready`. A fixed fictional
  unauthenticated rollback POST then returned `401 authentication_required` through the
  real TLS Gateway.
- [BOUNDARY | HIGH] No Operator-controlled private session file was supplied, so the
  authenticated `403/503` states and the complete checked-in verifier were not run
  against the Gateway/API. The real gate remains `false`; no successful rollback,
  Agent/KSS business-state access, KSS Query, model, ArtifactStore write, Phase F,
  publication, Release Gate or Production GO occurred. TDD-06I remains
  `PARTIAL_VERIFICATION`.

## 2026-09-01 Isolated real-dependency rollback rehearsal (TDD-06H)

- [KNOWN | HIGH] ADR-0237 adds a zero-argument verification entry that uses an exact
  disposable Compose project and `--env-file /dev/null`. Each test creates separate
  random PostgreSQL schemas for ProofAgent and KSS; no existing production-local data
  is read or changed.
- [COMPUTED | HIGH] The Production rollback POST ran through OIDC session,
  same-origin CSRF, `agent.publish`, the existing Workspace, a real KSS management
  HTTP client and real PostgreSQL authorities. A queryable Release committed one
  pointer/audit pair; a Release retired through the real KSS lifecycle returned the
  stable 409 and left both unchanged. The zero-argument entry passed 2 cases and its
  exact Compose project was empty after cleanup.
- [COMPUTED | HIGH] The non-database affected set passed 153 tests with one existing
  Authlib warning. The complete PostgreSQL-enabled backend passed 2761 tests, with 37
  dependency-conditioned skips, 2 deselections and the same warning. The new
  PostgreSQL tests were required and did not skip.
- [BOUNDARY | HIGH] The gate was true only in test composition. Real Production still
  passes `production_agent_rollback_enabled=False`. KSS used an in-process HTTP test
  transport and memory artifact storage; this is not deployed TLS/Vault/egress,
  multi-process topology, cross-service lease, online rollback, Release Gate evidence
  or Production GO.

## 2026-09-01 Production rollback admission contract (TDD-06G)

- [KNOWN | HIGH] ADR-0236 registers one strict Production Agent Version rollback
  POST on the existing Production configuration router. The body requires
  `expected_active_version_id`, including explicit JSON `null` for a confirmed
  no-Active state. Delivery requires `agent.publish`, projects the authenticated
  actor, and calls only the existing `AgentConfigurationWorkspace.rollback_version()`.
- [KNOWN | HIGH] One composition-owned `production_agent_rollback_enabled` gate
  controls command admission and the Draft `can_rollback` projection. `create_app`
  defaults it to `false`, and the real Production API composition passes `false`
  explicitly. Disabled admission returns `production_agent_rollback_unavailable`
  without a Workspace call.
- [COMPUTED | HIGH] RED evidence covered the missing Production route, a capability
  that stayed false under an enabled test gate, KSS Catalog unavailability mapped as
  409 instead of 503, an unstructured internal 500, and the real composition omitting
  an explicit false gate. The focused rollback contract passed 10 cases; three
  Production app security checks passed, including OIDC session and same-origin CSRF
  around the enabled test command.
- [COMPUTED | HIGH] The affected Production Agent/API/composition set passed 95 tests
  with one existing Authlib warning. The complete default backend passed 2520 tests,
  with 275 dependency-conditioned skips, 2 deselections, and the same warning. Ruff
  and mypy over 372 product sources passed.
- [BOUNDARY | HIGH] The real Production gate remains false. This slice did not change
  role mappings or Dashboard code; call real PostgreSQL, KSS, a model, or ArtifactStore;
  execute a rollback; create or deregister a Grant/Reference; enter Phase F; publish;
  deploy; establish a cross-service lease; or grant Production GO.

## 2026-09-01 PostgreSQL rollback transaction vertical verification (TDD-06F)

- [KNOWN | HIGH] TDD-06F adds a PostgreSQL integration test boundary around the
  existing `AgentConfigurationWorkspace.rollback_version()` and the production
  `PostgresConfigurationUnitOfWork`. It uses only fictional Agent/Version facts, a
  fixed in-memory ready KSS Catalog, and one isolated disposable PostgreSQL schema.
- [KNOWN | HIGH] This was a verification-first slice. The first valid vertical
  success test passed without a production-code change; the evidence gap was the
  missing combined test, not an observed rollback defect. The slice did not create
  an artificial RED or add another rollback/repository abstraction.
- [COMPUTED | HIGH] Three focused cases passed against PostgreSQL 17.5: pointer and
  audit committed together while both Published Versions remained immutable; two
  commands sharing one caller expectation produced one winner, one
  `active_agent_version_conflict`, and one audit; an injected failure after audit
  append rolled pointer and audit back together. The affected PostgreSQL Workspace,
  Agent Repository, and Configuration UoW set passed 15 tests.
- [COMPUTED | HIGH] The complete PostgreSQL-enabled backend suite passed 2747 tests
  with 37 dependency-conditioned skips, 2 deselections, and 1 existing Authlib
  warning. Ruff, mypy over 372 product sources, domain-context, lock-file, and diff
  checks passed. The test container and anonymous data volume were removed; an
  unrelated pre-existing orphan container was left untouched.
- [BOUNDARY | HIGH] Production still advertises `can_rollback=false`. This slice
  did not call a real KSS, model, or ArtifactStore; change a Grant/Reference; enter
  Phase F; publish a Version; expose a Production command; deploy; execute an online
  rollback; establish a cross-service transaction/lease; or grant Production GO.

## 2026-09-01 Caller-bound rollback confirmation freshness (TDD-06E)

- [KNOWN | HIGH] ADR-0235 makes `expected_active_version_id` a required part of
  the existing rollback command. `None` is an explicit no-active expectation;
  omission is invalid. The Workspace compares the caller-confirmed value before
  the KSS Catalog preflight and again in the write Unit of Work, then uses the
  same value for `rollback_from_version_id` and pointer compare-and-swap.
- [KNOWN | HIGH] The development rollback HTTP request now requires the expected
  pointer, and Agent Detail sends the Active Version displayed in its confirmation
  dialog. Production configuration remains unchanged with `can_rollback=false`.
- [COMPUTED | HIGH] RED evidence covered the missing Workspace parameter, pointer
  drift after KSS preflight, omitted/unknown development request fields, and the
  old empty Dashboard body plus dialog-rerender pointer adoption. GREEN/REFACTOR
  passed 18 Workspace rollback cases, 11 API rollback cases, and 84 focused
  Dashboard cases; the confirmation now freezes both target and expected pointer.
- [COMPUTED | HIGH] Full local verification passed 2509 backend tests with 272
  dependency-conditioned skips, 2 deselections, and 1 existing Authlib warning;
  the sandbox-only first run failed 8 existing loopback-bind cases, and the same
  command passed when local loopback was allowed. Dashboard passed 225 tests,
  Operator Chat passed 35, TypeScript and both production builds passed. Ruff,
  mypy over 372 product sources, domain-context, lock-file, and diff checks passed.
- [BOUNDARY | HIGH] This is local development evidence only. The slice did not
  call KSS, a model, or ArtifactStore; create or change a Grant/Reference; enter
  Phase F; publish or activate a new Version; expose Production rollback; deploy;
  execute a real rollback; or grant Production GO.

## 2026-09-01 Release-state rollback fail-closed core (TDD-06D)

- [KNOWN | HIGH] ADR-0234 keeps the existing
  `AgentConfigurationWorkspace.rollback_version()` application interface and adds one
  live KSS Catalog preflight before any active-pointer or audit write. `queryable` and
  `deprecated` exact Releases remain eligible; `retired`, `revoked`, missing,
  ambiguous or unavailable catalog facts fail closed with stable conflict codes.
- [KNOWN | HIGH] Formal Published Agent Versions resolve the retained
  Space/Base/Release Reference. A non-formal KSS-bound version is accepted only when
  its immutable Release ID has one catalog match. The target is read before the remote
  check and reread before the local write; drift creates no activation or audit.
- [COMPUTED | HIGH] RED reproduced the missing guard for both `retired` and `revoked`
  targets: the old implementation did not raise. GREEN/REFACTOR pass 16 rollback
  scenarios and all 67 Agent Configuration Workspace tests. The affected set passed
  193 tests with 14 conditioned skips; the complete backend passed 2505 with 272
  conditioned skips and 2 deselected after enabling required loopback sockets. Ruff,
  Mypy over 372 sources, domain-context, lock and diff checks passed.
- [BOUNDARY | HIGH] This is an application-core guard, not a production rollback
  endpoint or distributed transaction. It calls no KSS Query, external model or
  ArtifactStore; creates no Grant, Reference, Phase F, Version or publication state;
  and does not establish a release Gate or Production GO.

## 2026-09-01 fixed-synthetic governed Run verification (TDD-06C)

- [KNOWN | HIGH] ADR-0233 adds a zero-argument production-local verifier that advances
  the fixed synthetic Candidate through the public `execute_agent_package_run()` entry.
  Only the KSS service port is in memory; production runtime binding, query factory,
  Admission Scorer, Controlled ReAct, Evidence Evaluation, citation and receipt remain
  on the current execution path.
- [KNOWN | HIGH] The production-local run returned `answered_with_citations`, one
  Accepted Evidence item and one citation. Trace and receipt existed only in a temporary
  directory and were removed after verification. A low score fails closed; public
  failures contain only a stable envelope and allowlisted stage.
- [COMPUTED | HIGH] Initial RED produced 4 expected missing-entry failures. Two later
  focused RED tests caught missing stage projection and a read-only-container audit-path
  mismatch. The final focused set passed 6 tests, the affected set passed 104, and the
  complete backend passed 2496 with 272 conditioned skips, 2 deselected and one existing
  Authlib warning. Ruff, CI-scope Mypy, verifier Mypy and shell syntax passed.
- [KNOWN | HIGH] Independent immutable overlay image
  `5614b7398ee396d8d37ab153400a5055649932070f5ce83b5cc00a32870f3436` copied only the
  final verifier onto the previously baselined image. API, model-plane and Run Executor
  used that exact digest; the full baseline and checked-in zero-argument host entry
  passed. KSS Query remains 22, Formal Command remains 0 and `/readyz` remains the
  expected 503 only because `published_agent=not_ready`.
- [BOUNDARY | HIGH] Two full builds and two narrowed ordinary builds stalled at external
  base-image metadata resolution and were stopped. TDD-06C core behavior and immutable
  overlay host entry are `LOCAL_VERIFIED`, but the full production Dockerfile build is
  pending. This evidence does not cover a real KSS Query, Draft@14, DeepSeek, durable
  ArtifactStore, Phase F or formal publication and does not establish external
  cited-answer evidence, a release Gate or Production GO.

## 2026-09-01 fixed-synthetic Control Plane Admission verification (TDD-06B)

- [KNOWN | HIGH] ADR-0232 adds a second zero-argument production-local verifier. It
  places one fixed in-memory Candidate Result only at the KSS service boundary, then
  executes the public Knowledge Retrieval Service, deterministic Policy, deployment-owned
  Admission Scorer and Evidence Evaluation.
- [KNOWN | HIGH] The live verifier returned policy `default.allow`, Evidence Validation
  `passed` and accepted count 1. Policy denial stops before scoring; a score below the
  fixed threshold fails closed. Public output excludes the question, Candidate identity/
  content, score, threshold, citation, credential, endpoint and raw response.
- [COMPUTED | HIGH] RED produced 5 expected target failures while 10 prior checks stayed
  green. The final focused set passed 16 tests, the affected set passed 45, and the
  complete backend passed 2490 with 272 conditioned skips, 2 deselected and one existing
  Authlib warning. Ruff passed and Mypy passed 374 source files.
- [KNOWN | HIGH] Rebuilt production-local image
  `4a78f9e64024f51bf7e70392c9849ee7fd6b8766e64b41a21eca4bdf101e6fd6` passed the
  baseline. KSS Query count remains 22 and Formal Command count remains 0; `/readyz`
  remains the expected 503 only because `published_agent=not_ready`.
- [FRAME | HIGH] TDD-06B is `LOCAL_VERIFIED`; the Feature remains
  `PARTIAL_VERIFICATION`. It did not call a real KSS Query, DeepSeek, Artifact Store,
  Phase F or formal publication and does not establish positive cited-answer evidence,
  a release Gate or Production GO.

## 2026-09-01 fixed-synthetic production-local Admission Scorer verification (TDD-06A)

- [KNOWN | HIGH] ADR-0231 adds one zero-argument production-local verifier. It binds the
  deployment-owned Admission Scorer through the normal production runtime and scores one
  fixed synthetic Candidate. Callers cannot provide a Draft, Release, question, Candidate,
  Model Connection, credential or budget.
- [KNOWN | HIGH] Success proves the current compatibility Scorer ID/revision, versioned
  Secret Handle, Vault resolution, guarded egress and strict exact-candidate response
  contract work together. Output omits the synthetic input, Candidate identity/content,
  score, credential, endpoint and raw response.
- [COMPUTED | HIGH] RED produced 5 expected missing-entry failures. The final focused set
  passed 10 tests, the affected set passed 59, and the complete backend passed 2484 with
  272 conditioned skips, 2 deselected and one existing Authlib warning.
- [KNOWN | HIGH] Rebuilt production-local image
  `e2bb61b0c78a7e648ccd4d662a4094660327094f49c49ca804f7fb6b79011088` passed the baseline.
  The fixed synthetic live verifier returned one score for one Candidate. KSS Query count
  remains 22 and Formal Command count remains 0; `/readyz` remains the expected 503 only
  because `published_agent=not_ready`.
- [FRAME | HIGH] TDD-06A is `LOCAL_VERIFIED`; the Feature remains
  `PARTIAL_VERIFICATION`. It did not call KSS or DeepSeek and cannot establish Draft@14
  root cause, positive external cited-answer evidence, Phase F, publication approval,
  release Gate or Production GO.

## 2026-08-31 bounded Evidence Admission reason diagnostics (TDD-05Z)

- [KNOWN | HIGH] ADR-0230 keeps the external probe Admission stage code and adds six
  content-free reasons for scorer unavailable, invalid score, empty Candidate set,
  missing score, threshold not met and policy denial. Unknown facts remain unclassified.
- [KNOWN | HIGH] The scorer port now carries one typed `PA_KNOWLEDGE_001` reason. A
  completed Run may derive a reason only from existing trace-safe Evidence Evaluation
  metadata; exception text is never parsed.
- [KNOWN | HIGH] Evidence returned with managed scores below `min_score` now records
  `knowledge_candidate_threshold_not_met` instead of the incorrect
  `zero_knowledge_candidates` metadata.
- [KNOWN | HIGH] The strict failure envelope advances to
  `production-local-formal-candidate-external-smoke-failure.v2`; success remains v1.
  Only Admission failures may include an allowlisted `reason_code`.
- [COMPUTED | HIGH] RED reproduced four missing behaviors. The final core set passed 11
  tests, the affected set passed 146, and the complete backend passed 2474 with 272
  conditioned skips, 2 deselected and one existing Authlib warning.
- [FRAME | HIGH] TDD-05Z is `LOCAL_VERIFIED`; the Feature remains
  `PARTIAL_VERIFICATION`. No KSS, scorer or model call ran, so this slice does not
  retroactively classify TDD-05Y, authorize a retry, or provide publication/Production
  GO evidence.

## 2026-08-31 validation ArtifactStore cutover and explicit external gate (TDD-05Y)

- [KNOWN | HIGH] ADR-0229 removes the validation-only legacy artifact protocol. Agent
  validation now writes RUN_TRACE/GOVERNANCE_RECEIPT through the current
  `ArtifactStore`, verifies exact owner/kind/digest/length plus head/open read-back, and
  returns the existing public exact reference with a store-produced credential-free URI.
- [COMPUTED | HIGH] The related set passed 115 tests; the full backend passed 2467 with
  272 conditioned skips and 2 deselected. Mypy passed 372 product sources, Ruff passed,
  and focused formatting passed. The rebuilt image
  `1847e70c79bbaf57b36ce93a4a1eaba3267ad37cf4346aa462ec0b3ef4e1be2d`
  passed production-local baseline.
- [KNOWN | HIGH] Real MinIO verified a trace/receipt pair through immutable write, exact
  head/open, canonical URI including the `runs/` prefix, and exact deletion. Draft@14
  read-only preflight also passed with unchanged Candidate/Release digests and
  `publication_authorized=false`.
- [KNOWN | HIGH] After explicit approval of exact Draft@14, managed connection
  `model_deepseek` revision 1 and the bounded side effects, the existing host entry ran
  exactly once. It returned
  `formal_candidate_external_smoke_evidence_admission_failed` and stopped without retry.
- [KNOWN | HIGH] The call replayed existing succeeded Query
  `knowledge-query-f25bebcd4a9946578c46280a68387e32`, whose available result retains 3
  candidates and its prior digest. Query count therefore stayed 22 rather than creating
  a 23rd row. Command/Version/Active/Reference/Artifact remain 0 and Grant remains 5.
- [KNOWN | HIGH] The production-local baseline passed again after the governed failure;
  readiness remains the expected HTTP 503 only because `published_agent=not_ready`.
- [FRAME | HIGH] The ArtifactStore cutover is `LOCAL_VERIFIED`; the Feature remains
  `PARTIAL_VERIFICATION`. The bounded Evidence Admission failure is not positive external
  cited-answer evidence, and no formal publication, release Gate or Production GO
  follows from this slice. The one-use authorization is consumed and cannot be retried
  automatically.

## 2026-08-31 secret-free external probe stage diagnostics (TDD-05X)

- [KNOWN | HIGH] ADR-0228 adds five stable failure codes to the existing exact Formal
  Candidate probe: KSS, Evidence Admission, configured model, citation validation and
  artifact retention. Unknown or ambiguous failures keep the generic
  `formal_candidate_external_smoke_failed` code.
- [KNOWN | HIGH] Classification uses only existing structured subsystem codes,
  accepted/citation facts and trace-safe final-answer validation events. It does not
  parse exception messages, provider responses, questions, answers or Evidence content.
  The CLI still returns only its bounded failure schema and one stable code.
- [KNOWN | HIGH] The implementation is enabled only for the external probe invocation
  of the shared governed runtime. Formal online smoke and production candidate
  validation retain their existing behavior; no alternate executor, retry, API,
  Dashboard surface, Grant mutation or publication side effect was added.
- [COMPUTED | HIGH] External-probe behavior passed 18 tests; the complete two focused
  files passed 95 and the reference-derived affected set passed 118 with one existing
  warning. The complete backend passed 2467 tests with 272 dependency-conditioned skips
  and 2 deselected after the 8 loopback-socket tests were rerun outside the restricted
  sandbox. Full Ruff, focused format, Mypy over 372 source files and diff checks passed.
- [FRAME | HIGH] TDD-05X is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. No real KSS or model probe ran in this slice, so the prior
  Draft@14 generic failure cannot be classified retroactively. Positive external cited
  answer evidence remains `BLOCKED`. A new probe still requires fresh explicit
  authorization for the exact Candidate and allowed Query/artifact side effects.

## 2026-08-31 exact Draft Contract path normalization (TDD-05W)

- [KNOWN | HIGH] ADR-0227 adds one bounded production-local exact Draft CAS. It accepts
  only Agent/Draft/expected revision and fixes the two target paths in checked-in code;
  callers cannot supply YAML or path values.
- [KNOWN | HIGH] The command accepts only the exact legacy pair and changes only the
  scalar values for `audit.trace_path` and `audit.receipt_path`. Missing, duplicate,
  mixed, unexpected or already-normalized paths fail before Workspace persistence.
- [COMPUTED | HIGH] Focused behavior passed 15 tests; the affected set passed 123. The
  complete backend passed 2456 tests with 272 dependency-conditioned skips and 2
  deselected. Full repository Ruff and Mypy (374 source files), focused format, uv lock,
  domain-context, Shell syntax and diff checks passed.
- [KNOWN | HIGH] After one transient Docker Hub token EOF before product build, the
  retried production-local build succeeded with image
  `bf5fb14877db747a4ff9e3a0e0df1d1f36461903ce6e91240c6e68d3d0356998`.
  Baseline verification passed at schema `0024_formal_candidate_checkpoint`.
- [KNOWN | HIGH] The exact CAS advanced Draft 13 to 14 and contract-update audit count
  7 to 8. It returned `./trace.jsonl` and `./governance_receipt.md`. Replay against
  revision 14 failed with `draft_contract_paths_already_normalized`; revision 15 was not
  created.
- [KNOWN | HIGH] Draft@14 read-only preflight succeeded. Its Formal Candidate digest is
  `1e5aee4b24b184333a1d4f4d0a7798716cf8cfe426da4046605c06d3aea063bd` and its
  Knowledge Release candidate digest is
  `085038769d44ded6f031de42a8eaf3fa4a723d390eb45db9da2b5914bea89299`.
  `publication_authorized` remains false.
- [KNOWN | HIGH] After explicit authorization, the exact Draft@14 external-dependency
  probe ran once and returned bounded error `formal_candidate_external_smoke_failed`.
  The new KSS Query `knowledge-query-f25bebcd4a9946578c46280a68387e32` succeeded on
  `release-a4b70851cb914862000e15c3` with 3 candidates and a retained result digest.
  Query count advanced 21 to 22. No retry was attempted.
- [KNOWN | HIGH] The Draft selects active Model Connection `model_deepseek` revision 1
  (`deepseek` / `deepseek-v4-flash`; host `api.deepseek.com`). The bounded failure does
  not distinguish Evidence Admission, external model response/transport, citation
  validation or pre-retention execution failure. ProofAgent validation artifacts remain
  0, so no immutable trace/receipt evidence exists.
- [FRAME | HIGH] TDD-05W remains `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. Command, Version, Active and Reference remain 0; Grant remains
  5. Positive external cited-answer evidence is `BLOCKED`, not Production GO. TDD-05X
  now provides secret-free stage classification, but it did not rerun or retroactively
  classify this probe. Any retry still needs separate authorization.

## 2026-08-31 exact Formal Candidate external dependency probe (TDD-05V)

- [KNOWN | HIGH] ADR-0226 adds one explicit production-local probe outside formal
  publication. It accepts only exact Agent/Draft/revision, assembles the Candidate through
  production composition, uses a checked-in non-sensitive question and cannot select a
  Release, model, credential, Profile or budget.
- [KNOWN | HIGH] A materializable Candidate runs through the governed KSS-only
  `RunPurpose.VALIDATION` path, Evidence Admission and configured external model. Success
  requires `ANSWERED_WITH_CITATIONS`, at least one accepted nonblank citation and exact
  immutable trace/receipt read-back. Output excludes question, answer, Candidate/Evidence
  content, credentials, raw prompts and upstream detail.
- [COMPUTED | HIGH] Focused and affected behavior passed 156 tests. The complete backend
  passed 2441 tests with 272 dependency-conditioned skips and 2 deselected. Ruff, focused
  format, Mypy over 372 source files, lock, domain-context and Shell checks passed.
- [KNOWN | HIGH] Rebuilt production-local image
  `be61c35f3bfe3ddb439f30ffbd96f048c0816129fec315890dabe930d60bda63`
  passed its baseline at schema `0024_formal_candidate_checkpoint`; readiness remains the
  expected HTTP 503 only because `published_agent=not_ready`.
- [KNOWN | HIGH] The live exact Draft@13 probe stopped before KSS Query with
  `formal_candidate_contract_bundle_not_materializable`. Its immutable Contract Bundle
  contains package-escaping audit paths, so the secure materializer rejected it. Counts
  remained Command 0, Version 0, Active 0, Reference 0, Grant 5 and Query 21.
- [FRAME | HIGH] The TDD-05V implementation and fail-closed boundary are
  `LOCAL_VERIFIED`; the current Draft@13 external-dependency probe is `BLOCKED`, and the
  feature remains `PARTIAL_VERIFICATION`. No external KSS/model positive evidence,
  formal online-smoke qualification, publication approval or Production GO exists.

## 2026-08-31 actor-owned formal command status read (TDD-05U)

- [KNOWN | HIGH] ADR-0225 keeps exact POST replay as the only formal-command recovery
  mutation. The new exact-resource GET returns one existing public receipt and never
  acquires, renews or takes over the command lease.
- [KNOWN | HIGH] The read requires `agent.publish` and the exact creating actor subject.
  Missing command, another actor, or mismatched Agent/Draft path all return
  `formal_publication_command_not_found`. The response excludes actor, idempotency key,
  execution claim, Candidate checkpoint and raw request facts.
- [COMPUTED | HIGH] Focused application/API behavior passed 3 tests; the combined formal
  application and API files passed 131. PostgreSQL repository/migration contracts passed
  38 against a disposable PostgreSQL 17.5 instance, and the affected security,
  Persistence, Delivery and production-composition set passed 201.
- [COMPUTED | HIGH] The complete backend passed 2433 tests with 272
  dependency-conditioned skips and 2 deselected. Ruff and Mypy over 372 product source
  files passed.
- [KNOWN | HIGH] The rebuilt production-local image
  `030ce1a17c01768206759250bfb8b9db98133ff43ec2399e55d6f23e6cd33fb1`
  reached schema head `0024_formal_candidate_checkpoint` and passed the baseline.
  Formal Command, checkpoint, Published Version and Active Version counts remain zero.
- [FRAME | HIGH] TDD-05U is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. No formal publication POST or production-local command-status
  GET was invoked. Cross-operator audit/listing, background recovery, real external
  KSS/model evidence and Production GO remain separate work.

## 2026-08-31 durable Formal Candidate checkpoint (TDD-05T)

- [KNOWN | HIGH] ADR-0224 makes the first durable Formal Candidate identity part of
  each `in_progress` formal publication command. After read-only assembly and before
  Phase F, the current fenced execution atomically stores the formal-candidate digest,
  Knowledge Release candidate digest and PostgreSQL checkpoint time.
- [KNOWN | HIGH] An expired-command takeover still reassembles the Candidate from the
  exact Draft revision, live KSS catalog and deployment Profile. Both digests must match
  the checkpoint. Drift ends the original command with
  `formal_publication_candidate_checkpoint_conflict` before Phase F, Reference, Grant,
  smoke or publication; the checkpoint cannot be rebound.
- [KNOWN | HIGH] Migration `0024_formal_candidate_checkpoint` is expand-only. Exact
  checkpoint replay preserves the original timestamp; concurrent different candidates
  converge on one immutable checkpoint. Terminal commands and stale fencing tokens
  cannot create or change it.
- [COMPUTED | HIGH] Formal command behavior passed 76 tests. PostgreSQL repository,
  migration and production migration contracts passed 37; the affected set passed 196.
  The full backend passed 2430 with 271 dependency-conditioned skips and 2 deselected.
  Ruff and Mypy over 372 product source files passed.
- [KNOWN | HIGH] The rebuilt production-local image
  `9ea9b8a726e5c38c6b535d00c26f5078ba6515493fa2a961813fb3340c971493`
  reached schema head `0024_formal_candidate_checkpoint` and passed the baseline.
  Formal Command, checkpoint, Published Version and Active Version counts remain zero.
- [FRAME | HIGH] TDD-05T is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. No formal endpoint was invoked. A background recovery process,
  real external KSS/model evidence, Query Grant lifecycle, operator-command audit and
  Production GO remain separate work.

## 2026-08-31 formal publication fenced recovery (TDD-05S)

- [KNOWN | HIGH] ADR-0223 gives each durable `in_progress` formal publication command
  one database-time lease, execution owner and monotonic fencing token. Exact replay
  before expiry returns the same in-progress receipt without external work; exact replay
  after expiry may atomically acquire one new claim. A stale owner cannot commit success
  or failure after takeover.
- [KNOWN | HIGH] Phase F Record, provisional Version, validation Run and downstream
  Reference identities are now derived from the durable command identity, and Phase F
  uses the original command receipt time. A recovered execution therefore repeats the
  same external identity rather than creating a second logical publication attempt.
- [KNOWN | HIGH] Migration `0023_formal_publish_claim` is expand-only. Deployment owns
  `PROOF_AGENT_FORMAL_PUBLICATION_COMMAND_LEASE_SECONDS`; parsing accepts 1–3600 seconds,
  defaults to 900, and the checked-in production-local stack explicitly uses 900.
- [COMPUTED | HIGH] The formal command behavior file passed 74 tests. A disposable
  PostgreSQL 17.5 run passed 11 repository and migration tests; the affected set passed
  178. The full backend passed 2428 with 269 dependency-conditioned skips and 2
  deselected. Mypy covered 371 product source files. The rebuilt production-local stack
  reached schema head `0023_formal_publish_claim`, passed its baseline verifier, and kept
  Formal Command, Published Version and Active Version counts at zero.
- [FRAME | HIGH] TDD-05S is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. No formal endpoint was invoked and no Production GO exists.
  Candidate checkpointing was the next separate slice and is completed by TDD-05T
  above. A background recovery process, real external KSS/model evidence, Query Grant
  lifecycle and operator-command audit remain separate slices.

## 2026-08-31 production-local versioned runtime Grant cutover (TDD-05R)

- [KNOWN | HIGH] ADR-0222 moves active checked-in production-local Query authority to
  `proof-agent-production-local-v2`. ProofAgent runtime, the KSS immutable policy and
  runtime bootstrap use the same identity, while a distinct Secret Handle, Vault path
  and generated local credential isolate it from retained historical clients.
- [KNOWN | HIGH] Existing clients, Secret material and Grants were not compared,
  rewritten, revoked or deleted. The active ProofAgent locator no longer includes the
  old runtime Handle. KSS bootstrap still registers only a credential digest, and the
  existing operator-authenticated endpoint remains the sole Grant-creation authority.
- [KNOWN | HIGH] The final production-local image registered the v2 client and created
  Grant `query-grant-decb201089f91b5fb90dc392` for exact Release
  `release-a4b70851cb914862000e15c3`. A replay returned the same Grant ID; two separate
  Query IDs each returned 3 candidates within the `single_pass` budget.
- [KNOWN | HIGH] Read-only database checks found exactly one v2 Grant and two v2
  Queries. Total Grants advanced 4→5 and Queries 19→21. Formal Command, Agent Version,
  Active Version and active KSS Reference counts remain 0. Readiness remains the
  expected HTTP 503 only because `published_agent=not_ready`.
- [KNOWN | HIGH] The v2 Binding Profile changes the Formal Candidate digest. Draft@13
  now preflights to `9b76665641d00354876deeb7ed2ff79a90c4a15dbc6eda2e270df4cc7a2dc50e`;
  `publication_authorized` remains false, and any prior candidate approval is invalid.
- [COMPUTED | HIGH] RED failed once on the old Handle. Static deployment tests then
  passed 24 cases; the affected suite passed 74 with 5 conditioned skips, and a
  disposable PostgreSQL 17.5 run passed all 6 runtime-composition contracts. The full
  backend passed 2427 with 267 conditioned skips and 2 deselected. Image build/up,
  Query verifier replay, baseline, preflight, Ruff, format, Mypy over 370 source files,
  lock, domain-context, Shell, Compose and diff checks passed.
- [FRAME | HIGH] TDD-05R is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. No formal publication, real external model proof, old-client
  retirement, deployment approval or Production GO occurred.

## 2026-08-31 production-local exact Draft Memory repair (TDD-05Q)

- [KNOWN | HIGH] A three-argument production-local maintenance command now disables
  Memory only through the existing Agent Configuration Workspace. It validates the exact
  Agent/Draft/revision, requires Tools disabled and Memory enabled, preserves YAML outside
  the Memory mapping, then uses the existing complete-Contract validation, revision CAS,
  atomic save and configuration audit.
- [KNOWN | HIGH] The first live attempt failed closed before persistence because disabled
  Memory cannot retain an active provider. The Draft remained at revision 12 and its
  contract-update audit count remained 6. Read-only inspection confirmed no Memory scopes;
  the minimal valid normalization therefore changed `enabled` to false and removed only
  the provider line.
- [KNOWN | HIGH] The final exact CAS advanced Draft 12 to 13 and contract-update audit
  count 6 to 7. A replay against revision 13 returns `draft_memory_already_disabled` and
  does not create revision 14. Tools remain disabled, and the command never authorizes
  publication.
- [KNOWN | HIGH] The read-only Formal Candidate preflight now assembles Draft@13 against
  exact Release `release-a4b70851cb914862000e15c3`; its formal candidate SHA-256 is
  `ecd122b4a85e0bf5d0899e07e26e69eda043814880b9b3be59660475dccaf272`.
  Formal Command, Agent Version, Active Version and KSS Reference remain 0; Query Grant
  remains 4 and Knowledge Query remains 19.
- [COMPUTED | HIGH] Final focused checks passed 16 tests, the affected core set passed
  271, and the complete backend passed 2427 with 267 dependency-conditioned skips and
  2 deselected. Ruff, format, Mypy, shell syntax, image build, API health, live CAS,
  replay and preflight checks passed.
- [FRAME | HIGH] TDD-05Q is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. Candidate assembly is not a formal command approval. The old
  Release still has an independent historical Query Grant conflict, and Phase F, real
  upstream smoke, publication Gates and Production GO remain outside this slice.

## 2026-08-31 production-local Formal Candidate preflight (TDD-05P)

- [KNOWN | HIGH] The production formal command now exposes a read-only `preflight()`
  that reuses its exact Draft/KSS/deployment-Profile candidate assembler without
  reserving a command or entering Phase F, Reference, Query Grant, online smoke or
  publication stages. A three-argument production-local verifier returns only bounded,
  secret-free candidate facts and explicitly states that publication is not authorized.
- [KNOWN | HIGH] The final retained-volume live preflight failed closed for the exact
  current Draft@12 with `memory_must_be_disabled`. Read-only inspection confirmed Tools
  disabled and Memory enabled. The verifier did not modify the Draft or fabricate
  candidate digests.
- [COMPUTED | HIGH] Formal Command, Agent Version, Active Version, KSS Reference,
  Query Grant and Knowledge Query counts were identical before and after the live run.
  The affected suite passed 172 tests; the complete default backend passed 2412 with
  267 dependency-conditioned skips and 2 deselected. Focused checks, Ruff, format,
  Mypy, shell syntax, diff checks, final image build/up and the production-local
  baseline passed.
- [FRAME | HIGH] The preflight capability is `LOCAL_VERIFIED`, while the current exact
  candidate is `BLOCKED` and the feature remains `PARTIAL_VERIFICATION`. Any Draft
  Memory change requires a separate exact CAS mutation; it would not resolve the old
  Release Grant conflict or constitute publication approval or Production GO.

## 2026-08-31 production-local exact Query authority verifier (TDD-05O)

- [KNOWN | HIGH] A new explicit host verifier accepts one existing exact KSS Release,
  provisions or replays its operator-owned deployment-policy Grant, then runs one
  runtime-client `single_pass` Query. It rejects placeholders and identity, Release,
  strategy, budget or access-scope drift. Success and known failure output are bounded,
  machine-readable and secret-free.
- [KNOWN | HIGH] Retained-volume upgrade exposed and fixed a local identity compatibility
  defect: the existing runtime token remains bound to `proof-agent-production-local`, so
  checked-in local policy/bootstrap/runtime wiring preserves that identity. The generic
  bootstrap default remains unchanged. Current checkout build/up and the full baseline
  verifier pass; readiness remains intentionally blocked only by the unpublished Agent.
- [KNOWN | HIGH] The first explicit live Release stopped before Query with a stable 409
  because each of the three retained queryable Releases already had a historical immutable
  smoke Grant under different ID/scope facts. No historical Grant was altered or removed.
  The operator then used the existing KSS management publication API, outside the verifier,
  to create an independent local Base from two existing immutable Source Versions and
  publish a new queryable exact Release with no Grant.
- [KNOWN | HIGH] Two verifier runs against that new Release both exited 0. They replayed
  the same active Grant ID, created two different succeeded Query IDs, and each returned
  3 candidates within the checked-in `single_pass` budget. Read-only PostgreSQL checks
  confirmed exactly one target Grant, two target Queries, 4 Releases and 4 Grants in the
  retained local database.
- [COMPUTED | HIGH] Focused positive checks passed 15 tests; the affected set passed 100;
  the PostgreSQL-enabled full backend passed 2633 with 37 dependency-conditioned skips
  and 2 deselected. The final verifier-focused regression passed 30 tests with one existing
  warning, and the production-local baseline exited 0 after the two live runs.
- [FRAME | HIGH] TDD-05O is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. The new local Release and Grant are durable test evidence and
  remain in the retained stack because this slice has no selective revoke. This slice adds
  no Grant reconciliation/revoke, operator audit migration, formal Agent publication,
  external model proof, deployment approval or Production GO.

## 2026-08-31 production-local Query Grant policy/bootstrap (TDD-05N)

- [KNOWN | HIGH] KSS process configuration now parses one strict, secret-free
  `KSS_QUERY_GRANT_POLICY_JSON` into the frozen deployment policy. Unknown or invalid
  fields fail configuration closed; omitting the value keeps the provisioning route
  unavailable. Only the API role injects the policy into operator-authenticated runtime
  composition.
- [KNOWN | HIGH] The checked-in production-local harness now runs a hardened one-shot
  runtime client bootstrap after KSS migration. It reuses the existing runtime Secret,
  registers only its credential digest, creates no Grant, and must complete alongside
  the dedicated Reference bootstrap before KSS API startup. Static contracts require
  policy and bootstrap client identities to match.
- [COMPUTED | HIGH] The isolated PostgreSQL vertical read the checked-in policy and
  bootstrap facts, then passed Reference registration, operator-only exact-Release
  Grant provisioning and bounded Query. The affected set passed 84 tests; KSS contracts
  passed 422 with 13 dependency-conditioned skips; the PostgreSQL-enabled full backend
  passed 2624 with 37 dependency-conditioned skips and 2 deselected. Ruff, format and
  Mypy over 471 product source files passed.
- [FRAME | HIGH] TDD-05N is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. The production-local full stack, real model, formal
  publication, production access-scope enforcement, deployment and release Gates were
  not executed. This slice adds no SQL, new Secret, revoke/reconciler or operator audit
  store and is not Production GO.

## 2026-08-30 candidate-bound Query Grant Control staging (TDD-05M)

- [KNOWN | HIGH] Formal publication now stages one exact runtime Query Grant after
  active KSS Reference registration and before online smoke. Control derives the only
  request field from the validated Formal Candidate and rejects unavailable,
  inactive, Release-drifted or Space-drifted receipts before smoke or final writes.
- [KNOWN | HIGH] `FormalProductionAgentOnlineSmokeQualification` is now the strict
  `v2` contract and accepts only `FormalProductionAgentQueryGrantStaging`. The old
  Reference-staging-only call shape is removed. Production composition reuses the
  existing KSS operator Secret boundary for the guarded provisioner; runtime and
  Reference credentials still cannot provision Grants.
- [COMPUTED | HIGH] Focused formal-candidate checks passed 72 tests and production
  composition checks passed 11. The affected set passed 141 tests with 13
  dependency-conditioned skips. The PostgreSQL-enabled full backend passed 2620 tests
  with 37 dependency-conditioned skips, 2 deselected and one existing Authlib
  deprecation warning. Ruff, format, Mypy over 470 product source files, lock,
  domain-context and diff checks passed.
- [FRAME | HIGH] TDD-05M is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. A successfully staged Grant remains as exact,
  policy-bounded KSS authority if smoke or publication later fails. This slice adds no
  selective revoke/reconciler, operator-command audit store, new Secret Handle,
  production-local configuration, live model call, deployment, Git commit or
  Production GO.

## 2026-08-30 Query Grant operator transport and guarded adapter (TDD-05L)

- [KNOWN | HIGH] KSS now exposes `POST /v1/knowledge-query-grants` only when runtime
  composition injects both the immutable TDD-05K policy and authenticated operator
  management. The strict request contains only `knowledge_base_release_id`; the
  existing `knowledge_source.edit` permission protects the command. Runtime Query and
  Reference credentials cannot authenticate this operator endpoint.
- [KNOWN | HIGH] ProofAgent now owns a provider-neutral `KnowledgeQueryGrantProvisioner`
  port and a guarded HTTPS adapter. The adapter sends only the exact Release, validates
  the complete secret-free `knowledge-query-grant.v1` receipt, rejects redirects,
  non-success or oversized responses, unknown fields, inactive or duplicate-strategy
  receipts, and exact-Release drift.
- [COMPUTED | HIGH] Focused transport, adapter, runtime and canonical OpenAPI checks
  passed 25 tests. The isolated PostgreSQL/KSS/ProofAgent vertical passed. KSS contracts
  passed 418 tests with 13 dependency-conditioned skips; the PostgreSQL-enabled full
  backend passed 2611 tests with 37 dependency-conditioned skips, 2 deselected and one
  existing Authlib deprecation warning.
- [FRAME | HIGH] TDD-05L is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. The provisioner is not composed into formal publication.
  This slice adds no SQL, operator-command audit store, Secret Handle, production-local
  configuration, live model call, deployment, Git commit or Production GO.

## 2026-08-30 runtime Query Grant provisioning core (TDD-05K)

- [KNOWN | HIGH] KSS now exposes an application-only, secret-free provisioning seam
  for one runtime Query client policy and one exact Release. The immutable policy owns
  client identity, allowed strategies, maximum execution budget and effective
  access-scope digest; each call may supply only `knowledge_base_release_id`.
- [KNOWN | HIGH] KSS derives Knowledge Space from its Release authority and returns a
  strict `knowledge-query-grant.v1` receipt. Complete Grant facts determine the
  content-addressed Grant ID. Exact replay returns the same receipt, while a changed
  policy for the same client/Release conflicts instead of widening authorization.
- [COMPUTED | HIGH] The isolated PostgreSQL/KSS HTTP vertical proved exact replay,
  caller rejection for client/Space/budget fields, one exact Release, budget enforcement,
  and stable `403 knowledge_query_access_denied` for another queryable Release,
  over-budget work and the dedicated Reference client. KSS contracts passed 411 tests
  with 13 dependency-conditioned skips. The PostgreSQL-enabled full backend passed
  2588 tests with 37 dependency-conditioned skips and 2 deselected.
- [FRAME | HIGH] TDD-05K is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. No KSS provisioning HTTP endpoint, ProofAgent transport,
  formal publisher composition, migration, production-local stack, live model call,
  deployment, Git commit or Production GO was added.

## 2026-08-30 production-local dedicated Reference client (TDD-05J)

- [KNOWN | HIGH] The checked-in production-local harness now declares a dedicated,
  versioned KSS Reference client Secret Handle, stores its local fixture at an isolated
  Vault path, and runs a hardened one-shot KSS client bootstrap after KSS migration and
  before the KSS API. The production API configuration also supplies the already-hosted
  local Phase F evaluator origin required by the TDD-05I composition.
- [KNOWN | HIGH] Production composition rejects a Reference Secret Handle that is shared
  with either the Knowledge Operator or runtime Query client. The KSS bootstrap stores
  only the credential digest through `PostgresKnowledgeAccessControl`; it does not create
  an exact-Release Knowledge Query Grant or print the credential.
- [COMPUTED | HIGH] The dedicated registrar vertical passed against an isolated PostgreSQL
  service and recorded `proof-agent-formal-publication-reference` as the authenticated
  Reference owner. A Query using that credential returned the stable
  `403 knowledge_query_access_denied` result because no Query Grant exists. The affected
  set passed 593 tests with 13 dependency-conditioned skips. The PostgreSQL-enabled full
  backend passed 2588 tests with 37 dependency-conditioned skips and 2 deselected. Full
  Ruff, Mypy over 368 product source files, lock, Compose config, domain-context and diff
  checks passed.
- [FRAME | HIGH] TDD-05J is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. This is a checked-in local deployment contract, not a production
  credential, deployment rehearsal or Production GO. Runtime Query client provisioning,
  an exact-Release Query Grant, live KSS/model smoke, formal Agent publication, command
  recovery, Dashboard work and production cutover remain outside this slice.

## 2026-08-30 formal publication production composition cutover (TDD-05I)

- [KNOWN | HIGH] The production API now composes the durable formal publication command
  from PostgreSQL Configuration UoW, live KSS catalog, a deployment-owned KSS Binding
  Profile, the independent Phase F authority, a dedicated versioned KSS Reference client,
  the governed online smoke runner, immutable artifact storage and trusted Institution
  Authorization. Draft state remains the only exact Release-selection authority.
- [KNOWN | HIGH] `create_app(mode="production")` now fails during startup when the
  command is absent. The old `production-publish-agent` manifest CLI and
  `compose_production_agent_publisher` composition were removed, so they can no longer
  bypass the exact Draft, Reference-first and durable command-receipt chain. Development
  composition remains optional and fails unavailable at the endpoint seam.
- [COMPUTED | HIGH] The final focused composition/security set passed 16 tests and the
  directly affected set passed 180 with 13 dependency-conditioned skips. The complete
  backend passed 2354 tests with 267 dependency-conditioned skips and 2 deselected after
  the 8 socket-bound cases were rerun in a loopback-capable environment. Full Ruff,
  Mypy over 367 product source files, lock, domain-context and diff checks passed.
- [FRAME | HIGH] TDD-05I is `LOCAL_VERIFIED`; the feature remains
  `PARTIAL_VERIFICATION`. The checked-in production-local deployment does not yet provide
  the newly required dedicated Reference client Secret/Grant, so startup correctly remains
  fail-closed there until a separate deployment slice supplies it. No live KSS/model call,
  command recovery, Dashboard, deployment, Git commit or Production GO was performed.

## 2026-08-30 durable formal publication command (TDD-05H)

- [KNOWN | HIGH] ProofAgent now exposes a strict `agent.publish`-protected formal
  publication command contract. The server derives actor identity from the trusted
  operator context, injects the deployment-owned KSS Binding Profile, fingerprints the
  exact path/body, and persists actor-scoped `Idempotency-Key` state before any KSS or
  model call. Exact retries return the same success, failure, or `in_progress` receipt;
  a changed request is rejected before another external call.
- [KNOWN | HIGH] Migration `0022_formal_publish_cmd` and the PostgreSQL Configuration
  UoW add durable command receipts. Successful completion is committed atomically with
  Published Version, Active CAS and publication audit. Receipt-write failure rolls all
  final publication state back, and a stored terminal result cannot be downgraded.
  Process loss before terminal completion deliberately leaves `in_progress`; no unsafe
  timeout takeover or background retry was added.
- [COMPUTED | HIGH] The focused formal chain passed 63 tests; real PostgreSQL migration,
  repository, UoW and concurrent reservation passed 9; the affected set passed 170.
  The final PostgreSQL-enabled backend passed 2578 tests with 37 dependency-conditioned
  skips and 2 deselected. Ruff passed, Mypy passed over 367 product source files, 15
  slice Python files were format-clean, and lock/domain checks passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-05H while the feature remains
  `PARTIAL_VERIFICATION`. The production role composition does not yet inject the new
  command, the old manifest publisher/runtime path remains, and no live KSS/model,
  Dashboard, deployment, Git commit or Production GO evidence was produced.

## 2026-08-30 governed online smoke runner adapter (TDD-05G)

- [KNOWN | HIGH] ProofAgent now has a concrete formal online smoke runner that receives
  the Control-validated strict request and exact Reference staging together. It
  revalidates candidate, Phase F, version/run, digest, Space/Base/Release and Reference
  identity before any execution; no mutable latest lookup or candidate registry is
  introduced.
- [KNOWN | HIGH] The runner safely materializes the provisional Contract Bundle as a
  private read-only temporary Agent package and reuses the existing governed execution
  path with `RunPurpose.VALIDATION`, exact run/KSS/runtime facts and injected institution
  authorization. Only accepted evidence with a nonblank citation is counted; bounded
  Trace and Receipt files are retained in immutable storage with exact read-back.
  TDD-05E Control remains the cited-answer qualification authority.
- [COMPUTED | HIGH] The focused slice passed 57 tests; the core compatibility set
  passed 76; the directly affected set passed 144 with 15 dependency-conditioned
  skips. The full backend passed 2338 tests with 264 dependency-conditioned skips and
  2 deselected after rerunning the socket-bound cases in a loopback-capable environment.
  Mypy passed over 460 product source files; full Ruff, changed-file format, lock,
  domain-context and diff checks passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-05G, while the feature remains
  `PARTIAL_VERIFICATION`. The execution boundary was controlled in tests; there is no
  environment-backed live KSS/model smoke evidence. The old manifest publisher and
  runtime composition remain unchanged, and no public durable-idempotency formal
  publication command, Dashboard, deployment, Git commit or Production GO was added.

## 2026-08-30 formal publisher core and atomic activation (TDD-05F)

- [KNOWN | HIGH] ProofAgent now has a new application-only formal publisher core that
  consumes the exact Draft/KSS/Profile candidate, candidate-bound Phase F, durable KSS
  Reference staging and exact online smoke chain. It freezes the current Active pointer
  through a short read-only UoW before Reference registration, then closes the
  transaction before all external calls.
- [KNOWN | HIGH] A successful smoke produces one immutable Published Agent Version
  with a strict evidence envelope retaining the exact Draft revision, Phase F Record,
  active Reference receipt and smoke result. A final Configuration UoW atomically
  checks Draft revision, compares the Active pointer, persists Version/activation and
  appends publication audit. Draft/Active drift or audit/storage failure rolls back
  all final writes; the already registered Reference is conservatively retained.
- [COMPUTED | HIGH] The focused slice passed 53 tests, including adversarial failure
  contracts. Real PostgreSQL repository/UoW tests passed 12; the affected set passed
  373 tests with 4 dependency-conditioned skips. The PostgreSQL-enabled full backend
  passed 2561 tests with 37 dependency-conditioned skips and 2 deselected. Mypy passed
  over 460 product source files; full Ruff, changed-file format, lock and domain-context
  checks passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-05F, while the feature remains
  `PARTIAL_VERIFICATION`. The old manifest publisher is unchanged and runtime/Delivery
  does not route to the new core. No real online runner, persisted-idempotency public
  command, Dashboard, deployment or Production GO was added. TDD-05B through TDD-05F
  remain uncommitted.

## 2026-08-30 exact online smoke Control (TDD-05E)

- [KNOWN | HIGH] ProofAgent now has an application-only online smoke service that
  accepts only a validated `FormalProductionAgentReferenceStaging` with an active KSS
  Reference. Control derives a strict request bound to the exact agent, provisional
  version, validation run, candidate digests, Space/Base/Release and Reference ID.
- [KNOWN | HIGH] Only `ANSWERED_WITH_CITATIONS` with at least one accepted citation
  and distinct exact trace/receipt artifacts forms a strict qualification. Invalid
  staging, blank question, validator failure, unsuccessful outcome, identity drift or
  evidence aliasing fails closed through stable, non-sensitive errors. No Store,
  Active pointer, audit writer or deregistrar port exists in this service, so failure
  cannot publish or activate and leaves the registered Reference conservatively in
  KSS.
- [COMPUTED | HIGH] The focused slice passed 45 tests; the directly affected set
  passed 322 tests with 4 dependency-conditioned skips. The full backend passed 2326
  tests with 263 dependency-conditioned skips and 2 deselected after rerunning in an
  environment that permits loopback binding. Mypy passed over 459 product source
  files; full Ruff, changed-file format, lock, domain-context and diff checks passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-05E, while the feature remains
  `PARTIAL_VERIFICATION`. No real online runner adapter, formal publisher consumption,
  Published Version, Active CAS, Delivery, Dashboard, deployment or Production GO was
  added. TDD-05B through TDD-05E remain uncommitted.

## 2026-08-30 authenticated Reference registration transport (TDD-05D)

- [KNOWN | HIGH] KSS now exposes `POST /v1/knowledge-base-release-references` on
  its public client surface. The route uses existing Bearer client authentication,
  requires `Idempotency-Key`, derives client identity only from authentication, and
  delegates the strict exact request to the existing Reference application and
  PostgreSQL ledger. First registration and exact replay both return `200` with the
  same active resource.
- [KNOWN | HIGH] ProofAgent now has a separate HTTPS guarded registrar using a
  dedicated service-client authorization factory. It sends only the exact TDD-05C
  request and Control-owned key, rejects redirects, non-success, oversized/invalid or
  drifted wire responses, and maps the KSS resource into the strict local receipt.
  It does not reuse the Knowledge management/operator client.
- [COMPUTED | HIGH] KSS HTTP and registrar focused contracts passed 27 tests. The
  affected KSS/ProofAgent set passed 161 tests, including 39 real-PostgreSQL Reference
  and runtime tests. The full PostgreSQL-enabled backend passed 2541 tests with 37
  dependency-conditioned skips and 2 deselected; Mypy passed over 458 product source
  files. Full Ruff, affected format, domain-context, OpenAPI fingerprint and
  `git diff --check` passed.
- [KNOWN | HIGH] The isolated project `proofagent-kss-reference-tdd05d` used only
  PostgreSQL 17.5 on loopback port 55489. A ProofAgent → guarded HTTP → KSS runtime →
  PostgreSQL vertical proved exact replay leaves one active Reference and one audit.
  The exact Compose project and temporary volume were removed after verification.
  No production credential, data, service or deployment was used.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-05D, while the feature remains
  `PARTIAL_VERIFICATION`. No formal publisher consumption, online smoke, Agent
  Store/audit write, Published Version, Active CAS, deregistration/reconciler,
  production Secret/egress composition, Dashboard, deployment or Production GO was
  added. TDD-05B through TDD-05D remain uncommitted.

## 2026-08-30 Reference-first formal publication staging (TDD-05C)

- [KNOWN | HIGH] ProofAgent now has an application-only Reference stager that consumes
  one exact Phase F preparation. It revalidates candidate and record integrity before
  using an injected authenticated KSS registrar port. Control derives the idempotency
  key from the provisional version ID and accepts no caller-selected key.
- [KNOWN | HIGH] The strict request binds the Draft-owned Space/Base/Release to the
  future `published_agent_version` identity for `execution_or_rollback`. The active
  receipt must match every request fact. Drift or upstream failure is rejected; a
  registration that may already have succeeded is conservatively retained rather than
  compensated by an unsafe deregistration. The Phase F Record now also binds the
  provisional version and validation run identities.
- [COMPUTED | HIGH] The focused slice passed 34 tests; the directly affected set passed
  157. The full backend passed 2288 tests with 263 dependency-conditioned skips and 2
  deselected. Mypy passed over 457 product source files; full Ruff, format,
  domain-context and `git diff --check` passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for the TDD-05C port boundary, while the
  feature remains `PARTIAL_VERIFICATION`. No KSS registration HTTP or production
  adapter, Agent Store/audit write, online smoke, Published Version, activation,
  Delivery, deployment, production configuration or Production GO was added. TDD-05B
  and TDD-05C remain uncommitted.

## 2026-08-30 candidate-bound Phase F preparation (TDD-05B)

- [KNOWN | HIGH] ProofAgent now has an application-only Phase F preparer that first
  revalidates both retained Formal Production Agent Candidate digests and resolves
  Workflow Stage availability from the exact candidate Contract. It accepts four
  exact evidence artifacts and a trusted actor, with no Store or audit write.
- [KNOWN | HIGH] A strict immutable Phase F Record binds the formal-candidate digest,
  Knowledge Release digest, distinct Shadow/Capacity/Acceptance/Recovery evidence,
  actor and timestamp. Only an independent authority's explicit approval returns a
  `ProvisionalProductionAgentVersion`; that contract retains the exact Draft revision,
  KSS binding and Workflow facts while making no published or active claim.
- [COMPUTED | HIGH] The focused slice passed 18 tests; the directly affected set passed
  113. The full backend passed 2272 tests with 263 dependency-conditioned skips and 2
  deselected. Mypy passed over 456 product source files; Ruff, format, domain-context
  and `git diff --check` passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-05B, while the feature remains
  `PARTIAL_VERIFICATION`. The current publisher is unchanged. No KSS Reference,
  online smoke, Published Version write, Active pointer CAS, Delivery, deployment,
  production configuration or Production GO was added. These TDD-05B changes are
  not yet committed.

## 2026-08-30 exact Formal Production Agent Candidate assembler (TDD-05A)

- [KNOWN | HIGH] ProofAgent now has a read-only Control assembler rooted in one named
  Agent, exact Draft ID and exact Draft revision. It reads the Agent Configuration
  Store, reuses the existing publication-configuration projector against a ready,
  versioned live KSS catalog, and derives the executable Release only from the
  Draft-owned exact Space/Base/Base Version/Release tuple.
- [KNOWN | HIGH] The deployment-owned Profile is a strict immutable contract containing
  binding identity, a versioned Knowledge credential handle, Admission Scorer identity
  and revision, and required failure mode. It cannot carry an environment-selected
  Release. The resulting immutable candidate records the catalog revision and separates
  the existing Contract+binding digest from a formal digest that also binds Draft
  identity and revision.
- [COMPUTED | HIGH] The focused slice passed 10 tests; directly affected publication,
  Workspace and contract tests passed 115. The full backend passed 2264 tests with 263
  dependency-conditioned skips and 2 deselected; Mypy passed over 455 product source
  files and full Ruff passed. No external dependency, frontend, lock, schema, migration
  or OpenAPI change was required.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-05A, while the feature remains
  `PARTIAL_VERIFICATION`. The current publisher still accepts an independent manifest
  and environment-built Release binding. No Release Operator delivery entry, KSS
  Reference registration, Phase F, online smoke, Published Version write, activation,
  deployment, production configuration or Production GO was added.

## 2026-08-30 exact-resource Release Preparation expiry BFF (TDD-04H)

- [KNOWN | HIGH] KSS and ProofAgent now expose a no-body `POST :expire` command for
  one exact due ready Preparation. The BFF requires `knowledge_source.edit`; the
  guarded client verifies exact identity, expired state and same-resource `Location`;
  KSS checks path Scope before using PostgreSQL time and an exact row lock for the
  existing ready → expired transition.
- [KNOWN | HIGH] Exact replay returns the same durable expired state without an
  Idempotency-Key, second receipt or duplicate publication audit. Not-due, non-ready,
  body input, permission/Scope failure and upstream identity/state/private-field/
  Location drift fail closed. Eight concurrent exact calls converge on one terminal
  transition and one audit, and no queryable Release is created. The network contract
  intentionally does not expose global `expire_next()`, preventing an uncertain retry
  from selecting another candidate.
- [COMPUTED | HIGH] Six directly affected files passed 260 tests against isolated
  PostgreSQL, MinIO and OpenSearch. The full backend passed 2493 tests with 24 existing
  declared skips and 2 deselected; 2 explicit Hybrid integrations passed separately.
  Mypy over 454 product files, full Ruff, TypeScript, Dashboard 225, Chat 35, all
  frontend builds, domain/lock checks and `git diff --check` passed. Canonical KSS
  OpenAPI is bound to
  `cdb847191bc5f3658d4592f420852b1b990c5b7ca550b3138b07e69699b99ca2`;
  migration head and dependency locks are unchanged.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-04H, while the feature remains
  `PARTIAL_VERIFICATION`. No scheduler, continuous process role, Dashboard operation,
  artifact cleanup, Agent formal publication, deployment, production configuration
  or Production GO was added.

## 2026-08-30 bounded Release Preparation audit BFF (TDD-04G)

- [KNOWN | HIGH] ProofAgent now exposes a read-only same-origin
  `GET .../preparation-audit` route protected by `knowledge_source.view`. The guarded
  client validates the existing KSS audit wire contract and exact Space/Base, then
  returns a chronological secret-free projection with offset bounded to 20,000 and
  page size bounded to 100.
- [KNOWN | HIGH] Every identified actor is labelled `kss_service_operator`. This is
  the trusted service identity observed by KSS, not the browser or terminal operator;
  no delegated identity chain is fabricated. Worker, lease, fence, credential and raw
  rejection fields fail closed. The current Base audit contains management
  save/start/cancel successes and rejections; it does not merge Worker or publication
  audit, and offset pages are current-read snapshots rather than a stable cursor.
- [COMPUTED | HIGH] Focused unit files passed 59 tests and the real-dependency affected
  set passed 145 tests. The full backend passed 2479 tests with 24 existing declared
  skips and 2 deselected; 2 explicit Hybrid integrations passed separately. Mypy over
  454 product files, full Ruff, TypeScript, Dashboard 225, Chat 35, all frontend builds,
  lock checks, domain validation and `git diff --check` passed.
- [FRAME | HIGH] This is `LOCAL_VERIFIED` for TDD-04G, while the feature remains
  `PARTIAL_VERIFICATION`. No KSS storage/OpenAPI change, Dashboard, terminal identity
  delegation, expiry command, continuous process, artifact cleanup, Agent formal
  publication, deployment, production configuration or Production GO was added.

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
