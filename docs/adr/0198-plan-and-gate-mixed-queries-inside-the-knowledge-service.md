---
status: accepted
---

# Plan and gate mixed queries inside the Knowledge service

[FRAME | HIGH] Agent clients send a natural-language question, an exact Knowledge Base Version, and optional typed narrowing constraints to Knowledge Source Service rather than constructing document-index, structured-query, SQL, or search-backend plans. A service-owned planner revision produces a typed Knowledge Query Plan that selects bounded Lexical, Dense, Sparse, and Structured lanes, rewrites, filters, aggregations, and budgets. Before execution, a deterministic Knowledge Query Plan Gate verifies every referenced Source, Dataset Revision, schema field, operator, budget, and lane against the exact Base Version and effective Knowledge Query Access Scope; the planner cannot grant access, select mutable `latest`, emit backend-native executable syntax, adjudicate facts or conflicts, or approve its own proposal. The response includes a trace-safe plan summary, per-lane outcomes, and Candidate Evidence carrying exact Source Version, Knowledge Base Release, Citation Locator, Content Hash, and Retrieval Lineage. Proof Agent retains the outer decision to seek Knowledge and the wording of the Knowledge question. We accept a service-side planning layer so different Agents share one stable query contract instead of duplicating backend and schema knowledge.
