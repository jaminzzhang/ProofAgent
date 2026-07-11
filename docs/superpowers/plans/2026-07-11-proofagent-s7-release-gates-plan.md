# Proof Agent S7 Candidate Release Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Freeze all Gate tooling before candidate binding, then produce fresh immutable Evidence for every required Gate family and let the strict Manifest verifier—not a person or webpage—compute the only Initial Private Pilot `GO`/`NO-GO` decision.

**Architecture:** [FRAME | HIGH] S7A implements and commits the candidate binder, all producers/harnesses/workflows/governance, and verifier before binding. S8A then freezes all remaining docs/release-artifact code. S7B hashes that clean combined commit and executes the already-bound Gate code against the exact image/environment; S3 Evidence and a pure assembler/verifier reject missing, non-pass, stale, mismatched, insufficient, or untrusted input.

**Tech Stack:** [FRAME | HIGH] Python release tooling, GitHub Actions with pinned actions, pytest/coverage, Ruff, mypy, npm/Vitest/build, Playwright/axe, real PostgreSQL/S3/OIDC/Secret Provider/model/tool services, container/security scanners, OCI/SBOM/provenance tooling, fault injection, load/soak/recovery harnesses, DSSE/in-toto-compatible attestations.

---

## Prerequisites and Exit Contract

- [ ] [FRAME | HIGH] Begin S7A only after S6 is merged/green. Tasks 1–14 implement/test/freeze tooling with reference fixtures; they do not build or approve the production candidate.
- [ ] [FRAME | HIGH] After S7A’s clean commit, complete S8A and commit its docs/release-artifact tooling. Begin S7B only from the clean combined commit with no untracked files; developer `reports/` or `graphify-out/` content cannot enter binding or Evidence.
- [ ] [FRAME | HIGH] Use exact DCM dependencies and production configuration. Reference mocks may run PR tests, but they cannot produce candidate compatibility, real-LLM, load, fault, recovery, browser, or deployment passes.
- [ ] [FRAME | HIGH] S7B may write only external candidate/Evidence/Manifest/audit state. Any repository mutation returns to S7A/S8A and requires a new binding. Exit only with one strict Manifest whose verifier returns `GO`, all 13 results `passed`, fresh attested digest-bound Evidence, and no manual override.

# S7A — Pre-Candidate Gate Tooling and Governance Freeze

## Task 1: Implement Immutable Production Candidate Binding

**Files:**

- Create: `proof_agent/release/candidate.py`
- Create: `proof_agent/release/canonical_json.py`
- Create: `proof_agent/release/attestations.py`
- Create: `proof_agent/release/evidence.py`
- Modify: `proof_agent/release/contracts.py`
- Create: `tests/test_candidate_binding.py`
- Create: `tests/test_release_attestations.py`

- [ ] [FRAME | HIGH] Write red tests for dirty source, wrong commit length, mutable OCI tag, changed wheel/sdist/assets/migrations/Agent/evaluation/config/profile/DCM, duplicate file, symlink escape, nondeterministic canonical JSON, wrong attestation subject, and untrusted signer identity.
- [ ] [FRAME | HIGH] Add `proof-agent release bind-candidate` that consumes only clean-checkout outputs and emits canonical JSON. Bind source commit/clean state, product version, OCI digest, wheel+sdist bundle digest, Dashboard/Chat asset digests, migration-set digest, sole Agent ID/version/bundle digest, evaluation-contract digest, production configuration snapshot digest, Gate Profile digest, and DCM digest.
- [ ] [FRAME | HIGH] Derive `candidate_binding_sha256` from canonical bytes and `release_id` from product version plus a non-authoritative digest prefix. Every later object carries the full SHA-256.
- [ ] [FRAME | HIGH] Define detached DSSE/in-toto-compatible Evidence attestations. Trust policy pins the candidate CI workload identity/issuer and subject digest; a human-uploaded JSON file without valid attestation is not Evidence.
- [ ] [FRAME | HIGH] Commit with message `Bind immutable production release candidates`.

## Task 2: Build a Common Gate Producer and Evidence Protocol

**Files:**

