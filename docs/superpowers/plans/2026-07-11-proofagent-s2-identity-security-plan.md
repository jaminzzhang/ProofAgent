# Proof Agent S2 Identity and Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Enforce OIDC-exclusive production access, tenant-global named permissions, server-side Secret Handles, default-deny exact-origin egress, and read-only production tools without adding a local user or approval system.

**Architecture:** [FRAME | HIGH] Add strict security contracts and Control Plane services, persist sessions and versioned security configuration in PostgreSQL, keep OIDC/provider tokens server-side, route every outbound production call through one guarded HTTPS transport, and make backend authorization authoritative while the Dashboard projects permitted controls.

**Tech Stack:** [FRAME | HIGH] FastAPI, Authlib, cryptography AES-GCM, httpx, PostgreSQL, Pydantic v2, React 19, Vitest, pytest, contract-faithful OIDC and Secret Provider test services.

---

## Prerequisites and External Binding Checkpoint

- [ ] [FRAME | HIGH] Begin only after S1 is merged and its production PostgreSQL composition is green.
- [ ] [KNOWN | HIGH] Read the identity, tool/model/memory, app-surface, and Agent-configuration contexts routed by `CONTEXT-MAP.md`.
- [ ] [FRAME | HIGH] Before implementing the concrete Secret Provider adapter, record one exact protocol/adapter choice in `deploy/production/compatibility-input.json` with authentication method and versioned contract tests. The implementation must not invent universal Secret Provider compatibility; S6 later binds the exact deployed product/version/digest.
- [ ] [FRAME | HIGH] Exit only when production has no local identity, wildcard CORS, browser provider token, raw stored secret, environment credential reference, unguarded outbound request, approval-required tool, local handler, MCP stdio, or state-changing tool path.

## Task 1: Define Security Contracts and Exact Permission Vocabulary

**Files:**

