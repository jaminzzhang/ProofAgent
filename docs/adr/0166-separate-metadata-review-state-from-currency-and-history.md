---
status: accepted
---

# Separate metadata review state from currency and history

[FRAME | HIGH] Insurance Rule Metadata Review exposes four business states only: `needs_input`, `ready_for_approval`, `approved`, and `rejected`. Whether a review revision belongs to the current candidate is a separate currency fact, while corrections, workbook applications, approvals, and rejections remain immutable decision-history events. Approved and rejected revisions are not edited in place; a later metadata change creates a new current review revision and preserves the prior outcome as historical. This separation lets operators distinguish missing work from pending approval and prevents historical approval from being mistaken for current publication authority.
