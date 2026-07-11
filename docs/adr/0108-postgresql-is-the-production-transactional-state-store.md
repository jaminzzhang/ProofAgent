# PostgreSQL Is the Production Transactional State Store

Accepted.

[FRAME | HIGH] PostgreSQL is the sole authoritative store for mutable structured production configuration, run, conversation, Case Memory, approval snapshot and lock, evaluation, configuration-audit metadata, and coordination state. Logical Store and port boundaries remain provider-neutral, while local JSON, JSONL, directory, and in-memory implementations are limited to development and tests; caches and read projections cannot become an alternative source of truth. Large immutable artifact placement remains a separate storage decision.