- Create: `proof_agent/contracts/identity.py`
- Create: `proof_agent/contracts/security.py`
- Create: `proof_agent/contracts/secrets.py`
- Create: `proof_agent/contracts/egress.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `proof_agent/observability/api/operator_identity.py`
- Create: `tests/test_operator_permissions.py`

- [ ] [FRAME | HIGH] Write a red exact-set test for the approved permission vocabulary and one proving `approval.resolve` is impossible.
- [ ] [FRAME | HIGH] Implement a `Permission` string enum with exactly:

```text
run.submit, run.view, run.cancel
agent.view, agent.edit, agent.validate, agent.publish
knowledge_source.view, knowledge_source.edit, knowledge_source.publish, knowledge_source.archive
model_connection.view, model_connection.edit, model_connection.validate, model_connection.archive
tool_source.view, tool_source.edit, tool_source.validate, tool_source.archive
evaluation.view, evaluation.run, evaluation_curation.review
permission_mapping.view, permission_mapping.edit
egress_policy.view, egress_policy.edit
secret_handle.view, secret_handle.use
audit.view, audit.export
```

- [ ] [FRAME | HIGH] Define strict frozen OIDC principal, session, permission mapping/version, recovery mapping, authorization decision/audit, Secret Handle, exact HTTPS origin, Egress Policy/version, and production tool-effect contracts.
- [ ] [FRAME | HIGH] Keep provider SDK tokens/types and raw secrets out of contracts; use opaque encrypted-envelope bytes only in the session repository adapter. The single tenant is deployment-owned and never accepted from a browser/request parameter; do not add tenant switching or resource ACLs.
- [ ] [KNOWN | HIGH] Run the focused contracts/permission tests and mypy.
- [ ] [FRAME | HIGH] Commit with message `Define production identity and security contracts`.

## Task 2: Add Versioned Permission Mapping and Recovery Group

**Files:**

- Create: `proof_agent/control/security/__init__.py`
- Create: `proof_agent/control/security/permissions.py`
- Create: `proof_agent/contracts/ports/security_configuration.py`
- Create: `proof_agent/capabilities/persistence/postgres/security_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/migrations/versions/0002_identity_security.py`
- Create: `tests/test_permission_mapping.py`
- Modify: local persistence adapters for deterministic development

- [ ] [FRAME | HIGH] Write red tests for unmatched identity default-deny, union of all matched trusted groups/roles, atomic activation, invalid mapping rollback, previous-version rollback, immutable audit, and recovery mapping deletion/weakening/replacement rejection.
- [ ] [FRAME | HIGH] Persist immutable versions plus exactly one active pointer. Put complete validation, active-pointer switch, and audit append in one transaction.
- [ ] [FRAME | HIGH] Load the Recovery OIDC Group name and trusted claim path from deployment configuration, not Dashboard state. It always grants at least `permission_mapping.view`, `permission_mapping.edit`, and `audit.view`.
- [ ] [FRAME | HIGH] Expose ordinary mapping editing without approval; do not create per-user grants, resource ACLs, a user directory, or a user-management page.
- [ ] [FRAME | HIGH] Commit with message `Add global permission mapping and recovery group`.

## Task 3: Implement Backend-Managed OIDC Sessions

**Files:**

- Create: `proof_agent/contracts/ports/oidc.py`
- Create: `proof_agent/capabilities/identity/__init__.py`
- Create: `proof_agent/capabilities/identity/oidc_client.py`
- Create: `proof_agent/control/security/sessions.py`
- Create: `proof_agent/control/security/token_cipher.py`
- Create: `proof_agent/delivery/auth_api.py`
- Modify: `proof_agent/observability/api/app.py`
- Modify: `proof_agent/observability/api/dependencies.py`
- Create: `tests/fakes/oidc_provider.py`
- Create: `tests/test_oidc_sessions.py`

- [ ] [FRAME | HIGH] Add explicit dependencies under a `security`/`production` extra: Authlib, cryptography, and httpx; regenerate `uv.lock`.
- [ ] [FRAME | HIGH] Fix route contracts now and use them consistently:

```text
GET  /api/auth/login
GET  /api/auth/callback
GET  /api/auth/session
POST /api/auth/logout
```

- [ ] [FRAME | HIGH] Write red tests individually for state, nonce, PKCE, issuer, audience, signature, and callback replay failures before happy-path login.
- [ ] [FRAME | HIGH] Store only `SHA-256(session_token)` plus an AES-GCM encrypted provider-token envelope. The encryption key is resolved server-side through a dedicated Secret Handle and never stored in PostgreSQL or sent to the browser.
- [ ] [FRAME | HIGH] Set the browser cookie `Secure; HttpOnly; SameSite=Lax; Path=/` with a seven-day maximum; enforce server-side absolute expiry at login + 7 days and idle expiry after 24 hours without accepted operator activity.
- [ ] [FRAME | HIGH] Revalidate or refresh trusted claims before they become one hour old. Failure, revocation, issuer/audience drift, or invalid signature revokes the session and requires login. Rotate the opaque browser token after login, successful provider refresh, and privilege-relevant mapping change.
- [ ] [FRAME | HIGH] Bind each encrypted provider-token envelope to a key version. If the selected Secret Provider cannot resolve an overlapping prior version, rotating the session-envelope key deliberately revokes existing sessions and requires login; test and audit this fail-secure behavior.
- [ ] [FRAME | HIGH] Keep provider access/refresh/ID tokens server-side; `/api/auth/session` returns only trace-safe identity display, expiry, claim freshness, CSRF bootstrap, and effective permissions.
- [ ] [FRAME | HIGH] Commit with message `Add OIDC-exclusive backend sessions`.

## Task 4: Bind a Concrete External Secret Provider Adapter

**Files:**

- Create: `proof_agent/contracts/ports/secret_provider.py`
- Create: `proof_agent/capabilities/secrets/__init__.py`
- Create: `proof_agent/capabilities/secrets/configured_provider.py`
- Create: `proof_agent/capabilities/secrets/local_environment.py`
- Create: `proof_agent/capabilities/secrets/provider_adapter.py`
- Create: `deploy/production/compatibility-input.schema.json`
- Create: `deploy/production/compatibility-input.example.json`
- Create candidate-local ignored file at execution time: `deploy/production/compatibility-input.json`
- Create: `tests/fakes/secret_provider.py`
- Create: `tests/test_secret_handles.py`
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `proof_agent/bootstrap/model_resolution.py`

- [ ] [FRAME | HIGH] Write a provider contract suite before its adapter: validate opaque handle, resolve bytes server-side, missing/revoked failure, immediate rotation observation, no response/log/trace disclosure, bounded retry, and audit-safe error.
- [ ] [FRAME | HIGH] Validate the environment-specific compatibility input against its strict schema, then implement exactly that one selected protocol in `provider_adapter.py`; reject any production configuration whose protocol ID differs. S6 consumes the verified choice into the full DCM.
- [ ] [FRAME | HIGH] Keep `local_environment.py` available only when `PROOF_AGENT_MODE=development`; production validation rejects `*_env`, raw credential, inline token, password, connection string, and secret-looking values.
- [ ] [FRAME | HIGH] Change model, Knowledge, tool, OIDC-client-secret, session-envelope-key, PostgreSQL, and S3 credential configuration to opaque handles or deployment-injected infrastructure identity as appropriate.
- [ ] [FRAME | HIGH] Proof Agent validates/resolves handles but never creates, rotates, reveals, or deletes provider secrets.
- [ ] [FRAME | HIGH] Commit with message `Resolve production Secret Handles server-side`.

## Task 5: Enforce Same-Origin and CSRF on Every Mutation

**Files:**

- Create: `proof_agent/control/security/csrf.py`
- Create: `proof_agent/observability/api/security_middleware.py`
- Modify: `proof_agent/observability/api/app.py`
- Modify: every state-changing router under `proof_agent/delivery/` and `proof_agent/observability/api/routers/`
- Create: `tests/test_csrf.py`

- [ ] [FRAME | HIGH] Write one red matrix test that enumerates all state-changing routes and expects rejection without authenticated session, allowed stable `Origin`, and `X-CSRF-Token` tied to that session.
- [ ] [FRAME | HIGH] Remove wildcard CORS. Production serves Dashboard, Operator Chat, API, OIDC callback, and SSE from the stable same origin; no cross-origin credentialed browser API is supported.
- [ ] [FRAME | HIGH] Use constant-time CSRF comparison, rotate the CSRF token with session rotation, and reject missing/foreign `Origin`/`Referer` for browser mutations.
- [ ] [FRAME | HIGH] Add authoritative permission dependencies to every route; frontend visibility never substitutes for backend checks.
- [ ] [FRAME | HIGH] Commit with message `Enforce session CSRF and route permissions`.

## Task 6: Add Versioned Exact-Origin Egress Policy and Guarded HTTPS

**Files:**

- Create: `proof_agent/contracts/ports/guarded_http.py`
- Create: `proof_agent/control/security/egress.py`
- Create: `proof_agent/capabilities/egress/__init__.py`
- Create: `proof_agent/capabilities/egress/guarded_http.py`
- Modify: `proof_agent/capabilities/models/openai_compatible.py`
- Modify: `proof_agent/capabilities/knowledge/http_json.py`
- Modify: `proof_agent/capabilities/tools/brave_search.py`
- Modify: retained remote MCP/HTTPS adapter files after S0
- Create: `tests/test_egress_policy.py`
- Create: `tests/test_guarded_http.py`

- [ ] [FRAME | HIGH] Write red tests for exact allowed HTTPS origins and denial of HTTP, wildcard, userinfo, fragment, implicit widening, arbitrary port, off-policy redirect, retry to another origin, mixed/off-policy DNS results, DNS rebinding, and provider SDK bypass.
- [ ] [FRAME | HIGH] Normalize origins as lowercase IDNA host + explicit effective port, with no path/query. Policy activation is completely validated and atomic; previous version remains auditable/rollbackable.
- [ ] [FRAME | HIGH] For each hop, resolve the admitted hostname, validate every candidate address against the compiled decision, connect to a validated address while preserving TLS hostname verification, and repeat after redirect/retry. Never follow a redirect before authorizing its exact new origin.
- [ ] [FRAME | HIGH] Inject this transport into every model, Knowledge, tool, remote MCP, OIDC, and Secret Provider HTTP call. A production dependency-layout test forbids direct `httpx`, `urllib`, `requests`, provider-client transport, or socket construction outside admitted adapter modules.
- [ ] [FRAME | HIGH] Audit denials with trace-safe origin/reason codes and no credentials/query payload.
- [ ] [FRAME | HIGH] Commit with message `Enforce default-deny exact-origin egress`.

## Task 7: Reject Non-Read-Only Production Tools

**Files:**

- Modify: `proof_agent/contracts/tool.py`
- Modify: `proof_agent/capabilities/tools/gateway.py`
- Modify: `proof_agent/capabilities/tools/source_descriptors.py`
- Modify: retained remote tool/MCP modules
- Modify: `proof_agent/control/workflow/controlled_react/tool_proposal_scope.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `proof_agent/configuration/compiler.py`
- Create: `tests/test_production_tool_admission.py`

