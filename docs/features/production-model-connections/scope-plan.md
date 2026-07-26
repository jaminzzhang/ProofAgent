# Production Model Connections Scope Plan

> Historical plan. ADR-0153 supersedes the model Secret Handle decision with a
> write-only API Key encrypted in PostgreSQL under an external versioned keyring.

## In scope

1. Add an independent production Model Connection Configuration API mounted at `/api/config/model-connections`.
2. Persist create and lifecycle updates through `PostgresConfigurationUnitOfWork`, including an audit record in the same transaction.
3. Require optimistic revision preconditions for production mutations after creation.
4. Accept only `ProductionSecretHandle` credentials with purpose `model_credential` and the configured provider protocol.
5. Preserve OIDC permission and CSRF enforcement at the existing production middleware boundary.
6. Return list, detail, reference summary, deletion eligibility, validation, and smoke-test projections needed by the existing Models workspace.
7. Make the Dashboard choose environment references in development and Secret Handles in production from API capability metadata.

## Out of scope

- Secret creation, rotation, or deletion; those remain deployment/Vault responsibilities.
- Provider-specific model inventory discovery.
- Enabling shared model connections for the sole production Agent publication contract, which still has its own candidate admission rules.
- Automatic remote smoke calls; this slice may return a trace-safe skipped record after Secret Handle validation.

## Acceptance

- Production create no longer reaches `StaticFiles` and returns 201 for an authorized, CSRF-valid request.
- Environment credential references are rejected by the production API.
- PostgreSQL model version and configuration audit commit atomically.
- Stale revisions return 409 without partial audit writes.
- Dashboard submits a Secret Handle in production and preserves the existing environment-reference behavior in development.
