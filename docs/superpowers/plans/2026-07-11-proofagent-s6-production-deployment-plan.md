# Proof Agent S6 Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Package the S5 product into a hardened same-host Blue/Green Docker Compose deployment with concrete dependency binding, deep readiness, safe migration/switch/rollback, authenticated bundle download, telemetry, support policy, and executable runbooks.

**Architecture:** [FRAME | HIGH] A stable same-origin Gateway remains outside Blue/Green slots. Each slot runs API, Run Executor, Knowledge Worker, Dashboard static server, and Operator Chat static server from one immutable product image. PostgreSQL activation leases/fencing select the active worker slot; a deployment controller performs locked expand migration, standby validation, drain, atomic Gateway switch, activation, smoke, soak, and rollback.

**Tech Stack:** [FRAME | HIGH] Multi-stage Docker/BuildKit, Docker Compose, Nginx stable Gateway bound by compatibility manifest, Python wheel/sdist, npm/Vite static assets, FastAPI health/static services, PostgreSQL/S3/OIDC/Secret Provider/model integrations, OpenMetrics-compatible telemetry.

---

## Prerequisites and Exit Contract

- [ ] [FRAME | HIGH] Begin only after S5 is merged, reviewed, and green.
- [ ] [FRAME | HIGH] Before code that depends on concrete behavior, complete `deploy/production/deployment-compatibility-manifest.json` with exact product/version/digest, endpoint/origin, authentication, required capability, and test Evidence for PostgreSQL, S3, OIDC, Secret Provider, Gateway, and model. Include a read-only tool service only when the bound Agent uses `read_only_https`; otherwise bind `tool_mode=disabled`. Reject `TBD`, mutable-tag-only, missing, ambiguous, or generic entries.
- [ ] [KNOWN | HIGH] Read app-surface, observability, Agent-configuration, Knowledge, identity/security, and workflow contexts plus the complete approved deployment/operations sections.
- [ ] [FRAME | HIGH] Exit only after clean-room image/Compose/readiness/standby/drain/switch/activation/smoke/soak/rollback/download/alert prerequisites pass and every required runbook exists before S7 exercises it.

## Task 1: Define and Validate the Deployment Compatibility Manifest

**Files:**

- Create: `proof_agent/contracts/deployment.py`
- Create: `proof_agent/deployment/__init__.py`
- Create: `proof_agent/deployment/compatibility.py`
- Create: `deploy/production/deployment-compatibility-manifest.schema.json`
- Create: `deploy/production/deployment-compatibility-manifest.example.json`
- Create candidate-local ignored file at execution time: `deploy/production/deployment-compatibility-manifest.json`
- Create: `tests/test_deployment_compatibility_manifest.py`
- Modify: `.gitignore`

- [ ] [FRAME | HIGH] Write red strict-schema tests for missing component, unknown field, mutable image tag without digest, unversioned product, duplicate component, incomplete capability set, off-policy origin, stale/missing evidence, and generic “compatible S3/OIDC/etc.” claims.
- [ ] [FRAME | HIGH] Require exact components `postgresql`, `s3`, `oidc`, `secret_provider`, `gateway`, and `model_provider`; each binds product, semantic/build version, digest or immutable service revision, endpoint origin, adapter/protocol ID, tested capabilities, and Evidence digest. Require `read_only_tool` only for Agent `tool_mode=read_only_https`; for `disabled`, reject that component and record the disabled mode explicitly.
- [ ] [FRAME | HIGH] Canonically hash the complete manifest and include that digest in Production Candidate Binding/readiness. The actual candidate file is secret-free but environment-specific and is not replaced by the checked-in example.
- [ ] [FRAME | HIGH] Add `proof-agent deployment validate-compatibility --manifest PATH` with machine JSON and nonzero exit on any incomplete binding.
- [ ] [FRAME | HIGH] Commit with message `Define concrete deployment compatibility binding`.

## Task 2: Build Clean Distributions and One Hardened Product Image

**Files:**

- Create: `deploy/production/Dockerfile`
- Create: `deploy/production/.dockerignore`
- Create: `proof_agent/delivery/static_server.py`
- Modify: `proof_agent/delivery/cli.py`
- Modify: `pyproject.toml`
- Modify: `package.json`
- Modify: `uv.lock`, `package-lock.json`
- Create: `tests/test_static_server.py`
- Create: `tests/test_production_image_layout.py`

