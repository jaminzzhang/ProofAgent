# Local production-shaped Docker deployment

[FRAME | HIGH] This stack exercises the production composition and fail-closed
boundaries on one workstation. It is not a Phase F release authorization and does
not replace real model, capacity, recovery, or acceptance evidence.

## Topology

- TLS gateway: `https://proof-agent.localhost:8443`
- Knowledge Source Service TLS gateway: `https://proof-agent.localhost:8444`
- PostgreSQL authority: `127.0.0.1:55433`
- MinIO S3 API/console: `127.0.0.1:59010` / `127.0.0.1:59011`
- OpenSearch diagnostic port: `127.0.0.1:19210`
- OIDC: Keycloak behind `/oidc`
- Vault KV v2 for non-model secrets, PostgreSQL-encrypted model credentials, OpenSearch,
  and nine private-model origins behind the internal TLS gateway
- production API, Knowledge Worker, and same-image Run Executor roles
- one KSS image running isolated API, Query Executor, Knowledge Worker, Sync Scheduler,
  and one-shot Migration roles

[KNOWN | HIGH] ProofAgent and KSS share the physical PostgreSQL container but not a
logical database or login credential. ProofAgent owns `proof`; the dedicated,
non-superuser `knowledge_source_service` role owns the `knowledge_source_service`
database, its `public` schema, all KSS tables, and its migration ledger. KSS also owns
the versioned `proof-agent-knowledge-local` bucket namespace. Do not point KSS at the
`proof` database or reuse the `proof` role: both products have independent logical
authority and may use the same table names.

[KNOWN | HIGH] The local model plane is deterministic protocol compatibility only.
Its release verifier always denies authorization, so it cannot create formal Phase F
evidence.

## Requirements

- Docker Desktop with Compose v2/v5 and BuildKit
- `openssl`, `curl`, and `python3` on the host
- at least 6 GiB free Docker memory (OpenSearch is configured with a 768 MiB heap)

## Start

From the repository root:

```bash
./scripts/production-local-up.sh
```

The prepare step creates `.env.production-local`, including a separate random KSS
database credential, a model-credential keyring, a local CA, and a short-lived
deployment-compatibility fixture under
`docker/production-local/runtime/`. These paths are ignored by Git. The fixture exists
only to exercise the production composition's strict startup and freshness checks; its
`Local Harness` identities are not candidate-bound compatibility evidence and cannot
authorize a release. The prepare step also uses an anonymous deployment-local Docker
CLI configuration so a broken desktop credential helper cannot block public image
pulls; the host Docker login is not modified.

Open `https://proof-agent.localhost:8443`. KSS readiness is available at
`https://proof-agent.localhost:8444/readyz`. The certificate is issued by the generated
local CA, so a browser will warn until
`docker/production-local/runtime/tls/ca.crt` is trusted locally.

The local OIDC user is `proof-admin`. Retrieve its generated password without copying
the whole secret file:

```bash
sed -n 's/^PROOF_AGENT_ADMIN_PASSWORD=//p' .env.production-local
```

This is a Keycloak test identity inside the local OIDC realm, not a ProofAgent local
account or a production identity source.

[KNOWN | HIGH] Startup also publishes the checked-in reference-only Metadata Profile
and binds it only to the designated local fixture Source `ks_insurance` when that
Source exists. The Knowledge Worker allowlist is exact and defaults to empty outside
this harness; production deployments must publish and bind an authority-owned Profile
instead. The security bootstrap appends an immutable Permission Mapping revision when
new permissions are introduced. Existing operator sessions are invalidated by that
permission epoch change and must sign in again to receive refreshed claims.

After login, create `model_production_primary` on the Models page and enter the real
provider API Key once. The browser sends it only on create or replacement; API
responses show only `PostgreSQL encrypted`. The value is encrypted before the same
transaction commits the model connection and is never stored in the connection JSON.

## Verify

```bash
./scripts/production-local-verify.sh
```

The verifier checks the Agent TLS liveness endpoint, KSS TLS readiness, exact OIDC
issuer, the Agent private-model routes, TLS OpenSearch access, both PostgreSQL migration
ledgers, the KSS non-superuser role/database/schema/table ownership boundary, and
versioning on both S3 buckets. KSS readiness passes only when PostgreSQL, object storage,
and search are all ready. Any KSS database ownership drift fails verification.

After a Hybrid document completes, the `Reviews` tab should show
`proofagent-insurance-reference.v1`, the current Review Set, and the generated review
tasks. `Prepare publication` remains disabled until those tasks satisfy the governed
metadata review policy.

[KNOWN | HIGH] Before the sole Agent is published, `/livez` returns HTTP 200 while
`/readyz` returns HTTP 503 with only `published_agent=not_ready`. Run Executor remains
running and waits for that publication instead of falling back to local authority.

Useful diagnostics:

```bash
DOCKER_CONFIG="$PWD/docker/production-local/runtime/docker-cli" \
  docker compose --env-file .env.production-local \
  -f docker-compose.production-local.yml ps -a

DOCKER_CONFIG="$PWD/docker/production-local/runtime/docker-cli" \
  docker compose --env-file .env.production-local \
  -f docker-compose.production-local.yml logs -f api knowledge-worker run-executor

DOCKER_CONFIG="$PWD/docker/production-local/runtime/docker-cli" \
  docker compose --env-file .env.production-local \
  -f docker-compose.production-local.yml logs -f \
  kss-api kss-query-executor kss-knowledge-worker kss-sync-scheduler
```

## Model credential key rotation

The keyring JSON has `active_key_version` and a `keys` mapping of version names to
base64-encoded 32-byte keys. Rotate it in this order:

1. add `v2` while retaining `v1`, set `active_key_version` to `v2`, and replace the
   keyring file atomically;
2. recreate `api` and `run-executor` so both can decrypt old rows and write `v2`;
3. replace every API Key from the Models detail page (blank keeps the current key);
4. verify `SELECT key_version, count(*) FROM model_connection_credentials GROUP BY
   key_version` reports no `v1` rows;
5. remove `v1` from the keyring and recreate the processes again.

Keep PostgreSQL and keyring backups as separate protected recovery assets. Never
remove an old key version while any row still uses it. If the keyring is lost, the
encrypted API keys cannot be recovered and must be entered again.

## Stop and reset

Stop while preserving PostgreSQL, S3, OpenSearch, Vault, and Keycloak volumes:

```bash
./scripts/production-local-down.sh
```

To intentionally delete all local stack data, append `--volumes` to the equivalent
`docker compose down` command. This is destructive and is not performed by the helper.

## Replacing the compatibility model plane

Set the scheduler, Docling, Paddle, embedding, reranker, evaluation, KSS projection,
KSS Agentic controller, and KSS OCR origins to real private HTTPS services. Update the
exact Egress Policy revision and pinned model digests, then execute the S1-S6 and 13
formal release Gates. Do not change production mode to accept HTTP, runtime downloads,
filesystem authority, or unguarded clients.
