---
status: accepted
---

# Gate Production Agent Version rollback at composition

[KNOWN | HIGH] ADR-0234 and ADR-0235 make the existing Agent Configuration
Workspace revalidate the rollback target's exact KSS Release and require the Active
pointer confirmed by the caller. TDD-06F verifies that the same Workspace commits the
pointer and audit atomically through the production PostgreSQL Unit of Work. The
Production Agent Configuration router does not yet expose rollback, while the Dashboard
already hides the action behind the server-projected `can_rollback` capability.

[DECISION | HIGH] Add one strict Production command at
`POST /config/agents/{agent_id}/versions/{version_id}/rollback`. Its body requires
`expected_active_version_id`; JSON `null` is the explicit no-active expectation, while
omission and unknown fields are invalid. Delivery requires `agent.publish`, projects the
OIDC session actor, and calls only `AgentConfigurationWorkspace.rollback_version()`.
The development router is not mounted or reused in Production.

[DECISION | HIGH] A composition-owned `production_agent_rollback_enabled` gate controls
both command admission and the Draft's `can_rollback` projection. The default is
`false`, and the real Production API composition passes `false` explicitly. A caller
sees `can_rollback=true` only when the gate is enabled and its identity has
`agent.publish`. A disabled command returns
`production_agent_rollback_unavailable` without calling the Workspace.

[DECISION | HIGH] Stable domain failures remain content-free: missing Version maps to
404; pointer, target, or Release conflicts map to 409; an unavailable KSS Catalog maps
to 503; and an unknown internal failure maps to
`production_agent_rollback_failed` with status 500. Existing Production OIDC session
and same-origin CSRF middleware guard the POST before Delivery authorization.

[CONSEQUENCE | HIGH] Registering the route does not enable Production rollback. A later
slice must exercise the exact production dependency path and explicitly change the
composition gate before the Dashboard can advertise or submit the command in a real
deployment. Response-loss retries retain ADR-0235 semantics: an old pointer expectation
conflicts and requires reload rather than creating a second idempotency authority.

[BOUNDARY | HIGH] TDD-06G changes the Production Delivery contract, capability
projection, composition gate, tests, and evidence documentation only. It does not enable
the real Production composition, alter role mappings, call real PostgreSQL or KSS,
execute an online rollback, create or deregister a Grant or Reference, enter Phase F,
publish, deploy, establish a cross-service lease, or grant Production GO.
