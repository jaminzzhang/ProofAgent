---
status: accepted
---

# Keep Structured results outside relevance rank fusion

[FRAME | HIGH] Structured Retrieval Lane results remain typed, separately budgeted Structured Candidate Evidence Groups. A Bounded Structured Knowledge Query returns exact record- or aggregate-backed Candidate Evidence with schema types, projections, predicates, grouping, explicit typed order, stable record identities or aggregate-input identities, Citation Locators, and Retrieval Lineage. When no explicit order exists, the service uses a deterministic stable-record fallback. It does not flatten these results into text chunks, assign them pseudo semantic scores, or fabricate a global rank against unstructured evidence.

[FRAME | HIGH] Only exact-deduplicated Lexical, Sparse, and Dense candidates enter Weighted Reciprocal Rank Fusion and the optional version-pinned private Reranker. Structured Candidate Evidence Groups enter neither. Typed Mixed Retrieval Composition returns the relevance-ranked group and one or more Structured groups under the same query response, exact Knowledge Base Release, and Knowledge Query Plan while keeping their budgets and ordering semantics separate. Proof Agent receives every group as Candidate Evidence and retains Evidence Admission without assuming that a structured order and a relevance rank are comparable.

[FRAME | HIGH] We accept a grouped response contract and the absence of one universal Top-K because deterministic records and aggregates answer a different retrieval question from approximate semantic relevance. This preserves typed data semantics and aggregate reproducibility while still allowing one mixed Agent query to use structured and unstructured Knowledge together.
