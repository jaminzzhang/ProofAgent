# ADR-0248: Fence local business action outcomes

## Status

[FRAME | HIGH] Accepted for the bounded P1-3 local contracts and isolated simulation on 2026-09-07. No real business operation or production write is enabled.

## Decision

A trusted server authorization port must bind actor, tenant, operation, resource, exact parameter digest, tool contract version, permission version and expiry. A Boolean approval flag cannot authorize a write. Recheck the live authority immediately before dispatch and before disclosing a replayed result.

A development-only SQLite ledger owns each scoped business idempotency key. Short `BEGIN IMMEDIATE` transactions reserve and fence attempts; network calls occur outside transactions. A request fingerprint conflict is rejected. Persist `executing` before dispatch. Succeeded results replay only after current authorization; definite failures remain failed. Expired execution leases and uncertain provider outcomes enter `outcome_unknown`, requiring provider reconciliation rather than blind retry. Old attempts cannot commit after lease loss. A provider receipt must verify against the exact requested operation and parameters before success is recorded.

The ledger stores request fingerprints and verified receipt identifiers/digests, not raw parameters or provider payloads. It has an explicit retention interval; expiry never automatically deletes idempotency records or permits a duplicate execution. Purging or shortening the retry horizon requires a separate business retention decision. The local adapter rejects production mode. A production PostgreSQL authority and the actual business provider's idempotency, receipt verification and compensation semantics remain prerequisites for real integration.

Compensation is a new independently authorized operation with its own business key; there is no generic rollback. Existing Tool Gateway and production read-only restrictions remain in force. The local coordinator exercises the future port contract with simulated providers and is not exposed as an API or a second V3 execution path.