- Create: `proof_agent/release/producers/__init__.py`
- Create: `proof_agent/release/producers/base.py`
- Create: `proof_agent/release/orchestrator.py`
- Create: `proof_agent/release/freshness.py`
- Create: `proof_agent/release/assembler.py`
- Create: `tests/test_gate_producer_protocol.py`
- Create: `tests/test_release_manifest_assembly.py`
- Modify: `proof_agent/delivery/cli.py`

- [ ] [FRAME | HIGH] Write red tests proving a producer cannot choose its own Gate ID/optionality/freshness, mark missing work `passed`, refer to a mutable path, omit sample counts/thresholds, reuse another candidate’s Evidence, or emit unknown metrics/fields.
- [ ] [FRAME | HIGH] Give each producer a read-only candidate context and an Evidence writer that canonicalizes, hashes, uploads/reads back exact S3 objects, and creates a detached attestation before returning `GateResult`.
- [ ] [FRAME | HIGH] Add commands `proof-agent release run-gate GATE_ID`, `collect-evidence`, `assemble-manifest`, and `verify`. Status is computed from measured predicates; CLI has no `--force-pass`, `--override`, or optional-required-Gate switch.
- [ ] [FRAME | HIGH] Allow `passed`, `failed`, `skipped`, `error`, and `not_run` as producer facts, while the initial profile accepts only `passed` for every required Gate.
- [ ] [FRAME | HIGH] Commit with message `Add candidate-bound Gate producer protocol`.

## Task 3: Produce Backend/Frontend Quality and Distribution/Image Gates

**Files:**

- Create: `proof_agent/release/producers/quality.py`
- Create: `proof_agent/release/producers/distribution.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`
- Create: `tests/test_quality_gate_producer.py`
- Create: `tests/test_distribution_gate_producer.py`
- Create: `tests/release/clean_install_smoke.py`

- [ ] [FRAME | HIGH] Make PR CI require frozen Python/Node installs, complete pytest, Ruff, mypy, existing domain checks, frontend typecheck/tests/build, wheel/sdist build, and clean-install smoke. Expose a strict quality-producer command inventory that S8A extends with release-documentation/bilingual checks before binding. Pin every third-party action by commit SHA.
- [ ] [FRAME | HIGH] Add `pytest-cov` and fail backend line coverage below 90%. Add focused tests until the threshold passes; do not exclude production adapters/security/queue/release modules to manufacture coverage.
- [ ] [FRAME | HIGH] Quality Gate requires every command exit zero, zero skipped required integration tests, exact lock digests, and coverage at least 90%.
- [ ] [FRAME | HIGH] Distribution Gate installs wheel/sdist independently in clean environments, runs import/CLI/V3 smoke, verifies both frontend assets and static headers, starts the immutable image, checks hardening/content, and proves `/livez`/`/readyz` from the image rather than source.
- [ ] [FRAME | HIGH] Commit with message `Gate complete product quality and distributions`.

## Task 4: Produce Supply-Chain and Runtime-Security Gate

**Files:**

- Create: `proof_agent/release/producers/security.py`
- Create: `scripts/release/security_scan.py`
- Create: `security/scan-policy.yaml`
- Create: `security/tools.lock.json`
- Create: `tests/test_security_gate_producer.py`
- Create: `tests/release/security/negative_paths.py`
- Modify: `.github/workflows/ci.yml`

- [ ] [FRAME | HIGH] Pin tool releases/images by immutable digest in `security/tools.lock.json` and run Gitleaks secret scan, Semgrep/Bandit SAST, pip-audit plus npm audit dependency checks, license inventory, Syft SPDX/CycloneDX SBOM, Trivy filesystem/config/image scan, OCI provenance verification, container-structure/hardening tests, and authorized DAST against the isolated candidate.
- [ ] [FRAME | HIGH] Explicitly test the original high-risk chains: unauthenticated mutation, wildcard CORS/CSRF, arbitrary `http_json` SSRF, credential env/base-URL exfiltration, local/MCP stdio command execution, source/secret/run-data image inclusion, TrustedHost/TLS/header/body/rate limits, and production docs exposure.
- [ ] [FRAME | HIGH] Triage every advisory by ID, severity, direct/transitive/reachability/fixed version; the Gate requires zero unresolved Critical or High dependency, image, SAST, secret, DAST, or license-policy findings. There is no informal risk-acceptance pass path in the initial profile.
- [ ] [FRAME | HIGH] Generate CycloneDX or SPDX SBOMs plus signed provenance for distributions/image; verify subjects equal candidate digests.
- [ ] [FRAME | HIGH] Commit with message `Gate supply chain and runtime security`.

