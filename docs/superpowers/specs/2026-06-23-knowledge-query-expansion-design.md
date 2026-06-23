# Knowledge Query Expansion Design

## Problem

`run_c358ce0d` showed that Intent Resolution can generate a useful Retrieval Query Set, but the configured `single_step` retrieval strategy executed only the first required query. For broad knowledge questions, that wastes the model's query expansion work and can leave optional business-angle queries unused.

## Decision

Use one public **Knowledge Query Expansion** behavior for all LLM Intent Resolution knowledge-retrieval intents. Do not add business-specific query types. The LLM should produce a bounded Retrieval Query Set with complementary angles such as original wording, domain synonyms, entity and time qualifiers, metric or ranking qualifiers, and bilingual alternatives when useful.

## Execution Semantics

Direct `single_step` retrieval keeps its current behavior: select one required query item if present. ReAct reviewed retrieval changes behavior: when a multi-item Retrieval Query Set exists, it executes the whole ordered set as a query expansion batch within `retrieval.max_queries`, then evaluates the combined evidence.

## Tests

Add a prompt/payload test proving Intent Resolution exposes the public expansion policy to the LLM. Add a retrieval service test proving `retrieve_reviewed(..., execution_mode="react_reviewed_retrieval")` executes required and optional query items even when `strategy="single_step"`. Keep the existing direct `single_step` test unchanged.
