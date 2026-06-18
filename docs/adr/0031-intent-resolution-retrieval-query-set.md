# Intent Resolution Retrieval Query Set

Accepted.

Intent Resolution may emit a bounded, non-executing **Retrieval Query Set** for knowledge-retrieval intents, even though ADR-0025 keeps executable retrieval planning outside Intent Resolution. We chose this because knowledge retrieval is a foundational Agent flow: producing candidate search angles while the user intent is being understood avoids duplicating intent analysis later, while preserving the Control Envelope boundary that only governed Retrieval stages may review, select, execute, trace, route, and admit query results as evidence.

The Retrieval Query Set is required when Intent Resolution recommends Knowledge retrieval and no blocking missing fields remain. It defaults to at most three candidate queries, with a hard configurable cap of five through Agent-level `retrieval.max_queries`, and validation fails rather than silently truncating over-budget output. Each query item carries only audit-safe query text, intent angle, required flag, and reason; it must not name Knowledge Sources, providers, filters, scoped retrieval commands, or execution parameters.

For migration, the `IntentResolution` contract may default the Retrieval Query Set to an empty tuple so existing deterministic tests and non-retrieval intents remain valid. LLM Intent Resolution validation is stricter: when the recommended next action is Knowledge retrieval and no missing fields block execution, the model output must include at least one valid query item, and empty query text, missing intent angle, missing reason, or over-budget output fails closed.

`single_step` retrieval may record the Retrieval Query Set but executes at most one selected query. `agentic` retrieval may execute multiple required and optional query items within budget before the RetrievalPlanner appends any later rewrite queries for insufficient evidence.

Trace records the Retrieval Query Set in two places: as part of the `intent_resolution` payload for complete intent-governance projection, and as a separate `retrieval_query_set` event for retrieval-stage, Dashboard, and evaluation consumers. The standalone event links to the Intent Resolution id and records only query item fields, counts, configured budget, recommended next action, and validation status.