## Task 5: Produce Identity/Authorization and Secrets/Egress Gates

**Files:**

- Create: `proof_agent/release/producers/identity.py`
- Create: `proof_agent/release/producers/secrets_egress.py`
- Create: `tests/release/test_candidate_identity.py`
- Create: `tests/release/test_candidate_secrets_egress.py`
- Create: `tests/test_identity_gate_producer.py`
- Create: `tests/test_secrets_egress_gate_producer.py`

- [ ] [FRAME | HIGH] Run against the DCM-bound OIDC and Secret Provider through the candidate image/stable origin, not fakes.
- [ ] [FRAME | HIGH] Identity Gate proves Authorization Code + PKCE/state/nonce, secure opaque cookie, absolute/idle expiry, one-hour freshness, refresh/revocation/failure, CSRF, exact permission negatives, unmatched default deny, mapping atomicity/rollback/audit, and Recovery OIDC Group exercise.
- [ ] [FRAME | HIGH] Secrets/Egress Gate proves handle validate/resolve/missing/revoke/rotate/no-disclosure, production env/raw-secret rejection, exact-origin allow, HTTP/wildcard/redirect/retry/DNS/rebinding denial, provider SDK non-bypass, and read-only tool publication/runtime/state-change denial.
- [ ] [FRAME | HIGH] Evidence lasts at most 72 hours because it binds production integrations; security vulnerability evidence from Task 4 lasts 24 hours.
- [ ] [FRAME | HIGH] Commit with message `Gate identity secrets and egress controls`.

## Task 6: Produce Deterministic and Real-LLM Evaluation Gates

**Files:**

- Create: `proof_agent/release/producers/deterministic_evaluation.py`
- Create: `proof_agent/release/producers/real_llm_evaluation.py`
- Create: `tests/test_evaluation_gate_producers.py`
- Modify: `proof_agent/evaluation/real_llm_release.py`

- [ ] [FRAME | HIGH] Deterministic Gate loads the exact S5 evaluation-contract digest and sole Agent snapshot from the candidate image/config, runs every required case through queue/Executor/S3, and requires all safety/governance/evidence/citation/artifact predicates with zero skips.
- [ ] [FRAME | HIGH] Real-LLM Gate runs the same contract through the exact candidate model connection: supported cited answer, no-evidence refusal, clarification, state-changing denial, provider failure, hard budget, and Case Memory non-evidence. It additionally requires successful read-only tool use when the bound snapshot uses `read_only_https`; otherwise it requires explicit disabled-tool behavior. Neither branch may be skipped.
- [ ] [FRAME | HIGH] Reject stale prior results, a different model/deployment/image/Agent, mock provider, incomplete artifacts, missing samples, or a test selected by candidate optionality.
- [ ] [FRAME | HIGH] Store per-case trace-safe exact artifacts plus aggregate metrics; real-LLM Evidence lasts at most 72 hours.
- [ ] [FRAME | HIGH] Commit with message `Gate deterministic and real LLM Agent behavior`.

## Task 7: Produce Concrete Dependency Compatibility Gate

**Files:**

- Create: `proof_agent/release/producers/compatibility.py`
- Create: `tests/release/test_candidate_compatibility.py`
- Create: `tests/test_compatibility_gate_producer.py`

- [ ] [FRAME | HIGH] Iterate every required DCM component and run its adapter-specific capability suite against the exact version/revision/endpoint: PostgreSQL transactions/advisory lock/PITR capability; S3 version/conditional put/exact read-delete; OIDC discovery/JWKS/refresh/revocation; Secret Provider validate/resolve/revoke/rotate; Gateway TLS/SSE/atomic reload; and model timeouts/rate-limit/error contract. Run the read-only tool compatibility suite only for bound `read_only_https`; otherwise prove the Agent/runtime/DCM consistently bind `disabled`.
- [ ] [FRAME | HIGH] Require complete product/version/digest/Evidence binding and fail on “compatible family” claims unsupported by exact tests.
- [ ] [FRAME | HIGH] Record server-reported versions, capability results, endpoint certificate identity, adapter ID, and DCM digest; evidence lasts at most 72 hours.
- [ ] [FRAME | HIGH] Commit with message `Gate concrete production dependency compatibility`.

