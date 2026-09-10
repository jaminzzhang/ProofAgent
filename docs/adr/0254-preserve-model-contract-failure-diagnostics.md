# ADR-0254: Preserve model contract failures as failed runs

[KNOWN | HIGH] `run_36c2900a` stopped after two Intent Resolution responses. The
second normalization error escaped before run finalization and optional Stage
Capture, returning HTTP 400 without a terminal receipt or diagnostic capture.
`run_964c1d47` completed required retrieval but failed numeric fact validation and
then source selection; its outcome incorrectly implied missing evidence.

[FRAME | HIGH] The Control Plane maps exhausted Intent Resolution contract errors
and final-answer validation failures to the existing `FAILED_WITH_TRACE` outcome.
Intent failure stops before planning/retrieval. The invocation adapter retains both
LLM interaction records even when normalization raises. Normal run finalization,
receipt projection and opt-in validation capture then persist the failed result.
Request/configuration errors retain their existing HTTP error semantics. Other
exception classes and non-intent normalization errors are not silently relabeled.

Ordinary trace contains bounded stage, contract, field-path and violation-code
facts, never model content. Full model interactions remain exclusively in the
existing sensitive capture path with its sanitizer, authorization and retention
rules. A missing capture from a historical aborted run cannot be reconstructed.

Clarification assessment relationship errors have stable duplicate/unknown-field
codes. Initial and repair prompts describe exact membership in `missing_fields`;
defaultable preferences stay in the proposal until Control Plane policy applies.
The contract still rejects duplicates, unknown references and missing requirements.

Source selection keeps its one-repair and 1–16 unique known-ID limits. The prompt
and schema state uniqueness; errors distinguish JSON/shape/type/count/unknown-ID/
duplicate-ID failures without recording model values. Rendered source sentences
still pass all fact, conflict, safety and citation checks. No invalid selection is
silently trimmed, deduplicated or guessed.

DeepSeek standard endpoints still omit the strict beta flag. The existing beta
compatibility guard also declines schemas with unsupported array constraints.
This change does not switch endpoints or discard schema constraints to claim strict
provider enforcement; deterministic server validation remains authoritative.
