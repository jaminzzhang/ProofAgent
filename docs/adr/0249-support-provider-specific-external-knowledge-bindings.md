# ADR-0249: Provider-specific external Knowledge bindings

Date: 2026-09-07. Status: accepted for local implementation under the user's request
to support Agentset alongside Dify. Extends ADR-0242/0243; does not open production publication.

## Decision

- One ExternalKnowledgeBinding remains the public entry with strict provider-selected
  settings. Dify keeps dataset_id and existing serialization. Agentset uses namespace_id
  (ns_ prefix), optional fixed tenant_id and its own retrieval settings. Cross-provider
  identities/settings are rejected, not silently ignored. At most five total bindings.
- Agentset calls only POST {endpoint}/namespace/{namespace_id}/search behind the same
  Guarded HTTP and versioned Secret Provider. The frozen tenant becomes x-tenant-id;
  neither model nor query may change source, endpoint, tenant, key or headers.
- Agentset exposes semantic/keyword search, top_k (bounded here to 20), score threshold,
  rerank and a pinned rerank model. No arbitrary filter, ingestion or hosted chat.
- Search success rows supply opaque chunk IDs, not a guaranteed document identity.
  Agentset candidates therefore retain their raw chunk ID and no fabricated document ID.
  Source URIs use namespaces/[tenant]/chunks with percent-encoded IDs. Dify URIs remain
  unchanged. Structured records use the same strict parser and provider-specific source
  validation; content hashes, actual queries and bound Observation Truth remain mandatory.
- Native relevance is not proof of truth. Missing/bad text, scores, duplicate chunk IDs,
  malformed envelope, credential mismatch and transport/HTTP errors fail closed without
  exposing provider payloads or keys. All selected bindings remain required.
- Registry dispatch in Bootstrap owns adapters; no fallback from Agentset to Dify.

## Official evidence and limits

Checked 2026-09-07:
- https://docs.agentset.ai/api-reference/endpoint/search — endpoint, Bearer auth,
  x-tenant-id, success/data envelope and modes.
- https://docs.agentset.ai/search-and-retrieval/citations — stable opaque chunk IDs,
  including doc_123#4. Search examples also include chunk_abc123; no document ID assumed.
- https://docs.agentset.ai/production/data-segregation — fixed namespace/tenant scope.

Docs disagree on the default reranker; pin zeroentropy:zerank-2 explicitly (listed by
both API and search guide) instead of inheriting a remote default. Query bound remains
250 characters and 1 MiB/100 rows, matching this application's existing external budget.
Rerank limit equals configured top_k; no uncontrolled candidate expansion.

Verification: synthetic official-protocol adapter tests, mixed-source Harness and
structured provenance checks, configuration CAS routes, Dashboard interaction/build
and actual rendered fixture. Live provider credentials and production qualification
are separate and are not inferred from local tests.