## Task 8: Produce Capacity/Responsiveness and Queue/Progress Gates

**Files:**

- Create: `proof_agent/release/producers/performance.py`
- Create: `proof_agent/release/producers/queue_progress.py`
- Create: `tests/release/load/run_load.py`
- Create: `tests/release/load/scenarios.py`
- Create: `tests/release/test_candidate_queue_faults.py`
- Create: `tests/test_performance_gate_producer.py`
- Create: `tests/test_queue_progress_gate_producer.py`

- [ ] [FRAME | HIGH] Acquire 20 DCM-bound OIDC test-operator sessions and run at least 30 minutes against production dependencies. Collect at least 200 admissions/first-progress samples and at least 100 standard supported terminal samples before computing P95.
- [ ] [FRAME | HIGH] Prove five claimed Attempts plus 50 queued, request 51 explicit `429`/`Retry-After` with no partial Run, admission P95 ≤500 ms, first SSE P95 ≤1 s, free-slot start P95 ≤1 s, standard supported terminal P95 ≤60 s excluding visible queue, and every Attempt terminal ≤120 s.
- [ ] [FRAME | HIGH] Queue/Progress Gate separately proves idempotency conflict behavior, per-operator fairness, queued/running/finalizing cancel, `CANCEL_REQUESTED` capacity, lease loss, no replay, stale commit denial, unique terminal/visibility, reconnect current coarse state, allowed fine-detail loss, and disconnect without cancel.
- [ ] [FRAME | HIGH] Run a four-hour soak at the accepted envelope with no unbounded resource growth, stuck leases, orphan backlog breach, or SLO/error-budget violation.
- [ ] [FRAME | HIGH] Load/fault evidence lasts at most 72 hours and records complete raw trace-safe samples, percentile method, exclusions, and sample counts.
- [ ] [FRAME | HIGH] Commit with message `Gate production capacity queue and responsiveness`.

## Task 9: Produce Resilience and Timed Combined-Recovery Gate

**Files:**

- Create: `proof_agent/release/producers/recovery.py`
- Create: `tests/release/faults/run_fault_matrix.py`
- Create: `scripts/release/combined_restore_rehearsal.py`
- Create: `tests/test_recovery_gate_producer.py`

- [ ] [FRAME | HIGH] Execute authorized isolated faults for PostgreSQL unavailable/restart, S3 read/finalization/corruption, OIDC outage/refresh failure, Secret missing/revoke/rotate, egress deny, model timeout/429/5xx, tool outage, Executor kill/lease expiry, Gateway failure, and alert delivery.
- [ ] [FRAME | HIGH] Verify every failure matches the approved fail-closed semantics: no local authority/fallback, no hidden replay, explicit infrastructure result unavailability, correct fencing/capacity, sanitized errors, and alert/runbook linkage.
- [ ] [FRAME | HIGH] Perform a timed combined restore from PostgreSQL PITR and exact S3 object versions; measure RPO ≤15 minutes and RTO ≤4 hours, reapply retention, hide expired data, verify 100% exact refs/digests/manifests, validate sole Agent, and complete authenticated smoke before traffic.
- [ ] [FRAME | HIGH] Recovery Evidence lasts at most 30 days and is invalidated by topology, backup-policy, or migration-set digest change. Fault Evidence lasts at most 72 hours.
- [ ] [FRAME | HIGH] Commit with message `Gate fail closed resilience and combined recovery`.

## Task 10: Produce Deployment Gate

**Files:**

- Create: `proof_agent/release/producers/deployment.py`
- Create: `tests/release/run_blue_green_gate.py`
- Create: `tests/test_deployment_gate_producer.py`

- [ ] [FRAME | HIGH] Run from exact old/candidate immutable images. Prove locked expand-only migration, schema compatibility, both N/N-1 queue directions or admission-pause fallback, candidate standby, old 150-second drain, atomic UI/API/callback/SSE switch, higher candidate epoch, external smoke, 30-minute soak, rollback order/drain/fence/higher old epoch, no down migration, and rollback-asset retention calculation.
- [ ] [FRAME | HIGH] Inject drain-timeout and unhealthy-candidate cases and prove Gateway remains/restores old with no split activation.
- [ ] [FRAME | HIGH] Record routing generation, activation epochs, claim counts, exact images/config/migrations, smoke artifacts, and timings; Evidence lasts at most 72 hours.
- [ ] [FRAME | HIGH] Commit with message `Gate exact Blue Green deployment and rollback`.

