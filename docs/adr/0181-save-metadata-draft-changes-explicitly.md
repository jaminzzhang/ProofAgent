---
status: accepted
---

# Save metadata Draft changes explicitly

[FRAME | HIGH] Dashboard metadata forms do not autosave. One explicit Save Draft command applies a reasoned Metadata Review Draft Change against the exact Review version and identity, records the field diff, advances Source authority only after success, and computes `needs_input` or `ready_for_approval` from the resulting completeness. Unsaved local edits are visibly guarded and disable approval; editing an approved result first creates a new current Review revision. This avoids per-keystroke Source revisions and prepared-publication invalidation while preserving optimistic concurrency and auditability.
