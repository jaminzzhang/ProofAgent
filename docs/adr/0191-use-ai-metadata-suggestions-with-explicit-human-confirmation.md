---
status: accepted
---

# Use AI metadata suggestions with explicit human confirmation

[FRAME | HIGH] Hybrid document intake asks the private model plane for one Profile-valid Document Default and exact Rule Unit proposals, binds every proposal to server-owned document lineage, and deterministically collapses matching Rule Units into that default. Only divergent, uncertain, conflicting, or missing values remain as Rule Unit Override reviews. Committing a replacement document revision transactionally removes prior revisions of that stable document from current-review queries while retaining their immutable review and decision history. Dashboard presents the resulting AI suggestions for explicit operator confirmation; AI output remains an immutable proposal baseline and can neither approve metadata nor bypass exact review identity, source revision, permission, reason, audit, and publication gates. Missing or malformed proposals fail closed into governed review rather than silent acceptance.
