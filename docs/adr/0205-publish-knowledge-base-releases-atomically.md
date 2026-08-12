---
status: accepted
---

# Publish Knowledge Base Releases atomically

[FRAME | HIGH] Knowledge Base Version is an immutable description of an intended Source and retrieval-compatibility composition, but it is not a runtime query target by itself. Asynchronous preparation builds and validates all exact Knowledge Source Versions, Evidence Unit Manifests, Structured Knowledge Dataset Revisions, retrieval-index generations, retrieval profile, projection attestations, and smoke results into one non-queryable Prepared Knowledge Base Release. Preparation performs no partial runtime activation and does not hold a database transaction open across external or long-running work.

[FRAME | HIGH] One short transactional compare-and-swap validates that the Prepared Knowledge Base Release and all bound identities remain current, then creates one immutable queryable Knowledge Base Release or changes nothing. No query may observe a mix of old and new Sources, manifests, profiles, or index generations. Every runtime request names the exact `knowledge_base_release_id`; the service rejects missing, unqueryable, retired, or projection-mismatched Releases and never resolves `latest`, substitutes another Release, or falls back to a local index.

[FRAME | HIGH] A separate Recommended Knowledge Base Release Pointer may support management views, new-binding defaults, and upgrade notifications, but it is never consulted during query execution. Existing Agent bindings remain pinned until an explicit Draft upgrade, validation, and Agent publication. Rollback binds a later Agent version to a prior immutable Release rather than mutating Knowledge data. Referenced Releases and Releases inside retention remain queryable; cleanup requires reference and retention eligibility. This refines ADR-0195 and ADR-0198 from exact Base Version intent to exact published Release execution. We accept preparation storage and explicit upgrades to obtain atomic visibility, reproducible queries, safe rollback, and multi-Agent stability.