- [ ] [FRAME | HIGH] Add publication and runtime red tests for Local Tool Handler, MCP stdio, approval-required tools, and effects `create`, `update`, `delete`, `send`, `settle`, `execute`, or any unknown effect.
- [ ] [FRAME | HIGH] Require an explicit `effect: read`, immutable Tool Contract digest, exact HTTPS origin, bounded schema, Secret Handle refs, and successful `tool_source.validate` result before publication.
- [ ] [FRAME | HIGH] Repeat the same rejection at runtime scope resolution against the frozen execution snapshot; a stale/altered source cannot regain authority.
- [ ] [FRAME | HIGH] Keep state-changing behavior denied even when the tool declares an idempotency key.
- [ ] [FRAME | HIGH] Commit with message `Enforce read-only production tool boundary`.

## Task 8: Add Direct Dashboard Security Configuration

**Files:**

- Create: `proof_agent/delivery/security_configuration_api.py`
- Modify: `proof_agent/observability/api/app.py`
- Create: `dashboard/src/pages/SecurityPage.tsx`
- Create: `dashboard/src/pages/__tests__/SecurityPage.test.tsx`
- Create: `dashboard/src/auth/session.tsx`
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/router.tsx`
- Modify: `dashboard/src/components/Sidebar.tsx`
- Modify: `chat/src/api/client.ts`
- Create: `tests/test_security_configuration_api.py`

- [ ] [FRAME | HIGH] Fix API routes:

```text
GET/POST /api/security/permission-mappings
POST     /api/security/permission-mappings/{version}/activate
GET/POST /api/security/egress-policies
POST     /api/security/egress-policies/{version}/activate
POST     /api/security/secret-handles/validate
```

- [ ] [FRAME | HIGH] Write backend permission/CSRF/atomicity/audit tests and frontend permission-visibility tests first.
- [ ] [FRAME | HIGH] Show Recovery OIDC Group mapping as immutable. Allow ordinary mappings and egress origins to be edited/validated/activated directly; do not add approval UI.
- [ ] [FRAME | HIGH] Show Secret Handle metadata/validation only under `secret_handle.view/use`; never return a resolved value.
- [ ] [FRAME | HIGH] Add session-expired and claim-refresh-required UX to both Dashboard and Operator Chat; do not create account, password, profile, directory, role-assignment-to-user, or user-management screens.
- [ ] [FRAME | HIGH] Commit with message `Add permission-aware security configuration UI`.

## Task 9: S2 Full Verification and Review

- [ ] [KNOWN | HIGH] Run:

```bash
PROOF_AGENT_TEST_POSTGRES_DSN=postgresql+psycopg://proofagent:proofagent@127.0.0.1:55432/proofagent_test \
  uv run --extra dev --extra dashboard --extra postgres --extra security python -m pytest \
  tests/test_operator_permissions.py \
  tests/test_permission_mapping.py \
  tests/test_oidc_sessions.py \
  tests/test_csrf.py \
  tests/test_secret_handles.py \
  tests/test_egress_policy.py \
  tests/test_guarded_http.py \
  tests/test_production_tool_admission.py \
  tests/test_security_configuration_api.py -v
npm run test -w proof-agent-dashboard
npm run test -w proof-agent-chat
npm run build
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai --extra postgres --extra security mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

- [ ] [FRAME | HIGH] Independently review authentication cryptography/session lifecycle, permission completeness, CSRF route inventory, Recovery Group immutability, Secret Provider behavior, egress/DNS enforcement, SDK bypass negatives, and absence of local user/approval systems.
- [ ] [FRAME | HIGH] Resolve all P0/P1 findings, record the S2 commit in the master plan, and only then allow S4/S5 to consume these contracts.
