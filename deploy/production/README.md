# Production deployment assets

[KNOWN | HIGH] This directory now contains the checked-in foundations for S6: a strict Deployment Compatibility Manifest contract, a multi-stage product image, hardened Blue/Green slot Compose, a stable Nginx Gateway Compose, and the runtime binding for finalized Release Registry downloads. These files are production-oriented definitions, not evidence that a production candidate has been built, scanned, deployed or approved.

## Files

- `deployment-compatibility-manifest.schema.json` — editor/schema aid;
- `deployment-compatibility-manifest.example.json` — non-authoritative shape example with placeholder digests;
- `deployment-compatibility-manifest.json` — ignored, environment-specific candidate input;
- `Dockerfile` and `Dockerfile.dockerignore` — same-image API/Executor/Worker/static build;
- `slot/compose.yaml` and `slot/slot.env.example` — one `blue` or `green` product slot plus a non-restarting explicit migration profile;
- `gateway/compose.yaml` — stable Gateway outside both slots;
- `gateway/nginx.conf` — safe checked-in template whose `proof-agent.invalid` host must be rendered to the exact DCM-bound stable host;
- `gateway/active-upstreams.conf` — controller-owned atomic routing generation, initially pointing to blue.
- `gateway/admission-control.conf` — controller-owned atomic Run admission switch, initially open;
- `blue-green-request.example.json` — secret-free controller request shape; all identities and digests are placeholders;
- `docker-compose-driver.example.json` — strict, secret-free configuration shape for the built-in Compose operations driver;
- `stable-smoke-request.example.json` — non-secret synthetic Run input used by stable-origin smoke;
- `../../scripts/deployment/blue_green.py` — external, shell-free choreography runner and Docker/nginx control boundary; it is not copied into the product image.
- `../../scripts/deployment/compose_driver.py` — built-in `docker-compose-v1` operations driver; it is also excluded from the product image.

## Required preflight

Create the candidate-local DCM from the example using real exact product versions, immutable service revisions and fresh content-addressed Evidence. Never reuse the example hashes. Validate it at an explicit decision time:

```bash
proof-agent deployment validate-compatibility \
  --manifest deploy/production/deployment-compatibility-manifest.json \
  --at 2026-07-25T12:00:00Z
```

Build only with immutable `name@sha256:...` base references supplied by the candidate workflow:

```bash
docker buildx build \
  --file deploy/production/Dockerfile \
  --build-arg NODE_IMAGE="$NODE_IMAGE" \
  --build-arg UV_IMAGE="$UV_IMAGE" \
  --build-arg RUNTIME_IMAGE="$RUNTIME_IMAGE" \
  --tag proofagent:candidate \
  --load .
```

The build result must then be addressed by its registry digest; a mutable local tag is not an admissible Compose value.

Before starting a slot, create the external `proofagent-blue` and `proofagent-green` networks, external Vault/TLS secrets, candidate-local slot env file and exact config files. Validate rendering before mutation:

```bash
docker compose -f deploy/production/slot/compose.yaml config --quiet
docker compose -f deploy/production/gateway/compose.yaml config --quiet
```

Run the candidate migration job as a distinct step before starting any candidate service. `PROOF_AGENT_RELEASE_SCHEMA` must equal the Alembic head packaged in that exact image:

```bash
docker compose \
  --env-file /path/to/candidate-slot.env \
  -f deploy/production/slot/compose.yaml \
  --profile migration run --rm migrate
```

The job uses the same immutable image, obtains the global PostgreSQL advisory lock, accepts only revisions in the reviewed expand-only allowlist, and never performs a downgrade. A failed job is a deployment stop condition; API and worker startup do not retry or hide it.

[KNOWN | HIGH] Candidate processes honor `PROOF_AGENT_ACTIVATION_STATE`: only an `ACTIVE` process holding the exact PostgreSQL role lease claims work; `STANDBY` and `DRAINING` do not start new claims. Run Executor and Knowledge Worker expose loopback `/readyz` on ports 8001 and 8002, and Compose marks a process unhealthy when dependencies or its exact role lease are unavailable.

## Release Registry and exact downloads

[KNOWN | HIGH] Alembic revision `0013_release_registry` adds the two-state Release Registry. `PREPARING` binds one candidate-binding SHA-256 and exact Release Gate Manifest but is never downloadable. A single conditional PostgreSQL transaction changes it to `FINALIZED` and records the exact Bundle Index, detached attestation, trust identity and finalization time. A second finalization or any candidate, Manifest, owner, index or attestation mismatch fails closed.

The API needs a bounded tmpfs cache and deployment-owned Ed25519 public-key set:

```dotenv
PROOF_AGENT_RELEASE_BUNDLE_CACHE_DIR=/var/lib/proofagent/release-bundle-cache
PROOF_AGENT_RELEASE_TRUSTED_ED25519_KEYS_JSON={"release-key-2026-07":"BASE64_OF_32_RAW_PUBLIC_KEY_BYTES"}
```