- [ ] [FRAME | HIGH] Write clean-install wheel/sdist tests and image-layout negatives before the Dockerfile: no editable install, source tree, `.git`, tests, dev compiler/toolchain, local run history, `.env`, raw secrets, LangGraph/MCP stdio/local-handler packages, or root UID.
- [ ] [FRAME | HIGH] Define a `production` extra containing only the shipped Dashboard/API, ingestion/index, model, PostgreSQL, S3, and security runtime dependencies established by S1–S5; it must not include `dev`, test services, scanners, deployment controllers, or local-execution dependencies.
- [ ] [FRAME | HIGH] Use stages: pinned Node build with `npm ci`/root build; pinned Python build with `uv build`; fresh slim runtime installs only the wheel plus frozen `production` extras; copy only hashed Dashboard/Chat assets and release metadata.
- [ ] [FRAME | HIGH] Create a non-root fixed UID/GID, no shell-dependent entrypoint, read-only-compatible filesystem, `/tmp` and cache as bounded tmpfs, and `PYTHONDONTWRITEBYTECODE=1`.
- [ ] [FRAME | HIGH] Add `proof-agent serve-static --surface dashboard|operator-chat --host 0.0.0.0 --port PORT`; it serves immutable assets, SPA fallback, security headers, no directory listing, and an asset digest endpoint.
- [ ] [FRAME | HIGH] Build once by immutable digest. API, Executor, Knowledge Worker, Dashboard, and Operator Chat roles all reference that exact product image digest and differ only by command/config.
- [ ] [FRAME | HIGH] Commit with message `Build hardened multi-role production image`.

## Task 3: Create Stable Gateway and Blue/Green Compose Topology

**Files:**

- Create: `deploy/production/gateway/compose.yaml`
- Create: `deploy/production/gateway/nginx.conf`
- Create: `deploy/production/gateway/active-upstreams.conf`
- Create: `deploy/production/slot/compose.yaml`
- Create: `deploy/production/slot/slot.env.example`
- Create: `tests/test_production_compose.py`
- Create: `tests/test_gateway_configuration.py`

- [ ] [FRAME | HIGH] Render/validate Compose with the exact candidate image digest and `SLOT=blue|green`. Each slot contains separate `api`, `run-executor`, `knowledge-worker`, `dashboard`, and `operator-chat` roles.
- [ ] [FRAME | HIGH] For every product role set non-root user, `read_only: true`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, bounded CPU/memory/PIDs, bounded tmpfs, restart policy, internal network, and no source/secret/run-history bind mount or Docker socket.
- [ ] [FRAME | HIGH] Keep Gateway/TLS/routing config in a separate stable Compose project. Proxy `/api`, `/api/auth/callback`, and SSE with buffering disabled to one slot; proxy `/` and `/operator` assets to the same slot so one config reload switches all surfaces atomically.
- [ ] [FRAME | HIGH] Require TLS, exact trusted hosts/proxy headers/origin, security response headers, bounded request bodies, bounded header/timeouts, and per-session/IP admission-rate protection at Gateway/API; disable production OpenAPI/docs unless explicitly protected. Reject direct public access to slot ports.
- [ ] [FRAME | HIGH] Test `docker compose config`, Nginx config syntax, security options, role commands, same image digest, and absence of prohibited mounts/environment secret values.
- [ ] [FRAME | HIGH] Commit with message `Add stable Gateway and Blue Green Compose slots`.

## Task 4: Implement Liveness and Dependency-Aware Readiness

**Files:**

- Create: `proof_agent/contracts/health.py`
- Create: `proof_agent/observability/health/__init__.py`
- Create: `proof_agent/observability/health/readiness.py`
- Rewrite: `proof_agent/observability/api/routers/health.py`
- Modify: `proof_agent/observability/api/app.py`
- Modify: `proof_agent/delivery/run_executor.py`
- Modify: Knowledge Worker CLI/service
- Create: `tests/test_api_health.py`
- Create: `tests/test_worker_readiness.py`

