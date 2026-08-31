---
status: accepted
---

# Read formal publication command status without a second recovery path

[KNOWN | HIGH] ADR-0223 already makes exact `POST` replay the recovery authority for a
durable Formal Production Agent publication command. The same actor, request path,
request body and `Idempotency-Key` return the retained receipt before lease expiry and
may acquire one fenced takeover after expiry. A separate recovery command would create
a second state-changing path. Automatic recovery also cannot reconstruct the command
because the durable record intentionally retains a request digest rather than the raw
request body.

[DECISION | HIGH] ProofAgent exposes one read-only status resource at
`GET /api/config/agents/{agent_id}/drafts/{draft_id}/formal-publications/{command_id}`.
The caller must hold `agent.publish`. The trusted OIDC actor subject must exactly match
the actor subject that created the command. Agent, Draft and command identities must
all match the path.

[DECISION | HIGH] A missing command, a command owned by another actor, or a mismatched
Agent or Draft path returns the same `formal_publication_command_not_found` result. The
read does not reveal whether another actor owns the supplied command identity.

[DECISION | HIGH] The response is the existing trace-safe public receipt. It excludes
the actor subject, `Idempotency-Key`, execution owner, lease, fencing token, Candidate
checkpoint, raw request, smoke question and evidence content. Reading does not acquire,
renew or take over a lease and does not commit command state.

[CONSEQUENCE | HIGH] An operator first reads the exact command receipt. If the command
remains `in_progress`, recovery still requires replaying the original `POST` with the
same actor, path, body and `Idempotency-Key`. A status read never authorizes publication
and never creates a second logical attempt.

[BOUNDARY | HIGH] TDD-05U adds no list endpoint, cross-operator audit view, background
scanner, stored request body, automatic takeover, heartbeat, cancel command, Dashboard
control, real external-model proof or Production GO.
