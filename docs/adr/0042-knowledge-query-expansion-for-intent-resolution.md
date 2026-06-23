# Knowledge Query Expansion For Intent Resolution

Accepted.

LLM Intent Resolution will use a public, domain-neutral **Knowledge Query Expansion** behavior for knowledge-retrieval intents. Instead of adding query types such as sales-performance query, product-ranking query, or claims-materials query, the model expands the user request into a bounded Retrieval Query Set with complementary search angles: original wording, business synonyms, time or entity qualifiers, metric or ranking qualifiers, and bilingual alternatives when useful.

ReAct reviewed retrieval must execute a multi-item Retrieval Query Set as a query expansion batch, even when the Agent's configured retrieval strategy is `single_step`. The earlier `single_step` behavior of selecting only the first required item remains valid for direct non-ReAct retrieval calls, but it is insufficient after Intent Resolution has produced a governed query expansion set. Otherwise optional query items become trace-only decoration and runs can repeatedly execute the same required query.

We choose this over business-specific query types because each new business wording would otherwise require a new domain category and new control logic. We choose reviewed query-set execution over silently forcing every Agent to `agentic` because the workflow can preserve existing Agent configuration while still honoring Intent Resolution's bounded expansion output.
