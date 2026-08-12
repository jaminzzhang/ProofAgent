---
status: accepted
---

# Separate Knowledge Source Service from Agent evidence admission

[FRAME | HIGH] Hybrid Knowledge processing and candidate retrieval move behind an independently deployable and operated Knowledge Source Service. The service owns heterogeneous intake, original retention, structural parsing, normalization, Evidence Unit construction, indexing, Knowledge Base Release, and Lexical, Dense, Sparse, and Structured Hybrid Retrieval. Its stable API returns Candidate Evidence with exact Source Version, Release, Citation Locator, Content Hash, and Retrieval Lineage. It authenticates Agent clients and protects service resources but does not grant end-user permissions, perform Evidence Admission, adjudicate facts or conflicts, reason over answers, or generate final answers; Proof Agent retains user authorization, Control Plane policy, Evidence Admission, factual and conflict governance, and final-answer generation, while other Agent runtimes apply their own governance. We accept the network, compatibility, and operational cost of a service boundary so multiple Agents can reuse one Knowledge capability without inheriting Proof Agent-specific governance or allowing the Knowledge service to declare its own results accepted. Public management ingress and migration sequencing remain separate decisions.
