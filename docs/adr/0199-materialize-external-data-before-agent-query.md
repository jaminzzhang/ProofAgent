---
status: accepted
---

# Materialize external data before Agent query

[FRAME | HIGH] Knowledge Source Service V1 never federates an Agent query directly into an upstream database or HTTP API. Upload admission and full, incremental, or change-stream Knowledge Source Synchronization commit immutable Materialized Knowledge Source Revisions inside service authority, recording exact origin, upstream revision or watermark when available, ingestion identity, content digest, and lineage. A Knowledge Base Version pins those exact Revisions, and later synchronization creates a new Revision and prospective Base Version without mutating existing query behavior. Live remote federation remains a separate future capability and cannot participate in V1 Knowledge Base Version replay guarantees. We accept bounded freshness lag and additional storage so standard Agent queries remain reproducible, independent of upstream availability, protected by one service authorization boundary, and auditable against exact evidence inputs.
