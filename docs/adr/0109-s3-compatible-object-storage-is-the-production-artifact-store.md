# S3-Compatible Object Storage Is the Production Artifact Store

Accepted.

[FRAME | HIGH] S3-compatible object storage is the authoritative production store for immutable Trace, Governance Receipt, Knowledge document revision and snapshot, validation capture, evaluation, and export artifacts. PostgreSQL stores transactional metadata, immutable object references, digests, ownership facts, and lifecycle state rather than duplicating artifact payloads; artifact keys or versions are not overwritten after publication. Local filesystem artifact stores remain development-and-test implementations only.
