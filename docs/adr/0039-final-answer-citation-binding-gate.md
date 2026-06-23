# Final Answer Citation Binding Gate

Accepted.

The Controlled ReAct Loop will validate final answers against Observation Record citation state, not only against citation-looking text. Customer-visible factual claims must bind to supported `citation_refs` or `source_refs` that came from Accepted Evidence in an Observation Record. When Accepted Evidence exists but the final answer emits no supported citation reference for factual claims, validation fails closed.

We choose this over permissive text-pattern citation validation because a ReAct loop can still lose evidence provenance at the final answer boundary. The final answer model may summarize correctly but omit or invent citation-looking markers; governed output must prove that cited claims are connected to admitted observation state.
