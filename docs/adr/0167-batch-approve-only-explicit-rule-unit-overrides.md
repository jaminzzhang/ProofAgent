---
status: accepted
---

# Batch approve only explicit Rule Unit overrides

[FRAME | HIGH] The Document Metadata Default Review always receives its own explicit approval because it governs every inheriting Rule Unit. A reviewer may atomically approve an explicitly selected set of current, ready-for-approval Rule Unit Metadata Override Reviews from one document revision, with the command bound to the review-set generation and every selected review identity; any concurrent change rejects the whole batch. Dashboard confirmation shows the document, revision, affected Rule Unit count, governed-value summary, and required reason, while audit retains both batch and per-review decisions. Proof Agent does not provide a Source-wide or filter-implied approve-all shortcut.
