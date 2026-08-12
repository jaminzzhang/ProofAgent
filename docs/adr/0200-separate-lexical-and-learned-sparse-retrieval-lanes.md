---
status: accepted
---

# Separate Lexical and learned Sparse retrieval lanes

[FRAME | HIGH] Knowledge Source Service treats Lexical Retrieval Lane and Sparse Semantic Retrieval Lane as distinct capabilities. Lexical retrieval uses analyzed and exact terms, phrases, fields, and BM25-style corpus statistics without learned semantic expansion. Sparse retrieval uses a pinned learned encoder to produce weighted vocabulary dimensions for queries and Evidence Units. A Sparse model, tokenizer, weighting rule, or stored sparse-projection change creates a new retrieval-index compatibility generation; Knowledge Base Release and Retrieval Lineage identify the exact generation, lane budget, rank, failure, and candidate contribution. Dense and Structured lanes remain separately identified, and heterogeneous raw lane scores are not treated as directly comparable. We accept an additional model, projection, evaluation, and operating path because learned sparse retrieval adds semantic term expansion that is neither ordinary BM25 nor dense-vector similarity.