- [ ] [FRAME | HIGH] Fix endpoints `/livez` for process liveness only and `/readyz` for strict readiness; keep `/api/health` as a non-normative compatibility projection if current development clients need it.
- [ ] [FRAME | HIGH] Readiness reports release ID, OCI digest, slot, role, activation state `STANDBY|ACTIVE|DRAINING`, schema revision/compatible range, and compatibility-manifest digest.
- [ ] [FRAME | HIGH] Probe PostgreSQL transaction/schema, S3 exact read plus a background write-read verification no older than 60 seconds, OIDC discovery/JWKS, Secret Provider probe handle, compiled egress policy, sole Agent/config/artifact refs, and role-specific heartbeat/activation lease.
- [ ] [FRAME | HIGH] Standby workers are ready when dependencies/snapshot/contract are valid but they do not own activation. Do not confuse `STANDBY` with failure or allow it to claim work.
- [ ] [FRAME | HIGH] Return sanitized component status/reason codes; never return DSN, object key credentials, tokens, secret handles, raw endpoints with credentials, or provider payload.
- [ ] [FRAME | HIGH] Commit with message `Add role-aware production readiness`.

## Task 5: Make Migration an Explicit Locked One-Shot Job

**Files:**

- Modify: `deploy/production/slot/compose.yaml`
- Modify: `proof_agent/delivery/cli.py`
- Modify: `proof_agent/capabilities/persistence/postgres/database.py`
- Create: `tests/test_production_migration_job.py`

- [ ] [FRAME | HIGH] Add a non-restarting `migrate` profile/job that runs `proof-agent database upgrade --locked --expand-only --target RELEASE_SCHEMA` from the candidate image before slot startup.
- [ ] [FRAME | HIGH] Write tests for advisory lock exclusion, old/candidate compatible range, already-applied idempotency, failed migration no app startup, and absence of implicit migration in API/worker commands.
- [ ] [FRAME | HIGH] Reject down/destructive migration in the rollback window. Contract/drop work is a later maintenance release after retained rollback assets expire.
- [ ] [FRAME | HIGH] Commit with message `Run production migrations explicitly under lock`.

## Task 6: Implement Exact Blue/Green Deploy and Rollback Choreography

**Files:**

- Create: `scripts/deployment/blue_green.py`
- Create: `proof_agent/deployment/state.py`
- Create: `proof_agent/deployment/gateway.py`
- Create: `proof_agent/deployment/choreography.py`
- Create: `tests/test_blue_green_choreography.py`
- Create: `tests/test_gateway_switch.py`

- [ ] [FRAME | HIGH] Keep Docker/Gateway command execution in the deployment tool, never in Agent runtime. Wrap commands behind test fakes and record every step/result against candidate binding.
- [ ] [FRAME | HIGH] Implement forward steps exactly: validate binding/prechecks; locked expand migration; start candidate `STANDBY`; readiness + isolated smoke; old workers `DRAINING`; wait at most 150 seconds for old claims zero while admission continues; atomically switch all Gateway surfaces; grant candidate higher activation epoch; stable-origin OIDC/submission/SSE/terminal/S3 smoke; 30-minute soak; stop old compute.
- [ ] [FRAME | HIGH] If old claims do not reach zero within 150 seconds, abort before Gateway switch, return old workers to `ACTIVE` at their still-current epoch, keep the candidate in `STANDBY`, and record a failed deployment step; do not strand queued admission or activate the candidate.
- [ ] [FRAME | HIGH] Before switch, run S4 bidirectional N/N-1 queue-contract tests. On failure, require an explicit admission-pause mode for the entire switch/rollback window; never reinterpret queued data.
- [ ] [FRAME | HIGH] Generate candidate Gateway include to a temporary file, run `nginx -t`, atomic rename, reload, then verify one routing generation across UI/API/callback/SSE.
- [ ] [FRAME | HIGH] Implement rollback exactly: route browser/API to ready old API while its Executor remains standby; candidate Executor drains at most 150 seconds or is fenced/leases expire; grant old Executor a higher epoch; fail lost candidate Attempts explicitly; no silent replay/down migration.
- [ ] [FRAME | HIGH] Retain old image/config/assets until later of switch +24 hours and the end of the next complete weekday 09:00–18:00 Asia/Shanghai support window.
- [ ] [FRAME | HIGH] Commit with message `Implement fenced Blue Green deployment choreography`.

## Task 7: Add a Finalized Release Registry and Authenticated Exact Download

**Files:**

