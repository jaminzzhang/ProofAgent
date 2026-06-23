# Parallel Query Set Retrieval

Accepted.

ReAct reviewed retrieval may execute multiple Retrieval Query Items from one Retrieval Query Set concurrently when the Knowledge Provider explicitly declares `supports_parallel_retrieval`. The concurrency applies only inside one reviewed query expansion batch; it does not parallelize ReAct planning, review, RetrievalPlanner rewrite rounds, or provider-internal routing.

The Agent-level retrieval configuration adds `query_concurrency` as a bounded fan-out limit from one through five and `query_timeout_seconds` as a bounded query-set batch wait from 0.01 through 120 seconds. Defaults keep existing YAML valid: three concurrent query items and a ten-second timeout.

Timeout and failure semantics follow the required flag. If every required Retrieval Query Item returns normally before the batch timeout, retrieval proceeds with the evidence returned by completed required and optional items. Optional timeout or optional provider failure is traced as degraded retrieval and does not block evidence evaluation. If a required item times out or fails, the batch fails closed as `required_provider_failure`; optional evidence cannot compensate because required items represent the minimum intent coverage.

We choose provider-declared concurrency over assuming that retrieval is thread-safe because several providers have read-like public APIs but mutable implementation state such as trace summaries, routing model bindings, or audit writes. Trace emission is made thread-safe separately because audit sequence assignment is shared write state, not a retrieval read. Providers without explicit parallel support continue to use the existing sequential query-set execution path.