## Task 11: Produce Browser and Operations Gate

**Files:**

- Create: `proof_agent/release/producers/browser_operations.py`
- Create: `tests/release/browser/playwright.config.ts`
- Create: `tests/release/browser/package.json`
- Create: `tests/release/browser/operator-pilot.spec.ts`
- Create: `tests/release/browser/security-negative.spec.ts`
- Create: `tests/release/browser/accessibility.spec.ts`
- Create: `tests/release/operations/pilot-evidence.schema.json`
- Create: `tests/release/operations/runbook-exercise.schema.json`
- Create: `tests/test_browser_operations_gate_producer.py`
- Modify: `package.json`, `package-lock.json`

- [ ] [FRAME | HIGH] Register `tests/release/browser` as the `proof-agent-release-browser` npm workspace with pinned `@playwright/test` and `@axe-core/playwright`; add root `test:release-browser` without coupling it to Dashboard’s unit-test runner.
- [ ] [FRAME | HIGH] Through the stable origin, automate OIDC, permission variation, Agent/security configuration, Knowledge publication, Operator Chat, SSE reconnect, cancel, audit export/download, responsive/keyboard/axe checks, and explicit 404/unavailable customer/approval surfaces.
- [ ] [FRAME | HIGH] Exercise every S6 runbook and actual alert notification path in the isolated candidate environment; collect command/result/timing/actor/alert/Evidence refs without raw secrets.
- [ ] [FRAME | HIGH] Run a 3–5 operator internal pilot across one complete weekday 09:00–18:00 Asia/Shanghai support window. Required audit facts cover login, permission differences, Agent config, Knowledge publication, Operator Chat, cancellation, audit download, incident notification, and rollback rehearsal.
- [ ] [FRAME | HIGH] Pilot/runbook inputs are signed operational facts, not a human GO approval. The producer computes pass only when schema, actor count, full support-window duration, required scenario coverage, candidate binding, and attestations all validate.
- [ ] [FRAME | HIGH] Evidence lasts at most 72 hours for browser/BlueGreen-dependent facts; if the one-day pilot cannot complete within freshness, rerun the dependent browser/deployment subset before decision.
- [ ] [FRAME | HIGH] Commit with message `Gate browser workflows and operational readiness`.

## Task 12: Close Repository and Release Governance

**Files:**

- Create: `.github/CODEOWNERS`
- Create: `SECURITY.md`
- Create: `SUPPORT.md`
- Create or complete: `LICENSE`, `NOTICE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`
- Create: `.github/workflows/release-candidate.yml`
- Create: `docs/release-process.md`
- Create: `tests/test_repository_governance.py`

- [ ] [FRAME | HIGH] Configure required branch checks, protected main branch/no force push, least-privilege workflow permissions, pinned actions, environment-scoped candidate credentials, immutable version/tag policy, artifact retention, provenance, rollback ownership, security reporting, support/EOL, and third-party notices.
- [ ] [FRAME | HIGH] Candidate workflow builds once, binds once, runs/collects all Gates on appropriate isolated/self-hosted runners, uploads exact Evidence to S3, assembles/verifies Manifest, and fails the workflow on `NO-GO`. Triggering a workflow is not a release approval and cannot alter computed status.
- [ ] [FRAME | HIGH] Verify repository-host settings through API Evidence; a checked-in policy document alone does not prove enforcement.
- [ ] [FRAME | HIGH] Commit with message `Enforce repository and candidate release governance`.

## Task 13: Assemble and Verify the Sole GO/NO-GO Manifest

**Files:**

- Modify: `proof_agent/release/assembler.py`
- Modify: `proof_agent/release/verifier.py`
- Create: `tests/test_initial_private_pilot_manifest.py`

