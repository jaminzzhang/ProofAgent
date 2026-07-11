# Initial Production Memory Is PostgreSQL Case-Only

Accepted.

[FRAME | HIGH] The initial production release supports only Case Memory scoped to the current Operator Chat conversation or case, stored authoritatively in PostgreSQL and expired after 30 days. Case Memory may contain admitted structured case facts or bounded trace-safe summaries, remains non-evidence context, and cannot become a source of business truth or citation support.

[FRAME | HIGH] Customer Persistent User Memory, Shared Memory, operator profiles, external Mem0, and filesystem-backed local memory are unavailable in initial production. OIDC operator subjects must not be converted into persistent-memory user identities. Agent publication rejects those production configurations while deterministic local examples and tests may retain local memory adapters until their legacy packages are removed.
