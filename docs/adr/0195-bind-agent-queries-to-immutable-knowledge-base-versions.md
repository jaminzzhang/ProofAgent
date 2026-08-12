---
status: accepted
---

# Bind Agent queries to immutable Knowledge Base Versions

[FRAME | HIGH] Knowledge Source Service introduces Knowledge Base as the service-owned query aggregate above independently governed Knowledge Sources. Each immutable Knowledge Base Version pins the exact document, structured-dataset, and remote Source Publications, applicable Structured Knowledge Dataset Revisions, and retrieval-compatibility configuration available to a query. Agent integrations query an exact Knowledge Base Version rather than a mutable Source list or `latest` pointer; Source changes require publication of a new Base Version, and Candidate Evidence retains Base, Source, document or dataset, record or chunk, and revision provenance. We accept an additional composition and publication layer so different Agents receive one stable mixed-Knowledge contract instead of reimplementing Source selection, version pinning, and reproducibility. Migration sequencing remains a separate decision, but the target service contract has one version-bound query shape rather than permanent direct-Source and Base compatibility paths.