The detached envelope uses schema `proofagent.release-bundle-attestation.v1` and protocol `ed25519-sha256-v1`. It binds `issuer`, `subject`, `key_id`, the lowercase SHA-256 of the exact Index bytes, and an Ed25519 signature over `proofagent.release-bundle-index.v1\0` followed by the 32 digest bytes. Those identity fields must exactly equal the finalized Registry trust identity. Public keys are not Secrets, but the mapping is deployment configuration and must be reviewed, candidate-bound and rotated deliberately.

[KNOWN | HIGH] An authenticated operator with `audit.export` uses Dashboard `/releases` or `GET /api/releases/{release_id}/bundle/{artifact_name}`. The endpoint first materializes and verifies the exact PostgreSQL/S3 versions of `release-bundle-index.json` and its detached attestation into the read-only cache. Only then may the verified Index authorize its exact Manifest, HTML report, closure audit, Evidence, SBOM and provenance members. It supports single byte ranges from that cache, returns an attachment with `private, no-store` and `nosniff`, and records the actor, release, object and outcome in audit metadata. It never reads a repository-local `reports/` path, and the HTML report is never release authority.

[KNOWN | HIGH] This repository provides the Registry, download verifier and UI prerequisite, but no real candidate is finalized here. Post-GO bundle generation/finalization and candidate-bound download evidence remain S8B/S7B work; do not create a fake `FINALIZED` row or treat an empty Registry as release approval.

[KNOWN | HIGH] The provider-neutral controller now implements the exact forward, pre-switch abort and post-switch rollback state machine. Gateway changes render all upstreams and routing markers into a same-directory temporary include, validate it inside the running Gateway image, atomically replace it, reload nginx, then verify one generation across Dashboard, Operator Chat, API, OIDC callback and SSE. Mixed generations restore the old include and reload it. Every recorded step carries the candidate-binding SHA-256; rollback assets receive the later of a 24-hour deadline and the end of the next complete weekday 09:00–18:00 Asia/Shanghai support window.

[KNOWN | HIGH] Gateway Compose bind-mounts the controller directory, not the active include as a single file. This is required because a single-file bind pins the old inode and would hide a host-side atomic rename from nginx; keep the directory mount read-only and never replace it with a single-file mount.

[KNOWN | HIGH] The repository now includes the first concrete `docker-compose-v1` driver. It binds both immutable images and all candidate files, checks the current API/Worker authority, runs the locked migration, starts all candidate roles in standby, executes isolated readiness and bidirectional N/N-1 queue validation, atomically pauses Run admission only when explicitly authorized, drains/resumes Workers by safe signals, counts both PostgreSQL claim authorities, promotes with a higher epoch, runs stable-origin OIDC/session/submission/SSE/terminal/S3 smoke, soaks for exactly 30 minutes, and implements route-first rollback with fencing and lost-Attempt failure. External entry points remain supported for other environments.

[KNOWN | HIGH] This implementation has only local fake-command and contract verification in this workspace. It has not been exercised against a running Docker/nginx host, real OIDC session, real candidate image or disposable Blue/Green dependency stack. Production remains NO-GO until that rehearsal and the candidate-bound Gates pass.

Before an approved rehearsal, create four reviewed slot env files (`blue|green` × `active|standby`), copy both examples to candidate-local files, and create a mode-`0600`, non-symlink smoke session file containing only an already-authorized short-lived cookie:

```json
{"session_cookie":"replace-with-opaque-short-lived-session-cookie"}
```

Never commit that file or print it in deployment output. The smoke principal requires `run.submit` and `run.view`. Its synthetic Run must reach `succeeded`, then the driver reads the exact S3-backed result and receipt through the stable API.

If N/N-1 queue validation reports an incompatibility and the reviewed request explicitly authorizes admission pause, the stable-origin check must observe `POST /api/runs` returning 503 for the full transition instead of creating a synthetic Run. That fallback deliberately cannot claim submission/SSE/S3 smoke evidence; the disposable rehearsal and deployment Gate must record the reduced evidence path.

After all preflight evidence is approved, the controller shape is:

```bash
python3 scripts/deployment/blue_green.py \
  --request /approved/change/blue-green-request.json \
  --journal /immutable/evidence/blue-green-result.json \
  --driver docker-compose-v1 \
  --driver-config /approved/change/docker-compose-driver.json \
  --gateway-compose deploy/production/gateway/compose.yaml \
  --gateway-nginx-config deploy/production/gateway/nginx.conf \
  --gateway-active-include deploy/production/gateway/active-upstreams.conf \
  --stable-origin https://proof-agent.example.internal \
  --tls-ca-file /approved/pki/internal-ca.pem
```

This is an execution command, not a preflight example. It mutates migrations, slot lifecycle, PostgreSQL Worker authority, Run admission and Gateway routing. Use it only in an approved change window after a disposable Blue/Green rehearsal. A real run can sleep for the fixed 30-minute soak and returns a mode-`0600` journal; do not interrupt it merely because it is quiet.
