---
status: accepted
---

# Probe the deployed Production Agent rollback gate while closed

[KNOWN | HIGH] ADR-0236 keeps the real Production Agent rollback gate explicitly
disabled, while ADR-0237 verifies the enabled path only in an isolated test
composition. Before TDD-06I, no checked-in verifier exercised the disabled command
through the retained production-local TLS Gateway, OIDC session, same-origin CSRF and
Production API process.

[DECISION | HIGH] Add one explicit production-local verification entry that accepts a
single private session JSON file and reuses the existing bounded HTTPS transport. The
file contains only the `session_cookie` JSON field whose value is the
`proof_agent_session` cookie, must not be a symlink, and must deny group and other
permissions. The verifier obtains the current CSRF token and effective
permissions from `/api/auth/session`; it never prints the cookie or CSRF token.

[DECISION | HIGH] Use fixed fictional Agent and Version identifiers and send the same
strict rollback request through three admission states. No session must return `401`;
an authenticated session without same-origin CSRF must return `403`; an authenticated
session with `agent.publish`, the stable Origin and current CSRF token must return the
exact `503` body `{"detail":"production_agent_rollback_unavailable"}`. The final
result is evidence that the deployed route remains closed, not authority to open it.

[CONSEQUENCE | HIGH] TDD-06I reuses `StableOriginClient` and the existing private
session-file pattern instead of adding a login protocol, password flow, browser
credential, second HTTP client or database fixture. Unit evidence from ADR-0236
continues to prove that the closed gate does not call the Workspace; the deployed probe
proves the real Gateway/API admission result. Neither result alone establishes a
successful deployed rollback.

[BOUNDARY | HIGH] Session acquisition remains an operator-controlled prerequisite and
no credential enters Git, command arguments, logs or feature evidence. The verifier
does not inspect `.env`, change Compose configuration, enable the gate, read or mutate
Agent/KSS business records, call a KSS Query or model, write ArtifactStore data, enter
Phase F, publish, deploy, grant a Release Gate, or establish Production GO. A deployed
gate-enabled success rehearsal remains a later separately authorized slice.
