---
status: accepted
---

# Preserve typed structured Knowledge query semantics

[FRAME | HIGH] Knowledge Source Service represents admitted tabular and record-oriented data as immutable Structured Knowledge Dataset Revisions that preserve schema, field types, stable record identities, values, and source lineage; it does not reduce structured data to text chunks. Exact dataset revisions support a bounded read-only query contract with allowlisted projection, filtering, ordering, grouping, and aggregation, while arbitrary Agent-authored SQL is outside the service contract. Query results identify the exact records or aggregate inputs behind cited, version-bound Candidate Evidence. Unstructured documents retain their separate structured-document artifacts and retrieval path, and a mixed request may use both lanes without erasing provenance or allowing either lane to decide Evidence Admission. We accept a dual canonical model and query planner complexity because text-only RAG cannot reliably preserve numeric, temporal, schema, or aggregation semantics required by structured-data analysis.