- [ ] [FRAME | HIGH] Assemble exactly one result for every immutable profile Gate ID and reject unknown/duplicate/missing results.
- [ ] [FRAME | HIGH] Recompute all object/attestation/binding/freshness/threshold/sample predicates at decision time. Static Evidence remains valid only while binding is unchanged; vulnerability 24h; integration/LLM/load/fault/browser/deployment 72h; restore 30d plus invalidation rules.
- [ ] [FRAME | HIGH] Require deployment to begin within 24 hours after decision and before earliest Evidence expiry. Any mutation/re-evaluation produces a new manifest/digest/decision.
- [ ] [FRAME | HIGH] Mutation tests must turn a valid `GO` into `NO-GO` for every bound digest/result/evidence/attestation/freshness field.
- [ ] [FRAME | HIGH] Commit with message `Compute strict Initial Private Pilot release decision`.

## Task 14: Freeze and Review the S7A Tooling Commit

- [ ] [KNOWN | HIGH] Run PR checks first:

```bash
uv lock --check
uv run --extra dev --extra production python -m pytest tests/ --cov=proof_agent --cov-report=term-missing --cov-fail-under=90 -v
uv run --extra dev ruff check proof_agent tests scripts
uv run --extra dev --extra openai --extra production mypy proof_agent
python3 scripts/check-domain-contexts.py
npm ci
npm run typecheck
npm test
npm run build
uv build
git diff --check
```

- [ ] [FRAME | HIGH] Dry-run the workflow/producers against pinned reference services and synthetic valid/invalid candidate fixtures; do not label this candidate Evidence.
- [ ] [FRAME | HIGH] Ask an independent release/security reviewer to audit Gate completeness, tool trust, runner isolation, binding, sample/freshness/invalidation logic, attestation trust, long-run harnesses, and absence of override paths.
- [ ] [FRAME | HIGH] Resolve all P0/P1 findings, rerun checks, commit every S7A source/workflow/test/governance change, require a clean tree, and hand the exact commit to S8A. No producer implementation is allowed after candidate binding.

# S7B — Bound Candidate Gate Execution

## Task B1: Build Once and Bind the Clean S7A + S8A Candidate

- [ ] [FRAME | HIGH] From a fresh checkout of the exact combined commit, run the frozen build workflow once to produce wheel/sdist, frontend assets, migration set, Agent/config/evaluation bundles, and one immutable image digest.
- [ ] [FRAME | HIGH] Run the bound `release bind-candidate` implementation and independently recompute the canonical binding. Require clean source, exact DCM/Gate Profile, sole Agent/V3, and matching distribution/image/assets/migration/config/evaluation/docs/tooling commit.
- [ ] [FRAME | HIGH] Attest the candidate binding with the trusted CI workload identity. Do not rebuild individual artifacts after binding.

## Task B2: Execute Candidate Quality, Security, Integration, and Evaluation Gates

- [ ] [FRAME | HIGH] Run the already-bound quality, distribution/image, supply-chain/runtime-security, identity/authorization, secrets/egress, deterministic evaluation, real-LLM evaluation, dependency compatibility, and queue/progress producers against the exact candidate/DCM environment.
- [ ] [FRAME | HIGH] Upload/read-back/attest every Evidence object through the bound writer. A missing dependency, required skip, scanner error, mismatched artifact, or optional-tool mode inconsistency produces a non-pass result.

## Task B3: Execute Long-Running Capacity, Recovery, Deployment, and Operations Gates

- [ ] [FRAME | HIGH] Run the 30-minute 20-session/5-active/50-queued load, four-hour soak, fault matrix, timed combined PITR/S3 restore, exact Blue/Green/rollback rehearsal, full browser/accessibility suite, alert/runbook exercises, and 3–5 operator full-support-day pilot.
- [ ] [FRAME | HIGH] Do not shorten or replace these runs with reference mocks. Collect required sample counts, timings, exact dependency/binding data, attestations, and freshness/invalidation metadata.

## Task B4: Assemble and Independently Verify the Manifest

- [ ] [FRAME | HIGH] Run the bound assembler with exactly one result per required Gate and then run the verifier in a separate clean environment that re-downloads every exact Evidence object and validates every attestation/digest/binding/threshold/freshness predicate.
- [ ] [FRAME | HIGH] Archive verifier JSON/stdout/exit code externally. Any required status other than `passed` or any expired/missing/invalid input yields `NO-GO` with no override.
- [ ] [FRAME | HIGH] If correction requires source/docs/tests/frontend/workflow changes, return to S7A/S8A, create a new candidate, and rerun all invalidated Gates. Hand off to S8B only when the exact immutable Manifest verifies `GO`.
