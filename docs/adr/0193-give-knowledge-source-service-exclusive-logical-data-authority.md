---
status: accepted
---

# Give Knowledge Source Service exclusive logical data authority

[FRAME | HIGH] Knowledge Source Service is the exclusive logical authority for Knowledge Source lifecycle state, published versions, Knowledge artifacts, retrieval projections, and asynchronous Knowledge work. It owns its database or schema, credentials, migrations, object-storage namespace, search namespace, and queues; deployments may reuse physical PostgreSQL, object-storage, or OpenSearch clusters without sharing logical ownership. Proof Agent remains authoritative for its Agent bindings, releases, policies, and audit records, but stores only immutable external Knowledge references and digests, calls versioned service contracts, never reads Knowledge service storage directly, and fails closed when the service is unavailable. We accept explicit network availability and cross-service consistency work so the Knowledge service can deploy, migrate, recover, and roll back independently instead of remaining a storage-coupled Proof Agent process.
