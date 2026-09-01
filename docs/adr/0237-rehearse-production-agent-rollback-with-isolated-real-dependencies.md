---
status: accepted
---

# Rehearse Production Agent rollback with isolated real dependencies

[KNOWN | HIGH] ADR-0234 through ADR-0236 define exact KSS Release revalidation,
caller-confirmed Active pointer fencing, PostgreSQL atomicity, and a default-closed
Production HTTP admission gate. Before TDD-06H, these contracts had not been exercised
together against a real KSS management HTTP client and real PostgreSQL authorities.

[DECISION | HIGH] Add one zero-argument repository verification entry that creates an
exactly named, disposable Compose project with `--env-file /dev/null`. Each test creates
separate random PostgreSQL schemas for ProofAgent and KSS. KSS uses its real runtime,
PostgreSQL Catalog, Release lifecycle repository, and
`KnowledgeSourceServiceManagementClient` over the management HTTP contract. ProofAgent
uses the Production rollback POST, OIDC session and same-origin CSRF middleware, the
existing Agent Configuration Workspace, and `PostgresConfigurationUnitOfWork`.

[DECISION | HIGH] The rollback gate may be true only inside this isolated test
composition. The real Production API composition remains explicitly false. The
rehearsal proves two observable paths: a `queryable` exact Release permits one pointer
and audit commit, while a Release retired through the real KSS lifecycle returns the
stable conflict and leaves the pointer and audit unchanged.

[CONSEQUENCE | HIGH] TDD-06H adds no rollback service, persistence adapter, SQL,
migration, role mapping, or Production configuration. The checked-in entry starts only
the PostgreSQL test service, requires PostgreSQL tests instead of accepting skips, and
removes the exact Compose project and its re-creatable state on exit.

[BOUNDARY | HIGH] KSS runs in process behind a FastAPI TestClient and uses an in-memory
immutable artifact store because rollback reads Catalog state only. This does not prove
deployed TLS, Vault, network egress, multi-process topology, a cross-service lease, or an
emergency state change racing after preflight. It does not operate existing
`proofagent-production-local` data, enable the real gate, execute an online rollback,
call a KSS Query or model, create a Grant/Reference, publish, deploy, grant a Release
Gate, or establish Production GO.