- Create: `proof_agent/delivery/release_bundle_api.py`
- Create: `proof_agent/contracts/release_registry.py`
- Create: `proof_agent/contracts/ports/release_registry.py`
- Create: `proof_agent/capabilities/persistence/postgres/release_registry_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/migrations/versions/0005_release_registry.py`
- Modify: `proof_agent/observability/api/app.py`
- Create: `tests/test_release_registry.py`
- Create: `tests/test_release_bundle_download.py`
- Modify: `dashboard/src/api/client.ts`
- Create: `dashboard/src/pages/ReleasesPage.tsx`
- Create: `dashboard/src/pages/__tests__/ReleasesPage.test.tsx`
- Modify: Dashboard router/sidebar/i18n

- [ ] [FRAME | HIGH] Define a small release lifecycle registry, not an approval workflow. `PREPARING` binds candidate/Manifest identity but is not downloadable; one conditional `FINALIZED` transaction stores exact Bundle Index and detached-attestation refs/digests/trust identity plus finalization time.
- [ ] [FRAME | HIGH] Fix endpoint `GET /api/releases/{release_id}/bundle/{artifact_name}`. Trust bootstrap is explicit: the finalized registry directly authorizes only the exact `release-bundle-index.json` and its detached attestation; after verifying those, the exact Index authorizes Manifest, HTML, closure audit, Evidence, SBOM, and provenance members. The Index does not need to contain itself.
- [ ] [FRAME | HIGH] Write red tests for invalid release-state transition, double finalization, wrong candidate/index/attestation, unauthenticated, missing `audit.export`, path/key injection, unverified/unattested index, digest mismatch, non-index member, expired/invisible object, wrong release, range/stream behavior, and successful attachment filename.
- [ ] [FRAME | HIGH] Resolve the exact S3 object version from PostgreSQL and fully materialize/verify length and SHA-256 into a bounded read-only cache before sending response bytes; ranges, if supported, read only that verified immutable cache. Set safe `Content-Disposition: attachment`, `nosniff`, private no-store cache policy, and audit actor/release/object/outcome.
- [ ] [FRAME | HIGH] The endpoint never reads arbitrary local `reports/` paths and never treats HTML as GO/NO-GO authority.
- [ ] [FRAME | HIGH] Commit with message `Add permission-guarded release bundle download`.

## Task 8: Add Production Telemetry, Alerts, and Support Policy

**Files:**

- Create: `proof_agent/observability/metrics.py`
- Create: `proof_agent/observability/synthetic.py`
- Create: `deploy/production/observability/alerts.yaml`
- Create: `docs/operations/support-policy.md`
- Create: `tests/test_production_metrics.py`
- Create: `tests/test_alert_rules.py`

- [ ] [FRAME | HIGH] Expose bounded OpenMetrics for authenticated availability, admission/first-progress/queue/execution/finalization latency, queue/active/overload/cancel/timeout/lease loss, dependency/auth/permission/egress/Secret/artifact failures, orphan/retention backlog, and restore evidence.
- [ ] [FRAME | HIGH] Add an authenticated synthetic core workflow metric; process health alone does not measure the 99.0% monthly availability SLO.
- [ ] [FRAME | HIGH] Compute availability per calendar month with a 99.0% target and exclude no more than four hours of announced maintenance; continue measurement outside the support-response window.
- [ ] [FRAME | HIGH] Define actionable alert rules with owner/severity/runbook link for P0/P1 dependency, queue, security, artifact, retention, and synthetic failures. S7 must prove actual notification delivery through the DCM-bound alert integration.
- [ ] [FRAME | HIGH] Document 5x8 support weekdays 09:00–18:00 Asia/Shanghai, P0 30-minute and P1 four-hour acknowledgement, outside-window best effort, and up to four announced maintenance hours excluded from availability.
- [ ] [FRAME | HIGH] Commit with message `Add production SLO telemetry and support policy`.

## Task 9: Bind Backup, Recovery-Copy, and Restore Policy

**Files:**

- Create: `proof_agent/deployment/backup_policy.py`
- Create: `deploy/production/backup-recovery-policy.schema.json`
- Create: `deploy/production/backup-recovery-policy.example.json`
- Create candidate-local ignored file at execution time: `deploy/production/backup-recovery-policy.json`
- Create: `tests/test_backup_recovery_policy.py`

