---
status: accepted
---

# Deploy one Knowledge service with isolated process roles

[FRAME | HIGH] Knowledge Source Service V1 is one independently versioned product and logical data authority, implemented initially as one modular codebase and one OCI image with separately started API, Query Executor, Knowledge Worker, Scheduler, and migration process roles. Roles share provider-neutral domain and application modules but do not share in-memory authority. PostgreSQL owns mutable state and coordination, S3-compatible storage owns immutable originals and artifacts, and OpenSearch remains a rebuildable retrieval projection. Query work and ingestion work use separate bounded queues and worker pools so offline parsing, OCR, embedding, and indexing cannot starve online retrieval.

[FRAME | HIGH] The service may initially remain in the ProofAgent monorepo for coordinated contract migration, but it has its own Python distribution, dependency lock boundary, database role and schema, migrations, object namespace, search namespace, configuration, release artifact, readiness checks, and deployment lifecycle. Proof Agent depends only on the versioned HTTP/OpenAPI contract and a client adapter; it never imports service domain or persistence modules. A later repository split therefore changes source ownership mechanics rather than the runtime contract.

[FRAME | HIGH] V1 does not decompose ingestion, publication, query planning, structured execution, fusion, or citation resolution into separately versioned network microservices. Private parser, OCR, embedding, sparse-encoder, reranker, and planner model endpoints remain deployment-owned capability services behind ports. We accept one product with isolated roles to reduce distributed transaction and contract drift while preserving workload isolation and future module extraction seams.
