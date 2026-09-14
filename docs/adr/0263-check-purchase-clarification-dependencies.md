# ADR-0263: Check clarification dependencies against the current request

Date: 2026-09-14

[KNOWN | HIGH] In run_d9e43d0e, the user asked about a named life-insurance
product's coverage and whether it suited a 30-year-old prospective buyer. Trace
recorded three required public retrievals and three deferred personal-context
fields, but paused before retrieval on existing-product-policy information
qualified as “如有追问需要”. The capture contains no raw LLM interactions; the
exact original classification is unknown. Both absent and required_context
classifications reproduce this failure locally.

[FRAME | HIGH] Missing information must be relevant to a current requested
subtask. Hypothetical later questions do not create current prerequisites.
Intent and Planner prompts distinguish specific existing-policy case inputs
from overall coverage, needs and budget for purchase suitability. The latter
remain answer_context when public facts can be answered independently; age
alone does not establish suitability.

Control implements a bounded Chinese purchase-consultation dependency profile
in `proof_agent/control/workflow/context_dependencies.py`. It requires an
explicit insurance purchase/suitability question, rejects questions mentioning
policy-specific operations (including mixed requests), and matches the entire
missing-field label against a narrow existing-policy-information grammar.
Compound identity/permission requirements and unknown field names do not qualify.
This is a deliberate bounded exception to ADR-0261's default blocking rule,
not a general semantic proof or a blanket downgrade of required_context.

Intent normalization applies it only with required retrieval queries and an
ask/retrieval recommendation. It removes an irrelevant field rather than asking
it after the answer, preserves relevant deferred fields, and records the purchase
scope when the existing scope-assumption capacity permits. No user fact is inferred.
Planner applies the same dependency rule so it cannot recreate that prerequisite;
frozen Task required_context, tool_input, targeted tools and active tool plans
retain their gates. No schema, permission, evidence or completion gate changes.

[KNOWN | HIGH] Verification is synthetic and local. See
`docs/features/agent-kernel-quality/run-d9e43d0e-context-dependencies.md` and
`tests/test_purchase_context_dependencies.py`. The rule is conservative outside
its recognized wording; real-model compliance, broader language coverage and
the final real-provider answer remain unverified. Status: PARTIAL_VERIFICATION.