- [ ] [FRAME | HIGH] Define strict external-policy binding for PostgreSQL PITR/archive cadence, backup retention/encryption/independent authorization, S3 versioning/recovery mechanism, seven-additional-day maximum recovery-copy window, topology digest, backup-policy digest, restore target, and responsible operator/runbook.
- [ ] [FRAME | HIGH] Reject any policy whose maximum recoverable-point interval exceeds 15 minutes, whose recovery copy is ordinarily queryable, whose copy window exceeds seven additional days, or whose exact S3 version recovery/PG PITR is untestable.
- [ ] [FRAME | HIGH] Include this policy/configuration digest in candidate configuration and readiness, and expose no backup credentials to containers or Dashboard.
- [ ] [FRAME | HIGH] S7 must exercise—not merely inspect—this exact policy and measure RPO/RTO; a valid schema alone cannot pass recovery.
- [ ] [FRAME | HIGH] Commit with message `Bind production backup and recovery policy`.

## Task 10: Write Every Required Operations Runbook Before Gate Execution

**Files:**

- Create: `docs/runbooks/README.md`
- Create: `docs/runbooks/oidc-outage.md`
- Create: `docs/runbooks/recovery-oidc-group.md`
- Create: `docs/runbooks/postgresql-outage-and-pitr.md`
- Create: `docs/runbooks/s3-corruption-and-version-recovery.md`
- Create: `docs/runbooks/secret-rotation-and-revocation.md`
- Create: `docs/runbooks/egress-misconfiguration.md`
- Create: `docs/runbooks/executor-loss.md`
- Create: `docs/runbooks/queue-overload.md`
- Create: `docs/runbooks/blue-green-abort-and-rollback.md`
- Create: `docs/runbooks/combined-disaster-recovery.md`
- Create: `docs/runbooks/retention-and-recovery-copy-window.md`
- Modify: `docs/README.md`
- Create: `tests/test_runbook_inventory.py`

- [ ] [FRAME | HIGH] Give every runbook trigger/alert, impact, prerequisites/permissions, safe diagnostic commands, containment, recovery, verification, rollback/abort, escalation, Evidence capture, and post-incident steps.
- [ ] [FRAME | HIGH] Use only commands implemented by S1–S6 or exact deployment-controller commands; no fictional command, destructive wildcard, secret echo, down migration, unverified latest-version recovery, or manual database state edit.
- [ ] [FRAME | HIGH] Include combined restore ordering: restore PostgreSQL PITR and exact S3 versions; reapply retention; hide expired data; verify 100% refs/digests; validate sole Agent; authenticated smoke; then traffic.
- [ ] [FRAME | HIGH] Keep English authoritative now; Chinese sync occurs only in S8.
- [ ] [FRAME | HIGH] Commit with message `Add initial production operations runbooks`.

## Task 11: S6 Clean-Room Verification and Review

- [ ] [KNOWN | HIGH] Run:

```bash
uv build
npm ci
npm test
npm run build
docker buildx build --file deploy/production/Dockerfile --tag proofagent:candidate --load .
docker compose -f deploy/production/gateway/compose.yaml config
SLOT=green PROOF_AGENT_IMAGE="${PROOF_AGENT_CANDIDATE_IMAGE}" \
  docker compose -f deploy/production/slot/compose.yaml config
uv run --extra dev --extra production python -m pytest \
  tests/test_deployment_compatibility_manifest.py \
  tests/test_static_server.py \
  tests/test_production_image_layout.py \
  tests/test_production_compose.py \
  tests/test_gateway_configuration.py \
  tests/test_api_health.py \
  tests/test_worker_readiness.py \
  tests/test_production_migration_job.py \
  tests/test_blue_green_choreography.py \
  tests/test_gateway_switch.py \
  tests/test_release_bundle_download.py \
  tests/test_release_registry.py \
  tests/test_production_metrics.py \
  tests/test_alert_rules.py \
  tests/test_backup_recovery_policy.py \
  tests/test_runbook_inventory.py -v
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests scripts
uv run --extra dev --extra openai --extra production mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

- [ ] [FRAME | HIGH] Run an isolated Blue/Green rehearsal against production-equivalent external dependencies through readiness, standby, drain, switch, activation, smoke, 30-minute soak, and rollback; S7 later binds the full Gate Evidence.
- [ ] [FRAME | HIGH] Independently review image contents/hardening, Compose privilege/network/secret boundaries, DCM completeness, readiness depth, migration locking, switch atomicity, rollback ordering/fencing, download authorization, telemetry coverage, and runbook executability.
- [ ] [FRAME | HIGH] Resolve all P0/P1 findings, record the S6 commit in the master plan, and only then start candidate Gate production.
