# ADR-0253: Configure Agent clarification without relaxing evidence authority

[FRAME | HIGH] Agent `response.clarification_level` accepts `minimal`, `balanced`
(default), and `thorough`. It is part of the existing Agent Contract, Draft CAS,
immutable publication and execution-configuration binding, not an operator bypass.

Intent Resolution proposes bounded classifications for missing fields:
`required_context` (identity, authority, specific object, applicability or conflicting
user constraints), `preference` (answer scope/presentation), and `retrievable`
(facts that governed retrieval can establish). Unknown/unclassified fields remain
blocking. Only the Control Plane applies the configured level, before freezing
required retrieval queries and before independent Business Flow admission.

All levels retain required context. Minimal permits broad retrieval for preferences;
balanced permits a preference default only when explicitly proposed; thorough asks
about preferences. Retrievable facts never require user input. No-pack is not an
ambiguous route. Business Flow admission, Tool Gateway, policy and Evidence Admission
remain independent and mandatory. No new tool arguments or permissions are inferred.

If all missing fields are nonblocking, use bounded proposed retrieval queries or
the original user question as one required governed query. Model-proposed scope
assumptions remain bounded non-evidence context, are propagated to answer requests
with explicit disclosure instructions, and never enter known facts or tool inputs.
No string matching against customer questions or company-specific defaults is used.

The server supplies the current UTC date and the same clarification policy to intent
and planning. Necessary clarification asks one field in the user's language while
retaining all unresolved fields in state. Trace records the applied level and counts;
the existing intent projection carries bounded scope assumptions under its existing
audit audience/redaction boundary. No credentials, raw reasoning or source payloads
are added. Historical captures without new fields remain readable.

Validation covers three levels, missing classifications, required-context protection,
no-evidence refusal, prompt repair context, localized single-question output, config
save/reload and rendered Dashboard selection. Real model quality is a separate check.
