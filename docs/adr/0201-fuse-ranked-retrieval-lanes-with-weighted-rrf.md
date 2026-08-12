---
status: accepted
---

# Fuse ranked retrieval lanes with Weighted RRF

[FRAME | HIGH] Knowledge Source Service fuses Lexical, Sparse, and Dense candidates by exact Evidence Unit deduplication followed by Knowledge Base Release-pinned Weighted Reciprocal Rank Fusion over each lane's independent Top-K rank and configured weight. It may then apply one version-pinned private Reranker to already access-filtered fused candidates. Retrieval Lineage retains every lane's raw score, rank, weight, RRF contribution, fused rank, and reranker transition; heterogeneous raw scores are never compared directly. Fusion and reranking establish relevance order only and cannot determine factual truth, resolve conflicts, perform Evidence Admission, or generate answers. This extends the earlier Lexical-plus-Dense RRF direction to a distinct learned Sparse lane. We accept rank-fusion and optional reranker complexity to combine heterogeneous retrieval behavior without pretending their backend scores share one calibrated meaning. Structured result composition remains a separate decision.
