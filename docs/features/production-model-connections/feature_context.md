# Production Model Connections

## Objective

[KNOWN | HIGH] The production Dashboard must manage Shared Model Connections through an OIDC-authorized API backed by the authoritative PostgreSQL configuration unit of work. Production requests must reference model credentials only through `ProductionSecretHandle`; raw credentials and environment-variable credential references are not accepted.

## User-visible problem

[KNOWN | HIGH] `POST /api/config/model-connections` currently falls through to the Dashboard SPA static-file mount in production and returns HTTP 405. The development-only configuration router cannot be mounted in production because it depends on `LocalAgentConfigurationStore` and environment credential references.

## Governing context

- `docs/adr/0020-live-shared-model-connections.md`
- `docs/adr/0126-initial-production-authorization-uses-global-named-permissions.md`
- `docs/domain/tools-models-memory/CONTEXT.md`
- `AGENTS-COMMON.md`
