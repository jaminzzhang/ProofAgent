# Use One Rebuildable Knowledge Retrieval Index Service

Accepted.

[FRAME | HIGH] The expanded Knowledge architecture may add one internal Knowledge Retrieval Index Service outside PostgreSQL and S3-compatible object storage. It provides pre-retrieval authorization filters, lexical retrieval, vector retrieval, and hybrid candidate ranking over published Knowledge versions, but stores only rebuildable derived projections. PostgreSQL remains authoritative for mutable configuration, publication, authorization metadata, and lifecycle state; S3-compatible storage remains authoritative for originals and immutable parsed, structural, and indexable artifacts. Proof Agent accesses the service through a Knowledge Provider Adapter so replacement does not alter Knowledge Source, evidence, citation, or publication semantics. We accept one additional stateful service to meet the target corpus and query mix without accepting multiple specialized search databases or a third source of truth.
