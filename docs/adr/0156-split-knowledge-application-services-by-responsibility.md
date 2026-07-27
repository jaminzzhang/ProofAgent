---
status: accepted
---

# Split Knowledge application services by lifecycle responsibility

[FRAME | HIGH] The unified Knowledge application boundary is implemented through focused Configuration, Ingestion, Publication, and Operations application services behind one public API contract. Knowledge Worker and Run Executor remain independently composed process roles over the same PostgreSQL, S3, OpenSearch, security, and private-model ports; combining them into one large service or process would blur transaction ownership, queue fencing, readiness, and deployment-role isolation.
