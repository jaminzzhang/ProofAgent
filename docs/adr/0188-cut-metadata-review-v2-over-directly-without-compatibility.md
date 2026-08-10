---
status: accepted
---

# Cut Metadata Review V2 over directly without compatibility

[FRAME | HIGH] Metadata Review V2 is deployed in one maintenance-window cutover: stop Knowledge Source writes and Workers, verify a recoverable database and artifact backup plus migration preconditions, run the explicit schema/data migration, deploy the V2 Dashboard, API, and Worker image together, verify the full flow, then reopen writes. The release contains no V1 endpoint, parser, UI, dual read, dual write, runtime fallback, dark capability, or compatibility feature flag. Legacy V1 facts survive only as migrated read-only audit history. Failure before writes reopen restores the pre-cutover snapshot and old image; after the first V2 authority mutation rollback to V1 is invalid and repair proceeds forward.
